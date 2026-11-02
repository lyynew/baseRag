"""健康检查。

分开两个端点：
- /health     轻量，供 K8s liveness/readiness 与前端探活
- /health/deep 深检，依赖全部挨个查，运维用
"""

import time

from fastapi import APIRouter
from redis.asyncio import Redis

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import check_db

router = APIRouter(tags=["health"])
logger = get_logger(__name__)

_started_at = time.time()


@router.get("/health", summary="存活检查")
async def health() -> dict:
    db_ok, db_err = await check_db()
    return {
        "status": "ok" if db_ok else "degraded",
        "app": settings.app_name,
        "env": settings.app_env,
        "uptime_seconds": int(time.time() - _started_at),
        "dependencies": {"mysql": "up" if db_ok else f"down: {db_err}"},
    }


@router.get("/health/deep", summary="依赖深检")
async def health_deep() -> dict:
    result: dict[str, object] = {}

    db_ok, db_err = await check_db()
    result["mysql"] = {"ok": db_ok, "error": db_err}

    # Redis
    redis_ok, redis_err = True, None
    client = Redis.from_url(settings.redis_url, socket_connect_timeout=3)
    try:
        await client.ping()
    except Exception as exc:  # noqa: BLE001
        redis_ok, redis_err = False, f"{type(exc).__name__}: {exc}"
    finally:
        await client.aclose()
    result["redis"] = {"ok": redis_ok, "error": redis_err}

    # Milvus：连接较重，仅在深检时尝试
    milvus_ok, milvus_err, collection_exists = True, None, False
    try:
        from pymilvus import connections, utility
    except ImportError:
        result["milvus"] = {"ok": True, "skipped": "pymilvus 未安装（仅跑 API 时正常）"}
    else:
        try:
            connections.connect(
                alias="health",
                host=settings.milvus_host,
                port=str(settings.milvus_port),
                timeout=3,
            )
            collection_exists = utility.has_collection(settings.milvus_collection, using="health")
            connections.disconnect("health")
        except Exception as exc:  # noqa: BLE001
            milvus_ok, milvus_err = False, f"{type(exc).__name__}: {exc}"
        result["milvus"] = {
            "ok": milvus_ok,
            "collection_exists": collection_exists,
            "error": milvus_err,
        }

    # 配置完整性
    problems = settings.validate_for_prod()
    result["config"] = {"ok": not problems, "problems": problems}

    all_ok = all(bool(v.get("ok")) for v in result.values() if isinstance(v, dict))  # type: ignore[union-attr]
    return {"status": "ok" if all_ok else "degraded", "checks": result}
