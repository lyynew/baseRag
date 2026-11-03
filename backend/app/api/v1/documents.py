"""文档上传、列表、删除、重建、任务进度。"""

import asyncio
from pathlib import Path

from fastapi import APIRouter, File, Query, UploadFile
from sqlalchemy import delete, select

from app.core.config import settings
from app.core.deps import CurrentUser, DbSession
from app.core.errors import AppError, ErrorCode
from app.core.logging import get_logger
from app.db.models.enums import DocStatus, IngestTaskStatus, IngestTaskType
from app.db.models.knowledge import Chunk, Document, IngestTask
from app.schemas.kb import DocumentOut, IngestTaskOut, UploadResult
from app.services import kb_service
from app.services.storage import StorageService, get_storage
from app.services.vector_store import get_vector_store

logger = get_logger(__name__)
router = APIRouter()


def _ext_of(filename: str) -> str:
    return Path(filename).suffix.lstrip(".").lower()


def _check_ext(ext: str) -> None:
    if not ext:
        raise AppError("文件缺少扩展名", code=ErrorCode.UNSUPPORTED_FILE_TYPE, status_code=415)
    if ext not in settings.allowed_extensions:
        raise AppError(
            f"不支持 .{ext} 格式，当前支持：{', '.join(settings.allowed_extensions)}",
            code=ErrorCode.UNSUPPORTED_FILE_TYPE,
            status_code=415,
        )


async def _get_doc_or_404(db, doc_id: int) -> Document:
    doc = (
        await db.execute(
            select(Document).where(Document.id == doc_id, Document.is_deleted == 0)
        )
    ).scalar_one_or_none()
    if doc is None:
        raise AppError("文档不存在", code=ErrorCode.DOC_NOT_FOUND, status_code=404)
    return doc


async def _dispatch_ingest(doc_id: int, task_id: int) -> None:
    """投递入库任务。

    celery 模式：投给 worker，接口立即返回（推荐，生产用）
    inline 模式：进程内异步执行，仅用于本地开发（重启会丢任务）
    """
    if settings.ingest_mode == "inline":
        from app.services.ingest import ingest_document

        async def _run() -> None:
            try:
                await ingest_document(doc_id, task_id)
            except Exception:  # noqa: BLE001
                logger.exception("inline_ingest_failed", doc_id=doc_id)

        asyncio.create_task(_run())
        logger.info("ingest_dispatched_inline", doc_id=doc_id, task_id=task_id)
        return

    from app.workers.tasks import parse_document_task

    parse_document_task.delay(doc_id, task_id)
    logger.info("ingest_dispatched_celery", doc_id=doc_id, task_id=task_id)


