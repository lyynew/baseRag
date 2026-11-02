"""混合检索对比测试：在大批语义相似的文档中找精确编号。

为什么这么设计：
只在 5 条互不明显重叠的文档里测，"DL380" 这种查询纯向量也能命中，
看不出 BM25 的价值。真正的失效场景是——**几十条语义高度相似的文档，
其中只有一条含某个专有编号**，此时纯向量的排名会被"语义相近"稀释，
而 BM25 靠字面精确匹配能把它顶上来。

用法：
    python -m scripts.test_hybrid --drop
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.embedding import EmbeddingClient  # noqa: E402
from app.services.vector_store import VectorStore  # noqa: E402

KB_ID = 99  # 独立测试库

# 20 条**只差编号**的文档：语义几乎完全相同，向量高度重合。
# 这是 dense 检索的确定性弱点——余弦相似度区分不开 RACK-007 和 RACK-008，
# 而 BM25 靠精确字面匹配必然能分开。真实场景对应：设备台账、工单列表、条款编号。
CHUNKS: list[str] = [
    f"设备台账：机柜编号 RACK-{i:03d}，位于 A 机房第 {i % 4 + 1} 排，"
    "运维负责人为张三，季度巡检日期为每季度最后一周。"
    for i in range(1, 21)
]
CHUNKS += [
    "员工出差住宿标准：一线城市每晚不超过 600 元，二线城市不超过 400 元。",
    "数据库每日凌晨 3 点执行全量备份，备份文件保留 30 天。",
    "年假需提前 3 个工作日申请，超过 3 天需部门负责人审批。",
]

CASES = [
    ("RACK-007", 6, "纯编号：20 条几乎相同的文档里定位一条"),
    ("RACK-015 那个机柜谁负责", 14, "编号 + 语义"),
    ("出差住宿能报多少", 20, "纯语义（对照组）"),
    ("备份保留多久", 21, "纯语义（对照组）"),
]


async def main() -> int:
    drop = "--drop" in sys.argv
    print("=" * 78)
    print("混合检索 vs 纯向量检索（23 条文档，其中 20 条只差编号）")
    print("=" * 78)

    store = VectorStore()
    print(f"collection: {store.ensure_collection(drop_existing=drop)}")

    embedder = EmbeddingClient()
    res = await embedder.embed_documents(CHUNKS)
    rows = [
        {"id": i + 1, "kb_id": KB_ID, "doc_id": 100 + i, "content": text, "vector": vec}
        for i, (text, vec) in enumerate(zip(CHUNKS, res.vectors, strict=True))
    ]
    store.upsert(rows)
    print(f"写入 {len(rows)} 条切片，消耗 {res.prompt_tokens} token")
    print("目标切片：按 CASES 指定\n")

    dense_ok = hybrid_ok = 0
    print(f"{'查询':<34}{'期望':<7}{'纯向量排名':<14}{'混合检索排名':<14}")
    print("-" * 78)

    def rank_of(hits: list, idx: int) -> int | None:
        for i, h in enumerate(hits):
            if h.chunk_id - 1 == idx:
                return i + 1
        return None

    for query, expect_idx, _note in CASES:
        qv = await embedder.embed_query(query)

        dense_hits = store.search(qv, kb_ids=[KB_ID], top_k=10)
        hybrid_hits = store.hybrid_search(qv, query, kb_ids=[KB_ID], top_k=10)

        d_rank = rank_of(dense_hits, expect_idx)
        h_rank = rank_of(hybrid_hits, expect_idx)
        dense_ok += 1 if d_rank == 1 else 0
        hybrid_ok += 1 if h_rank == 1 else 0

        d_str = "top1 ✓" if d_rank == 1 else (f"第 {d_rank} 位 ✗" if d_rank else "未进前10 ✗")
        h_str = "top1 ✓" if h_rank == 1 else (f"第 {h_rank} 位 ✗" if h_rank else "未进前10 ✗")
        print(f"{query[:32]:<34}#{expect_idx+1:<6}{d_str:<14}{h_str:<14}")

    print("-" * 78)
    print(f"纯向量 top1 命中 : {dense_ok}/{len(CASES)}")
    print(f"混合检索 top1 命中: {hybrid_ok}/{len(CASES)}")
    print(f"\nEmbedding 消耗: {embedder.usage.prompt_tokens} token")

    store.delete_by_kb(KB_ID)
    store.close()
    print("已清理测试向量")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
