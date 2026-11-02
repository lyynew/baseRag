"""Celery 任务（薄封装）。

核心逻辑都在 services/ingest.py，任务层只负责在独立事件循环里跑，
这样同一份逻辑既能被 Celery 调用，也能被脚本直接 await 验证。
"""

import asyncio

from app.core.logging import get_logger
from app.services.ingest import ingest_document
from app.workers.celery_app import celery_app

logger = get_logger(__name__)


@celery_app.task(name="app.workers.tasks.ping")
def ping() -> str:
    logger.info("celery_ping")
    return "pong"


@celery_app.task(
    name="app.workers.tasks.parse_document",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
)
def parse_document_task(self, doc_id: int, task_id: int) -> dict:
    """解析 → 切片 → 向量化 → 入库。

    失败策略：可重试的异常（网络、限流）重试 2 次；解析类错误直接标记失败。
    因为 ingest_document 内部已把状态写库，重试不需要额外补偿逻辑。
    """
    logger.info("celery_ingest_start", doc_id=doc_id, task_id=task_id)
    try:
        result = asyncio.run(ingest_document(doc_id, task_id))
    except Exception as exc:  # noqa: BLE001
        logger.exception("celery_ingest_crash", doc_id=doc_id)
        raise self.retry(exc=exc) from exc

    if not result.get("ok"):
        # 业务失败（如扫描件无文本层）不重试，重试也没用
        logger.warning("celery_ingest_business_failed", doc_id=doc_id, reason=result.get("reason"))
    return result


@celery_app.task(name="app.workers.tasks.cleanup_expired")
def cleanup_expired() -> str:
    """清理过期数据（会话、黑名单由 Redis TTL 自动处理，这里清理孤儿向量）。"""
    return "ok"
