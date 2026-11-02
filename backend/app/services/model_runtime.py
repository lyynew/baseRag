"""模型运行时配置：优先读数据库，回退环境变量。

为什么要有这一层：
- 后台要能切换模型（DeepSeek ↔ MiMo）而不用重启服务，所以配置必须落库
- 首次部署时数据库还没数据，必须能回退到 .env，否则起不来
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.db.models.chat import ModelConfig
from app.services.crypto import decrypt_secret

logger = get_logger(__name__)


@dataclass
class ModelRuntime:
    provider: str
    base_url: str
    api_key: str
    model: str
    max_context: int = 32768
    max_output: int = 4096
    supports_json: bool = True
    supports_stream: bool = True
    source: str = "env"  # env | db


def _from_env(provider: str) -> ModelRuntime:
    if provider == "mimo":
        return ModelRuntime(
            provider="mimo",
            base_url=settings.mimo_base_url,
            api_key=settings.mimo_api_key,
            model=settings.mimo_model,
            supports_json=True,
            source="env",
        )
    return ModelRuntime(
        provider="deepseek",
        base_url=settings.deepseek_base_url,
        api_key=settings.deepseek_api_key,
        model=settings.deepseek_model,
        supports_json=True,
        source="env",
    )


async def load_model_runtime(
    db: AsyncSession, provider: str | None = None
) -> ModelRuntime:
    """按 provider 取启用中的配置；未指定则取默认。都查不到就回退 .env。"""
    provider = (provider or settings.default_chat_provider or "deepseek").lower()

    stmt = select(ModelConfig).where(
        ModelConfig.provider == provider, ModelConfig.enabled.is_(True)
    )
    # 同 provider 多条时优先默认
    stmt = stmt.order_by(ModelConfig.is_default.desc(), ModelConfig.id.asc())
    row = (await db.execute(stmt)).scalars().first()

    if row is None:
        logger.debug("model_config_fallback_env", provider=provider)
        return _from_env(provider)

    try:
        api_key = decrypt_secret(row.api_key_enc)
    except Exception:  # noqa: BLE001
        logger.exception("model_config_decrypt_failed", provider=provider)
        # 数据库配置坏了也不能让问答彻底不可用，回退环境变量
        return _from_env(provider)

    return ModelRuntime(
        provider=row.provider,
        base_url=row.base_url,
        api_key=api_key,
        model=row.model,
        max_context=row.max_context,
        max_output=row.max_output,
        supports_json=row.supports_json,
        supports_stream=row.supports_stream,
        source="db",
    )


async def load_default_runtime(db: AsyncSession) -> ModelRuntime:
    row = (
        await db.execute(
            select(ModelConfig).where(
                ModelConfig.enabled.is_(True), ModelConfig.is_default.is_(True)
            )
        )
    ).scalars().first()
    if row is not None:
        return await load_model_runtime(db, row.provider)
    return await load_model_runtime(db, settings.default_chat_provider)