@router.post(
    "/{kb_id}/documents",
    response_model=UploadResult,
    summary="上传文档（流式落对象存储，异步解析入库）",
)
async def upload_document(
    kb_id: int,
    db: DbSession,
    user: CurrentUser,
    file: UploadFile = File(...),
) -> UploadResult:
    kb = await kb_service.ensure_kb_access(db, user, kb_id, need_write=True)

    filename = file.filename or "unnamed"
    ext = _ext_of(filename)
    _check_ext(ext)

    # 预估容量（UploadFile.size 可能为 None，保存后还会校验一次）
    if file.size and kb.total_size_bytes + file.size > settings.max_kb_total_mb * 1024 * 1024:
        raise AppError(
            f"超出知识库容量上限 {settings.max_kb_total_mb}MB",
            code=ErrorCode.KB_QUOTA_EXCEEDED,
            status_code=413,
        )

    doc = Document(
        kb_id=kb_id,
        name=filename,
        file_ext=ext,
        file_size=0,
        storage_key="",
        sha256="",
        status=DocStatus.PENDING,
        chunk_config_snapshot=kb.chunk_config or {},
        created_by=user.id,
    )
    db.add(doc)
    await db.flush()  # 拿到自增 id 用于对象键

    storage: StorageService = get_storage()
    key = StorageService.build_key(kb_id, doc.id, filename)
    try:
        size, sha256 = await storage.save_upload(
            file.file, key, file.content_type or "application/octet-stream"
        )
    except AppError:
        await db.rollback()
        raise

    # 同一知识库内按 sha256 去重，避免重复入库浪费向量化费用
    dup = (
        await db.execute(
            select(Document).where(
                Document.kb_id == kb_id,
                Document.sha256 == sha256,
                Document.id != doc.id,
                Document.is_deleted == 0,
            )
        )
    ).scalar_one_or_none()
    if dup is not None:
        await storage.delete(key)
        await db.rollback()
        raise AppError(
            f"该文件已存在（{dup.name}），无需重复上传",
            code=ErrorCode.CONFLICT,
            status_code=409,
            detail={"existing_doc_id": dup.id},
        )

    doc.storage_key = key
    doc.file_size = size
    doc.sha256 = sha256

    # 容量二次校验（防止绕过 UploadFile.size）
    if kb.total_size_bytes + size > settings.max_kb_total_mb * 1024 * 1024:
        await storage.delete(key)
        await db.rollback()
        raise AppError(
            f"超出知识库容量上限 {settings.max_kb_total_mb}MB",
            code=ErrorCode.KB_QUOTA_EXCEEDED,
            status_code=413,
        )

    task = IngestTask(
        kb_id=kb_id,
        doc_id=doc.id,
        task_type=IngestTaskType.PARSE,
        status=IngestTaskStatus.QUEUED,
        created_by=user.id,
        checkpoint={},
    )
    db.add(task)
    await db.commit()
    await db.refresh(doc)
    await db.refresh(task)

    await _dispatch_ingest(doc.id, task.id)
    logger.info("doc_uploaded", doc_id=doc.id, kb_id=kb_id, size=size, ext=ext)
    return UploadResult(
        document=DocumentOut.model_validate(doc),
        task=IngestTaskOut.model_validate(task),
    )


@router.get("/{kb_id}/documents", response_model=list[DocumentOut], summary="文档列表")
async def list_documents(
    kb_id: int,
    db: DbSession,
    user: CurrentUser,
    status: str | None = Query(default=None),
    keyword: str | None = Query(default=None, max_length=128),
) -> list[DocumentOut]:
    await kb_service.ensure_kb_access(db, user, kb_id)

    stmt = select(Document).where(Document.kb_id == kb_id, Document.is_deleted == 0)
    if status:
        stmt = stmt.where(Document.status == status)
    if keyword:
        stmt = stmt.where(Document.name.like(f"%{keyword}%"))
    stmt = stmt.order_by(Document.id.desc())

    docs = (await db.execute(stmt)).scalars().all()
    return [DocumentOut.model_validate(d) for d in docs]


@router.get("/documents/{doc_id}", response_model=DocumentOut, summary="文档详情")
async def get_document(doc_id: int, db: DbSession, user: CurrentUser) -> DocumentOut:
    doc = await _get_doc_or_404(db, doc_id)
    await kb_service.ensure_kb_access(db, user, doc.kb_id)
    return DocumentOut.model_validate(doc)


