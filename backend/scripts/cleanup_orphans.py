"""孤儿数据清理：对齐 MySQL chunks 与 Milvus 向量。

产生孤儿的两个来源（都已修）：
1. 重建只删 MySQL 行不删 Milvus 旧向量 → 同一文档向量数是切片数的 N 倍；
2. 删文档时软删了文档、删不掉向量（被静默吞掉）→ chunks 行和向量都残留。

清理原则：**以 MySQL chunks 表为准**。Milvus 里凡是 id 不在有效 chunks 集合的向量，
一律删除；MySQL 里文档已软删的 chunks 行一并删除。幂等，可重复执行。

用法：
    python -m scripts.cleanup_orphans            # 只报告
    python -m scripts.cleanup_orphans --apply    # 实际清理
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, func, select  # noqa: E402

from app.db.models.knowledge import Chunk, Document, KnowledgeBase  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402
from app.services.vector_store import get_vector_store  # noqa: E402


async def main() -> int:
    apply_changes = "--apply" in sys.argv
    print(("清理模式" if apply_changes else "报告模式（加 --apply 才会真正删除）") + "\n")

    async with SessionLocal() as db:
        # ---------- 1. 软删文档的 chunks 行 ----------
        # 孤儿定义：文档已删 或 所属知识库已删
        orphan_rows = (
            await db.execute(
                select(Chunk.id)
                .join(Document, Chunk.doc_id == Document.id)
                .join(KnowledgeBase, Document.kb_id == KnowledgeBase.id)
                .where(
                    (Document.is_deleted == 1) | (KnowledgeBase.is_deleted == 1)
                )
            )
        ).scalars().all()
        print(f"MySQL：文档/知识库已删遗留的切片行 {len(orphan_rows)} 条")
        if apply_changes and orphan_rows:
            await db.execute(delete(Chunk).where(Chunk.id.in_(orphan_rows)))
            await db.commit()

        # ---------- 2. 有效 chunks 集合 ----------
        valid_ids = set(
            (
                await db.execute(
                    select(Chunk.id)
                    .join(Document, Chunk.doc_id == Document.id)
                    .join(KnowledgeBase, Document.kb_id == KnowledgeBase.id)
                    .where(Document.is_deleted == 0, KnowledgeBase.is_deleted == 0)
                )
            )
            .scalars()
            .all()
        )
        print(f"MySQL：有效切片 {len(valid_ids)} 条")

        # ---------- 3. Milvus 对账 ----------
        store = get_vector_store()
        # Milvus 单次 query 上限 16384，分页拉全量
        rows: list[dict] = []
        offset = 0
        page = 10000
        while True:
            batch = store.client.query(
                collection_name=store.collection,
                output_fields=["id", "doc_id"],
                limit=page,
                offset=offset,
            )
            rows.extend(batch)
            if len(batch) < page:
                break
            offset += page
        stale = [r["id"] for r in rows if r["id"] not in valid_ids]
        by_doc: dict[int, int] = {}
        for r in rows:
            by_doc[r["doc_id"]] = by_doc.get(r["doc_id"], 0) + 1

        print(f"Milvus：向量总数 {len(rows)}")
        print(f"Milvus：孤儿向量（id 不在有效切片中）{len(stale)} 条")

        # 各文档向量数 vs 切片数
        print("\n—— 各文档向量/切片对比 ——")
        doc_rows = (
            await db.execute(
                select(Document.id, Document.name, Document.is_deleted, Document.chunk_count)
            )
        ).all()
        mismatch = 0
        for did, name, deleted, chunk_count in doc_rows:
            v = by_doc.get(did, 0)
            flag = ""
            if deleted:
                flag = "（已删除）"
            elif v != chunk_count:
                flag = "  ← 不一致"
                mismatch += 1
            print(f"  doc {did:>3} {name:<28} 向量={v:<4} 切片={chunk_count:<4} {flag}")

        if apply_changes and stale:
            for i in range(0, len(stale), 500):
                store.delete_by_ids(stale[i : i + 500])
            print(f"\n已删除孤儿向量 {len(stale)} 条")
        elif stale:
            print("\n（未删除，加 --apply 执行）")

        # ---------- 4. 重算统计 ----------
        if apply_changes:
            # 逐文档重算 chunk_count（软删文档的计数字段容易残留旧值）
            for doc in (await db.execute(select(Document))).scalars().all():
                n = (
                    await db.execute(
                        select(func.count(Chunk.id)).where(Chunk.doc_id == doc.id)
                    )
                ).scalar()
                doc.chunk_count = int(n) if doc.is_deleted == 0 else 0
        if apply_changes:
            for kb in (await db.execute(select(KnowledgeBase))).scalars().all():
                n_docs = (
                    await db.execute(
                        select(func.count(Document.id)).where(
                            Document.kb_id == kb.id, Document.is_deleted == 0
                        )
                    )
                ).scalar()
                n_chunks = (
                    await db.execute(
                        select(func.count(Chunk.id))
                        .join(Document, Chunk.doc_id == Document.id)
                        .where(Document.kb_id == kb.id, Document.is_deleted == 0)
                    )
                ).scalar()
                kb.doc_count = int(n_docs)
                kb.chunk_count = int(n_chunks)
            await db.commit()
            print("已重算各知识库 doc_count / chunk_count")

        store.close()
        print(f"\n不一致文档 {mismatch} 个（加 --apply 会一并清理多余向量）")

    await engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
