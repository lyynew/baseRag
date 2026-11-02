"""把一个目录下的 Markdown/文本文件灌入指定知识库（新建或追加）。

用途：造一个真实可用的知识库做演示与回归，也用于批量导入既有文档。

用法：
    # 新建知识库并导入
    python -m scripts.seed_kb "Vue3 基础知识" ../knowledge/vue3 --password xxx

    # 追加到已有知识库
    python -m scripts.seed_kb "Vue3 基础知识" ../knowledge/vue3 --kb-id 12 --password xxx

为什么串行上传：
每个文件都会触发一次入库任务（解析→切片→向量化）。并发上传会让 embedding 侧
瞬时打满并发，触发 429 后靠退避重试，反而更慢，日志也更难读。串行等待
「上传 → 任务成功」再传下一个，总耗时可预期。
"""

import argparse
import os
import sys
import time
from pathlib import Path

import httpx

BASE_URL = os.environ.get("SMOKE_BASE_URL", "http://127.0.0.1:8000")
USERNAME = "admin"
MIME = {".md": "text/markdown", ".txt": "text/plain", ".csv": "text/csv"}
SUPPORTED = {".md", ".markdown", ".txt", ".csv"}


def wait_task(c: httpx.Client, headers: dict, task_id: int, timeout: int = 600) -> dict:
    deadline = time.time() + timeout
    last: dict = {}
    while time.time() < deadline:
        r = c.get(f"/api/v1/kb/tasks/{task_id}", headers=headers)
        if r.status_code != 200:
            return {"status": "error", "raw": r.text[:200]}
        last = r.json()
        if last.get("status") in ("success", "failed", "canceled"):
            return last
        time.sleep(2)
    return last or {"status": "timeout"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("name", help="知识库名称（不存在则创建）")
    ap.add_argument("dir", help="文档目录")
    ap.add_argument("--kb-id", type=int, default=0, help="已有知识库 id，指定则追加")
    ap.add_argument("--password", default=os.environ.get("ADMIN_PASSWORD", ""))
    ap.add_argument("--description", default="")
    args = ap.parse_args()

    if not args.password:
        print("缺少密码：--password 或环境变量 ADMIN_PASSWORD")
        return 2

    root = Path(args.dir)
    if not root.is_dir():
        print(f"目录不存在：{root}")
        return 2
    files = sorted(p for p in root.iterdir() if p.suffix.lower() in SUPPORTED)
    if not files:
        print(f"{root} 下没有可导入的文件（支持 {', '.join(sorted(SUPPORTED))}）")
        return 2

    print(f"目标: {BASE_URL}")
    print(f"文档: {len(files)} 个\n")

    with httpx.Client(base_url=BASE_URL, timeout=120) as c:
        r = c.post("/api/v1/auth/login", json={"username": USERNAME, "password": args.password})
        if r.status_code != 200:
            print(f"登录失败: {r.status_code} {r.text[:200]}")
            return 1
        H = {"Authorization": f"Bearer {r.json()['access_token']}"}

        kb_id = args.kb_id
        if not kb_id:
            r = c.post(
                "/api/v1/kb",
                headers=H,
                json={
                    "name": args.name,
                    "description": args.description or f"由 scripts.seed_kb 导入（{root.name}）",
                    "chunk_config": {
                        "strategy": "markdown_header",
                        "chunk_size": 400,
                        "chunk_overlap": 60,
                        "min_chunk_size": 30,
                        "keep_table_intact": True,
                    },
                    "retrieve_config": {
                        "top_k": 30,
                        "rerank_top_n": 8,
                        "rerank_enabled": True,
                    },
                },
            )
            if r.status_code != 200:
                print(f"建库失败: {r.status_code} {r.text[:300]}")
                return 1
            kb = r.json()
            kb_id = kb["id"]
            print(
                f"[建库] id={kb_id}  {kb['name']}  "
                f"{kb['embedding_model']}/{kb['embedding_dim']}\n"
            )
        else:
            print(f"[追加] 目标知识库 id={kb_id}\n")

        ok, skipped, failed = 0, 0, []
        total_chunks = 0
        started = time.time()

        for i, path in enumerate(files, 1):
            name = path.name
            content = path.read_bytes()
            r = c.post(
                f"/api/v1/kb/{kb_id}/documents",
                headers=H,
                files={"file": (name, content, MIME.get(path.suffix.lower(), "text/plain"))},
            )
            if r.status_code != 200:
                failed.append((name, f"上传 {r.status_code} {r.text[:120]}"))
                print(f"[{i}/{len(files)}] {name}  上传失败 {r.status_code}")
                continue

            body = r.json()
            if body.get("duplicated"):
                skipped += 1
                print(f"[{i}/{len(files)}] {name}  已存在，跳过")
                continue

            task_id = body["task"]["id"]
            t = wait_task(c, H, task_id)
            if t.get("status") == "success":
                ok += 1
                chunks = int(t.get("total_items") or 0)
                total_chunks += chunks
                print(f"[{i}/{len(files)}] {name}  {chunks} 切片")
            else:
                msg = t.get("error_msg") or t.get("status")
                failed.append((name, str(msg)[:160]))
                print(f"[{i}/{len(files)}] {name}  入库失败: {msg}")

        cost = time.time() - started
        r = c.get(f"/api/v1/kb/{kb_id}/documents", headers=H)
        docs = r.json() if r.status_code == 200 else []
        ready = [d for d in docs if d.get("status") == "ready"]

    print("\n—— 结果 ——")
    print(f"成功 {ok} 个 / 跳过 {skipped} 个 / 失败 {len(failed)} 个")
    print(f"新增切片 {total_chunks} 个，耗时 {cost:.1f}s")
    print(f"知识库 id={kb_id} 当前文档 {len(docs)} 个（就绪 {len(ready)} 个）")
    if failed:
        print("\n失败明细：")
        for n, m in failed:
            print(f"  - {n}: {m}")
    print(f"\n访问：{BASE_URL.replace('8000', '5173')}/admin/kb/{kb_id}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
