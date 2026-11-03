"""P6 智能体全链路冒烟。

覆盖：草稿不可见 → 发布 → 前台建会话提问（引用）→ 权限隔离 →
提示词覆盖即时生效 → 全员开关 → 审计 → 试跑接口。

用法：
    python -m scripts.smoke_agent <admin_password>
"""

import os
import sys
import time

import httpx

BASE_URL = os.environ.get("SMOKE_BASE_URL", "http://127.0.0.1:8000")
passed, failed = 0, 0
MARK = "【智能体冒烟】"


def check(name: str, ok: bool, detail: str = "") -> bool:
    global passed, failed
    if ok:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name}  {detail}")
    return ok


def wait_ask(r: httpx.Response) -> dict:
    return r.json() if r.status_code == 200 else {"answer": "", "citations": []}


def main() -> int:
    password = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("ADMIN_PASSWORD", "")
    if not password:
        print("缺少密码")
        return 2

    print(f"目标: {BASE_URL}\n")
    with httpx.Client(base_url=BASE_URL, timeout=180) as c:
        # ---------- 登录 ----------
        r = c.post("/api/v1/auth/login", json={"username": "admin", "password": password})
        if not check("管理员登录", r.status_code == 200, r.text[:150]):
            return 1
        H = {"Authorization": f"Bearer {r.json()['access_token']}"}

        # 普通用户
        uname = f"agtester{int(time.time()) % 10000}"
        r = c.post(
            "/api/v1/users",
            headers=H,
            json={"username": uname, "password": "Test12345", "role_codes": ["user"]},
        )
        uid = r.json().get("id") if r.status_code in (200, 201) else None
        UH = {}
        if uid:
            r = c.post("/api/v1/auth/login", json={"username": uname, "password": "Test12345"})
            if r.status_code == 200:
                UH = {"Authorization": f"Bearer {r.json()['access_token']}"}
        check("普通用户就绪", bool(UH), "普通用户登录失败，权限用例将跳过")

        # 找一个知识库
        kbs = c.get("/api/v1/kb", headers=H).json()
        if not kbs:
            print("没有可用知识库，无法继续")
            return 1
        kb_id = kbs[0]["id"]

        # ---------- 创建（草稿） ----------
        print("创建与发布 …")
        r = c.post(
            "/api/v1/admin/agents",
            headers=H,
            json={
                "name": f"冒烟助手{int(time.time()) % 10000}",
                "description": "smoke_agent 自动创建",
                "emoji": "🧪",
                "kb_ids": [kb_id],
            },
        )
        if not check("创建智能体（草稿）", r.status_code == 200, r.text[:200]):
            return 1
        agent = r.json()
        aid = agent["id"]
        check("默认未发布", agent["is_published"] is False)
        check("默认全员可用", agent["is_public"] is True)

        # ---------- 草稿不可见 ----------
        if UH:
            r = c.get("/api/v1/agents", headers=UH)
            ids = [x["id"] for x in r.json()]
            check("草稿对普通用户不可见", aid not in ids, str(ids)[:80])
            r = c.post(
                "/api/v1/chat/sessions", headers=UH, json={"agent_id": aid, "title": "x"}
            )
            check("草稿建会话被拒", r.status_code == 403, str(r.status_code))

        # ---------- 发布 ----------
        r = c.post(f"/api/v1/admin/agents/{aid}/publish", headers=H, params={"published": True})
        check("发布", r.status_code == 200 and r.json()["is_published"] is True, r.text[:150])

        if UH:
            r = c.get("/api/v1/agents", headers=UH)
            ids = [x["id"] for x in r.json()]
            check("发布后前台可见", aid in ids, str(ids)[:80])

        # ---------- 前台问答 ----------
        print("前台问答 …")
        if UH:
            r = c.post("/api/v1/chat/sessions", headers=UH, json={"agent_id": aid})
            if not check("普通用户建会话", r.status_code == 200, r.text[:200]):
                return 1
            sid = r.json()["id"]
            check("会话绑定了智能体", r.json().get("agent_id") == aid)
            check("kb_ids 来自智能体", kb_id in (r.json().get("kb_ids") or []))

            r = c.post(
                f"/api/v1/chat/sessions/{sid}/ask",
                headers=UH,
                json={"question": "v-for 的 key 为什么不能用 index"},
            )
            d = wait_ask(r)
            check("提问成功", r.status_code == 200, r.text[:200])
            check("答案非空且有引用", len(d.get("answer", "")) > 10 and d.get("citations"))
            c.delete(f"/api/v1/chat/sessions/{sid}", headers=UH)

        # ---------- 权限与防呆 ----------
        print("权限与防呆 …")
        r = c.post("/api/v1/chat/sessions", headers=H, json={"agent_id": 999999})
        check("不存在的智能体 404", r.status_code == 404, str(r.status_code))

        r = c.post(f"/api/v1/admin/agents/{aid}/publish", headers=H, params={"published": False})
        check("下线", r.status_code == 200 and r.json()["is_published"] is False)
        if UH:
            r = c.post("/api/v1/chat/sessions", headers=UH, json={"agent_id": aid})
            check("下线后建会话被拒", r.status_code == 403, str(r.status_code))
        c.post(f"/api/v1/admin/agents/{aid}/publish", headers=H, params={"published": True})

        if UH:
            r = c.post(
                "/api/v1/admin/agents",
                headers=UH,
                json={"name": "x", "kb_ids": [kb_id]},
            )
            check("普通用户建智能体 403", r.status_code == 403, str(r.status_code))

        # ---------- 全员开关 ----------
        print("全员开关 …")
        r = c.patch(f"/api/v1/admin/agents/{aid}", headers=H, json={"is_public": False})
        check("设为非公开", r.status_code == 200 and r.json()["is_public"] is False)
        if UH:
            r = c.get("/api/v1/agents", headers=UH)
            ids = [x["id"] for x in r.json()]
            check("非公开对普通用户隐藏", aid not in ids, str(ids)[:80])
        r = c.get("/api/v1/agents", headers=H)
        check("管理员仍可见非公开", aid in [x["id"] for x in r.json()])
        c.patch(f"/api/v1/admin/agents/{aid}", headers=H, json={"is_public": True})

        # ---------- 提示词覆盖 ----------
        print("提示词覆盖 …")
        r = c.patch(
            f"/api/v1/admin/agents/{aid}",
            headers=H,
            json={
                "prompt_overrides": {
                    "system_qa": (
                        MARK + " 你必须先输出" + MARK + "，然后基于资料回答。\n"
                        "资料：{{context}}\n问题：{{question}}"
                    )
                }
            },
        )
        check("保存覆盖", r.status_code == 200, r.text[:150])

        r = c.post(
            f"/api/v1/admin/agents/{aid}/test",
            headers=H,
            json={"question": "出差住宿标准是多少"},
        )
        tr = r.json() if r.status_code == 200 else {}
        check("试跑成功", r.status_code == 200 and len(tr.get("answer", "")) > 0, r.text[:200])
        ans = tr.get("answer", "")
        # 用 system_prompt_head（确定性）而不是模型输出判断覆盖是否生效——
        # 模型可能把标记词转述成别的写法（实测 MiMo 把"冒烟"写成了"smoke"）
        check(
            "试跑使用覆盖提示词",
            MARK in tr.get("system_prompt_head", ""),
            tr.get("system_prompt_head", "")[:80],
        )
        m, pt, ct = tr.get("model"), tr.get("prompt_tokens"), tr.get("completion_tokens")
        print(
            f"         模型={m} {pt}+{ct}t {tr.get('latency_ms')}ms 资料{tr.get('sources')}条"
        )

        if UH:
            r = c.post("/api/v1/chat/sessions", headers=UH, json={"agent_id": aid})
            sid = r.json()["id"]
            r = c.post(
                f"/api/v1/chat/sessions/{sid}/ask",
                headers=UH,
                json={"question": "出差住宿标准是多少"},
            )
            d = wait_ask(r)
            # 问答走覆盖提示词：模型被要求在答案前输出标记；即使措辞有变化，
            # 只要它按覆盖提示词回答（开头出现"【智能体"字样）即视为生效
            ans = d.get("answer", "")
            check("问答走覆盖提示词", "【智能体" in ans, ans[:60])
            c.delete(f"/api/v1/chat/sessions/{sid}", headers=UH)

        r = c.patch(f"/api/v1/admin/agents/{aid}", headers=H, json={"prompt_overrides": {}})
        check("清除覆盖", r.status_code == 200 and r.json()["prompt_overrides"] == {})

        # ---------- 校验 ----------
        r = c.patch(
            f"/api/v1/admin/agents/{aid}",
            headers=H,
            json={"prompt_overrides": {"bad_key": "x"}},
        )
        check("非法提示词 key 被拒", r.status_code == 422, str(r.status_code))
        r = c.post(
            "/api/v1/admin/agents", headers=H, json={"name": "x", "kb_ids": [999999]}
        )
        check("不存在的知识库被拒", r.status_code == 422, str(r.status_code))

        # ---------- 审计 ----------
        r = c.get("/api/v1/admin/audit-logs", headers=H, params={"limit": 60})
        body = r.json()
        logs = body.get("items") if isinstance(body, dict) else body
        actions = {x["action"] for x in logs}
        check("agent.create 入审计", "agent.create" in actions, str(sorted(actions))[:150])
        check("agent.publish 入审计", "agent.publish" in actions, str(sorted(actions))[:150])
        check("agent.update 入审计", "agent.update" in actions, str(sorted(actions))[:150])

        # ---------- 清理 ----------
        r = c.delete(f"/api/v1/admin/agents/{aid}", headers=H)
        check("删除智能体", r.status_code == 200)
        r = c.get("/api/v1/agents", headers=H)
        check("删除后前台不可见", aid not in [x["id"] for x in r.json()])
        if uid:
            c.delete(f"/api/v1/users/{uid}", headers=H)

    print(f"\n结果: {passed} 通过, {failed} 失败")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
