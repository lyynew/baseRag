"""P3 后台接口冒烟：用户/角色/模型配置/审计/用量/权限隔离。

用法：
    python -m scripts.smoke_admin <admin_password>
"""

import os
import sys
import time
from pathlib import Path

import httpx

BASE_URL = os.environ.get("SMOKE_BASE_URL", "http://127.0.0.1:8000")
passed, failed = 0, 0
TEST_USER = f"tester{int(time.time()) % 10000}"
TEST_PWD = "Test12345"


def check(name: str, ok: bool, detail: str = "") -> bool:
    global passed, failed
    if ok:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name}  {detail}")
    return ok


def main() -> int:
    password = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("ADMIN_PASSWORD", "")
    if not password:
        print("缺少密码")
        return 2

    print(f"目标: {BASE_URL}\n")
    with httpx.Client(base_url=BASE_URL, timeout=60) as c:
        r = c.post("/api/v1/auth/login", json={"username": "admin", "password": password})
        if not check("管理员登录", r.status_code == 200, r.text[:200]):
            return 1
        H = {"Authorization": f"Bearer {r.json()['access_token']}"}

        # ---------- 角色与权限 ----------
        print("角色与权限 …")
        r = c.get("/api/v1/roles", headers=H)
        roles = r.json() if r.status_code == 200 else []
        check("角色列表", len(roles) >= 3, str(len(roles)))
        role_codes = {x["code"] for x in roles}
        check("内置三角色齐备", {"super_admin", "admin", "user"} <= role_codes, str(role_codes))

        r = c.get("/api/v1/permissions", headers=H)
        perms = r.json() if r.status_code == 200 else []
        check("权限码列表", len(perms) >= 10, str(len(perms)))

        user_role = next((x for x in roles if x["code"] == "user"), None)
        if user_role:
            r = c.patch(
                f"/api/v1/roles/{user_role['id']}",
                headers=H,
                json={"permissions": ["chat:use", "kb:read"]},
            )
            check("修改普通角色权限", r.status_code == 200, r.text[:200])
            if r.status_code == 200:
                check("权限已生效", set(r.json()["permissions"]) == {"chat:use", "kb:read"},
                      str(r.json().get("permissions")))

            # 改回去，避免影响后续测试
            c.patch(
                f"/api/v1/roles/{user_role['id']}",
                headers=H,
                json={"permissions": ["chat:use"]},
            )

        sa = next((x for x in roles if x["code"] == "super_admin"), None)
        if sa:
            r = c.patch(
                f"/api/v1/roles/{sa['id']}", headers=H, json={"permissions": ["chat:use"]}
            )
            check("超管权限不可改（防锁死）", r.status_code == 403, str(r.status_code))

        # ---------- 用户管理 ----------
        print("\n用户管理 …")
        r = c.post(
            "/api/v1/users",
            headers=H,
            json={
                "username": TEST_USER,
                "password": TEST_PWD,
                "nickname": "冒烟测试用户",
                "role_codes": ["user"],
            },
        )
        created = r.status_code == 200
        check("创建用户", created, r.text[:300])
        uid = r.json()["id"] if created else 0
        if uid:
            check("默认角色正确", r.json()["roles"] == ["user"], str(r.json().get("roles")))

            r = c.get("/api/v1/users", headers=H, params={"keyword": TEST_USER})
            check("按关键词搜索用户", r.status_code == 200 and len(r.json()) >= 1, r.text[:200])

            # 权限隔离：新用户是 user 角色，访问后台必须 403
            r2 = c.post(
                "/api/v1/auth/login", json={"username": TEST_USER, "password": TEST_PWD}
            )
            if check("新用户可登录", r2.status_code == 200, r2.text[:200]):
                UH = {"Authorization": f"Bearer {r2.json()['access_token']}"}
                r3 = c.get("/api/v1/users", headers=UH)
                check("普通用户访问用户列表被拒 403", r3.status_code == 403, str(r3.status_code))
                r3 = c.get("/api/v1/admin/models", headers=UH)
                check("普通用户访问模型配置被拒 403", r3.status_code == 403, str(r3.status_code))
                r3 = c.get("/api/v1/admin/audit-logs", headers=UH)
                check("普通用户访问审计被拒 403", r3.status_code == 403, str(r3.status_code))
                r3 = c.get("/api/v1/kb", headers=UH)
                check("普通用户可访问知识库列表", r3.status_code == 200, str(r3.status_code))

            # 改成 admin 角色后应能访问
            r = c.patch(
                f"/api/v1/users/{uid}", headers=H, json={"role_codes": ["admin"]}
            )
            check("调整用户角色", r.status_code == 200 and "admin" in r.json()["roles"],
                  r.text[:200])

            r = c.post(f"/api/v1/users/{uid}/reset-password", headers=H,
                       json={"new_password": "NewPass123"})
            check("重置密码", r.status_code == 200, r.text[:200])

            r = c.post(f"/api/v1/users/{uid}/unlock", headers=H)
            check("解除锁定", r.status_code == 200, r.text[:200])

            # 不能禁用自己
            me = c.get("/api/v1/auth/me", headers=H).json()
            r = c.patch(f"/api/v1/users/{me['id']}", headers=H, json={"is_active": False})
            check("不能禁用自己", r.status_code == 409, str(r.status_code))

        # ---------- 模型配置 ----------
        print("\n模型配置 …")
        r = c.get("/api/v1/admin/models", headers=H)
        models = r.json() if r.status_code == 200 else []
        check("模型配置列表", r.status_code == 200, r.text[:200])

        # 仅记录本次新建的模型 id，便于人工清理
        if not any(m["provider"] == "mimo" for m in models):
            env_path = Path(__file__).resolve().parent.parent / ".env"
            env: dict[str, str] = {}
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if "=" in line and not line.strip().startswith("#"):
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.split("#")[0].strip()
            r = c.post(
                "/api/v1/admin/models",
                headers=H,
                json={
                    "provider": "mimo",
                    "name": "MiMo V2.6 Flash",
                    "base_url": env.get("MIMO_BASE_URL", ""),
                    "api_key": env.get("MIMO_API_KEY", ""),
                    "model": env.get("MIMO_MODEL", ""),
                    "max_context": 128000,
                    "max_output": 4096,
                },
            )
            if check("新增模型配置", r.status_code == 200, r.text[:300]):
                _ = r.json()["id"]
                check("返回密钥已脱敏", "****" in r.json()["api_key_masked"],
                      r.json().get("api_key_masked", ""))
                print(f"         脱敏后: {r.json()['api_key_masked']}")

        models = c.get("/api/v1/admin/models", headers=H).json()
        target = next((m for m in models if m["provider"] == "mimo"), None)
        if target:
            mid = target["id"]
            r = c.post(f"/api/v1/admin/models/{mid}/test", headers=H)
            body = r.json() if r.status_code == 200 else {}
            check("连通性测试成功", body.get("ok") is True, str(body)[:200])
            if body.get("ok"):
                print(f"         {body['latency_ms']}ms  reply={body.get('reply')[:30]}")

            r = c.post(f"/api/v1/admin/models/{mid}/set-default", headers=H)
            check("设为默认模型", r.status_code == 200, r.text[:200])
            if r.status_code == 200:
                dft = [m for m in r.json() if m["is_default"]]
                check("默认模型唯一", len(dft) == 1, str([m["model"] for m in dft]))

            r = c.delete(f"/api/v1/admin/models/{mid}", headers=H)
            check("默认模型不可删除", r.status_code == 409, str(r.status_code))

            r = c.patch(
                f"/api/v1/admin/models/{mid}", headers=H, json={"max_output": 3072}
            )
            check("修改模型配置", r.status_code == 200 and r.json()["max_output"] == 3072,
                  r.text[:200])

        # ---------- 审计与用量 ----------
        print("\n审计与用量 …")
        r = c.get("/api/v1/admin/audit-logs", headers=H, params={"days": 1, "limit": 50})
        logs = r.json() if r.status_code == 200 else []
        check("审计日志可查", r.status_code == 200 and len(logs) > 0, str(len(logs)))
        actions = {x["action"] for x in logs}
        check(
            "用户创建已入审计",
            any("user.create" in a for a in actions),
            str(sorted(actions))[:150],
        )
        check("模型变更已入审计", any("model." in a for a in actions), str(sorted(actions))[:150])

        r = c.get("/api/v1/admin/usage", headers=H, params={"days": 7})
        if check("用量统计", r.status_code == 200, r.text[:200]):
            u = r.json()
            print(f"         7 天: {u['total_calls']} 次调用, "
                  f"prompt={u['total_prompt_tokens']} completion={u['total_completion_tokens']}")

        r = c.get("/api/v1/admin/usage/daily", headers=H, params={"days": 7})
        check("按天用量", r.status_code == 200 and "items" in r.json(), r.text[:150])

        # ---------- 清理 ----------
        if uid:
            r = c.delete(f"/api/v1/users/{uid}", headers=H)
            check("删除测试用户", r.status_code == 200, r.text[:200])

    print(f"\n结果: {passed} 通过, {failed} 失败")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
