"""Redis 客户端。

用途：refresh token 白名单（可主动踢人）、登录失败计数、检索结果缓存、分布式锁、限流令牌桶。
"""

from redis.asyncio import ConnectionPool, Redis

from app.core.config import settings

_pool = ConnectionPool.from_url(
    settings.redis_url,
    max_connections=32,
    socket_connect_timeout=3,
    socket_timeout=5,
    decode_responses=True,
)


def get_redis() -> Redis:
    """注意：Redis 客户端是长连接池，不要每个请求新建后关闭。"""
    return Redis(connection_pool=_pool)


# ---- Key 规范（统一前缀，避免与 Celery 的 db 混用）----
KEY_REFRESH = "rag:auth:refresh:{jti}"          # value: user_id, TTL = refresh 有效期
KEY_USER_REFRESH = "rag:auth:uref:{user_id}"    # set: 该用户所有有效 refresh 的 jti
KEY_DENYLIST = "rag:auth:deny:{jti}"            # value: "1", TTL = token 剩余时间
KEY_LOGIN_FAIL = "rag:auth:fail:{username}"     # 连续失败计数
KEY_LOCK = "rag:auth:lock:{username}"           # 账号锁定标记
KEY_KEEPALIVE = "rag:celery:worker:alive"       # worker 存活心跳（compose healthcheck 用）


async def close_redis() -> None:
    await _pool.disconnect()
