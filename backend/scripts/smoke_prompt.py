"""P5 提示词管理冒烟：列表/详情/校验/保存/版本/预览/试跑/回滚/恢复/权限隔离/即时生效。

用法：
    python -m scripts.smoke_prompt <admin_password>

会真实调用一次模型进行试跑，并跑一次完整问答验证"改完立即生效"，
总花费在几百 token 量级。
"""

import os
import sys
import time

import httpx

BASE_URL = os.environ.get("SMOKE_BASE_URL", "http://127.0.0.1:8000")
passed, failed = 0, 0
MARK = "【冒烟标记】"


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
    with httpx.Client(base_url=BASE_URL, timeout=120) as c:
        r = c.post("/api/v1/auth/login", json={"username": "admin", "password": password})
        if not check("管理员登录", r.status_code == 200, r.text[:200]):
            return 1
        H = {"Authorization": f"Bearer {r.json()['access_token']}"}

        # ---------- 列表与详情 ----------
        print("列表与详情 …")
        r = c.get("/api/v1/admin/prompts", headers=H)
        items = r.json() if r.status_code == 200 else []
        check("模板列表", r.status_code == 200 and len(items) == 3, str(len(items)))
        codes = {x["code"] for x in items}
        check(
            "三套内置模板齐备",
            {"system_qa", "direct_answer", "query_rewrite"} <= codes,
            str(codes),
        )

        r = c.get("/api/v1/admin/prompts/variables", headers=H)
        vars_ = r.json() if r.status_code == 200 else []
        check(
            "变量清单",
            r.status_code == 200 and {"context", "question"} <= {v["name"] for v in vars_},
            str([v["name"] for v in vars_]),
        )

        # 先把模板恢复一次默认，让后续断言的版本基线可预期（否则受上次运行残留影响）
        c.post("/api/v1/admin/prompts/system_qa/reset", headers=H)

        r = c.get("/api/v1/admin/prompts/system_qa", headers=H)
        detail = r.json() if r.status_code == 200 else {}
        check("详情返回内容", len(detail.get("content", "")) > 50, str(detail)[:150])
        base_version = int(detail.get("version") or 0)
        original = detail.get("content", "")

        # ---------- 变量校验 ----------
        print("变量校验 …")
        r = c.put(
            "/api/v1/admin/prompts/system_qa",
            headers=H,
            json={"content": "请基于 {{contxt}} 回答 {{question}}"},
        )
        check("未知变量被拒", r.status_code == 400, f"{r.status_code} {r.text[:120]}")
        check(
            "报错指出变量名",
            "contxt" in r.text,
            r.text[:150],
        )

        r = c.put("/api/v1/admin/prompts/system_qa", headers=H, json={"content": "   "})
        check("空内容被拒", r.status_code == 400, str(r.status_code))

        # ---------- 保存与版本 ----------
        print("保存与版本 …")
        new_content = (
            MARK + "你是知识库助手。资料：{{context}}\n\n问题：{{question}}\n"
            "回答时必须先在开头输出" + MARK + "。"
        )
        r = c.put(
            "/api/v1/admin/prompts/system_qa",
            headers=H,
            json={"content": new_content, "note": "冒烟测试修改"},
        )
        saved = r.json() if r.status_code == 200 else {}
        check("保存成功", r.status_code == 200, r.text[:200])
        check("版本递增", saved.get("version", 0) == base_version + 1, str(saved.get("version")))
        check("标记为已自定义", saved.get("is_customized") is True, str(saved))

        r = c.get("/api/v1/admin/prompts/system_qa/versions", headers=H)
        versions = r.json() if r.status_code == 200 else []
        check("版本历史已记录", len(versions) >= 1, str(len(versions)))
        check(
            "历史保留改动前的内容",
            any(original[:20] in v["content"] for v in versions),
            str([(v["version"], v["content"][:16]) for v in versions]),
        )

        # ---------- 预览 ----------
        print("预览 …")
        r = c.post(
            "/api/v1/admin/prompts/system_qa/preview",
            headers=H,
            json={"values": {"context": "出差住宿一线城市 600 元", "question": "能报多少"}},
        )
        pv = r.json() if r.status_code == 200 else {}
        check("预览成功", r.status_code == 200, r.text[:150])
        check("变量已替换", "600 元" in pv.get("rendered", ""), pv.get("rendered", "")[:100])
        check("无未知占位符", "{{" not in pv.get("rendered", ""), pv.get("rendered", "")[:100])
        check("给出 token 估算", pv.get("tokens_estimate", 0) > 0, str(pv.get("tokens_estimate")))

        r = c.post(
            "/api/v1/admin/prompts/system_qa/preview",
            headers=H,
            json={"values": {"question": "只给问题"}},
        )
        pv2 = r.json() if r.status_code == 200 else {}
        check("缺变量被列出", "context" in (pv2.get("missing") or []), str(pv2.get("missing")))

        # ---------- 试跑（真实调用模型） ----------
        print("试跑 …")
        r = c.post(
            "/api/v1/admin/prompts/system_qa/test",
            headers=H,
            json={"question": "测试一个问题", "content": "你是一个测试助手，直接回答“OK”。"},
        )
        tr = r.json() if r.status_code == 200 else {}
        check("试跑返回答案", r.status_code == 200 and len(tr.get("answer", "")) > 0, r.text[:150])
        check("试跑统计 token", tr.get("prompt_tokens", 0) > 0, str(tr.get("prompt_tokens")))
        print(f"         模型={tr.get('model')} 耗时={tr.get('latency_ms')}ms "
              f"tokens={tr.get('prompt_tokens')}+{tr.get('completion_tokens')}")

        # ---------- 即时生效（缓存必须失效） ----------
        print("即时生效 …")
        r = c.get("/api/v1/kb", headers=H)
        kbs = r.json() if r.status_code == 200 else []
        if not kbs:
            check("存在可用知识库", False, "没有知识库，跳过生效验证")
        else:
            kb_id = kbs[0]["id"]
            r = c.post(
                "/api/v1/chat/sessions",
                headers=H,
                json={"kb_ids": [kb_id], "title": "提示词生效验证"},
            )
            sid = r.json()["id"] if r.status_code in (200, 201) else None
            if not sid:
                check("创建会话", False, r.text[:200])
            else:
                started = time.time()
                r = c.post(
                    f"/api/v1/chat/sessions/{sid}/ask",
                    headers=H,
                    json={"question": "出差住宿标准是多少钱"},
                    timeout=180,
                )
                body = r.json() if r.status_code == 200 else {}
                ans = body.get("answer", "")
                cost = int((time.time() - started) * 1000)
                check("问答链路可用", r.status_code == 200, r.text[:200])
                # 刚才保存的模板要求"回答开头必须输出标记"，能体现说明新提示词已生效
                check("改完提示词立即生效", MARK in ans, ans[:60])
                print(f"         模型={body.get('model')} 耗时={cost}ms 回答={ans[:40]}")
                c.delete(f"/api/v1/chat/sessions/{sid}", headers=H)

        # ---------- 回滚 ----------
        print("回滚 …")
        back_to = int(saved.get("version") or 1)
        r = c.post(f"/api/v1/admin/prompts/system_qa/rollback/{back_to}", headers=H)
        rb = r.json() if r.status_code == 200 else {}
        check("回滚成功", r.status_code == 200, r.text[:200])
        check(
            "回滚生成新版本（不覆盖历史）",
            rb.get("version", 0) > back_to,
            f"rollback={rb.get('version')} target=v{back_to}",
        )
        check("回滚内容与目标版本一致", MARK in rb.get("content", ""), rb.get("content", "")[:60])

        r = c.post("/api/v1/admin/prompts/system_qa/rollback/99", headers=H)
        check("不存在的版本被拒", r.status_code == 404, str(r.status_code))

        # ---------- 恢复默认 ----------
        print("恢复默认 …")
        r = c.post("/api/v1/admin/prompts/system_qa/reset", headers=H)
        rs = r.json() if r.status_code == 200 else {}
        check("恢复成功", r.status_code == 200, r.text[:150])
        check("内容等于内置", rs.get("content") == original, "内容不一致")
        check("不再标记自定义", rs.get("is_customized") is False, str(rs.get("is_customized")))
        # 恢复默认后必须还能继续保存（版本号不能与历史撞车，这是曾经的隐藏 bug）
        r = c.put(
            "/api/v1/admin/prompts/system_qa",
            headers=H,
            json={"content": original + "\n补充一句：回答保持简洁。", "note": "恢复后再改"},
        )
        check("恢复后仍可保存", r.status_code == 200, r.text[:200])
        r = c.post("/api/v1/admin/prompts/system_qa/reset", headers=H)
        check("可再次恢复默认", r.status_code == 200, r.text[:150])

        # ---------- 审计 ----------
        print("审计 …")
        r = c.get("/api/v1/admin/audit-logs", headers=H, params={"limit": 50})
        logs = r.json() if r.status_code == 200 else []
        actions = {x["action"] for x in (logs.get("items") if isinstance(logs, dict) else logs)}
        check("提示词操作入审计", "prompt.update" in actions, str(sorted(actions))[:150])
        check("回滚入审计", "prompt.rollback" in actions, str(sorted(actions))[:150])
        check("恢复入审计", "prompt.reset" in actions, str(sorted(actions))[:150])

        # ---------- 权限隔离 ----------
        print("权限隔离 …")
        uname = f"ptester{int(time.time()) % 10000}"
        r = c.post(
            "/api/v1/users",
            headers=H,
            json={"username": uname, "password": "Test12345", "role_codes": ["user"]},
        )
        uid = r.json().get("id") if r.status_code in (200, 201) else None
        if uid:
            r = c.post("/api/v1/auth/login", json={"username": uname, "password": "Test12345"})
            if r.status_code == 200:
                UH = {"Authorization": f"Bearer {r.json()['access_token']}"}
                r = c.get("/api/v1/admin/prompts", headers=UH)
                check("普通用户看提示词 403", r.status_code == 403, str(r.status_code))
                r = c.put(
                    "/api/v1/admin/prompts/system_qa", headers=UH, json={"content": "hack"}
                )
                check("普通用户改提示词 403", r.status_code == 403, str(r.status_code))
            c.delete(f"/api/v1/users/{uid}", headers=H)

    print(f"\n结果: {passed} 通过, {failed} 失败")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
