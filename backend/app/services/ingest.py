"""入库编排：解析 → 切片 → 向量化 → 写 Milvus。

设计要点：
1. **分段提交**：先落 MySQL chunks（拿到自增 id 作为 Milvus 主键），再分批向量化。
   这样崩溃后重跑能按 embedded 标记跳过已完成的部分（断点续跑）。
2. **进度可观测**：每批更新 ingest_tasks，前端轮询展示。
3. **失败可诊断**：状态、错误信息、trace_id 全部落库，不依赖日志翻找。
4. **成本可核算**：每次向量化的 token 数写 llm_call_logs。
"""

import time
from datetime import datetime

from sqlalchemy import delete, func, select

from app.core.logging import get_logger, get_trace_id
from app.db.models.chat import LlmCallLog
from app.db.models.enums import DocStatus, IngestTaskStatus
from app.db.models.knowledge import Chunk, Document, IngestTask, KnowledgeBase
from app.db.session import SessionLocal
from app.services.chunker import ChunkConfig, split_text
from app.services.embedding import EmbeddingClient
from app.services.parser import parse_document
from app.services.storage import get_storage
from app.services.vector_store import get_vector_store

logger = get_logger(__name__)

EMBED_BATCH = 10  # 百炼单批上限


async def _set_status(session, doc: Document, status: DocStatus, error: str | None = None) -> None:
    doc.status = status
    doc.error_msg = error
    await session.commit()


async def _update_task(
    session,
    task_id: int,
    *,
    status: IngestTaskStatus | None = None,
    processed: int | None = None,
    total: int | None = None,
    error: str | None = None,
    checkpoint: dict | None = None,
) -> None:
    task = (
        await session.execute(select(IngestTask).where(IngestTask.id == task_id))
    ).scalar_one_or_none()
    if task is None:
        return
    if status:
        task.status = status
    if total is not None:
        task.total_items = total
    if processed is not None:
        task.processed_items = processed
        # 注意用 task.total_items，而不是入参 total（后者可能为 None）
        task.progress = (
            min(100, int(processed / task.total_items * 100)) if task.total_items else 0
        )
    if error is not None:
        task.error_msg = error[:2000]
    if checkpoint is not None:
        task.checkpoint = checkpoint
    if status in (IngestTaskStatus.SUCCESS, IngestTaskStatus.FAILED):
        task.finished_at = datetime.now()
    await session.commit()


