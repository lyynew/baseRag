"""后台：提示词模板管理。

权限沿用 config:read / config:write——提示词属于系统配置，不需要新开权限码。

为什么不放在 admin.py：
提示词有版本、回滚、预览、试跑四组接口，塞进 admin.py 会让那个文件超过 600 行，
而且它和模型配置不是同一类东西（一个是接哪个模型，一个是让模型怎么说），
后期排查问题时要翻半天。单独一个文件更好定位。
"""

import time
from datetime import datetime

from fastapi import APIRouter, Depends, Query

from app.core.deps import CurrentUser, DbSession, require_perm
from app.core.logging import get_logger
from app.db.models.chat import AuditLog
from app.schemas.prompt import (
    PromptOut,
    PromptPreviewIn,
    PromptPreviewOut,
    PromptTestIn,
    PromptTestOut,
    PromptUpdate,
    PromptVarMeta,
    PromptVersionOut,
)
from app.services import prompt_service
from app.services.embedding import get_embedding_client
from app.services.llm import get_llm
from app.services.model_runtime import load_default_runtime
from app.services.prompt_service import ALLOWED_VARS, render
from app.services.vector_store import get_vector_store

logger = get_logger(__name__)
router = APIRouter()


def _audit(
    db,
    user,
    action: str,
    code: str,
    kb_id: int,
    before: dict | None = None,
    after: dict | None = None,
) -> None:
    db.add(
        AuditLog(
            operator_id=user.id,
            operator_name=user.username,
            action=action,
            target_type="prompt",
            target_id=None,
            before={"code": code, "kb_id": kb_id, **(before or {})},
            after={"code": code, "kb_id": kb_id, **(after or {})},
            result="ok",
            created_at=datetime.now(),
        )
    )


@router.get(
    "",
    response_model=list[PromptOut],
    summary="提示词模板列表",
    dependencies=[Depends(require_perm("config:read"))],
)
async def list_prompts(db: DbSession) -> list[PromptOut]:
    rows = await prompt_service.list_templates(db)
    return [PromptOut(**r) for r in rows]


@router.get(
    "/variables",
    response_model=list[PromptVarMeta],
    summary="可用变量清单",
    dependencies=[Depends(require_perm("config:read"))],
)
async def list_variables() -> list[PromptVarMeta]:
    return [PromptVarMeta(name=k, desc=v) for k, v in ALLOWED_VARS.items()]


@router.get(
    "/{code}",
    response_model=PromptOut,
    summary="提示词详情",
    dependencies=[Depends(require_perm("config:read"))],
)
async def get_prompt(
    code: str, db: DbSession, kb_id: int = Query(default=0, ge=0)
) -> PromptOut:
    tpl = await prompt_service.get_effective(code, kb_id, db=db)
    builtin = prompt_service.DEFAULT_PROMPTS.get(code, {})
    return PromptOut(
        **tpl,
        is_customized=tpl["content"] != builtin.get("content"),
    )


@router.put(
    "/{code}",
    response_model=PromptOut,
    summary="保存提示词（自动版本 +1）",
    dependencies=[Depends(require_perm("config:write"))],
)
async def save_prompt(
    code: str,
    payload: PromptUpdate,
    db: DbSession,
    user: CurrentUser,
    kb_id: int = Query(default=0, ge=0),
) -> PromptOut:
    before = await prompt_service.get_effective(code, kb_id, db=db)
    saved = await prompt_service.save(
        db,
        code=code,
        content=payload.content,
        name=payload.name,
        description=payload.description,
        kb_id=kb_id,
        note=payload.note,
        user_id=user.id,
    )
    _audit(
        db,
        user,
        "prompt.update",
        code,
        kb_id,
        before={"version": before["version"], "content": before["content"]},
        after={"version": saved["version"], "content": payload.content},
    )
    await db.commit()

    tpl = await prompt_service.get_effective(code, kb_id, db=db)
    builtin = prompt_service.DEFAULT_PROMPTS.get(code, {})
    return PromptOut(**tpl, is_customized=tpl["content"] != builtin.get("content"))


@router.post(
    "/{code}/reset",
    response_model=PromptOut,
    summary="恢复出厂默认",
    dependencies=[Depends(require_perm("config:write"))],
)
async def reset_prompt(
    code: str, db: DbSession, user: CurrentUser, kb_id: int = Query(default=0, ge=0)
) -> PromptOut:
    before = await prompt_service.get_effective(code, kb_id, db=db)
    await prompt_service.reset(db, code=code, kb_id=kb_id, user_id=user.id)
    _audit(
        db,
        user,
        "prompt.reset",
        code,
        kb_id,
        before={"version": before["version"], "content": before["content"]},
    )
    await db.commit()

    tpl = await prompt_service.get_effective(code, kb_id, db=db)
    return PromptOut(**tpl, is_customized=False)


