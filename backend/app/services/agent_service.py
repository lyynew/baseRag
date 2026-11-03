"""智能体服务：CRUD、发布、试跑、运行时配置装配。

与 chat_service 的分工：
- 这里只管智能体本身的增删改查和"一次试跑"；
- 问答链路需要 agent 配置时直接查 Agent 模型（chat_service 里），
  不 import 本模块，避免 agent_service ⇄ chat_service 循环依赖。
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ErrorCode
from app.core.logging import get_logger
from app.db.models.agent import AGENT_PROMPT_KEYS, Agent
from app.db.models.chat import ChatMessage, ChatSession
from app.db.models.knowledge import KnowledgeBase
from app.schemas.agent import AgentBrief, AgentIn, AgentOut, AgentTestIn, AgentTestOut, AgentUpdate
from app.services import prompt_service
from app.services.llm import get_llm
from app.services.model_runtime import load_default_runtime, load_model_runtime

logger = get_logger(__name__)

DEFAULT_RETRIEVE = {
    "top_k": 30,
    "rerank_top_n": 8,
    "score_threshold": 0.0,
    "rerank_enabled": True,
}


# ---------------- 查询 ----------------
async def get_agent(db: AsyncSession, agent_id: int) -> Agent:
    agent = (
        await db.execute(
            select(Agent).where(Agent.id == agent_id, Agent.is_deleted == 0)
        )
    ).scalar_one_or_none()
    if agent is None:
        raise AppError("智能体不存在", code=ErrorCode.NOT_FOUND, status_code=404)
    return agent


async def usable_agents(db: AsyncSession, user, *, published_only: bool = True) -> list[Agent]:
    """前台可见的智能体：已发布 +（全员 或 超管/管理员）。"""
    stmt = select(Agent).where(Agent.is_deleted == 0)
    if published_only:
        stmt = stmt.where(Agent.is_published.is_(True))
    rows = (await db.execute(stmt.order_by(Agent.id))).scalars().all()

    is_manager = user.is_superuser or "config:read" in _perm_codes(user)
    if is_manager:
        return list(rows)
    return [a for a in rows if a.is_public]


def _perm_codes(user) -> set[str]:
    from app.core.rbac import user_permission_codes

    return user_permission_codes(user)


async def _kb_names(db: AsyncSession, kb_ids: list[int]) -> list[str]:
    if not kb_ids:
        return []
    rows = (
        await db.execute(
            select(KnowledgeBase.name).where(
                KnowledgeBase.id.in_(kb_ids), KnowledgeBase.is_deleted == 0
            )
        )
    ).scalars().all()
    return list(rows)


async def _to_out(db: AsyncSession, a: Agent) -> AgentOut:
    session_count = (
        await db.execute(
            select(func.count(ChatSession.id)).where(
                ChatSession.agent_id == a.id, ChatSession.is_deleted == 0
            )
        )
    ).scalar() or 0
    message_count = (
        await db.execute(
            select(func.count(ChatMessage.id))
            .join(ChatSession, ChatMessage.session_id == ChatSession.id)
            .where(ChatSession.agent_id == a.id, ChatSession.is_deleted == 0)
        )
    ).scalar() or 0

    return AgentOut(
        id=a.id,
        name=a.name,
        description=a.description,
        emoji=a.emoji,
        kb_ids=list(a.kb_ids or []),
        kb_names=await _kb_names(db, a.kb_ids or []),
        provider=a.provider,
        model=a.model,
        prompt_overrides=dict(a.prompt_overrides or {}),
        retrieve_config=dict(a.retrieve_config or {}),
        gen_settings=dict(a.gen_settings or {}),
        is_published=a.is_published,
        is_public=a.is_public,
        session_count=int(session_count),
        message_count=int(message_count),
        owner_id=a.owner_id,
        created_at=a.created_at,
        updated_at=a.updated_at,
    )


async def list_agents_admin(db: AsyncSession) -> list[AgentOut]:
    rows = (
        await db.execute(select(Agent).where(Agent.is_deleted == 0).order_by(Agent.id.desc()))
    ).scalars().all()
    return [await _to_out(db, a) for a in rows]


async def list_agents_public(db: AsyncSession, user) -> list[AgentBrief]:
    rows = await usable_agents(db, user)
    return [
        AgentBrief(
            id=a.id,
            name=a.name,
            description=a.description,
            emoji=a.emoji,
            kb_count=len(a.kb_ids or []),
            model=a.model,
            is_public=a.is_public,
        )
        for a in rows
    ]


# ---------------- 写操作 ----------------
async def _validate_kb_ids(db: AsyncSession, kb_ids: list[int]) -> None:
    if not kb_ids:
        raise AppError("至少绑定一个知识库", code=ErrorCode.VALIDATION_ERROR, status_code=422)
    rows = (
        await db.execute(
            select(KnowledgeBase.id).where(
                KnowledgeBase.id.in_(kb_ids), KnowledgeBase.is_deleted == 0
            )
        )
    ).scalars().all()
    missing = [k for k in kb_ids if k not in rows]
    if missing:
        raise AppError(
            f"知识库不存在或已删除：{missing}", code=ErrorCode.VALIDATION_ERROR, status_code=422
        )


def _validate_overrides(overrides: dict[str, str]) -> None:
    for code, content in (overrides or {}).items():
        if code not in AGENT_PROMPT_KEYS:
            raise AppError(
                f"未知的提示词标识：{code}", code=ErrorCode.VALIDATION_ERROR, status_code=422
            )
        prompt_service.validate_content(content)


def _clean_retrieve(cfg: dict | None) -> dict:
    cfg = cfg or {}
    out = {}
    for k in DEFAULT_RETRIEVE:
        if k in cfg and cfg[k] is not None:
            out[k] = cfg[k]
    return out


async def create_agent(db: AsyncSession, user, payload: AgentIn) -> AgentOut:
    await _validate_kb_ids(db, payload.kb_ids)
    _validate_overrides(payload.prompt_overrides)

    agent = Agent(
        name=payload.name.strip(),
        description=payload.description,
        emoji=payload.emoji or "🤖",
        kb_ids=list(payload.kb_ids),
        provider=payload.provider,
        model=payload.model,
        prompt_overrides=dict(payload.prompt_overrides),
        retrieve_config=_clean_retrieve(payload.retrieve_config),
        gen_settings=dict(payload.gen_settings or {}),
        is_published=payload.is_published,
        is_public=payload.is_public,
        owner_id=user.id,
    )
    db.add(agent)
    await db.commit()
    await db.refresh(agent)
    logger.info("agent_created", agent_id=agent.id, name=agent.name)
    return await _to_out(db, agent)


async def update_agent(db: AsyncSession, agent_id: int, payload: AgentUpdate) -> AgentOut:
    agent = await get_agent(db, agent_id)
    data = payload.model_dump(exclude_unset=True)

    if "kb_ids" in data and data["kb_ids"] is not None:
        await _validate_kb_ids(db, data["kb_ids"])
    if "prompt_overrides" in data and data["prompt_overrides"] is not None:
        _validate_overrides(data["prompt_overrides"])

    for key, value in data.items():
        if key == "retrieve_config" and value is not None:
            setattr(agent, key, _clean_retrieve(value))
        elif value is not None or key in ("description", "provider", "model"):
            setattr(agent, key, value)

    await db.commit()
    await db.refresh(agent)
    logger.info("agent_updated", agent_id=agent.id)
    return await _to_out(db, agent)


async def delete_agent(db: AsyncSession, agent_id: int) -> None:
    agent = await get_agent(db, agent_id)
    agent.is_deleted = 1
    await db.commit()
    logger.info("agent_deleted", agent_id=agent_id)


async def set_publish(db: AsyncSession, agent_id: int, published: bool) -> AgentOut:
    agent = await get_agent(db, agent_id)
    if published and not (agent.kb_ids or []):
        raise AppError(
            "没有绑定知识库，无法发布", code=ErrorCode.VALIDATION_ERROR, status_code=422
        )
    agent.is_published = published
    await db.commit()
    await db.refresh(agent)
    logger.info("agent_publish_changed", agent_id=agent_id, published=published)
    return await _to_out(db, agent)


# ---------------- 运行时装配（试跑用；问答链路在 chat_service 里） ----------------
def effective_retrieve(agent: Agent) -> dict:
    """agent 覆盖 → 默认。知识库级配置的回退在 chat_service 里（需要查库）。"""
    cfg = dict(DEFAULT_RETRIEVE)
    cfg.update({k: v for k, v in (agent.retrieve_config or {}).items() if v is not None})
    return cfg


async def test_agent(db: AsyncSession, user, agent_id: int, payload: AgentTestIn) -> AgentTestOut:
    """用智能体的完整配置（模型+提示词+知识库+检索参数）跑一次真实问答。

    发布前验证用：改完配置在这里看效果，不用去前台提问。
    """
    import time

    from app.services.chat_service import extract_citations

    agent = await get_agent(db, agent_id)
    kb_ids = list(agent.kb_ids or [])
    if not kb_ids:
        raise AppError("智能体未绑定知识库", code=ErrorCode.VALIDATION_ERROR, status_code=422)

    rcfg = effective_retrieve(agent)

    # 复用真实问答的检索图（含混合召回、精排、降级），保证试跑行为与线上一致
    from app.services.rag_graph import run_retrieval

    retrieved = await run_retrieval(
        payload.question,
        kb_ids,
        top_k=int(rcfg.get("top_k", 30)),
        rerank_top_n=int(rcfg.get("rerank_top_n", 8)),
        score_threshold=float(rcfg.get("score_threshold", 0.0)),
        rerank_enabled=bool(rcfg.get("rerank_enabled", True)),
    )
    hits = retrieved.get("hits", [])
    context = retrieved.get("context", "")

    # 提示词：agent 覆盖优先。version=0 表示"agent 覆盖版"（无独立版本历史）
    overrides = agent.prompt_overrides or {}
    if overrides.get("system_qa"):
        system = prompt_service.render(
            overrides["system_qa"],
            {
                "question": payload.question,
                "context": context,
                "kb_name": "、".join(await _kb_names(db, kb_ids)),
                "sources": len(hits),
            },
        )
        prompt_version = 0
    else:
        system, prompt_version = await prompt_service.render_for(
            prompt_service.CODE_SYSTEM_QA,
            {
                "question": payload.question,
                "context": context,
                "kb_name": "、".join(await _kb_names(db, kb_ids)),
                "sources": len(hits),
            },
            kb_id=kb_ids[0] if len(kb_ids) == 1 else None,
            db=db,
        )

    gen = agent.gen_settings or {}
    messages = [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": f"资料：\n{context}\n\n问题：{payload.question}"
            if context
            else f"问题：{payload.question}",
        },
    ]

    runtime = await (
        load_model_runtime(db, agent.provider)
        if agent.provider
        else load_default_runtime(db)
    )
    llm = get_llm(runtime=runtime)

    started = time.perf_counter()
    result = await llm.chat(
        messages,
        max_tokens=int(gen.get("max_tokens", 2048)),
        temperature=float(gen.get("temperature", 0.3)),
    )
    latency = int((time.perf_counter() - started) * 1000)

    citations = extract_citations(result.content, hits)

    return AgentTestOut(
        answer=result.content,
        model=llm.model,
        provider=llm.provider,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
        latency_ms=latency,
        sources=len(hits),
        citations=citations,
        system_prompt_head=system[:120],
    )
