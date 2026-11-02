"""Celery 应用。

队列设计（关键）：
- parse    : 解析 + 切片，CPU/IO 密集、内存峰值高 → 独立 worker，并发 1
- embed    : 向量化，网络密集、有 QPS 限流 → 独立 worker，并发可高
- default  : 轻量任务（清理、统计）

大文件必须走 parse 队列的专用 worker，否则会拖死普通文档的解析。
"""

from celery import Celery

from app.core.config import settings

broker_url = (
    f"redis://{':' + settings.redis_password + '@' if settings.redis_password else ''}"
    f"{settings.redis_host}:{settings.redis_port}/{settings.celery_broker_db}"
)
backend_url = (
    f"redis://{':' + settings.redis_password + '@' if settings.redis_password else ''}"
    f"{settings.redis_host}:{settings.redis_port}/{settings.celery_backend_db}"
)

celery_app = Celery(
    "rag",
    broker=broker_url,
    backend=backend_url,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Shanghai",
    enable_utc=False,
    # 任务超时：解析允许 30 分钟，向量化 20 分钟
    task_time_limit=1800,
    task_soft_time_limit=1740,
    # 避免 worker 崩溃后任务永久卡住
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    result_expires=86400,
    task_routes={
        "app.workers.tasks.parse_document": {"queue": "parse"},
        "app.workers.tasks.embed_chunks": {"queue": "embed"},
        "app.workers.tasks.reindex_kb": {"queue": "parse"},
        "app.workers.tasks.cleanup_expired": {"queue": "default"},
    },
    task_default_queue="default",
)
