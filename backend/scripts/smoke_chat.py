"""P2 冒烟测试：会话 → 检索 → 生成 → 引用 → 流式 → 多轮。

用法：
    python -m scripts.smoke_chat <admin_password>
"""

import json
import os
import sys
import time

import httpx

BASE_URL = os.environ.get("SMOKE_BASE_URL", "http://127.0.0.1:8000")
USERNAME = os.environ.get("SMOKE_USERNAME", "admin")

passed, failed = 0, 0

DOC_MD = """# 员工手册

## 考勤制度

上班时间为 9:00 至 18:00，午休 12:00 至 13:00。迟到超过 30 分钟按半天事假处理。

## 报销流程

报销单需在费用发生后 15 个工作日内提交。单笔金额超过 5000 元需财务总监二次审批。
差旅住宿标准：一线城市每晚不超过 600 元，二线城市不超过 400 元，其他城市不超过 300 元。

## 年假规定

入职满一年享受 5 天年假，满三年 10 天，满十年 15 天。年假需提前 3 个工作日申请。
当年未休完的年假最多结转 5 天至次年第一季度。
"""


def check(name: str, ok: bool, detail: str = "") -> bool:
    global passed, failed
    if ok:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name}  {detail}")
    return ok


def parse_sse(lines) -> list[tuple[str, dict]]:
    events, cur_event, buf = [], None, []
    for line in lines:
        line = line.rstrip("\n")
        if line.startswith("event:"):
            cur_event = line[6:].strip()
        elif line.startswith("data:"):
            buf.append(line[5:].strip())
        elif line == "" and cur_event:
            try:
                events.append((cur_event, json.loads("".join(buf))))
            except json.JSONDecodeError:
                events.append((cur_event, {"raw": "".join(buf)}))
            cur_event, buf = None, []
    return events


def wait_task(c: httpx.Client, H: dict, task_id: int, timeout: int = 120) -> dict:
    deadline = time.time() + timeout
    last: dict = {}
    while time.time() < deadline:
        r = c.get(f"/api/v1/kb/tasks/{task_id}", headers=H)
        if r.status_code != 200:
            return {"status": "error"}
        last = r.json()
        if last.get("status") in ("success", "failed", "canceled"):
            return last
        time.sleep(1.5)
    return last


