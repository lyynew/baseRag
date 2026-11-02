"""P1 冒烟测试：建库 → 上传 → 解析切片 → 向量化 → 入库 → 检索。

用法：
    python -m scripts.smoke_kb <admin_password>
    python -m scripts.smoke_kb <password> --keep   # 保留测试知识库

设计原则：走真实 HTTP 接口，不直接调内部函数，确保接口层与业务层都正确。
"""

import os
import sys
import time

import httpx

BASE_URL = os.environ.get("SMOKE_BASE_URL", "http://127.0.0.1:8000")
USERNAME = os.environ.get("SMOKE_USERNAME", "admin")

passed, failed = 0, 0


def check(name: str, ok: bool, detail: str = "") -> bool:
    global passed, failed
    if ok:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name}  {detail}")
    return ok


EMPLOYEE_MD = """# 员工手册

## 考勤制度

上班时间为 9:00 至 18:00，午休 12:00 至 13:00。迟到超过 30 分钟按半天事假处理。
每月允许 3 次 15 分钟以内的弹性到岗，需提前在考勤系统报备。

## 报销流程

报销单需在费用发生后 15 个工作日内提交，逾期原则上不予受理。
单笔金额超过 5000 元的报销需财务总监二次审批。差旅住宿标准见下表：

| 城市级别 | 住宿上限（元/晚） | 交通标准 |
| --- | --- | --- |
| 一线城市 | 600 | 高铁二等座、飞机经济舱 |
| 二线城市 | 400 | 高铁二等座 |
| 其他城市 | 300 | 高铁二等座 |

## 年假规定

入职满一年享受 5 天年假，满三年 10 天，满十年 15 天。年假需提前 3 个工作日申请，
经直属主管审批后生效。当年未休完的年假最多结转 5 天至次年第一季度。
"""

OPS_TXT = """服务器运维规范

每日凌晨 2 点执行自动巡检，检查项包括磁盘使用率、CPU 负载、内存占用和关键进程存活状态。

磁盘使用率超过 80% 触发邮件告警，超过 90% 立即短信通知值班工程师处理。
CPU 负载连续 5 分钟高于 16 触发扩容评估流程。

重启生产服务器必须先在值班群报备，并确认没有正在运行的批处理任务。
所有变更必须通过发布平台执行并留存审计记录，禁止直接 SSH 登录生产机操作。

数据库备份每日凌晨 3 点执行，备份文件加密后上传对象存储，保留 30 天。
"""

QUERIES = [
    ("出差住酒店一晚最多能报多少钱", "员工手册"),
    ("磁盘使用率到多少会发短信告警", "服务器运维规范"),
    ("年假可以结转几天", "员工手册"),
]


def wait_task(c: httpx.Client, headers: dict, task_id: int, timeout: int = 120) -> dict:
    """轮询任务直到结束。"""
    deadline = time.time() + timeout
    last = {}
    while time.time() < deadline:
        r = c.get(f"/api/v1/kb/tasks/{task_id}", headers=headers)
        if r.status_code != 200:
            return {"status": "error", "raw": r.text[:200]}
        last = r.json()
        if last.get("status") in ("success", "failed", "canceled"):
            return last
        time.sleep(1.5)
    return last or {"status": "timeout"}


