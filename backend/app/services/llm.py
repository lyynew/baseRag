"""对话模型客户端（DeepSeek / MiMo，均为 OpenAI 兼容协议）。

双通道的关键约束（见技术选型 §6.5.1）：
- prompt 里不能有任何厂商专有标记，只用标准 system/user/assistant
- max_tokens 必须显式传，两家默认值都偏小，不传会出现"答案说一半就断"
- tokenizer 不同，成本统计必须按模型分开累计
- MiMo 是推理模型，会额外产生 reasoning_tokens（付费但通常不展示给用户）

超时策略：首 token 30s、整体 120s。不要用 httpx 默认的 5s，长回答一定超时。
"""

import json
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Literal

import httpx

from app.core.config import settings
from app.core.errors import AppError, ErrorCode
from app.core.logging import get_logger
from app.services.model_runtime import ModelRuntime

logger = get_logger(__name__)

Provider = Literal["deepseek", "mimo"]

CONNECT_TIMEOUT = 10.0
READ_TIMEOUT = 120.0


@dataclass
class ChatResult:
    content: str
    reasoning: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    finish_reason: str = "stop"
    model: str = ""
    provider: str = ""


@dataclass
class StreamStats:
    content: str = ""
    reasoning: str = ""
    chunks: int = 0
    ttft_ms: int | None = None
    total_ms: int = 0
    extra: dict = field(default_factory=dict)


class LlmClient:
    def __init__(
        self,
        provider: Provider | None = None,
        runtime: ModelRuntime | None = None,
    ) -> None:
        self.max_context = 32768
        if runtime is not None:
            # 来自数据库的配置（后台可改，改完立刻生效）
            self.provider = runtime.provider
            self.base_url = runtime.base_url.rstrip("/")
            self.api_key = runtime.api_key
            self.model = runtime.model
            self.supports_json = runtime.supports_json
            self.max_context = runtime.max_context
            self.max_output = runtime.max_output
            self.source = runtime.source
        else:
            self.provider = (provider or settings.default_chat_provider).lower()
            self.base_url, self.api_key, self.model, self.supports_json = self._resolve(
                self.provider
            )
            self.max_output = 2048
            self.source = "env"

    @staticmethod
    def _resolve(provider: str) -> tuple[str, str, str, bool]:
        if provider == "mimo":
            return (
                settings.mimo_base_url.rstrip("/"),
                settings.mimo_api_key,
                settings.mimo_model,
                True,  # 实测 mimo-v2.6-flash 支持 json_object
            )
        return (
            settings.deepseek_base_url.rstrip("/"),
            settings.deepseek_api_key,
            settings.deepseek_model,
            True,
        )

    def _ensure_configured(self) -> None:
        missing = []
        if not self.base_url:
            missing.append(f"{self.provider.upper()}_BASE_URL")
        if not self.api_key:
            missing.append(f"{self.provider.upper()}_API_KEY")
        if not self.model:
            missing.append(f"{self.provider.upper()}_MODEL")
        if missing:
            raise AppError(
                f"模型未配置完整，缺少：{', '.join(missing)}",
                code=ErrorCode.MODEL_NOT_CONFIGURED,
                status_code=503,
            )

    def _payload(
        self,
        messages: list[dict],
        *,
        temperature: float,
        max_tokens: int,
        json_mode: bool,
        stream: bool,
    ) -> dict:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }
        if json_mode and self.supports_json:
            payload["response_format"] = {"type": "json_object"}
        return payload

    async def chat(
        self,
        messages: list[dict],
        *,
        temperature: float = 0.3,
        max_tokens: int = 2048,
        json_mode: bool = False,
    ) -> ChatResult:
        self._ensure_configured()
        started = time.perf_counter()

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(READ_TIMEOUT, connect=CONNECT_TIMEOUT)
        ) as client:
            try:
                resp = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=self._payload(
                        messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        json_mode=json_mode,
                        stream=False,
                    ),
                )
            except httpx.TimeoutException as exc:
                raise AppError(
                    "模型响应超时，请稍后重试", code=ErrorCode.MODEL_CALL_FAILED, status_code=504
                ) from exc
            except httpx.TransportError as exc:
                raise AppError(
                    f"无法连接模型服务：{exc}", code=ErrorCode.MODEL_CALL_FAILED, status_code=502
                ) from exc

        latency = int((time.perf_counter() - started) * 1000)
        if resp.status_code != 200:
            raise AppError(
                f"模型返回错误：{resp.text[:200]}",
                code=ErrorCode.MODEL_CALL_FAILED,
                status_code=502,
            )

        body = resp.json()
        choice = body["choices"][0]
        msg = choice.get("message", {})
        usage = body.get("usage", {}) or {}

        return ChatResult(
            content=msg.get("content") or "",
            reasoning=msg.get("reasoning_content") or "",
            prompt_tokens=int(usage.get("prompt_tokens", 0) or 0),
            completion_tokens=int(usage.get("completion_tokens", 0) or 0),
            latency_ms=latency,
            finish_reason=choice.get("finish_reason") or "stop",
            model=self.model,
            provider=self.provider,
        )

    async def astream(
        self,
        messages: list[dict],
        *,
        temperature: float = 0.3,
        max_tokens: int = 2048,
        stats: StreamStats | None = None,
    ) -> AsyncIterator[str]:
        """流式生成，逐段 yield 正文增量（不含 reasoning，避免前端混入思考过程）。"""
        self._ensure_configured()
        stats = stats if stats is not None else StreamStats()
        started = time.perf_counter()

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(READ_TIMEOUT, connect=CONNECT_TIMEOUT)
        ) as client:
            try:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=self._payload(
                        messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        json_mode=False,
                        stream=True,
                    ),
                ) as resp:
                    if resp.status_code != 200:
                        raw = await resp.aread()
                        raise AppError(
                            f"模型返回错误：{raw[:200].decode('utf-8', 'ignore')}",
                            code=ErrorCode.MODEL_CALL_FAILED,
                            status_code=502,
                        )

                    async for line in resp.aiter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            obj = json.loads(data)
                        except json.JSONDecodeError:
                            continue

                        choices = obj.get("choices") or []
                        if not choices:
                            # 部分厂商在最后一个包单独回 usage
                            if obj.get("usage"):
                                stats.extra["usage"] = obj["usage"]
                            continue

                        delta = choices[0].get("delta") or {}
                        piece = delta.get("content")
                        if delta.get("reasoning_content"):
                            stats.reasoning += delta["reasoning_content"]

                        if piece:
                            if stats.ttft_ms is None:
                                stats.ttft_ms = int((time.perf_counter() - started) * 1000)
                            stats.chunks += 1
                            stats.content += piece
                            yield piece
            except httpx.TimeoutException as exc:
                raise AppError(
                    "模型流式响应超时", code=ErrorCode.MODEL_CALL_FAILED, status_code=504
                ) from exc

        stats.total_ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            "llm_stream_done",
            provider=self.provider,
            model=self.model,
            chunks=stats.chunks,
            ttft_ms=stats.ttft_ms,
            total_ms=stats.total_ms,
        )


def get_llm(
    provider: Provider | None = None, runtime: ModelRuntime | None = None
) -> LlmClient:
    return LlmClient(provider, runtime)
