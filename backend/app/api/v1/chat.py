"""问答接口：会话管理 + 非流式/流式提问。"""

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.core.deps import CurrentUser, DbSession
from app.core.errors import AppError, ErrorCode
from app.core.logging import get_logger
from app.db.models.chat import ChatMessage, ChatSession
from app.schemas.chat import (
    AskRequest,
    AskResponse,
    FeedbackRequest,
    MessageOut,
    SessionCreate,
    SessionOut,
)
from app.services import chat_service

logger = get_logger(__name__)
router = APIRouter()


@router.post("/sessions", response_model=SessionOut, summary="创建会话")
async def create_session(
    payload: SessionCreate, db: DbSession, user: CurrentUser
) -> SessionOut:
    session = await chat_service.create_session(db, user, payload.agent_id, payload.title)
    return SessionOut.model_validate(session)


@router.get("/sessions", response_model=list[SessionOut], summary="我的会话列表")
async def list_sessions(
    db: DbSession,
    user: CurrentUser,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[SessionOut]:
    rows = (
        await db.execute(
            select(ChatSession)
            .where(ChatSession.user_id == user.id, ChatSession.is_deleted == 0)
            .order_by(ChatSession.updated_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    return [SessionOut.model_validate(s) for s in rows]


@router.get("/sessions/{session_id}", response_model=SessionOut, summary="会话详情")
async def get_session(session_id: int, db: DbSession, user: CurrentUser) -> SessionOut:
    session = await _own_session(db, user.id, session_id)
    return SessionOut.model_validate(session)


@router.delete("/sessions/{session_id}", summary="删除会话（软删除）")
async def delete_session(session_id: int, db: DbSession, user: CurrentUser) -> dict:
    session = await _own_session(db, user.id, session_id)
    session.is_deleted = 1
    await db.commit()
    return {"message": "已删除"}


@router.get("/sessions/{session_id}/messages", response_model=list[MessageOut], summary="历史消息")
async def list_messages(
    session_id: int,
    db: DbSession,
    user: CurrentUser,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[MessageOut]:
    await _own_session(db, user.id, session_id)
    rows = (
        await db.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.seq)
            .limit(limit)
        )
    ).scalars().all()
    return [MessageOut.model_validate(m) for m in rows]


@router.post("/sessions/{session_id}/ask", response_model=AskResponse, summary="提问（非流式）")
async def ask(
    session_id: int, payload: AskRequest, db: DbSession, user: CurrentUser
) -> AskResponse:
    result = await chat_service.ask(db, user, session_id, payload.question)
    return AskResponse(**result)


@router.post("/sessions/{session_id}/stream", summary="提问（SSE 流式）")
async def ask_stream(
    session_id: int, payload: AskRequest, user: CurrentUser
) -> StreamingResponse:
    """事件类型：retrieval → delta×N → done，异常时给 error。"""

    async def gen() -> AsyncIterator[str]:
        try:
            async for evt in chat_service.ask_stream(user, session_id, payload.question):
                data = json.dumps(evt["data"], ensure_ascii=False)
                yield f"event: {evt['event']}\ndata: {data}\n\n"
        except Exception as exc:  # noqa: BLE001
            logger.exception("sse_failed", error=str(exc))
            payload_err = json.dumps(
                {"code": "INTERNAL_ERROR", "message": "服务异常，请重试"}, ensure_ascii=False
            )
            yield f"event: error\ndata: {payload_err}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # 告诉 Nginx 不要缓冲，否则流式会变成"一次性吐出"
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/messages/{message_id}/feedback", summary="对回答点赞/点踩")
async def feedback(
    message_id: int, payload: FeedbackRequest, db: DbSession, user: CurrentUser
) -> dict:
    msg = (
        await db.execute(select(ChatMessage).where(ChatMessage.id == message_id))
    ).scalar_one_or_none()
    if msg is None:
        raise AppError("消息不存在", code=ErrorCode.NOT_FOUND, status_code=404)

    session = await _own_session(db, user.id, msg.session_id)
    if msg.role != "assistant":
        raise AppError("只能对回答进行评价", code=ErrorCode.VALIDATION_ERROR, status_code=422)

    msg.feedback = payload.feedback
    await db.commit()
    logger.info("feedback_recorded", message_id=message_id, feedback=payload.feedback)
    return {"message": "已记录", "session_id": session.id}


async def _own_session(db, user_id: int, session_id: int) -> ChatSession:
    session = (
        await db.execute(
            select(ChatSession).where(
                ChatSession.id == session_id,
                ChatSession.user_id == user_id,
                ChatSession.is_deleted == 0,
            )
        )
    ).scalar_one_or_none()
    if session is None:
        raise AppError("会话不存在", code=ErrorCode.NOT_FOUND, status_code=404)
    return session
