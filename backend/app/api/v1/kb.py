"""知识库管理接口。"""

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.core.deps import CurrentUser, DbSession, require_perm
from app.core.errors import AppError, ErrorCode
from app.core.logging import get_logger
from app.core.rbac import user_permission_codes
from app.db.models.auth import User
from app.db.models.chat import AuditLog
from app.db.models.knowledge import Chunk, Document, KbMember, KnowledgeBase
from app.schemas.kb import (
    KbCreate,
    KbMemberAdd,
    KbMemberOut,
    KbOut,
    KbUpdate,
    SearchHit,
    SearchRequest,
    SearchResponse,
)
from app.services import kb_service
from app.services.embedding import get_embedding_client
from app.services.rerank import get_rerank_client
from app.services.vector_store import get_vector_store

logger = get_logger(__name__)
router = APIRouter()


@router.post(
    "",
    response_model=KbOut,
    summary="创建知识库",
    dependencies=[Depends(require_perm("kb:write"))],
)
async def create_kb(payload: KbCreate, db: DbSession, user: CurrentUser) -> KbOut:
    from app.core.config import settings

    kb = KnowledgeBase(
        name=payload.name,
        description=payload.description,
        owner_id=user.id,
        sensitivity=payload.sensitivity,
        embedding_model=settings.embedding_model,
        embedding_dim=settings.embedding_dim,
        # 本项目所有知识库共用同一个 collection，用 kb_id 过滤（见技术选型 §6.1）
        milvus_collection=settings.milvus_collection,
        chunk_config=payload.chunk_config.model_dump(),
        retrieve_config=payload.retrieve_config.model_dump(),
    )
    db.add(kb)
    await db.flush()

    # 创建者自动成为 owner
    db.add(KbMember(kb_id=kb.id, user_id=user.id, role="owner", granted_by=user.id))
    await db.commit()
    await db.refresh(kb)

    logger.info("kb_created", kb_id=kb.id, name=kb.name, owner=user.id)
    out = KbOut.model_validate(kb)
    out.my_role = "owner"
    return out


@router.get("", response_model=list[KbOut], summary="知识库列表（按权限过滤）")
async def list_kbs(
    db: DbSession,
    user: CurrentUser,
    keyword: str | None = Query(default=None, max_length=64),
) -> list[KbOut]:
    pairs = await kb_service.list_accessible_kbs(db, user, keyword=keyword)
    result = []
    for kb, role in pairs:
        item = KbOut.model_validate(kb)
        item.my_role = role
        result.append(item)
    return result


@router.get("/{kb_id}", response_model=KbOut, summary="知识库详情")
async def get_kb(kb_id: int, db: DbSession, user: CurrentUser) -> KbOut:
    kb = await kb_service.ensure_kb_access(db, user, kb_id)
    out = KbOut.model_validate(kb)
    out.my_role = await kb_service.my_role_for(db, user, kb_id)
    return out


@router.patch("/{kb_id}", response_model=KbOut, summary="修改知识库（切片参数变更会提示需要重建）")
async def update_kb(
    kb_id: int, payload: KbUpdate, db: DbSession, user: CurrentUser
) -> KbOut:
    kb = await kb_service.ensure_kb_access(db, user, kb_id, need_write=True)

    before = {
        "name": kb.name,
        "sensitivity": kb.sensitivity,
        "chunk_config": kb.chunk_config,
        "retrieve_config": kb.retrieve_config,
    }
    chunk_changed = False

    if payload.name is not None:
        kb.name = payload.name
    if payload.description is not None:
        kb.description = payload.description
    if payload.sensitivity is not None:
        kb.sensitivity = payload.sensitivity
    if payload.retrieve_config is not None:
        kb.retrieve_config = payload.retrieve_config.model_dump()
    if payload.chunk_config is not None:
        new_cfg = payload.chunk_config.model_dump()
        # 切片参数一变，所有已入库切片都失效 → 必须全量重建并重新计费
        chunk_changed = new_cfg != (kb.chunk_config or {})
        kb.chunk_config = new_cfg

    after = {
        "name": kb.name,
        "sensitivity": kb.sensitivity,
        "chunk_config": kb.chunk_config,
        "retrieve_config": kb.retrieve_config,
    }

    # 改切片参数会影响全库，写审计便于追溯"谁在什么时候改了什么"
    if before != after:
        db.add(
            AuditLog(
                operator_id=user.id,
                operator_name=user.username,
                action="kb.update_config",
                target_type="knowledge_base",
                target_id=kb.id,
                before=before,
                after=after,
                result="ok",
                created_at=datetime.now(),
            )
        )

    await db.commit()
    await db.refresh(kb)

    logger.info("kb_updated", kb_id=kb.id, chunk_changed=chunk_changed, by=user.id)
    out = KbOut.model_validate(kb)
    out.my_role = await kb_service.my_role_for(db, user, kb_id)
    if chunk_changed:
        logger.warning("kb_chunk_config_changed_need_reindex", kb_id=kb.id)
    return out


