"""Rerank 服务（百炼 gte-rerank-v2）。

注意：Rerank 不走 OpenAI 兼容协议，用的是 DashScope 原生接口，所以单独封装。

作用：向量召回只看"语义整体相近"，容易把主题相似但答非所问的段落排前面。
Cross-encoder 会逐条比较 query 与候选，区分度显著更高（实测无关段落分数可降到 0.01 以下）。
链路：召回 top 30 → rerank → 取 top 5~8 喂给大模型。
"""

import asyncio
import random

import httpx

from app.core.config import settings
from app.core.errors import AppError, ErrorCode
from app.core.logging import get_logger

logger = get_logger(__name__)

RERANK_URL = (
    "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank"
)

# 一次 rerank 的候选上限，控制计费（输入是 query × N）
MAX_CANDIDATES = 100


class RerankClient:
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.api_key = api_key or settings.dashscope_api_key
        self.model = model or settings.rerank_model
        self.timeout = timeout
        self.total_tokens = 0

    async def rerank(
        self,
        query: str,
        documents: list[str],
        top_n: int = 8,
    ) -> list[tuple[int, float]]:
        """返回 [(原始下标, 相关性分数)]，按分数降序。"""
        if not documents or not settings.rerank_enabled:
            return [(i, 0.0) for i in range(len(documents))][:top_n]

        docs = documents[:MAX_CANDIDATES]
        payload = {
            "model": self.model,
            "input": {"query": query, "documents": docs},
            "parameters": {"return_documents": False, "top_n": min(top_n, len(docs))},
        }

        last_err = ""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for attempt in range(3):
                try:
                    resp = await client.post(
                        RERANK_URL,
                        headers={"Authorization": f"Bearer {self.api_key}"},
                        json=payload,
                    )
                    if resp.status_code == 200:
                        body = resp.json()
                        self.total_tokens += int(body.get("usage", {}).get("total_tokens", 0) or 0)
                        results = body["output"]["results"]
                        return [(int(r["index"]), float(r["relevance_score"])) for r in results]

                    if resp.status_code in (429,) or resp.status_code >= 500:
                        last_err = f"{resp.status_code}"
                    else:
                        raise AppError(
                            f"Rerank 调用失败：{resp.text[:200]}",
                            code=ErrorCode.MODEL_CALL_FAILED,
                            status_code=502,
                        )
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    last_err = f"{type(exc).__name__}: {exc}"

                await asyncio.sleep((2**attempt) * 0.5 + random.uniform(0, 0.3))

        logger.warning("rerank_failed_fallback", reason=last_err)
        # 降级：保持召回顺序，不让 rerank 故障阻断整条问答链路
        return [(i, 0.0) for i in range(len(docs))][:top_n]


_client: RerankClient | None = None


def get_rerank_client() -> RerankClient:
    global _client
    if _client is None:
        _client = RerankClient()
    return _client
