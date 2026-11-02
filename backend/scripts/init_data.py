"""初始化基础数据：权限、内置角色、超管账号。

幂等：可重复执行，已存在的数据会跳过或更新，不会产生重复。

用法：
    python -m scripts.init_data
    ADMIN_INIT_PASSWORD='YourPass123' python -m scripts.init_data
"""

import asyncio
import secrets
import string
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import os  # noqa: E402

from sqlalchemy import select  # noqa: E402

from app.core.rbac import PERMISSIONS, ROLE_NAMES, ROLE_PERMISSIONS  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.db.models.auth import Permission, Role, User  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402
from app.services import prompt_service  # noqa: E402


def _random_password(length: int = 16) -> str:
    alphabet = string.ascii_letters + string.digits
    while True:
        pwd = "".join(secrets.choice(alphabet) for _ in range(length))
        if any(c.islower() for c in pwd) and any(c.isupper() for c in pwd) and any(
            c.isdigit() for c in pwd
        ):
            return pwd


async def init_permissions(session) -> dict[str, Permission]:
    existing = {
        p.code: p for p in (await session.execute(select(Permission))).scalars().all()
    }
    created = 0
    for code, name in PERMISSIONS.items():
        if code in existing:
            existing[code].name = name
            continue
        obj = Permission(code=code, name=name, group_name=code.split(":")[0])
        session.add(obj)
        existing[code] = obj
        created += 1
    await session.flush()
    print(f"[权限] 新增 {created} 条，现有 {len(existing)} 条")
    return existing


async def init_roles(session, perms: dict[str, Permission]) -> dict[str, Role]:
    existing = {r.code: r for r in (await session.execute(select(Role))).scalars().all()}
    created = 0
    for code, perm_codes in ROLE_PERMISSIONS.items():
        role = existing.get(code)
        if role is None:
            role = Role(code=code, name=ROLE_NAMES.get(code, code), is_builtin=True)
            session.add(role)
            existing[code] = role
            created += 1
        else:
            role.name = ROLE_NAMES.get(code, code)
            role.is_builtin = True

        # 全量对齐权限（"*" 表示全部）
        if perm_codes == ["*"]:
            role.permissions = list(perms.values())
        else:
            role.permissions = [perms[c] for c in perm_codes if c in perms]
    await session.flush()
    print(f"[角色] 新增 {created} 个，现有 {len(existing)} 个")
    return existing


async def init_admin(session, roles: dict[str, Role]) -> None:
    admin = (
        await session.execute(select(User).where(User.username == "admin"))
    ).scalar_one_or_none()

    if admin is not None:
        print("[超管] admin 已存在，跳过（如需重置密码请用后台或脚本单独处理）")
        return

    password = os.environ.get("ADMIN_INIT_PASSWORD") or _random_password()
    admin = User(
        username="admin",
        nickname="超级管理员",
        password_hash=hash_password(password),
        is_active=True,
        is_superuser=True,
    )
    admin.roles = [roles["super_admin"]]
    session.add(admin)
    await session.flush()

    print("[超管] 已创建 admin 账号")
    if not os.environ.get("ADMIN_INIT_PASSWORD"):
        print(f"        初始密码（仅显示一次，请立即保存）：{password}")


async def main() -> None:
    try:
        async with SessionLocal() as session:
            perms = await init_permissions(session)
            roles = await init_roles(session, perms)
            await init_admin(session, roles)
            await session.commit()

            # 内置提示词入库：已有自定义内容不会被覆盖
            created = await prompt_service.ensure_seed(session)
            print(f"[提示词] 新增 {created} 条内置模板")
        print("初始化完成")
    finally:
        # 显式释放连接池，否则脚本退出时 aiomysql 会在已关闭的 event loop 上析构而报错
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
