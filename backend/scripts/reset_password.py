"""重置用户密码（应急用）。

场景：管理员忘记密码，或初始密码丢失（init_data 只在首次创建时打印一次）。

用法：
    python -m scripts.reset_password admin                # 随机生成强密码
    python -m scripts.reset_password admin MyPass123      # 指定密码
    python -m scripts.reset_password admin --unlock       # 同时解除登录锁定

安全提示：该脚本绕过所有 Web 层校验，只能在能直连数据库的服务器上执行，
不要把它的能力暴露成接口。
"""

import asyncio
import secrets
import string
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.core.security import hash_password  # noqa: E402
from app.db.models.auth import User  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402


def _random_password(length: int = 16) -> str:
    alphabet = string.ascii_letters + string.digits
    while True:
        pwd = "".join(secrets.choice(alphabet) for _ in range(length))
        if (
            any(c.islower() for c in pwd)
            and any(c.isupper() for c in pwd)
            and any(c.isdigit() for c in pwd)
        ):
            return pwd


async def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]

    if not args:
        print("用法: python -m scripts.reset_password <用户名> [新密码]")
        return 2

    username = args[0]
    plain = args[1] if len(args) > 1 else _random_password()

    try:
        async with SessionLocal() as session:
            user = (
                await session.execute(
                    select(User).where(User.username == username, User.is_deleted == 0)
                )
            ).scalar_one_or_none()

            if user is None:
                print(f"用户不存在：{username}")
                return 1

            user.password_hash = hash_password(plain)
            # 重置密码时一并解锁，否则用户改完密码还是登不进去
            user.failed_login_count = 0
            user.locked_until = None

            await session.commit()
            print(f"已重置 {username} 的密码（并解除登录锁定）")
            if len(args) <= 1:
                print(f"新密码（仅显示一次，请立即保存）：{plain}")
            print("提示：该用户已登录的设备不会被立即踢下线（access 最长 30 分钟后过期）。")
            print("      若要立即失效全部会话，请在后台对他执行『重置密码』或禁用再启用。")
    finally:
        await engine.dispose()

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