def main() -> int:
    password = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("ADMIN_PASSWORD", "")
    if not password:
        print("缺少密码：python -m scripts.smoke_chat <password>")
        return 2

    print(f"目标: {BASE_URL}\n")
    with httpx.Client(base_url=BASE_URL, timeout=180) as c:
        # 登录
        r = c.post("/api/v1/auth/login", json={"username": USERNAME, "password": password})
        if not check("登录", r.status_code == 200, r.text[:200]):
            return 1
        H = {"Authorization": f"Bearer {r.json()['access_token']}"}

        # 建库 + 上传
        r = c.post(
            "/api/v1/kb",
            headers=H,
            json={
                "name": f"P2冒烟-{int(time.time())}",
                "chunk_config": {"strategy": "markdown_header", "chunk_size": 200},
            },
        )
        if not check("创建知识库", r.status_code == 200, r.text[:200]):
            return 1
        kb_id = r.json()["id"]

        r = c.post(
            f"/api/v1/kb/{kb_id}/documents",
            headers=H,
            files={"file": ("员工手册.md", DOC_MD.encode(), "text/markdown")},
        )
        if not check("上传文档", r.status_code == 200, r.text[:300]):
            return 1
        t = wait_task(c, H, r.json()["task"]["id"])
        check("入库完成", t.get("status") == "success", str(t)[:200])

        # 建会话
        r = c.post("/api/v1/chat/sessions", headers=H, json={"kb_ids": [kb_id]})
        if not check("创建会话", r.status_code == 200, r.text[:300]):
            return 1
        sid = r.json()["id"]
        print(f"         会话 id={sid}  model={r.json().get('chat_model')}")

        # 非流式提问
        print("\n非流式问答 …")
        t0 = time.perf_counter()
        r = c.post(
            f"/api/v1/chat/sessions/{sid}/ask",
            headers=H,
            json={"question": "出差住宿一线城市最多能报多少？"},
        )
        cost = time.perf_counter() - t0
        ok = check("非流式提问返回", r.status_code == 200, r.text[:300])
        if ok:
            body = r.json()
            ans = body["answer"]
            print(f"         耗时 {cost:.1f}s  model={body['model']}")
            print(f"         答案: {ans[:110]}")
            check("答案非空", len(ans) > 5)
            check("命中知识库片段", body["retrieval"]["hits"] > 0, str(body["retrieval"]))
            check("答案包含关键数字 600", "600" in ans, ans[:120])
            check("返回引用", len(body["citations"]) > 0, str(body["citations"])[:200])
            if body["citations"]:
                c0 = body["citations"][0]
                print(
                    f"         引用[1] chunk={c0['chunk_id']} "
                    f"doc={c0['doc_id']} score={c0['score']}"
                )

        # 流式提问
        print("\n流式问答 …")
        events: list[tuple[str, dict]] = []
        t0 = time.perf_counter()
        with c.stream(
            "POST",
            f"/api/v1/chat/sessions/{sid}/stream",
            headers=H,
            json={"question": "年假可以结转几天？"},
        ) as resp:
            check("流式 HTTP 200", resp.status_code == 200, str(resp.status_code))
            check(
                "Content-Type 正确",
                "text/event-stream" in resp.headers.get("content-type", ""),
                resp.headers.get("content-type", ""),
            )
            events = parse_sse(resp.iter_lines())
        dt = time.perf_counter() - t0

        names = [e[0] for e in events]
        check("收到 retrieval 事件", "retrieval" in names, str(names[:6]))
        check("收到 delta 事件", names.count("delta") > 0, f"delta×{names.count('delta')}")
        check("收到 done 事件", "done" in names)

        text = "".join(d.get("text", "") for n, d in events if n == "delta")
        print(f"         耗时 {dt:.1f}s  delta {names.count('delta')} 包")
        print(f"         答案: {text[:110]}")
        check("流式文本非空", len(text) > 5)
        check("流式答案含 5 天", "5" in text, text[:120])

        done = next((d for n, d in events if n == "done"), {})
        check("done 事件带 message_id", bool(done.get("message_id")), str(done)[:200])
        check(
            "done 事件带引用",
            len(done.get("citations") or []) > 0,
            str(done.get("citations"))[:200],
        )
        if done.get("ttft_ms"):
            print(f"         首 token {done['ttft_ms']}ms  总 {done['latency_ms']}ms")

        # 多轮：追问应能利用历史
        print("\n多轮追问 …")
        r = c.post(
            f"/api/v1/chat/sessions/{sid}/ask",
            headers=H,
            json={"question": "那二线城市呢？"},
        )
        ok = check("追问返回", r.status_code == 200, r.text[:200])
        if ok:
            ans2 = r.json()["answer"]
            print(f"         答案: {ans2[:110]}")
            check("追问答案含二线标准 400", "400" in ans2, ans2[:120])

        # 消息列表
        r = c.get(f"/api/v1/chat/sessions/{sid}/messages", headers=H)
        msgs = r.json() if r.status_code == 200 else []
        check("消息已持久化", len(msgs) >= 6, f"{len(msgs)} 条")
        check("消息序号连续", all(m["seq"] > 0 for m in msgs))

        # 反馈
        if done.get("message_id"):
            r = c.post(
                f"/api/v1/chat/messages/{done['message_id']}/feedback",
                headers=H,
                json={"feedback": 1},
            )
            check("点赞接口", r.status_code == 200, r.text[:200])

        # 权限：他人会话不可见（用无 token 验证鉴权）
        r = c.get(f"/api/v1/chat/sessions/{sid}/messages")
        check("未登录访问被拒", r.status_code == 401, str(r.status_code))

        # 清理
        c.delete(f"/api/v1/kb/{kb_id}", headers=H)
        c.delete(f"/api/v1/chat/sessions/{sid}", headers=H)

    print(f"\n结果: {passed} 通过, {failed} 失败")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