@router.delete("/{kb_id}", summary="删除知识库（软删除）")
async def delete_kb(kb_id: int, db: DbSession, user: CurrentUser) -> dict:
    kb = await kb_service.ensure_kb_access(db, user, kb_id, need_write=True)

    codes = user_permission_codes(user)
    if kb.owner_id != user.id and not user.is_superuser and "kb:delete" not in codes:
        raise AppError(
            "只有创建者或管理员可以删除知识库",
            code=ErrorCode.FORBIDDEN,
            status_code=403,
        )

    kb.is_deleted = 1
    # 同步清理向量，否则会留下永远检索不到的孤儿数据，且持续占用内存
    try:
        get_vector_store().delete_by_kb(kb_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("milvus_delete_kb_failed", kb_id=kb_id, error=str(exc))

    db.add(
        AuditLog(
            operator_id=user.id,
            operator_name=user.username,
            action="kb.delete",
            target_type="knowledge_base",
            target_id=kb_id,
            result="ok",
            created_at=datetime.now(),
        )
    )
    await db.commit()
    logger.info("kb_deleted", kb_id=kb_id, by=user.id)
    return {"message": "已删除"}


@router.get("/{kb_id}/members", response_model=list[KbMemberOut], summary="知识库成员")
async def list_members(kb_id: int, db: DbSession, user: CurrentUser) -> list[KbMemberOut]:
    await kb_service.ensure_kb_access(db, user, kb_id)

    rows = (
        await db.execute(
            select(KbMember, User).join(User, User.id == KbMember.user_id).where(
                KbMember.kb_id == kb_id
            )
        )
    ).all()
    return [
        KbMemberOut(
            user_id=m.user_id, username=u.username, nickname=u.nickname, role=m.role
        )
        for m, u in rows
    ]


@router.post("/{kb_id}/members", response_model=KbMemberOut, summary="添加/调整成员")
async def add_member(
    kb_id: int, payload: KbMemberAdd, db: DbSession, user: CurrentUser
) -> KbMemberOut:
    await kb_service.ensure_kb_access(db, user, kb_id, need_write=True)

    target = (
        await db.execute(
            select(User).where(User.id == payload.user_id, User.is_deleted == 0)
        )
    ).scalar_one_or_none()
    if target is None:
        raise AppError("用户不存在", code=ErrorCode.NOT_FOUND, status_code=404)

    member = await kb_service.add_member(
        db, kb_id, payload.user_id, payload.role, user.id
    )
    logger.info("kb_member_added", kb_id=kb_id, user_id=payload.user_id, role=payload.role)
    return KbMemberOut(
        user_id=member.user_id,
        username=target.username,
        nickname=target.nickname,
        role=member.role,
    )


@router.delete("/{kb_id}/members/{user_id}", summary="移除成员")
async def remove_member(kb_id: int, user_id: int, db: DbSession, user: CurrentUser) -> dict:
    kb = await kb_service.ensure_kb_access(db, user, kb_id, need_write=True)
    if user_id == kb.owner_id:
        raise AppError("不能移除知识库创建者", code=ErrorCode.CONFLICT, status_code=409)
    await kb_service.remove_member(db, kb_id, user_id)
    return {"message": "已移除"}


@router.post("/{kb_id}/search", response_model=SearchResponse, summary="检索预览（只召回，不生成）")
async def search_kb(
    kb_id: int, payload: SearchRequest, db: DbSession, user: CurrentUser
) -> SearchResponse:
    """调试与前端预览用：验证切片、向量化、rerank 的实际效果。

    只消耗一次 query 向量化（十几 token）和一次 rerank（可选），成本极低。
    """
    kb = await kb_service.ensure_kb_access(db, user, kb_id)
    rcfg = kb.retrieve_config or {}
    top_k = payload.top_k or int(rcfg.get("top_k", 30))
    rerank_top_n = int(rcfg.get("rerank_top_n", 8))

    embedder = get_embedding_client()
    qv = await embedder.embed_query(payload.query)

    store = get_vector_store()
    # 稠密 + BM25 混合召回。RRF 融合分与余弦分不可比，故此处不做阈值过滤，
    # 相关性判断交给 rerank（score_threshold 只对纯向量模式有意义）。
    hits = store.hybrid_search(qv, payload.query, [kb_id], top_k=top_k)
    if not hits:
        return SearchResponse(
            query=payload.query, hits=[], vector_hits=0, rerank_applied=False,
            tokens=embedder.usage.prompt_tokens,
        )

    # 补充文档名，便于前端直接展示来源
    doc_ids = {h.doc_id for h in hits}
    name_map = dict(
        (
            await db.execute(
                select(Document.id, Document.name).where(Document.id.in_(doc_ids))
            )
        ).all()
    )
    meta_map = dict(
        (
            await db.execute(
                select(Chunk.id, Chunk.section_path).where(
                    Chunk.id.in_([h.chunk_id for h in hits])
                )
            )
        ).all()
    )

    rerank_applied = False
    if payload.rerank and rcfg.get("rerank_enabled", True) and len(hits) > 1:
        reranker = get_rerank_client()
        ranked = await reranker.rerank(payload.query, [h.content for h in hits], top_n=rerank_top_n)
        rerank_applied = True
        ordered = [(hits[i], score) for i, score in ranked if i < len(hits)]
    else:
        ordered = [(h, h.score) for h in hits[:rerank_top_n]]

    return SearchResponse(
        query=payload.query,
        hits=[
            SearchHit(
                chunk_id=h.chunk_id,
                doc_id=h.doc_id,
                doc_name=name_map.get(h.doc_id),
                content=h.content,
                score=round(score, 4),
                vector_score=round(h.score, 4),
                section_path=meta_map.get(h.chunk_id),
            )
            for h, score in ordered
        ],
        vector_hits=len(hits),
        rerank_applied=rerank_applied,
        tokens=embedder.usage.prompt_tokens,
    )
