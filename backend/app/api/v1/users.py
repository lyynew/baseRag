"""用户与角色权限管理（后台）。"""

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from app.core.deps import CurrentUser, DbSession, require_perm
from app.core.errors import AppError, ErrorCode
from app.core.logging import get_logger
from app.core.rbac import PERMISSIONS, ROLE_NAMES, user_permission_codes
from app.core.security import hash_password
from app.db.models.auth import Permission, Role, User, UserRole
from app.db.models.chat import AuditLog
from app.schemas.admin import (
    PermissionOut,
    ResetPasswordRequest,
    RoleOut,
    RoleUpdate,
    UserCreate,
    UserOut,
    UserUpdate,
)
from app.services.auth_service import revoke_all_for_user

logger = get_logger(__name__)
router = APIRouter()


def _to_user_out(user: User) -> UserOut:
    """手动构造而不是 model_validate(user)。

    UserOut.roles 是 list[str]（角色 code），而 User.roles 是 list[Role] 对象，
    直接用 from_attributes 校验会报 string_type 错误。
    """
    return UserOut(
        id=user.id,
        username=user.username,
        nickname=user.nickname,
        email=user.email,
        phone=user.phone,
        is_active=user.is_active,
        is_superuser=user.is_superuser,
        roles=[r.code for r in user.roles],
        last_login_at=user.last_login_at,
        last_login_ip=user.last_login_ip,
        locked_until=user.locked_until,
        created_at=user.created_at,
    )


async def _audit(db, user: User, action: str, target_type: str, target_id: int | None,
                 before: dict | None = None, after: dict | None = None) -> None:
    db.add(
        AuditLog(
            operator_id=user.id,
            operator_name=user.username,
            action=action,
            target_type=target_type,
            target_id=target_id,
            before=before,
            after=after,
            result="ok",
            created_at=datetime.now(),
        )
    )


async def _roles_by_codes(db, codes: list[str]) -> list[Role]:
    if not codes:
        return []
    rows = (await db.execute(select(Role).where(Role.code.in_(codes)))).scalars().all()
    found = {r.code for r in rows}
    missing = [c for c in codes if c not in found]
    if missing:
        raise AppError(
            f"角色不存在：{', '.join(missing)}", code=ErrorCode.NOT_FOUND, status_code=404
        )
    return list(rows)


