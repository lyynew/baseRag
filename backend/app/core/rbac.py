"""RBAC 权限判定。

设计取舍：不引入 Casbin。
理由：本项目权限模型是「3 个全局角色 + 库级 owner/viewer」，属于最简单的 RBAC。
Casbin 的 adapter 会额外建一张 casbin_rule 表，与已有的 roles/permissions 表功能重叠，
两套数据需要同步，是典型的 bug 源。

此处保持与 Casbin 一致的调用形态（has_permission(sub, obj, act)），
将来若真要做多租户域隔离或 ABAC，替换本模块实现即可，业务层无感。
"""

from collections.abc import Iterable

from app.core.errors import ForbiddenError
from app.db.models.auth import User

# ---------------- 权限码清单 ----------------
# 命名规范：资源:动作。新增权限必须在此登记，init_data 会同步到 permissions 表。
PERMISSIONS: dict[str, str] = {
    # 后台 - 用户管理
    "user:read": "查看用户",
    "user:write": "新增/编辑用户",
    "user:delete": "删除用户",
    # 后台 - 角色权限
    "role:read": "查看角色",
    "role:write": "配置角色权限",
    # 后台 - 知识库管理
    "kb:read": "查看知识库",
    "kb:write": "创建/编辑知识库",
    "kb:delete": "删除知识库",
    "doc:write": "上传/删除文档",
    "doc:reindex": "触发全量重建",
    # 后台 - 系统配置
    "config:read": "查看系统配置",
    "config:write": "修改系统配置与模型",
    # 后台 - 审计
    "audit:read": "查看审计日志",
    # 前台
    "chat:use": "使用问答",
}

# 内置角色 → 权限集合
ROLE_PERMISSIONS: dict[str, list[str]] = {
    "super_admin": ["*"],
    "admin": [
        "user:read", "user:write",
        "role:read",
        "kb:read", "kb:write", "kb:delete",
        "doc:write", "doc:reindex",
        "config:read", "config:write",
        "audit:read",
        "chat:use",
    ],
    "user": ["chat:use"],
}

ROLE_NAMES: dict[str, str] = {
    "super_admin": "超级管理员",
    "admin": "管理员",
    "user": "普通用户",
}


def user_permission_codes(user: User) -> set[str]:
    """汇总用户的全部权限码。superuser 直接拿全部。"""
    if user.is_superuser:
        return set(PERMISSIONS.keys()) | {"*"}

    codes: set[str] = set()
    for role in user.roles:
        codes.update(ROLE_PERMISSIONS.get(role.code, []))
    return codes


def has_permission(user: User, required: str | Iterable[str], *, mode: str = "all") -> bool:
    """判定是否拥有权限（或权限组）。"""
    codes = user_permission_codes(user)
    if "*" in codes:
        return True

    required_list = [required] if isinstance(required, str) else list(required)
    if not required_list:
        return True

    if mode == "any":
        return any(c in codes for c in required_list)
    return all(c in codes for c in required_list)


def ensure_permission(user: User, required: str | Iterable[str], *, mode: str = "all") -> None:
    if not has_permission(user, required, mode=mode):
        raise ForbiddenError("没有权限执行该操作")


def can_access_kb(user: User, kb_id: int, *, need_write: bool = False) -> bool:
    """知识库访问判定。

    判定顺序：superuser → 全局 admin 权限 → 库成员身份 → 默认拒绝。
    kb_members 关系需要调用方预先加载，这里只做纯判定。
    """
    if user.is_superuser:
        return True

    codes = user_permission_codes(user)
    if need_write:
        if "kb:write" in codes or "*" in codes:
            return True
    elif "kb:read" in codes or "*" in codes:
        return True

    for m in getattr(user, "kb_memberships", []) or []:
        if m.kb_id != kb_id:
            continue
        if need_write:
            return m.role == "owner"
        return True
    return False
