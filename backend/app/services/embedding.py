"""Embedding 服务（阿里云百炼，OpenAI 兼容协议）。

为什么不用 LangChain 的 OpenAIEmbeddings：
1. 百炼单批最多 10 条，需要自己控制分批与并发；
2. 需要精确统计 token 消耗（成本可核算、可熔断）；
3. 需要按知识库记录 embedding_model / dim，换模型时必须走重建流程。
自己封装一层反而更可控。

关键约束（踩过的坑）：
- 单批 <= 10 条，单条 <= 8192 token；一条超长会导致整批失败，必须预校验
- 必然遇到 429/5xx，需要指数退避 + 抖动
- 返回向量已归一化，相似度用 COSINE
"""

import asyncio
import random
from dataclasses import dataclass, field

import httpx

from app.core.config import settings
from app.core.errors import AppError, ErrorCode
from app.core.logging import get_logger

logger = get_logger(__name__)

# 百炼单条输入上限（token），留一点余量
MAX_TOKENS_PER_INPUT = 8000


@dataclass
class EmbeddingResult:
    vectors: list[list[float]]
    prompt_tokens: int = 0
    total_tokens: int = 0


@dataclass
class UsageMeter:
    """累计用量，用于成本核算与熔断。"""

    prompt_tokens: int = 0
    calls: int = 0
    failures: int = 0
    by_model: dict[str, int] = field(default_factory=dict)

    def add(self, model: str, tokens: int) -> None:
        self.prompt_tokens += tokens
        self.by_model[model] = self.by_model.get(model, 0) + tokens
        self.calls += 1

    def summary(self) -> dict:
        return {
            "calls": self.calls,
            "failures": self.failures,
            "prompt_tokens": self.prompt_tokens,
            "by_model": dict(self.by_model),
        }


def _rough_token_len(text: str) -> int:
    """粗略估算 token 数，仅用于入库前的超长拦截。

    中文按 ~1.5 token/字，英文按 ~1 token/4 字符，取较大值，宁可高估。
    """
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    other = len(text) - cjk
    return int(cjk * 1.8 + other / 3.5) + 1


class EmbeddingClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        batch_size: int | None = None,
        concurrency: int | None = None,
        timeout: float = 40.0,
    ) -> None:
        self.api_key = api_key or settings.dashscope_api_key
        self.base_url = (base_url or settings.dashscope_base_url).rstrip("/")
        self.model = model or settings.embedding_model
        self.batch_size = min(batch_size or settings.embedding_batch_size, 10)  # 硬上限 10
        self.concurrency = concurrency or settings.embedding_concurrency
        self.timeout = timeout
        self.usage = UsageMeter()

    @property
    def dim(self) -> int:
        return settings.embedding_dim

    async def _post_batch(self, client: httpx.AsyncClient, batch: list[str]) -> EmbeddingResult:
        payload = {"model": self.model, "input": batch, "encoding_format": "float"}

        last_err: str = ""
        for attempt in range(4):
            try:
                resp = await client.post(
                    f"{self.base_url}/embeddings",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=payload,
                )
                if resp.status_code == 200:
                    body = resp.json()
                    # 按 index 排序，防止返回乱序导致向量与文本错位
                    items = sorted(body["data"], key=lambda x: x["index"])
                    vectors = [it["embedding"] for it in items]
                    usage = body.get("usage", {}) or {}
                    tokens = int(usage.get("prompt_tokens", 0) or 0)
                    self.usage.add(self.model, tokens)
                    return EmbeddingResult(vectors, tokens, int(usage.get("total_tokens", 0) or 0))

                # 4xx 不重试（除 429）
                if resp.status_code == 429:
                    last_err = "429 限流"
                elif resp.status_code >= 500:
                    last_err = f"{resp.status_code} 服务端错误"
                else:
                    body_txt = resp.text[:300]
                    raise AppError(
                        f"Embedding 调用失败：{body_txt}",
                        code=ErrorCode.MODEL_CALL_FAILED,
                        status_code=502,
                        detail={"status": resp.status_code, "model": self.model},
                    )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_err = f"{type(exc).__name__}: {exc}"

            # 指数退避 + 抖动，避免多 worker 同时重试打爆限流
            wait = (2**attempt) * 0.5 + random.uniform(0, 0.3)
            logger.warning(
                "embedding_retry", attempt=attempt + 1, wait=round(wait, 2), reason=last_err
            )
            await asyncio.sleep(wait)

        self.usage.failures += 1
        raise AppError(
            f"Embedding 重试 4 次仍失败：{last_err}",
            code=ErrorCode.MODEL_RATE_LIMITED,
            status_code=503,
        )

    async def embed_documents(self, texts: list[str]) -> EmbeddingResult:
        """批量向量化文档切片。"""
        if not texts:
            return EmbeddingResult([])

        # 超长文本单独截断，避免拖垮整批
        safe_texts: list[str] = []
        for t in texts:
            if _rough_token_len(t) > MAX_TOKENS_PER_INPUT:
                logger.warning("chunk_too_long_truncated", chars=len(t))
                safe_texts.append(t[: MAX_TOKENS_PER_INPUT])
            else:
                safe_texts.append(t)

        batches = [
            safe_texts[i : i + self.batch_size]
            for i in range(0, len(safe_texts), self.batch_size)
        ]
        sem = asyncio.Semaphore(self.concurrency)

        async with httpx.AsyncClient(timeout=self.timeout) as client:

            async def run(batch: list[str]) -> EmbeddingResult:
                async with sem:
                    return await self._post_batch(client, batch)

            results = await asyncio.gather(*(run(b) for b in batches))

        vectors: list[list[float]] = []
        tokens = 0
        for r in results:
            vectors.extend(r.vectors)
            tokens += r.prompt_tokens

        if vectors and len(vectors[0]) != self.dim:
            raise AppError(
                f"向量维度不匹配：模型返回 {len(vectors[0])}，配置为 {self.dim}",
                code=ErrorCode.EMBEDDING_DIM_MISMATCH,
                status_code=500,
            )
        return EmbeddingResult(vectors, tokens)

    async def embed_query(self, text: str) -> list[float]:
        res = await self.embed_documents([text])
        if not res.vectors:
            raise AppError("查询向量化失败", code=ErrorCode.MODEL_CALL_FAILED, status_code=502)
        return res.vectors[0]


_client: EmbeddingClient | None = None


def get_embedding_client() -> EmbeddingClient:
    global _client
    if _client is None:
        _client = EmbeddingClient()
    return _client