async def ingest_document(doc_id: int, task_id: int | None = None) -> dict:
    """完整的单文档入库流程。可重复执行（幂等）。"""
    started = time.perf_counter()
    trace_id = get_trace_id()

    async with SessionLocal() as session:
        doc = (
            await session.execute(select(Document).where(Document.id == doc_id))
        ).scalar_one_or_none()
        if doc is None:
            logger.warning("ingest_doc_missing", doc_id=doc_id)
            return {"ok": False, "reason": "document not found"}

        kb = (
            await session.execute(
                select(KnowledgeBase).where(KnowledgeBase.id == doc.kb_id)
            )
        ).scalar_one_or_none()
        if kb is None:
            await _set_status(session, doc, DocStatus.FAILED, "知识库不存在")
            return {"ok": False, "reason": "kb not found"}

        if task_id:
            await _update_task(session, task_id, status=IngestTaskStatus.RUNNING)

        tmp_path = None
        try:
            # ---------- 1. 解析 ----------
            await _set_status(session, doc, DocStatus.PARSING)
            storage = get_storage()
            tmp_path = await storage.download_to_temp(doc.storage_key)
            parsed = parse_document(tmp_path, doc.file_ext)

            doc.page_count = parsed.page_count
            doc.char_count = parsed.char_count
            doc.no_text_layer = False
            await session.commit()

            # ---------- 2. 切片 ----------
            await _set_status(session, doc, DocStatus.SPLITTING)
            cfg = ChunkConfig.from_dict(kb.chunk_config)
            drafts = split_text(parsed.text, cfg)
            if not drafts:
                raise ValueError("切片结果为空，请检查文档内容或切片参数")

            doc.chunk_config_snapshot = cfg.to_dict()

            # 重跑/重建时先清掉旧数据（幂等）。
            # 两个都要清：只清 MySQL 行会让旧向量以旧 id 留在 Milvus，
            # 同一文档的向量数变成切片数的 N 倍（本次事故就是 3 倍），
            # 检索时同一内容重复占位，还会拖慢查询。
            await session.execute(delete(Chunk).where(Chunk.doc_id == doc.id))
            await session.commit()
            try:
                get_vector_store().delete_by_doc(doc.id)
            except Exception as exc:  # noqa: BLE001  清理失败不阻断重建，但必须留痕
                logger.warning("stale_vectors_cleanup_failed", doc_id=doc.id, error=str(exc))

            chunk_rows = [
                Chunk(
                    doc_id=doc.id,
                    kb_id=doc.kb_id,
                    chunk_index=d.index,
                    content=d.content,
                    char_count=d.char_count,
                    token_count=0,
                    section_path=d.section_path,
                    embedded=False,
                    meta={"section_path": d.section_path} if d.section_path else {},
                )
                for d in drafts
            ]
            session.add_all(chunk_rows)
            await session.commit()

            doc.chunk_count = len(chunk_rows)
            await session.commit()

            total = len(chunk_rows)
            if task_id:
                await _update_task(session, task_id, total=total, processed=0)

            # ---------- 3. 向量化并写 Milvus ----------
            await _set_status(session, doc, DocStatus.EMBEDDING)
            embedder = EmbeddingClient()
            store = get_vector_store()
            store.ensure_collection()

            processed = 0
            for i in range(0, total, EMBED_BATCH):
                batch = chunk_rows[i : i + EMBED_BATCH]
                contents = [c.content for c in batch]
                res = await embedder.embed_documents(contents)

                store.upsert(
                    [
                        {
                            "id": c.id,
                            "kb_id": c.kb_id,
                            "doc_id": c.doc_id,
                            "content": c.content,
                            "vector": vec,
                        }
                        for c, vec in zip(batch, res.vectors, strict=True)
                    ]
                )
                for c in batch:
                    c.embedded = True
                    c.milvus_id = c.id
                processed += len(batch)

                # 记录用量，便于成本核算
                session.add(
                    LlmCallLog(
                        scene="embedding",
                        provider="dashscope",
                        model=embedder.model,
                        ref_type="document",
                        ref_id=doc.id,
                        prompt_tokens=res.prompt_tokens,
                        completion_tokens=0,
                        latency_ms=0,
                        status="ok",
                        trace_id=trace_id,
                    )
                )
                await session.commit()

                if task_id:
                    await _update_task(
                        session,
                        task_id,
                        processed=processed,
                        checkpoint={"embedded_chunks": processed},
                    )

            # ---------- 4. 收尾 ----------
            await _set_status(session, doc, DocStatus.READY)

            # 校验 MySQL 与 Milvus 数量一致（"精致"要求里的数据一致性检查）
            db_count = (
                await session.execute(
                    select(func.count()).select_from(Chunk).where(Chunk.doc_id == doc.id)
                )
            ).scalar_one()
            vec_count = store.count(f"doc_id == {doc.id}")
            consistent = db_count == vec_count

            # 更新知识库统计
            kb.doc_count = (
                await session.execute(
                    select(func.count())
                    .select_from(Document)
                    .where(Document.kb_id == kb.id, Document.is_deleted == 0)
                )
            ).scalar_one()
            kb.chunk_count = (
                await session.execute(
                    select(func.count()).select_from(Chunk).where(Chunk.kb_id == kb.id)
                )
            ).scalar_one()
            kb.total_size_bytes = (
                await session.execute(
                    select(func.coalesce(func.sum(Document.file_size), 0)).where(
                        Document.kb_id == kb.id, Document.is_deleted == 0
                    )
                )
            ).scalar_one()
            await session.commit()

            if task_id:
                await _update_task(
                    session, task_id, status=IngestTaskStatus.SUCCESS, processed=total
                )

            elapsed = time.perf_counter() - started
            logger.info(
                "ingest_done",
                doc_id=doc.id,
                chunks=total,
                tokens=embedder.usage.prompt_tokens,
                elapsed=f"{elapsed:.1f}s",
                consistent=consistent,
            )
            return {
                "ok": True,
                "doc_id": doc.id,
                "chunks": total,
                "tokens": embedder.usage.prompt_tokens,
                "elapsed_sec": round(elapsed, 2),
                "consistent": consistent,
                "db_count": db_count,
                "vector_count": vec_count,
            }

        except Exception as exc:  # noqa: BLE001
            msg = f"{type(exc).__name__}: {exc}"
            logger.exception("ingest_failed", doc_id=doc_id, error=msg)
            # 无文本层单独标记，前端要给出明确提示而不是笼统"失败"
            is_no_text = "NO_TEXT_LAYER" in msg or "文本层" in str(exc)
            await _set_status(
                session,
                doc,
                DocStatus.NO_TEXT_LAYER if is_no_text else DocStatus.FAILED,
                msg[:2000],
            )
            if task_id:
                await _update_task(
                    session, task_id, status=IngestTaskStatus.FAILED, error=msg
                )
            return {"ok": False, "reason": msg}
        finally:
            if tmp_path is not None:
                try:
                    tmp_path.unlink(missing_ok=True)
                except OSError:
                    pass
