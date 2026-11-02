"""端到端验证：文档 → 切片 → 向量化 → Milvus 入库 → 检索。

目的：用最小成本（几千 token）验证整条向量链路是否打通，
并实测 token 消耗，确认成本可控。

用法：
    python -m scripts.test_vector_pipeline
    python -m scripts.test_vector_pipeline --drop     # 重建 collection
"""

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import settings  # noqa: E402
from app.services.embedding import EmbeddingClient  # noqa: E402
from app.services.rerank import RerankClient  # noqa: E402
from app.services.vector_store import VectorStore  # noqa: E402

# ---------------- 测试语料：4 篇短文，主题互不重叠，便于验证召回 ----------------
DOCS = [
    {
        "doc_id": 1,
        "name": "差旅报销制度",
        "text": (
            "员工出差需提前在系统中提交出差申请，经直属主管审批后方可预订交通与住宿。"
            "住宿标准：一线城市每晚不超过 600 元，二线城市不超过 400 元，其他城市不超过 300 元。"
            "交通标准：高铁二等座、飞机经济舱。市内交通凭票据实报实销，单日上限 100 元。"
            "报销需在出差结束后 15 个工作日内提交，逾期原则上不予受理，特殊情况需部门总监签字。"
        ),
    },
    {
        "doc_id": 2,
        "name": "服务器运维规范",
        "text": (
            "生产环境服务器禁止直接登录操作，所有变更必须通过发布平台执行并留下审计记录。"
            "每日凌晨 2 点自动巡检一次，巡检项包括磁盘使用率、CPU 负载、内存占用和关键进程存活。"
            "磁盘使用率超过 80% 触发告警，超过 90% 立即通知值班工程师处理。"
            "任何重启操作必须先在值班群报备，并确认无正在运行的批处理任务。"
        ),
    },
    {
        "doc_id": 3,
        "name": "请假与考勤流程",
        "text": (
            "年假需提前 3 个工作日申请，3 天以内由直属主管审批，超过 3 天需部门负责人二次审批。"
            "病假需提供二级以上医院开具的证明，当天无法到岗的应在上 午 10 点前电话告知主管。"
            "事假每月累计不超过 3 天，超出部分按事假工资标准扣减。"
            "所有请假必须在考勤系统中登记，未登记的缺勤按旷工处理。"
        ),
    },
    {
        "doc_id": 4,
        "name": "数据库备份与恢复策略",
        "text": (
            "MySQL 生产库每日凌晨 3 点执行一次全量逻辑备份，备份文件加密后上传至对象存储。"
            "全量备份保留 30 天，每月的第一个备份额外保留 12 个月用于年度审计。"
            "恢复演练每季度执行一次，必须在校验环境中完成，严禁直接在生产库演练。"
            "备份失败时系统自动重试两次，仍失败则立即短信通知 DBA。"
        ),
    },
]

# 查询 → 期望命中的文档
QUERIES = [
    ("出差住酒店一晚最多能报多少钱", 1),
    ("数据库的备份文件保存多久", 4),
    ("请假三天以内谁审批", 3),
    ("服务器磁盘快满了会告警吗", 2),
]


def simple_split(text: str, size: int = 200) -> list[str]:
    """极简切片：按句号切，累积到 size 字。正式实现用 LangChain 的分割器。"""
    parts = [p.strip() for p in text.replace("。", "。\n").split("\n") if p.strip()]
    chunks, buf = [], ""
    for p in parts:
        if len(buf) + len(p) <= size:
            buf += p
        else:
            if buf:
                chunks.append(buf)
            buf = p
    if buf:
        chunks.append(buf)
    return chunks


