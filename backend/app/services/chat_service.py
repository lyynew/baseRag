"""问答编排：会话管理、检索、生成、引用。

关键实现细节：
1. **流式响应里不能用请求的 db session**——StreamingResponse 返回后 FastAPI 会关闭依赖，
   生成器再访问就会报 "session is closed"。所以生成器内部自建 SessionLocal。
2. 引用用 [1][2] 角标，生成后正则提取并与 hits 映射，越界编号直接丢弃（防止模型编造引用）。
3. 历史只取最近 N 轮喂模型，全量仍落库（存全量 ≠ 喂全量）。
"""

import re
import time
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError, ErrorCode
from app.core.logging import get_logger
from app.db.models.auth import User
from app.db.models.chat import ChatMessage, ChatSession, LlmCallLog
from app.db.models.enums import ChatRole
from app.db.models.knowledge import KnowledgeBase
from app.db.session import SessionLocal
from app.services import kb_service, prompt_service
from app.services.llm import ChatResult, LlmClient, StreamStats, get_llm
from app.services.model_runtime import load_model_runtime
from app.services.rag_graph import run_retrieval

logger = get_logger(__name__)

# 历史滑窗：最近 6 轮（12 条消息）
HISTORY_TURNS = 6
CITATION_RE = re.compile(r"\[(\d{1,2})\]")


async def _build_context_messages(
    db: AsyncSession,
    question: str,
    context: str,
    history: list[dict],
    kb_id: int | None = None,
    kb_name: str = "",
    sources: int = 0,
) -> tuple[list[dict], int]:
    """拼装问答 messages，system 段从提示词模板渲染。

    返回 (messages, 提示词版本号)，版本号写入 llm_call_logs，用于事后归因。
    """
    system, version = await prompt_service.render_for(
        prompt_service.CODE_SYSTEM_QA,
        {"question": question, "context": context, "kb_name": kb_name, "sources": sources},
        kb_id=kb_id,
        db=db,
    )
    messages: list[dict] = [{"role": "system", "content": system}]
    for h in history:
        role = h.get("role")
        if role in ("user", "assistant") and h.get("content"):
            messages.append({"role": role, "content": h["content"]})
    user_content = f"资料：\n{context}\n\n问题：{question}" if context else f"问题：{question}"
    messages.append({"role": "user", "content": user_content})
    return messages, version


async def _build_direct_messages(
    db: AsyncSession, question: str, kb_id: int | None = None, kb_name: str = ""
) -> tuple[list[dict], int]:
    """寒暄/无关问题：走 direct_answer 模板，不检索、不带资料。"""
    system, version = await prompt_service.render_for(
        prompt_service.CODE_DIRECT,
        {"question": question, "kb_name": kb_name},
        kb_id=kb_id,
        db=db,
    )
    return (
        [
            {"role": "system", "content": system},
            {"role": "user", "content": question},
        ],
        version,
    )


def extract_citations(answer: str, hits: list[dict]) -> list[dict]:
    """从答案里提取引用角标，映射到实际命中的切片。越界编号丢弃。"""
    seen: list[int] = []
    for m in CITATION_RE.finditer(answer or ""):
        idx = int(m.group(1))
        if 1 <= idx <= len(hits) and idx not in seen:
            seen.append(idx)

    return [
        {
            "index": idx,
            "chunk_id": hits[idx - 1]["chunk_id"],
            "doc_id": hits[idx - 1]["doc_id"],
            "score": hits[idx - 1].get("score", 0),
            "snippet": hits[idx - 1]["content"][:200],
        }
        for idx in seen
    ]


async def _load_history(
    db: AsyncSession, session_id: int, limit: int = HISTORY_TURNS * 2
) -> list[dict]:
    rows = (
        await db.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.seq.desc())
            .limit(limit)
        )
    ).scalars().all()
    rows = list(reversed(rows))
    return [{"role": m.role, "content": m.content} for m in rows if m.content]


async def _next_seq(db: AsyncSession, session_id: int) -> int:
    current = (
        await db.execute(
            select(func.coalesce(func.max(ChatMessage.seq), 0)).where(
                ChatMessage.session_id == session_id
            )
        )
    ).scalar_one()
    return int(current) + 1


