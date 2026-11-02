"""认证服务：登录、令牌签发与轮换、登出。

安全设计：
- access 短（30 分钟）不落库，登出靠 Redis 黑名单拦截剩余有效期
- refresh 长（7 天）必须存在于 Redis 白名单，否则无效 → 可用于"踢人"
- 刷新时轮换：旧 refresh 立即作废，防止重放
- 登录失败计数落 MySQL（重启不丢），达到阈值锁定账号
"""

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError, ErrorCode
from app.core.logging import get_logger
from app.core.rbac import user_permission_codes
from app.core.redis_client import KEY_DENYLIST, KEY_REFRESH, KEY_USER_REFRESH, get_redis
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    token_remaining_seconds,
    verify_password,
)
from app.db.models.auth import User
from app.schemas.auth import RoleBrief, TokenResponse, UserInfo

logger = get_logger(__name__)


async def _get_user_by_username(db: AsyncSession, username: str) -> User | None:
    return (
        await db.execute(
            select(User).where(User.username == username, User.is_deleted == 0)
        )
    ).scalar_one_or_none()


async def _issue_tokens(user: User) -> TokenResponse:
    """签发双 Token，并把 refresh 的 jti 写入 Redis 白名单。"""
    access = create_access_token(user.id)
    refresh = create_refresh_token(user.id)

    payload = decode_token(refresh, "refresh")
    ttl = token_remaining_seconds(payload)
    jti = payload["jti"]
    redis = get_redis()
    try:
        await redis.set(KEY_REFRESH.format(jti=jti), str(user.id), ex=ttl)
        # 按用户维度登记，支持"改密码后踢掉所有设备"
        user_key = KEY_USER_REFRESH.format(user_id=user.id)
        await redis.sadd(user_key, jti)
        await redis.expire(user_key, settings.refresh_token_expire_days * 86400)
    finally:
        await redis.aclose()

    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        expires_in=settings.access_token_expire_minutes * 60,
    )


async def authenticate(
    db: AsyncSession, username: str, password: str, ip: str
) -> tuple[User, TokenResponse]:
    user = await _get_user_by_username(db, username)

    # 统一提示，避免通过报错差异枚举用户名
    bad_cred = AppError("用户名或密码错误", code=ErrorCode.BAD_CREDENTIALS, status_code=401)

    if user is None:
        logger.info("login_failed", username=username, reason="user_not_found", ip=ip)
        raise bad_cred

    now = datetime.now()
    if user.locked_until and user.locked_until > now:
        remain = int((user.locked_until - now).total_seconds() // 60) + 1
        raise AppError(
            f"账号已锁定，请 {remain} 分钟后再试",
            code=ErrorCode.ACCOUNT_LOCKED,
            status_code=423,
        )

    if not user.is_active:
        raise AppError("账号已被禁用", code=ErrorCode.ACCOUNT_DISABLED, status_code=403)

    if not verify_password(password, user.password_hash):
        user.failed_login_count += 1
        if user.failed_login_count >= settings.login_max_fail:
            user.locked_until = now + timedelta(seconds=settings.login_lock_seconds)
            user.failed_login_count = 0
            logger.warning(
                "account_locked",
                username=username,
                lock_seconds=settings.login_lock_seconds,
                ip=ip,
            )
        else:
            logger.info(
                "login_failed",
                username=username,
                reason="bad_password",
                fail_count=user.failed_login_count,
                ip=ip,
            )
        await db.commit()
        raise bad_cred

    # 登录成功
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now
    user.last_login_ip = ip
    await db.commit()
    await db.refresh(user)

    tokens = await _issue_tokens(user)
    logger.info("login_success", user_id=user.id, username=user.username, ip=ip)
    return user, tokens


async def rotate_refresh(db: AsyncSession, refresh_token: str) -> tuple[User, TokenResponse]:
    """刷新令牌：校验白名单 → 作废旧 refresh → 签发新的一对。"""
    payload = decode_token(refresh_token, "refresh")
    jti = payload.get("jti", "")

    redis = get_redis()
    try:
        key = KEY_REFRESH.format(jti=jti)
        exists = await redis.exists(key)
        if not exists:
            raise AppError(
                "登录已失效，请重新登录", code=ErrorCode.TOKEN_INVALID, status_code=401
            )
        await redis.delete(key)
    finally:
        await redis.aclose()

    user_id = int(payload["sub"])
    user = (
        await db.execute(
            select(User).where(User.id == user_id, User.is_deleted == 0)
        )
    ).scalar_one_or_none()
    if user is None or not user.is_active:
        raise AppError("账号不可用", code=ErrorCode.ACCOUNT_DISABLED, status_code=403)

    tokens = await _issue_tokens(user)
    logger.info("token_rotated", user_id=user.id)
    return user, tokens


async def logout(access_token: str | None, refresh_token: str | None) -> None:
    """登出：access 进黑名单（剩余有效期），refresh 从白名单移除。"""
    redis = get_redis()
    try:
        if access_token:
            try:
                payload = decode_token(access_token, "access")
                ttl = token_remaining_seconds(payload)
                if ttl > 0:
                    await redis.set(KEY_DENYLIST.format(jti=payload.get("jti", "")), "1", ex=ttl)
            except AppError:
                pass  # token 已过期，无需处理

        if refresh_token:
            try:
                payload = decode_token(refresh_token, "refresh")
                jti = payload.get("jti", "")
                await redis.delete(KEY_REFRESH.format(jti=jti))
                await redis.srem(
                    KEY_USER_REFRESH.format(user_id=payload.get("sub")), jti
                )
            except AppError:
                pass
    finally:
        await redis.aclose()


async def revoke_all_for_user(user_id: int) -> int:
    """踢掉某用户在所有设备上的登录态（改密码、禁用账号时调用）。"""
    redis = get_redis()
    removed = 0
    try:
        user_key = KEY_USER_REFRESH.format(user_id=user_id)
        jtis = await redis.smembers(user_key)
        if jtis:
            await redis.delete(*[KEY_REFRESH.format(jti=j) for j in jtis])
            removed = len(jtis)
        await redis.delete(user_key)
    finally:
        await redis.aclose()

    if removed:
        logger.info("revoke_all_sessions", user_id=user_id, count=removed)
    return removed


def to_user_info(user: User) -> UserInfo:
    codes = user_permission_codes(user)
    return UserInfo(
        id=user.id,
        username=user.username,
        nickname=user.nickname,
        email=user.email,
        avatar=user.avatar,
        is_superuser=user.is_superuser,
        roles=[RoleBrief(code=r.code, name=r.name) for r in user.roles],
        permissions=sorted(c for c in codes if c != "*"),
    )
