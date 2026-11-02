"""FastAPI 依赖：当前用户、权限校验、审计上下文。"""

from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ErrorCode, ForbiddenError
from app.core.rbac import ensure_permission
from app.core.redis_client import KEY_DENYLIST, get_redis
from app.core.security import decode_token
from app.db.models.auth import User
from app.db.session import get_db

bearer_scheme = HTTPBearer(auto_error=False, description="Bearer <access_token>")

DbSession = Annotated[AsyncSession, Depends(get_db)]


async def get_current_user(
    db: DbSession,
    cred: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
) -> User:
    if cred is None or not cred.credentials:
        raise AppError("请先登录", code=ErrorCode.UNAUTHORIZED, status_code=401)

    payload = decode_token(cred.credentials, "access")

    # 登出后 token 进黑名单，剩余有效期内一律拒绝
    jti = payload.get("jti", "")
    if jti:
        redis = get_redis()
        try:
            if await redis.exists(KEY_DENYLIST.format(jti=jti)):
                raise AppError(
                    "登录已失效，请重新登录",
                    code=ErrorCode.TOKEN_INVALID,
                    status_code=401,
                )
        finally:
            await redis.aclose()

    user_id = int(payload["sub"])
    user = (
        await db.execute(
            select(User).where(User.id == user_id, User.is_deleted == 0)
        )
    ).scalar_one_or_none()

    if user is None:
        raise AppError("用户不存在", code=ErrorCode.TOKEN_INVALID, status_code=401)
    if not user.is_active:
        raise AppError("账号已被禁用", code=ErrorCode.ACCOUNT_DISABLED, status_code=403)
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_perm(*codes: str, mode: str = "all"):
    """接口级权限校验。

    用法：
        @router.post("/kb", dependencies=[Depends(require_perm("kb:write"))])
    或需要拿到用户时：
        async def create_kb(user: CurrentUser, _: None = Depends(require_perm("kb:write")))
    """

    async def _checker(user: CurrentUser) -> None:
        ensure_permission(user, list(codes), mode=mode)

    return _checker


def require_superuser(user: CurrentUser) -> None:
    if not user.is_superuser:
        raise ForbiddenError("仅超级管理员可执行该操作")


def get_client_ip(request: Request) -> str:
    """取真实 IP：优先 X-Forwarded-For（Nginx 场景），其次直连地址。"""
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
