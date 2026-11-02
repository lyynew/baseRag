"""端到端冒烟测试：登录 → 鉴权 → 刷新 → 轮换 → 登出 → 黑名单。

用法：
    python -m scripts.smoke_test <admin_password>
    ADMIN_PASSWORD=xxx python -m scripts.smoke_test

设计目的：一条命令验证"服务 + 数据库 + Redis"整条链路是否正常，
不依赖 pytest，方便部署后在生产机上直接跑。
"""

import os
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BASE_URL = os.environ.get("SMOKE_BASE_URL", "http://127.0.0.1:8000")
USERNAME = os.environ.get("SMOKE_USERNAME", "admin")

passed, failed = 0, 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global passed, failed
    if ok:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name}  {detail}")


def main() -> int:
    password = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("ADMIN_PASSWORD", "")
    if not password:
        print("缺少密码：python -m scripts.smoke_test <password>")
        return 2

    print(f"目标: {BASE_URL}\n")
    with httpx.Client(base_url=BASE_URL, timeout=15) as c:
        # 1. 健康检查
        r = c.get("/health/deep")
        body = r.json()
        check("健康检查可达", r.status_code == 200, str(r.status_code))
        checks = body.get("checks", {})
        check("MySQL 可用", checks.get("mysql", {}).get("ok") is True, str(checks.get("mysql")))
        check("Redis 可用", checks.get("redis", {}).get("ok") is True, str(checks.get("redis")))

        # 2. 错误密码
        r = c.post(
            "/api/v1/auth/login",
            json={"username": USERNAME, "password": "definitely-wrong-123"},
        )
        check(
            "错误密码被拒",
            r.status_code == 401 and r.json().get("code") == "BAD_CREDENTIALS",
            f"{r.status_code}",
        )

        # 3. 正常登录
        r = c.post("/api/v1/auth/login", json={"username": USERNAME, "password": password})
        check("登录成功", r.status_code == 200, r.text[:200])
        if r.status_code != 200:
            return 1
        tokens = r.json()
        access, refresh = tokens["access_token"], tokens["refresh_token"]
        check("返回双 Token", bool(access) and bool(refresh))
        check("access_token 是合法 JWT", access.count(".") == 2, access[:40])

        # 4. 鉴权访问
        r = c.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access}"})
        check("携带 Token 访问 /me", r.status_code == 200, r.text[:200])
        me = r.json() if r.status_code == 200 else {}
        check("超管标识正确", me.get("is_superuser") is True, str(me.get("is_superuser")))
        check("权限码非空", len(me.get("permissions", [])) > 0, str(len(me.get("permissions", []))))
        check("角色含 super_admin", any(x["code"] == "super_admin" for x in me.get("roles", [])),
              str(me.get("roles")))

        # 5. 无 Token 被拒
        r = c.get("/api/v1/auth/me")
        check("无 Token 返回 401", r.status_code == 401, str(r.status_code))

        # 6. 刷新令牌
        r = c.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
        check("刷新成功", r.status_code == 200, r.text[:200])
        new_tokens = r.json() if r.status_code == 200 else {}
        new_refresh = new_tokens.get("refresh_token", "")
        check("刷新后 refresh 已轮换", new_refresh != refresh)

        # 7. 旧 refresh 不可再用（防重放）
        r = c.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
        check("旧 refresh 失效", r.status_code == 401, str(r.status_code))

        # 8. 登出
        r = c.post(
            "/api/v1/auth/logout",
            headers={"Authorization": f"Bearer {new_tokens.get('access_token', access)}"},
            json={"refresh_token": new_refresh},
        )
        check("登出成功", r.status_code == 200, r.text[:200])

        # 9. 登出后 access 进黑名单
        final_access = new_tokens.get("access_token", access)
        r = c.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {final_access}"})
        check("登出后 Token 失效", r.status_code == 401, str(r.status_code))

    print(f"\n结果: {passed} 通过, {failed} 失败")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
