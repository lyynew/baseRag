"""LangGraph 检索编排图。

为什么生成不放进图里：
生成需要 token 级流式输出，如果塞进节点会变成"节点跑完才拿到整段"，前端就得干等。
所以图负责「问题 → 可用上下文」的决策部分（含改写、召回、质量判断、重试循环），
生成放在 service 层流式执行。这样流式和非流式接口共用同一套检索逻辑，不会出现两套行为。

图结构：
    START → route ─┬→ direct（寒暄/无意义，直接回）
                   └→ rewrite → retrieve → grade ─┬→ ready
                                  ↑               └→ rewrite（召回不足，重试一次）
                                  └───────────────┘
"""

from collections.abc import Awaitable, Callable
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from app.core.logging import get_logger
from app.services.embedding import get_embedding_client
from app.services.rerank import get_rerank_client
from app.services.vector_store import get_vector_store

logger = get_logger(__name__)

MAX_RETRY = 1

# 召回不足的判定阈值。注意这是 **rerank 分**（0~1），不是余弦相似度：
# 混合检索经 RRF 融合后分数变成 0.01~0.05 量级，无法直接比较，所以统一看精排分。
LOW_SCORE_THRESHOLD = 0.1


class RagState(TypedDict, total=False):
    question: str
    rewritten: str
    kb_ids: list[int]
    history: list[dict]
    top_k: int
    rerank_top_n: int
    score_threshold: float
    rerank_enabled: bool

    hits: list[dict]
    context: str
    retry: int
    need_retrieve: bool
    reason: str
    tokens: int


# 是否属于"不需要检索"的寒暄/指令类问题
_GREETING = ("你好", "hi", "hello", "在吗", "谢谢", "再见", "你是谁")


def _is_smalltalk(q: str) -> bool:
    s = q.strip().lower()
    if len(s) <= 2:
        return True
    return any(s == g or (s.startswith(g) and len(s) <= 8) for g in _GREETING)


async def _node_route(state: RagState) -> dict:
    """轻量意图判断，用规则而不是再调一次模型，省钱也更快。"""
    q = state.get("question", "").strip()
    if not q:
        return {"need_retrieve": False, "reason": "empty_question"}
    if _is_smalltalk(q):
        return {"need_retrieve": False, "reason": "smalltalk"}
    return {"need_retrieve": True, "reason": "needs_knowledge"}


def make_rewrite_node(rewriter: Callable[[str, list[dict]], Awaitable[str]] | None):
    """查询改写节点。

    只在多轮对话且问题很短时触发（如"那它呢？"），单轮问题原样透传，
    避免每问一句都多花一次模型调用。
    """

    async def _node(state: RagState) -> dict:
        q = state.get("question", "").strip()
        history = state.get("history") or []
        if rewriter is None or not history or len(q) > 30:
            return {"rewritten": q}

        try:
            improved = await rewriter(q, history)
            improved = (improved or "").strip()
            if improved and improved != q:
                logger.info("query_rewritten", before=q, after=improved)
                return {"rewritten": improved}
        except Exception as exc:  # noqa: BLE001  改写失败不该阻断问答
            logger.warning("query_rewrite_failed", error=str(exc))
        return {"rewritten": q}

    return _node


