"""知识库业务逻辑：权限判定与访问控制。

判定顺序（与技术选型 §6.7.1 一致）：
  1. superuser / 拥有 kb:write 全局权限 → 全库可读写
  2. 拥有 kb:read 全局权限 → 全库可读
  3. kb_members 表中为 owner → 该库可读写
  4. kb_members 表中为 viewer → 该库只读
  5. 其余 → 拒绝
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ErrorCode, ForbiddenError
from app.core.rbac import user_permission_codes
from app.db.models.auth import User
from app.db.models.enums import KbMemberRole
from app.db.models.knowledge import KbMember, KnowledgeBase


def _global_role(user: User) -> str | None:
    """返回全局身份：admin 表示拥有全部库的读写，reader 表示只读。"""
    codes = user_permission_codes(user)
    if "*" in codes or "kb:write" in codes:
        return "admin"
    if "kb:read" in codes:
        return "reader"
    return None


async def get_kb_or_404(db: AsyncSession, kb_id: int) -> KnowledgeBase:
    kb = (
        await db.execute(
            select(KnowledgeBase).where(
                KnowledgeBase.id == kb_id, KnowledgeBase.is_deleted == 0
            )
        )
    ).scalar_one_or_none()
    if kb is None:
        raise AppError("知识库不存在", code=ErrorCode.KB_NOT_FOUND, status_code=404)
    return kb


async def member_role(db: AsyncSession, kb_id: int, user_id: int) -> str | None:
    row = (
        await db.execute(
            select(KbMember.role).where(
                KbMember.kb_id == kb_id, KbMember.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    return row


async def ensure_kb_access(
    db: AsyncSession, user: User, kb_id: int, *, need_write: bool = False
) -> KnowledgeBase:
    kb = await get_kb_or_404(db, kb_id)

    g_role = _global_role(user)
    if g_role == "admin":
        return kb
    if g_role == "reader" and not need_write:
        return kb

    m_role = await member_role(db, kb_id, user.id)
    if m_role == KbMemberRole.OWNER:
        return kb
    if m_role == KbMemberRole.VIEWER and not need_write:
        return kb

    raise ForbiddenError("没有该知识库的访问权限")


async def my_role_for(db: AsyncSession, user: User, kb_id: int) -> str | None:
    g_role = _global_role(user)
    if g_role:
        return g_role
    return await member_role(db, kb_id, user.id)


async def list_accessible_kbs(
    db: AsyncSession, user: User, *, keyword: str | None = None
) -> list[tuple[KnowledgeBase, str | None]]:
    """返回当前用户可见的知识库及其角色。"""
    stmt = select(KnowledgeBase).where(KnowledgeBase.is_deleted == 0)
    if keyword:
        stmt = stmt.where(KnowledgeBase.name.like(f"%{keyword}%"))
    stmt = stmt.order_by(KnowledgeBase.updated_at.desc())

    g_role = _global_role(user)
    if g_role:
        kbs = (await db.execute(stmt)).scalars().all()
        return [(kb, g_role) for kb in kbs]

    # 普通用户：只列被邀请的库
    stmt = stmt.join(KbMember, KbMember.kb_id == KnowledgeBase.id).where(
        KbMember.user_id == user.id
    )
    rows = (await db.execute(stmt)).scalars().all()
    if not rows:
        return []

    memberships = dict(
        (
            await db.execute(
                select(KbMember.kb_id, KbMember.role).where(KbMember.user_id == user.id)
            )
        ).all()
    )
    return [(kb, memberships.get(kb.id)) for kb in rows]


async def add_member(
    db: AsyncSession, kb_id: int, target_user_id: int, role: str, granted_by: int
) -> KbMember:
    exists = (
        await db.execute(
            select(KbMember).where(
                KbMember.kb_id == kb_id, KbMember.user_id == target_user_id
            )
        )
    ).scalar_one_or_none()

    if exists:
        exists.role = role
        await db.commit()
        return exists

    member = KbMember(
        kb_id=kb_id, user_id=target_user_id, role=role, granted_by=granted_by
    )
    db.add(member)
    await db.commit()
    return member


async def remove_member(db: AsyncSession, kb_id: int, target_user_id: int) -> None:
    member = (
        await db.execute(
            select(KbMember).where(
                KbMember.kb_id == kb_id, KbMember.user_id == target_user_id
            )
        )
    ).scalar_one_or_none()
    if member is None:
        raise AppError("该用户不在此知识库中", code=ErrorCode.NOT_FOUND, status_code=404)
    await db.delete(member)
    await db.commit()