def main() -> int:
    password = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("ADMIN_PASSWORD", "")
    if not password:
        print("缺少密码：python -m scripts.smoke_kb <password>")
        return 2
    keep = "--keep" in sys.argv

    print(f"目标: {BASE_URL}\n")
    with httpx.Client(base_url=BASE_URL, timeout=60) as c:
        # 1. 登录
        r = c.post("/api/v1/auth/login", json={"username": USERNAME, "password": password})
        if not check("登录", r.status_code == 200, r.text[:200]):
            return 1
        tok = r.json()["access_token"]
        H = {"Authorization": f"Bearer {tok}"}

        # 2. 建库（结构化切片，便于验证 section_path）
        kb_name = f"P1冒烟-{int(time.time())}"
        r = c.post(
            "/api/v1/kb",
            headers=H,
            json={
                "name": kb_name,
                "description": "自动化冒烟测试创建",
                "chunk_config": {
                    "strategy": "markdown_header",
                    "chunk_size": 200,
                    "chunk_overlap": 40,
                },
            },
        )
        if not check("创建知识库", r.status_code == 200, r.text[:300]):
            return 1
        kb = r.json()
        kb_id = kb["id"]
        print(
            f"         知识库 id={kb_id}  "
            f"embedding={kb['embedding_model']}/{kb['embedding_dim']}"
        )

        # 3. 上传两个文件
        uploads = [
            ("员工手册.md", EMPLOYEE_MD.encode("utf-8"), "text/markdown"),
            ("服务器运维规范.txt", OPS_TXT.encode("utf-8"), "text/plain"),
        ]
        task_ids, doc_ids = [], []
        for name, content, mime in uploads:
            r = c.post(
                f"/api/v1/kb/{kb_id}/documents",
                headers=H,
                files={"file": (name, content, mime)},
            )
            ok = check(f"上传 {name}", r.status_code == 200, r.text[:300])
            if ok:
                body = r.json()
                task_ids.append(body["task"]["id"])
                doc_ids.append(body["document"]["id"])

        # 4. 等入库完成
        print("\n等待入库 …")
        for name, task_id in zip([u[0] for u in uploads], task_ids, strict=False):
            t = wait_task(c, H, task_id)
            ok = check(f"入库 {name}", t.get("status") == "success", str(t)[:300])
            if ok:
                print(
                    f"         进度 {t['progress']}%  切片 {t['total_items']} 个"
                )

        # 5. 文档状态
        r = c.get(f"/api/v1/kb/{kb_id}/documents", headers=H)
        docs = r.json() if r.status_code == 200 else []
        check("文档列表可查", len(docs) == 2, str(len(docs)))
        for d in docs:
            check(
                f"状态 ready: {d['name']}",
                d["status"] == "ready",
                f"status={d['status']} err={d.get('error_msg')}",
            )
            print(f"         {d['name']}: {d['chunk_count']} 切片, {d['char_count']} 字")

        # 6. 查看切片（验证 section_path）
        if doc_ids:
            r = c.get(f"/api/v1/kb/{kb_id}/chunks/{doc_ids[0]}", headers=H)
            if r.status_code == 200:
                data = r.json()
                paths = [i["section_path"] for i in data["items"] if i.get("section_path")]
                check("切片含章节路径", len(paths) > 0, str(paths)[:200])
                parts = data["items"][:2]
                check("切片内容非空", all(i["content"] for i in parts))

        # 7. 检索验证
        print("\n检索验证 …")
        correct = 0
        for q, expect_doc in QUERIES:
            r = c.post(f"/api/v1/kb/{kb_id}/search", headers=H, json={"query": q, "rerank": True})
            if r.status_code != 200:
                check(f"检索: {q}", False, r.text[:200])
                continue
            body = r.json()
            top = body["hits"][0] if body["hits"] else None
            ok = top is not None and expect_doc in (top.get("doc_name") or "")
            correct += 1 if ok else 0
            check(f"检索命中: {q}", ok, f"got={top.get('doc_name') if top else None}")
            if top:
                print(
                    f"         来自 {top['doc_name']}  score={top['score']} "
                    f"向量分={top['vector_score']}  召回 {body['vector_hits']} 条"
                )

        # 8. 权限：无 token 访问
        r = c.get(f"/api/v1/kb/{kb_id}")
        check("未登录被拒", r.status_code == 401, str(r.status_code))

        # 9. 清理
        if not keep:
            r = c.delete(f"/api/v1/kb/{kb_id}", headers=H)
            check("删除知识库", r.status_code == 200, r.text[:200])

    print(f"\n结果: {passed} 通过, {failed} 失败  检索 {correct}/{len(QUERIES)}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