@router.get(
    "/{code}/versions",
    response_model=list[PromptVersionOut],
    summary="版本历史",
    dependencies=[Depends(require_perm("config:read"))],
)
async def list_versions(
    code: str,
    db: DbSession,
    kb_id: int = Query(default=0, ge=0),
    limit: int = Query(default=30, ge=1, le=100),
) -> list[PromptVersionOut]:
    rows = await prompt_service.list_versions(db, code=code, kb_id=kb_id, limit=limit)
    return [PromptVersionOut(**r) for r in rows]


@router.post(
    "/{code}/rollback/{version}",
    response_model=PromptOut,
    summary="回滚到指定版本（生成新版本，不覆盖历史）",
    dependencies=[Depends(require_perm("config:write"))],
)
async def rollback_prompt(
    code: str,
    version: int,
    db: DbSession,
    user: CurrentUser,
    kb_id: int = Query(default=0, ge=0),
) -> PromptOut:
    before = await prompt_service.get_effective(code, kb_id, db=db)
    saved = await prompt_service.rollback(
        db, code=code, version=version, kb_id=kb_id, user_id=user.id
    )
    _audit(
        db,
        user,
        "prompt.rollback",
        code,
        kb_id,
        before={"version": before["version"]},
        after={"version": saved["version"], "from_version": version},
    )
    await db.commit()
    tpl = await prompt_service.get_effective(code, kb_id, db=db)
    return PromptOut(**tpl, is_customized=True)


@router.post(
    "/{code}/preview",
    response_model=PromptPreviewOut,
    summary="渲染预览（不调模型、不花钱）",
    dependencies=[Depends(require_perm("config:read"))],
)
async def preview_prompt(
    code: str, payload: PromptPreviewIn, db: DbSession, kb_id: int = Query(default=0, ge=0)
) -> PromptPreviewOut:
    if payload.content is not None:
        used = prompt_service.validate_content(payload.content)
        content = payload.content
        version = 0
    else:
        tpl = await prompt_service.get_effective(code, kb_id, db=db)
        used = list(tpl["variables"])
        content = tpl["content"]
        version = int(tpl["version"])

    missing = [v for v in used if not payload.values.get(v)]
    rendered = render(content, payload.values)
    # 中文约 1.5 token/字，仅作量级参考，实际以厂商计费为准
    est = int(len(rendered) * 1.5)

    return PromptPreviewOut(
        rendered=rendered,
        variables=used,
        missing=missing,
        chars=len(rendered),
        tokens_estimate=est,
        version=version,
    )


@router.post(
    "/{code}/test",
    response_model=PromptTestOut,
    summary="用此提示词试跑一次（会产生少量 token 费用）",
    dependencies=[Depends(require_perm("config:write"))],
)
async def test_prompt(
    code: str, payload: PromptTestIn, db: DbSession, kb_id: int = Query(default=0, ge=0)
) -> PromptTestOut:
    """改完提示词直接看效果，不必切到前台提问。

    提供 kb_id 时会真实检索一次作为资料，token 花费通常在几百量级。
    """
    if payload.content is not None:
        prompt_service.validate_content(payload.content)
        content = payload.content
        version = 0
    else:
        tpl = await prompt_service.get_effective(code, kb_id, db=db)
        content = tpl["content"]
        version = int(tpl["version"])

    context = ""
    sources = 0
    if payload.kb_id:
        try:
            embedder = get_embedding_client()
            qv = await embedder.embed_query(payload.question)
            hits = get_vector_store().hybrid_search(qv, payload.question, [payload.kb_id], top_k=5)
            sources = len(hits)
            context = "\n\n".join(
                f"[{i + 1}] {h.content[:600]}" for i, h in enumerate(hits)
            )
        except Exception as exc:  # noqa: BLE001  检索失败仍可测提示词本身
            logger.warning("prompt_test_retrieve_failed", error=str(exc))

    system = render(
        content,
        {
            "question": payload.question,
            "context": context,
            "kb_name": f"知识库 {payload.kb_id}" if payload.kb_id else "",
            "sources": sources,
        },
    )
    messages = [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": f"资料：\n{context}\n\n问题：{payload.question}"
            if context
            else f"问题：{payload.question}",
        },
    ]

    runtime = await load_default_runtime(db)
    llm = get_llm(runtime=runtime)
    started = time.perf_counter()
    result = await llm.chat(messages, max_tokens=1024)

    return PromptTestOut(
        answer=result.content,
        model=llm.model,
        provider=llm.provider,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
        latency_ms=int((time.perf_counter() - started) * 1000),
        sources=sources,
        rendered_system=system,
        version=version,
    )