async def main() -> int:
    drop = "--drop" in sys.argv

    print("=" * 68)
    print("RAG 向量链路端到端验证")
    print("=" * 68)
    print(f"Embedding 模型 : {settings.embedding_model}")
    print(f"向量维度       : {settings.embedding_dim}")
    print(f"Milvus          : {settings.milvus_host}:{settings.milvus_port}")
    print(f"Collection      : {settings.milvus_collection}")

    store = VectorStore()
    reranker = RerankClient()
    try:
        state = store.ensure_collection(drop_existing=drop)
        print(f"Collection      : {state}")
    except Exception as exc:  # noqa: BLE001
        print(f"\n[失败] 无法连接 Milvus：{type(exc).__name__}: {exc}")
        store.close()
        return 1

    # 1) 切片
    rows: list[dict] = []
    chunk_id = 1
    for d in DOCS:
        for idx, chunk in enumerate(simple_split(d["text"], size=90)):
            rows.append(
                {
                    "id": chunk_id,
                    "kb_id": 1,
                    "doc_id": d["doc_id"],
                    "content": chunk,
                    "chunk_index": idx,
                }
            )
            chunk_id += 1
    total_chars = sum(len(r["content"]) for r in rows)
    print(f"\n切片数         : {len(rows)} 个（共 {total_chars} 字）")

    # 2) 向量化
    client = EmbeddingClient()
    print("\n开始向量化 …")
    t0 = time.perf_counter()
    try:
        res = await client.embed_documents([r["content"] for r in rows])
    except Exception as exc:  # noqa: BLE001
        print(f"[失败] 向量化异常：{type(exc).__name__}: {exc}")
        store.close()
        return 1
    elapsed = time.perf_counter() - t0
    print(f"向量数         : {len(res.vectors)}，维度 {len(res.vectors[0])}")
    print(f"耗时           : {elapsed:.2f}s")
    print(f"**消耗 token   : {res.prompt_tokens}**")

    # 3) 入库
    for r, vec in zip(rows, res.vectors, strict=True):
        r["vector"] = vec
    written = store.upsert(rows)
    print(f"写入 Milvus    : {written} 条")
    count = store.count("kb_id == 1")
    print(f"库内实体数     : {count}")

    # 4) 检索验证
    print("\n" + "-" * 68)
    print("检索验证")
    print("-" * 68)
    correct = 0
    for q, expect_doc in QUERIES:
        qv = await client.embed_query(q)
        hits = store.search(qv, kb_ids=[1], top_k=5)
        if not hits:
            print(f"  [FAIL] {q} → 无召回")
            continue

        dense_top = hits[0]
        # 精排：把召回候选交给 cross-encoder 重新打分
        ranked = await reranker.rerank(q, [h.content for h in hits], top_n=3)
        rr_idx, rr_score = ranked[0] if ranked else (0, 0.0)
        rr_top = hits[rr_idx] if ranked else dense_top

        ok = rr_top.doc_id == expect_doc
        correct += 1 if ok else 0
        mark = "PASS" if ok else "FAIL"
        expect_name = next(d["name"] for d in DOCS if d["doc_id"] == expect_doc)
        dense_name = next(d["name"] for d in DOCS if d["doc_id"] == dense_top.doc_id)
        rr_name = next(d["name"] for d in DOCS if d["doc_id"] == rr_top.doc_id)
        print(f"  [{mark}] {q}")
        print(f"         向量召回 : {dense_name} ({dense_top.score:.4f})")
        print(f"         rerank 后: {rr_name} ({rr_score:.4f})   期望: {expect_name}")

    # 5) 成本汇总
    print("\n" + "=" * 68)
    print("成本汇总")
    print("=" * 68)
    print(f"Embedding 总计  : {client.usage.prompt_tokens} token")
    print(f"  入库         : {res.prompt_tokens}")
    print(f"  查询         : {client.usage.prompt_tokens - res.prompt_tokens}")
    print(f"Rerank 总计    : {reranker.total_tokens} token")
    print(f"全部合计       : {client.usage.prompt_tokens + reranker.total_tokens} token")
    print(f"请求次数       : {client.usage.calls}（失败重试 {client.usage.failures} 次）")
    print(f"按模型         : {client.usage.by_model}")
    print("\n注：具体单价以百炼控制台为准。本次总量在千 token 量级，")
    print("    属于最低计费档位（通常不足 0.01 元），远低于 1 元预算。")

    print(f"\n召回准确率     : {correct}/{len(QUERIES)}")

    store.close()
    return 0 if correct == len(QUERIES) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
