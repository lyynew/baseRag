"""应用入口。

启动顺序：日志 → 配置自检 → 建表检查（仅提示，不自动迁移）→ 挂载路由。
"""

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.api.v1.health import router as health_router
from app.core.config import settings
from app.core.errors import register_exception_handlers
from app.core.logging import get_logger, set_trace_id, setup_logging
from app.db.session import check_db

setup_logging(level=settings.log_level, json_output=settings.log_json)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    logger.info(
        "app_starting",
        app=settings.app_name,
        env=settings.app_env,
        api_prefix=settings.api_v1_prefix,
    )

    # 生产配置自检：缺密钥等问题直接拒绝启动，而不是运行到一半才炸
    problems = settings.validate_for_prod()
    if problems:
        for p in problems:
            logger.error("config_invalid", problem=p)
        raise RuntimeError(f"生产配置校验失败：{'；'.join(problems)}")

    db_ok, db_err = await check_db()
    if db_ok:
        logger.info("mysql_connected", host=settings.mysql_host, db=settings.mysql_db)
    else:
        logger.warning("mysql_unavailable", error=db_err)
        if not settings.mysql_allow_startup_without_db:
            raise RuntimeError(f"MySQL 连接失败：{db_err}")

    logger.info(
        "app_ready",
        embedding_model=settings.embedding_model,
        chat_provider=settings.default_chat_provider,
        milvus_collection=settings.milvus_collection,
    )
    yield
    logger.info("app_stopped")


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    docs_url="/docs" if not settings.is_prod else None,
    redoc_url=None,
    openapi_url="/openapi.json" if not settings.is_prod else None,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Trace-Id"],
)


@app.middleware("http")
async def trace_and_timing(request: Request, call_next):
    """为每个请求分配 trace_id，并记录耗时。前端报错时可凭 trace_id 定位。"""
    incoming = request.headers.get("X-Trace-Id")
    tid = incoming or structlog.contextvars.get_contextvars().get("trace_id")
    if not tid:
        from app.core.logging import new_trace_id

        tid = new_trace_id()
    # 两个 context 都要设：structlog 的用于日志字段，自有 ContextVar 用于错误响应体
    structlog.contextvars.bind_contextvars(trace_id=tid)
    set_trace_id(tid)

    started = time.perf_counter()
    try:
        response = await call_next(request)
    finally:
        structlog.contextvars.unbind_contextvars("trace_id")

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    response.headers["X-Trace-Id"] = tid

    if request.url.path not in ("/health", "/metrics"):
        logger.info(
            "http_request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            elapsed_ms=elapsed_ms,
            trace_id=tid,
        )
    # 慢请求单独打点，便于优化
    if elapsed_ms > 3000:
        logger.warning(
            "slow_request",
            method=request.method,
            path=request.url.path,
            elapsed_ms=elapsed_ms,
            trace_id=tid,
        )
    return response


register_exception_handlers(app)
# 健康检查挂根路径：K8s 探针、Nginx 上游检查、运维脚本都用 /health
app.include_router(health_router)
app.include_router(api_router, prefix=settings.api_v1_prefix)


@app.get("/", include_in_schema=False)
async def root() -> JSONResponse:
    return JSONResponse(
        {
            "app": settings.app_name,
            "version": "0.1.0",
            "docs": "/docs" if not settings.is_prod else None,
            "api": settings.api_v1_prefix,
        }
    )
