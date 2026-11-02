"""异步数据库会话。

数据库不可用时应用仍可启动（dev 便利），/health 会明确报 down。
生产环境由 config.validate_for_prod() 拦下这种配置。
"""

from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

engine = create_async_engine(
    settings.mysql_dsn,
    echo=settings.mysql_echo,
    pool_size=settings.mysql_pool_size,
    max_overflow=settings.mysql_max_overflow,
    pool_pre_ping=True,     # 断线自动重连，避免 MySQL wait_timeout 掉连接后报错
    pool_recycle=1800,
)

SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖：每个请求一个会话，异常自动回滚。"""
    async with SessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def check_db() -> tuple[bool, str | None]:
    """连通性检查，供 /health 使用。"""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True, None
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"