async def _resolve_kb_config(
    db: AsyncSession, user: User, kb_ids: list[int]
) -> dict[str, Any]:
    """取会话绑定知识库的检索参数（取第一个库的配置作为代表）。

    prompt_kb_id：仅在恰好绑定一个知识库时才允许使用该库的提示词覆盖。
    多库会话语义模糊（三份提示词没法都生效），统一走全局提示词。
    """
    if not kb_ids:
        return {
            "top_k": 30,
            "rerank_top_n": 8,
            "score_threshold": 0.0,
            "rerank_enabled": True,
            "kb_name": "",
            "prompt_kb_id": None,
        }

    for kb_id in kb_ids:
        await kb_service.ensure_kb_access(db, user, kb_id)

    rows = (
        await db.execute(select(KnowledgeBase).where(KnowledgeBase.id.in_(kb_ids)))
    ).scalars().all()
    by_id = {k.id: k for k in rows}
    first = by_id.get(kb_ids[0])
    cfg = (first.retrieve_config if first else None) or {}
    names = [by_id[k].name for k in kb_ids if k in by_id]
    return {
        "top_k": int(cfg.get("top_k", 30)),
        "rerank_top_n": int(cfg.get("rerank_top_n", 8)),
        "score_threshold": float(cfg.get("score_threshold", 0.0)),
        "rerank_enabled": bool(cfg.get("rerank_enabled", True)),
        "kb_name": "、".join(names),
        "prompt_kb_id": kb_ids[0] if len(kb_ids) == 1 else None,
    }