async def _node_retrieve(state: RagState) -> dict:
    kb_ids = state.get("kb_ids") or []
    if not kb_ids:
        return {"hits": [], "context": "", "reason": "no_kb"}

    query = state.get("rewritten") or state.get("question", "")
    embedder = get_embedding_client()
    store = get_vector_store()

    try:
        qv = await embedder.embed_query(query)
        # 稠密 + BM25 双路召回（RRF 融合）。
        # 这里不传 score_threshold：RRF 融合分与余弦分不可比，过滤会把结果清空。
        hits = store.hybrid_search(
            qv,
            query,
            kb_ids=kb_ids,
            top_k=int(state.get("top_k", 30)),
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("retrieve_failed", error=str(exc))
        # 混合检索失败时降级为纯向量，保证问答不中断
        try:
            hits = store.search(
                await embedder.embed_query(query),
                kb_ids=kb_ids,
                top_k=int(state.get("top_k", 30)),
                score_threshold=float(state.get("score_threshold", 0.0)) or None,
            )
            logger.warning("retrieve_fallback_dense_only")
        except Exception as exc2:  # noqa: BLE001
            logger.exception("retrieve_fallback_failed", error=str(exc2))
            return {"hits": [], "context": "", "reason": "retrieve_failed"}

    tokens = embedder.usage.prompt_tokens

    # 精排
    rerank_applied = False
    if state.get("rerank_enabled", True) and len(hits) > 1:
        try:
            reranker = get_rerank_client()
            ranked = await reranker.rerank(
                query,
                [h.content for h in hits],
                top_n=int(state.get("rerank_top_n", 8)),
            )
            ordered = [(hits[i], score) for i, score in ranked if i < len(hits)]
            rerank_applied = True
        except Exception as exc:  # noqa: BLE001
            logger.warning("rerank_failed_use_vector_order", error=str(exc))
            ordered = [(h, h.score) for h in hits[: int(state.get("rerank_top_n", 8))]]
    else:
        ordered = [(h, h.score) for h in hits[: int(state.get("rerank_top_n", 8))]]

    payload = [
        {
            "chunk_id": h.chunk_id,
            "doc_id": h.doc_id,
            "content": h.content,
            "score": round(float(score), 4),
            "vector_score": round(float(h.score), 4),
        }
        for h, score in ordered
    ]

    # 组装带编号的上下文，编号与引用一一对应
    ctx_parts = []
    for idx, item in enumerate(payload, 1):
        ctx_parts.append(f"[{idx}] {item['content']}")

    logger.info(
        "retrieve_done",
        query=query[:50],
        hits=len(hits),
        kept=len(payload),
        rerank=rerank_applied,
        top_score=payload[0]["score"] if payload else 0,
    )
    return {
        "hits": payload,
        "context": "\n\n".join(ctx_parts),
        "tokens": tokens,
        "reason": "retrieved",
    }


async def _node_grade(state: RagState) -> dict:
    """判断召回质量，决定是否值得再试一次。"""
    hits = state.get("hits") or []
    retry = int(state.get("retry", 0))

    if not hits:
        if retry < MAX_RETRY:
            return {"retry": retry + 1, "reason": "empty_result_retry"}
        return {"reason": "empty_result_give_up"}

    top = float(hits[0]["score"])
    if top < LOW_SCORE_THRESHOLD and retry < MAX_RETRY:
        return {"retry": retry + 1, "reason": "low_score_retry"}

    return {"reason": "ok"}


def _route_after_grade(state: RagState) -> str:
    reason = state.get("reason", "")
    if reason.endswith("_retry"):
        return "rewrite"
    return "ready"


def build_graph(rewriter: Callable[[str, list[dict]], Awaitable[str]] | None = None):
    graph = StateGraph(RagState)

    graph.add_node("route", _node_route)
    graph.add_node("rewrite", make_rewrite_node(rewriter))
    graph.add_node("retrieve", _node_retrieve)
    graph.add_node("grade", _node_grade)

    graph.add_edge(START, "route")
    graph.add_conditional_edges(
        "route",
        lambda s: "rewrite" if s.get("need_retrieve") else END,
        {"rewrite": "rewrite", END: END},
    )
    graph.add_edge("rewrite", "retrieve")
    graph.add_edge("retrieve", "grade")
    graph.add_conditional_edges(
        "grade", _route_after_grade, {"rewrite": "rewrite", "ready": END}
    )
    return graph.compile()


_compiled: Any = None


def get_graph():
    global _compiled
    if _compiled is None:
        _compiled = build_graph()
    return _compiled


async def run_retrieval(
    question: str,
    kb_ids: list[int],
    *,
    history: list[dict] | None = None,
    top_k: int = 30,
    rerank_top_n: int = 8,
    score_threshold: float = 0.0,
    rerank_enabled: bool = True,
    rewriter: Callable[[str, list[dict]], Awaitable[str]] | None = None,
) -> RagState:
    """跑一遍检索图，返回包含 hits / context 的最终状态。

    传入 rewriter 时现场构图（构造成本只有几十微秒），因为改写器来自提示词配置、
    每次请求可能不同，不能像无改写版本那样用全局单例缓存。
    """
    graph = build_graph(rewriter) if rewriter else get_graph()
    init: RagState = {
        "question": question,
        "kb_ids": kb_ids,
        "history": history or [],
        "top_k": top_k,
        "rerank_top_n": rerank_top_n,
        "score_threshold": score_threshold,
        "rerank_enabled": rerank_enabled,
        "retry": 0,
    }
    result = await graph.ainvoke(init, {"recursion_limit": 12})
    return result  # type: ignore[return-value]