# ---------------- 用户 ----------------
@router.get(
    "/users",
    response_model=list[UserOut],
    summary="用户列表",
    dependencies=[Depends(require_perm("user:read"))],
)
async def list_users(
    db: DbSession,
    keyword: str | None = Query(default=None, max_length=64),
    is_active: bool | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[UserOut]:
    stmt = select(User).where(User.is_deleted == 0)
    if keyword:
        stmt = stmt.where(
            (User.username.like(f"%{keyword}%")) | (User.nickname.like(f"%{keyword}%"))
        )
    if is_active is not None:
        stmt = stmt.where(User.is_active.is_(is_active))
    stmt = stmt.order_by(User.id).limit(limit).offset(offset)
    users = (await db.execute(stmt)).scalars().all()
    return [_to_user_out(u) for u in users]


@router.post(
    "/users",
    response_model=UserOut,
    summary="创建用户",
    dependencies=[Depends(require_perm("user:write"))],
)
async def create_user(payload: UserCreate, db: DbSession, user: CurrentUser) -> UserOut:
    exists = (
        await db.execute(select(User).where(User.username == payload.username))
    ).scalar_one_or_none()
    if exists is not None:
        raise AppError("用户名已存在", code=ErrorCode.CONFLICT, status_code=409)

    roles = await _roles_by_codes(db, payload.role_codes)
    new_user = User(
        username=payload.username,
        nickname=payload.nickname or payload.username,
        email=payload.email,
        phone=payload.phone,
        password_hash=hash_password(payload.password),
        is_active=True,
    )
    new_user.roles = roles
    db.add(new_user)
    await db.flush()

    await _audit(db, user, "user.create", "user", new_user.id, None,
                 {"username": new_user.username, "roles": payload.role_codes})
    await db.commit()
    await db.refresh(new_user)
    logger.info("user_created", user_id=new_user.id, by=user.id)
    return _to_user_out(new_user)


@router.get(
    "/users/{user_id}",
    response_model=UserOut,
    summary="用户详情",
    dependencies=[Depends(require_perm("user:read"))],
)
async def get_user(user_id: int, db: DbSession) -> UserOut:
    target = (
        await db.execute(select(User).where(User.id == user_id, User.is_deleted == 0))
    ).scalar_one_or_none()
    if target is None:
        raise AppError("用户不存在", code=ErrorCode.NOT_FOUND, status_code=404)
    return _to_user_out(target)


@router.patch(
    "/users/{user_id}",
    response_model=UserOut,
    summary="修改用户（含启用/禁用、角色）",
    dependencies=[Depends(require_perm("user:write"))],
)
async def update_user(
    user_id: int, payload: UserUpdate, db: DbSession, user: CurrentUser
) -> UserOut:
    target = (
        await db.execute(select(User).where(User.id == user_id, User.is_deleted == 0))
    ).scalar_one_or_none()
    if target is None:
        raise AppError("用户不存在", code=ErrorCode.NOT_FOUND, status_code=404)

    if target.is_superuser and user.id != target.id and not user.is_superuser:
        raise AppError(
            "不能修改超级管理员的账号", code=ErrorCode.FORBIDDEN, status_code=403
        )
    if payload.is_active is False and target.id == user.id:
        raise AppError("不能禁用自己", code=ErrorCode.CONFLICT, status_code=409)

    before = {
        "nickname": target.nickname,
        "email": target.email,
        "is_active": target.is_active,
        "roles": [r.code for r in target.roles],
    }

    if payload.nickname is not None:
        target.nickname = payload.nickname
    if payload.email is not None:
        target.email = payload.email
    if payload.phone is not None:
        target.phone = payload.phone
    if payload.is_active is not None:
        target.is_active = payload.is_active
        if payload.is_active is False:
            # 禁用后立刻踢掉所有会话，避免已登录的人继续操作
            await revoke_all_for_user(target.id)
    if payload.role_codes is not None:
        target.roles = await _roles_by_codes(db, payload.role_codes)

    after = {
        "nickname": target.nickname,
        "email": target.email,
        "is_active": target.is_active,
        "roles": [r.code for r in target.roles],
    }
    if before != after:
        await _audit(db, user, "user.update", "user", target.id, before, after)

    await db.commit()
    await db.refresh(target)
    return _to_user_out(target)


@router.delete(
    "/users/{user_id}",
    summary="删除用户（软删除）",
    dependencies=[Depends(require_perm("user:delete"))],
)
async def delete_user(user_id: int, db: DbSession, user: CurrentUser) -> dict:
    target = (
        await db.execute(select(User).where(User.id == user_id, User.is_deleted == 0))
    ).scalar_one_or_none()
    if target is None:
        raise AppError("用户不存在", code=ErrorCode.NOT_FOUND, status_code=404)
    if target.id == user.id:
        raise AppError("不能删除自己", code=ErrorCode.CONFLICT, status_code=409)
    if target.is_superuser:
        raise AppError("不能删除超级管理员", code=ErrorCode.FORBIDDEN, status_code=403)

    target.is_deleted = 1
    target.is_active = False
    await revoke_all_for_user(target.id)
    await _audit(db, user, "user.delete", "user", target.id, {"username": target.username})
    await db.commit()
    logger.info("user_deleted", user_id=target.id, by=user.id)
    return {"message": "已删除"}


@router.post(
    "/users/{user_id}/reset-password",
    summary="重置密码（同时踢掉该用户所有登录）",
    dependencies=[Depends(require_perm("user:write"))],
)
async def reset_password(
    user_id: int, payload: ResetPasswordRequest, db: DbSession, user: CurrentUser
) -> dict:
    target = (
        await db.execute(select(User).where(User.id == user_id, User.is_deleted == 0))
    ).scalar_one_or_none()
    if target is None:
        raise AppError("用户不存在", code=ErrorCode.NOT_FOUND, status_code=404)

    target.password_hash = hash_password(payload.new_password)
    target.failed_login_count = 0
    target.locked_until = None
    await revoke_all_for_user(target.id)
    await _audit(db, user, "user.reset_password", "user", target.id)
    await db.commit()
    return {"message": "密码已重置，该用户需重新登录"}


@router.post(
    "/users/{user_id}/unlock",
    summary="解除账号锁定",
    dependencies=[Depends(require_perm("user:write"))],
)
async def unlock_user(user_id: int, db: DbSession, user: CurrentUser) -> dict:
    target = (
        await db.execute(select(User).where(User.id == user_id, User.is_deleted == 0))
    ).scalar_one_or_none()
    if target is None:
        raise AppError("用户不存在", code=ErrorCode.NOT_FOUND, status_code=404)

    target.failed_login_count = 0
    target.locked_until = None
    await _audit(db, user, "user.unlock", "user", target.id)
    await db.commit()
    return {"message": "已解锁"}


# ---------------- 角色与权限 ----------------
@router.get(
    "/roles",
    response_model=list[RoleOut],
    summary="角色列表（含权限）",
    dependencies=[Depends(require_perm("role:read"))],
)
async def list_roles(db: DbSession) -> list[RoleOut]:
    roles = (await db.execute(select(Role).order_by(Role.id))).scalars().all()
    counts = dict(
        (
            await db.execute(
                select(UserRole.role_id, func.count()).group_by(UserRole.role_id)
            )
        ).all()
    )
    return [
        RoleOut(
            id=r.id,
            code=r.code,
            name=r.name,
            description=r.description,
            is_builtin=r.is_builtin,
            permissions=[p.code for p in r.permissions],
            user_count=int(counts.get(r.id, 0)),
        )
        for r in roles
    ]


@router.get(
    "/permissions",
    response_model=list[PermissionOut],
    summary="全部权限码",
    dependencies=[Depends(require_perm("role:read"))],
)
async def list_permissions(db: DbSession) -> list[PermissionOut]:
    rows = (await db.execute(select(Permission).order_by(Permission.group_name,
                                                        Permission.code))).scalars().all()
    if not rows:
        return [
            PermissionOut(code=c, name=n, group_name=c.split(":")[0])
            for c, n in PERMISSIONS.items()
        ]
    return [
        PermissionOut(code=r.code, name=r.name, group_name=r.group_name) for r in rows
    ]


@router.patch(
    "/roles/{role_id}",
    response_model=RoleOut,
    summary="修改角色的权限（覆盖式）",
    dependencies=[Depends(require_perm("role:write"))],
)
async def update_role(
    role_id: int, payload: RoleUpdate, db: DbSession, user: CurrentUser
) -> RoleOut:
    role = (await db.execute(select(Role).where(Role.id == role_id))).scalar_one_or_none()
    if role is None:
        raise AppError("角色不存在", code=ErrorCode.NOT_FOUND, status_code=404)

    # 超级管理员权限是硬编码全通，不允许在界面上改，避免把自己锁死
    if role.code == "super_admin" and payload.permissions is not None:
        raise AppError(
            "超级管理员权限不可修改（恒为全部权限）",
            code=ErrorCode.FORBIDDEN,
            status_code=403,
        )

    before = {"name": role.name, "permissions": [p.code for p in role.permissions]}

    if payload.name is not None:
        role.name = payload.name
    if payload.description is not None:
        role.description = payload.description
    if payload.permissions is not None:
        perms = (
            await db.execute(
                select(Permission).where(Permission.code.in_(payload.permissions))
            )
        ).scalars().all()
        missing = set(payload.permissions) - {p.code for p in perms}
        if missing:
            raise AppError(
                f"未知权限码：{', '.join(sorted(missing))}",
                code=ErrorCode.VALIDATION_ERROR,
                status_code=422,
            )
        role.permissions = list(perms)

    after = {"name": role.name, "permissions": [p.code for p in role.permissions]}
    if before != after:
        await _audit(db, user, "role.update", "role", role.id, before, after)

    await db.commit()
    await db.refresh(role)
    logger.info("role_updated", role=role.code, by=user.id)
    return RoleOut(
        id=role.id,
        code=role.code,
        name=role.name,
        description=role.description,
        is_builtin=role.is_builtin,
        permissions=[p.code for p in role.permissions],
    )


@router.get("/users/{user_id}/effective-permissions", summary="查看某用户实际拥有的权限")
async def effective_permissions(
    user_id: int, db: DbSession, user: CurrentUser
) -> dict:
    if user_id != user.id and "user:read" not in user_permission_codes(user):
        raise AppError("没有权限查看他人权限", code=ErrorCode.FORBIDDEN, status_code=403)

    target = (
        await db.execute(select(User).where(User.id == user_id, User.is_deleted == 0))
    ).scalar_one_or_none()
    if target is None:
        raise AppError("用户不存在", code=ErrorCode.NOT_FOUND, status_code=404)

    codes = user_permission_codes(target)
    return {
        "user_id": user_id,
        "username": target.username,
        "roles": [r.code for r in target.roles],
        "permissions": sorted(c for c in codes if c != "*"),
        "is_superuser": target.is_superuser,
        "role_names": {r.code: ROLE_NAMES.get(r.code, r.name) for r in target.roles},
    }