@router.delete("/documents/{doc_id}", summary="删除文档（含向量与原始文件）")
async def delete_document(doc_id: int, db: DbSession, user: CurrentUser) -> dict:
    doc = await _get_doc_or_404(db, doc_id)
    kb = await kb_service.ensure_kb_access(db, user, doc.kb_id, need_write=True)

    # 先删向量再删记录。顺序很关键：
    # 向量删不掉就抛错、不软删文档——否则文档"看着没了"，检索却还能命中它的内容，
    # 而且没有任何地方能看出来为什么（本次实际发生过：删了 README 仍被引用）。
    try:
        get_vector_store().delete_by_doc(doc.id)
    except Exception as exc:  # noqa: BLE001
        logger.error("milvus_delete_failed", doc_id=doc.id, error=str(exc))
        raise AppError(
            "向量清理失败，文档未删除，请稍后重试",
            code=ErrorCode.INTERNAL_ERROR,
            status_code=503,
        ) from exc

    # 切片行一并删除：软删文档而留着 chunks，会成为永远查不到来源的孤儿行
    await db.execute(delete(Chunk).where(Chunk.doc_id == doc.id))

    await get_storage().delete(doc.storage_key)
    # 注意顺序：先用旧值扣减统计，再清零，否则 kb.chunk_count 会减成 0
    kb.doc_count = max(0, kb.doc_count - 1)
    kb.total_size_bytes = max(0, kb.total_size_bytes - doc.file_size)
    kb.chunk_count = max(0, kb.chunk_count - doc.chunk_count)
    doc.is_deleted = 1
    doc.chunk_count = 0

    await db.commit()
    logger.info("doc_deleted", doc_id=doc_id, kb_id=doc.kb_id, by=user.id)
    return {"message": "已删除"}


@router.post(
    "/documents/{doc_id}/reindex",
    response_model=IngestTaskOut,
    summary="重建单个文档向量",
)
async def reindex_document(doc_id: int, db: DbSession, user: CurrentUser) -> IngestTaskOut:
    doc = await _get_doc_or_404(db, doc_id)
    await kb_service.ensure_kb_access(db, user, doc.kb_id, need_write=True)

    running = (
        await db.execute(
            select(IngestTask).where(
                IngestTask.doc_id == doc_id,
                IngestTask.status.in_([IngestTaskStatus.QUEUED, IngestTaskStatus.RUNNING]),
            )
        )
    ).scalar_one_or_none()
    if running is not None:
        raise AppError(
            "该文档已有进行中的任务", code=ErrorCode.CONFLICT, status_code=409
        )

    task = IngestTask(
        kb_id=doc.kb_id,
        doc_id=doc.id,
        task_type=IngestTaskType.REINDEX,
        status=IngestTaskStatus.QUEUED,
        created_by=user.id,
        checkpoint={},
    )
    db.add(task)
    doc.status = DocStatus.PENDING
    await db.commit()
    await db.refresh(task)

    await _dispatch_ingest(doc.id, task.id)
    return IngestTaskOut.model_validate(task)


@router.get("/tasks/{task_id}", response_model=IngestTaskOut, summary="任务进度")
async def get_task(task_id: int, db: DbSession, user: CurrentUser) -> IngestTaskOut:
    task = (
        await db.execute(select(IngestTask).where(IngestTask.id == task_id))
    ).scalar_one_or_none()
    if task is None:
        raise AppError("任务不存在", code=ErrorCode.NOT_FOUND, status_code=404)
    await kb_service.ensure_kb_access(db, user, task.kb_id)
    return IngestTaskOut.model_validate(task)


@router.get("/{kb_id}/chunks/{doc_id}", summary="查看文档切片（调试用）")
async def list_chunks(
    kb_id: int,
    doc_id: int,
    db: DbSession,
    user: CurrentUser,
    limit: int = Query(default=20, ge=1, le=200),
) -> dict:
    await kb_service.ensure_kb_access(db, user, kb_id)
    doc = await _get_doc_or_404(db, doc_id)
    if doc.kb_id != kb_id:
        raise AppError("文档不属于该知识库", code=ErrorCode.NOT_FOUND, status_code=404)

    rows = (
        await db.execute(
            select(Chunk)
            .where(Chunk.doc_id == doc_id)
            .order_by(Chunk.chunk_index)
            .limit(limit)
        )
    ).scalars().all()

    total = (
        await db.execute(
            select(Chunk.id).where(Chunk.doc_id == doc_id)
        )
    ).scalars().all()

    return {
        "doc_id": doc_id,
        "total": len(total),
        "items": [
            {
                "id": c.id,
                "index": c.chunk_index,
                "section_path": c.section_path,
                "char_count": c.char_count,
                "embedded": c.embedded,
                "content": c.content[:300] + ("…" if len(c.content) > 300 else ""),
            }
            for c in rows
        ],
    }