async def create_session(
    db: AsyncSession, user: User, kb_ids: list[int], title: str | None = None
) -> ChatSession:
    if not kb_ids:
        raise AppError("请至少选择一个知识库", code=ErrorCode.VALIDATION_ERROR, status_code=422)
    for kb_id in kb_ids:
        await kb_service.ensure_kb_access(db, user, kb_id)

    session = ChatSession(
        user_id=user.id,
        title=title or "新对话",
        kb_ids=kb_ids,
        chat_provider=settings.default_chat_provider,
        chat_model=get_llm().model,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


def _make_rewriter(db: AsyncSession, kb_id: int | None, llm: LlmClient):
    """构造查询改写器。

    改写只在「多轮 + 问题很短」时触发（判断在图里），所以正常情况下不会增加调用。
    失败一律返回原问题，绝不阻断问答。
    """

    async def _rewrite(question: str, history: list[dict]) -> str:
        prompt, _version = await prompt_service.render_for(
            prompt_service.CODE_REWRITE,
            {"question": question},
            kb_id=kb_id,
            db=db,
        )
        messages: list[dict] = [{"role": "system", "content": prompt}]
        for h in history[-4:]:
            if h.get("role") in ("user", "assistant") and h.get("content"):
                messages.append({"role": h["role"], "content": h["content"][:500]})
        messages.append({"role": "user", "content": f"最新问题：{question}"})

        result = await llm.chat(messages, max_tokens=200, temperature=0.0)
        text = (result.content or "").strip().strip('"').strip("“”").split("\n")[0].strip()
        # 改写结果异常长说明模型没按指令输出（比如开始解释），宁可不用
        if not text or len(text) > 200:
            return question
        return text

    return _rewrite


async def _prepare(
    db: AsyncSession, user: User, session_id: int, question: str
) -> tuple[ChatSession, dict]:
    """公共前置：校验会话、跑检索图、落用户消息。"""
    session = (
        await db.execute(
            select(ChatSession).where(
                ChatSession.id == session_id,
                ChatSession.user_id == user.id,
                ChatSession.is_deleted == 0,
            )
        )
    ).scalar_one_or_none()
    if session is None:
        raise AppError("会话不存在", code=ErrorCode.NOT_FOUND, status_code=404)

    kb_ids = list(session.kb_ids or [])
    cfg = await _resolve_kb_config(db, user, kb_ids)
    history = await _load_history(db, session_id)

    # 改写用的模型：与问答同一通道，避免维护两套配置
    runtime = await load_model_runtime(db, session.chat_provider)
    rewriter = _make_rewriter(db, cfg.get("prompt_kb_id"), get_llm(runtime=runtime))

    retrieved = await run_retrieval(
        question,
        kb_ids,
        history=history,
        top_k=cfg["top_k"],
        rerank_top_n=cfg["rerank_top_n"],
        score_threshold=cfg["score_threshold"],
        rerank_enabled=cfg["rerank_enabled"],
        rewriter=rewriter,
    )

    # 用户消息先落库（即使后续生成失败，也能看到问过什么）
    seq = await _next_seq(db, session_id)
    user_msg = ChatMessage(
        session_id=session_id,
        seq=seq,
        role=ChatRole.USER,
        content=question,
        citations=[],
        retrieval_snapshot={
            "hits": retrieved.get("hits", []),
            "reason": retrieved.get("reason"),
            "rewritten": retrieved.get("rewritten"),
        },
        created_at=datetime.now(),
    )
    db.add(user_msg)

    if session.message_count == 0:
        session.title = question[:40]
    session.message_count = (session.message_count or 0) + 1
    await db.commit()

    return session, {
        "history": history,
        "hits": retrieved.get("hits", []),
        "context": retrieved.get("context", ""),
        "need_retrieve": retrieved.get("need_retrieve", True),
        "reason": retrieved.get("reason", ""),
        "embed_tokens": retrieved.get("tokens", 0),
        "cfg": cfg,
        "kb_name": cfg.get("kb_name", ""),
        "prompt_kb_id": cfg.get("prompt_kb_id"),
    }


async def _persist_answer(
    db: AsyncSession,
    *,
    session: ChatSession,
    question: str,
    answer: str,
    prep: dict,
    usage: dict,
    latency_ms: int,
    ttft_ms: int | None,
    llm: LlmClient,
    prompt_version: int | None = None,
    prompt_code: str | None = None,
) -> ChatMessage:
    citations = extract_citations(answer, prep["hits"])
    seq = await _next_seq(db, session.id)

    assistant_msg = ChatMessage(
        session_id=session.id,
        seq=seq,
        role=ChatRole.ASSISTANT,
        content=answer,
        citations=citations,
        retrieval_snapshot={
            "hits": prep["hits"],
            "reason": prep["reason"],
            "need_retrieve": prep["need_retrieve"],
        },
        provider=llm.provider,
        model=llm.model,
        prompt_tokens=int(usage.get("prompt_tokens", 0)),
        completion_tokens=int(usage.get("completion_tokens", 0)),
        latency_ms=latency_ms,
        ttft_ms=ttft_ms,
        created_at=datetime.now(),
    )
    db.add(assistant_msg)

    db.add(
        LlmCallLog(
            scene="chat",
            provider=llm.provider,
            model=llm.model,
            ref_type="chat_session",
            ref_id=session.id,
            user_id=session.user_id,
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=int(usage.get("completion_tokens", 0)),
            latency_ms=latency_ms,
            prompt_code=prompt_code,
            prompt_version=prompt_version,
            status="ok",
            created_at=datetime.now(),
        )
    )

    session.message_count = (session.message_count or 0) + 1
    session.chat_provider = llm.provider
    session.chat_model = llm.model
    await db.commit()
    await db.refresh(assistant_msg)
    return assistant_msg


async def ask(
    db: AsyncSession, user: User, session_id: int, question: str
) -> dict:
    """非流式问答。"""
    question = question.strip()
    if not question:
        raise AppError("问题不能为空", code=ErrorCode.VALIDATION_ERROR, status_code=422)

    session, prep = await _prepare(db, user, session_id, question)
    # 从数据库读模型配置：后台切模型后无需重启
    runtime = await load_model_runtime(db, session.chat_provider)
    llm = get_llm(runtime=runtime)

    started = time.perf_counter()
    if not prep["need_retrieve"]:
        messages, prompt_version = await _build_direct_messages(
            db, question, prep["prompt_kb_id"], prep["kb_name"]
        )
    else:
        messages, prompt_version = await _build_context_messages(
            db,
            question,
            prep["context"],
            prep["history"],
            kb_id=prep["prompt_kb_id"],
            kb_name=prep["kb_name"],
            sources=len(prep["hits"]),
        )
    prompt_code = (
        prompt_service.CODE_DIRECT
        if not prep["need_retrieve"]
        else prompt_service.CODE_SYSTEM_QA
    )

    result: ChatResult = await llm.chat(messages, max_tokens=2048)
    latency = int((time.perf_counter() - started) * 1000)

    msg = await _persist_answer(
        db,
        session=session,
        question=question,
        answer=result.content,
        prep=prep,
        usage={
            "prompt_tokens": result.prompt_tokens,
            "completion_tokens": result.completion_tokens,
        },
        latency_ms=latency,
        ttft_ms=None,
        llm=llm,
        prompt_version=prompt_version,
        prompt_code=prompt_code,
    )

    return {
        "message_id": msg.id,
        "session_id": session.id,
        "answer": msg.content,
        "citations": msg.citations,
        "model": llm.model,
        "usage": {
            "prompt_tokens": result.prompt_tokens,
            "completion_tokens": result.completion_tokens,
            "embed_tokens": prep["embed_tokens"],
        },
        "latency_ms": latency,
        "retrieval": {"reason": prep["reason"], "hits": len(prep["hits"])},
    }


async def ask_stream(
    user: User, session_id: int, question: str
) -> AsyncIterator[dict]:
    """流式问答，产出 SSE 事件字典。

    注意：这里自己开 session，不复用请求依赖的 session（流式期间它会被关闭）。
    """
    question = (question or "").strip()
    if not question:
        yield {"event": "error", "data": {"code": "VALIDATION_ERROR", "message": "问题不能为空"}}
        return

    async with SessionLocal() as db:
        try:
            session, prep = await _prepare(db, user, session_id, question)
        except AppError as exc:
            yield {"event": "error", "data": {"code": str(exc.code), "message": exc.message}}
            return
        except Exception as exc:  # noqa: BLE001
            logger.exception("stream_prepare_failed", error=str(exc))
            yield {
                "event": "error",
                "data": {"code": "INTERNAL_ERROR", "message": "检索失败，请稍后重试"},
            }
            return

        runtime = await load_model_runtime(db, session.chat_provider)
        llm = get_llm(runtime=runtime)

        # 先推送检索结果，前端可以在等待生成时先展示引用来源
        yield {
            "event": "retrieval",
            "data": {
                "need_retrieve": prep["need_retrieve"],
                "reason": prep["reason"],
                "hits": [
                    {
                        "index": i + 1,
                        "chunk_id": h["chunk_id"],
                        "doc_id": h["doc_id"],
                        "score": h["score"],
                        "snippet": h["content"][:120],
                    }
                    for i, h in enumerate(prep["hits"])
                ],
            },
        }

        if not prep["need_retrieve"]:
            messages, prompt_version = await _build_direct_messages(
                db, question, prep["prompt_kb_id"], prep["kb_name"]
            )
            prompt_code = prompt_service.CODE_DIRECT
        else:
            messages, prompt_version = await _build_context_messages(
                db,
                question,
                prep["context"],
                prep["history"],
                kb_id=prep["prompt_kb_id"],
                kb_name=prep["kb_name"],
                sources=len(prep["hits"]),
            )
            prompt_code = prompt_service.CODE_SYSTEM_QA

        stats = StreamStats()
        started = time.perf_counter()
        buffer: list[str] = []

        try:
            async for piece in llm.astream(messages, max_tokens=2048, stats=stats):
                buffer.append(piece)
                yield {"event": "delta", "data": {"text": piece}}
        except AppError as exc:
            yield {"event": "error", "data": {"code": str(exc.code), "message": exc.message}}
            return
        except Exception as exc:  # noqa: BLE001
            logger.exception("stream_generate_failed", error=str(exc))
            yield {
                "event": "error",
                "data": {"code": "MODEL_CALL_FAILED", "message": "生成失败，请重试"},
            }
            return

        answer = "".join(buffer)
        latency = int((time.perf_counter() - started) * 1000)

        # 流式拿不到 usage，按字符数估算（中文约 1.5 token/字），仅用于成本量级监控
        usage = stats.extra.get("usage") or {}
        est_prompt = int((len(prep["context"]) + len(question)) * 1.5 / 6) + 200
        usage = {
            "prompt_tokens": int(usage.get("prompt_tokens", est_prompt) or est_prompt),
            "completion_tokens": int(
                usage.get("completion_tokens", int(len(answer) * 1.5)) or int(len(answer) * 1.5)
            ),
        }

        try:
            msg = await _persist_answer(
                db,
                session=session,
                question=question,
                answer=answer,
                prep=prep,
                usage=usage,
                latency_ms=latency,
                ttft_ms=stats.ttft_ms,
                llm=llm,
                prompt_version=prompt_version,
                prompt_code=prompt_code,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("persist_answer_failed", error=str(exc))
            yield {
                "event": "error",
                "data": {"code": "INTERNAL_ERROR", "message": "回答已生成但保存失败"},
            }
            return

        yield {
            "event": "done",
            "data": {
                "message_id": msg.id,
                "session_id": session.id,
                "citations": msg.citations,
                "model": llm.model,
                "usage": usage,
                "latency_ms": latency,
                "ttft_ms": stats.ttft_ms,
            },
        }
