"""认证接口。"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.security import HTTPAuthorizationCredentials

from app.core.deps import CurrentUser, DbSession, bearer_scheme, get_client_ip
from app.core.errors import AppError, ErrorCode
from app.core.security import hash_password, verify_password
from app.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    RefreshRequest,
    TokenResponse,
    UserInfo,
)
from app.services import auth_service

router = APIRouter()


@router.post("/login", response_model=TokenResponse, summary="账号密码登录")
async def login(
    payload: LoginRequest,
    request: Request,
    db: DbSession,
) -> TokenResponse:
    _, tokens = await auth_service.authenticate(
        db, payload.username, payload.password, get_client_ip(request)
    )
    return tokens


@router.post("/refresh", response_model=TokenResponse, summary="刷新令牌（旧 refresh 立即失效）")
async def refresh(payload: RefreshRequest, db: DbSession) -> TokenResponse:
    _, tokens = await auth_service.rotate_refresh(db, payload.refresh_token)
    return tokens


@router.post("/logout", summary="登出")
async def logout(
    db: DbSession,
    user: CurrentUser,
    payload: RefreshRequest | None = None,
    cred: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
) -> dict:
    access_token = cred.credentials if cred else None
    await auth_service.logout(access_token, payload.refresh_token if payload else None)
    return {"message": "已退出登录"}


@router.get("/me", response_model=UserInfo, summary="当前用户信息与权限")
async def me(user: CurrentUser) -> UserInfo:
    return auth_service.to_user_info(user)


@router.post("/change-password", summary="修改自己的密码")
async def change_password(
    payload: ChangePasswordRequest,
    db: DbSession,
    user: CurrentUser,
) -> dict:
    if not verify_password(payload.old_password, user.password_hash):
        raise AppError("原密码不正确", code=ErrorCode.BAD_CREDENTIALS, status_code=400)

    user.password_hash = hash_password(payload.new_password)
    await db.commit()

    # 踢掉所有设备的 refresh，旧会话无法续期；access 最长 30 分钟后自然失效
    await auth_service.revoke_all_for_user(user.id)
    return {"message": "密码已修改，请重新登录"}
