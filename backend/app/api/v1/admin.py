"""后台：模型配置、审计日志、用量统计、系统参数。"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, desc, func, select

from app.core.deps import CurrentUser, DbSession, require_perm
from app.core.errors import AppError, ErrorCode
from app.core.logging import get_logger
from app.db.models.chat import AuditLog, LlmCallLog, ModelConfig, SystemSetting
from app.schemas.admin import (
    AuditLogOut,
    ModelConfigIn,
    ModelConfigOut,
    ModelConfigUpdate,
    ModelTestResult,
    SettingItem,
    SettingUpdate,
    UsageStat,
    UsageSummary,
)
from app.services.crypto import decrypt_secret, encrypt_secret, mask_secret
from app.services.llm import get_llm
from app.services.model_runtime import ModelRuntime

logger = get_logger(__name__)
router = APIRouter()


def _to_out(row: ModelConfig, plain_key: str = "") -> ModelConfigOut:
    masked = mask_secret(plain_key) if plain_key else "****"
    return ModelConfigOut(
        id=row.id,
        provider=row.provider,
        name=row.name,
        base_url=row.base_url,
        api_key_masked=masked,
        model=row.model,
        max_context=row.max_context,
        max_output=row.max_output,
        supports_json=row.supports_json,
        supports_stream=row.supports_stream,
        enabled=row.enabled,
        is_default=row.is_default,
        created_at=row.created_at,
    )


# ---------------- 模型配置 ----------------
@router.get(
    "/models",
    response_model=list[ModelConfigOut],
    summary="模型配置列表（密钥脱敏）",
    dependencies=[Depends(require_perm("config:read"))],
)
async def list_models(db: DbSession) -> list[ModelConfigOut]:
    rows = (
        await db.execute(
            select(ModelConfig).order_by(ModelConfig.is_default.desc(), ModelConfig.id)
        )
    ).scalars().all()
    result = []
    for r in rows:
        masked = "****"
        try:
            masked = mask_secret(decrypt_secret(r.api_key_enc))
        except Exception:  # noqa: BLE001
            masked = "****（解密失败）"
        result.append(_to_out(r, masked))
    return result


@router.post(
    "/models",
    response_model=ModelConfigOut,
    summary="新增模型配置",
    dependencies=[Depends(require_perm("config:write"))],
)
async def create_model(
    payload: ModelConfigIn, db: DbSession, user: CurrentUser
) -> ModelConfigOut:
    dup = (
        await db.execute(
            select(ModelConfig).where(
                ModelConfig.provider == payload.provider, ModelConfig.model == payload.model
            )
        )
    ).scalar_one_or_none()
    if dup is not None:
        raise AppError(
            "该提供方下已存在同名模型", code=ErrorCode.CONFLICT, status_code=409
        )

    row = ModelConfig(
        provider=payload.provider,
        name=payload.name,
        base_url=payload.base_url,
        api_key_enc=encrypt_secret(payload.api_key),
        model=payload.model,
        max_context=payload.max_context,
        max_output=payload.max_output,
        supports_json=payload.supports_json,
        supports_stream=payload.supports_stream,
        enabled=payload.enabled,
        is_default=False,
    )
    db.add(row)
    await db.flush()
    await _audit(db, user, "model.create", "model_config", row.id,
                 None, {"provider": row.provider, "model": row.model})
    await db.commit()
    await db.refresh(row)
    return _to_out(row, mask_secret(payload.api_key))


@router.patch(
    "/models/{model_id}",
    response_model=ModelConfigOut,
    summary="修改模型配置（api_key 留空表示不改）",
    dependencies=[Depends(require_perm("config:write"))],
)
async def update_model(
    model_id: int, payload: ModelConfigUpdate, db: DbSession, user: CurrentUser
) -> ModelConfigOut:
    row = (
        await db.execute(select(ModelConfig).where(ModelConfig.id == model_id))
    ).scalar_one_or_none()
    if row is None:
        raise AppError("模型配置不存在", code=ErrorCode.NOT_FOUND, status_code=404)

    before = {
        "name": row.name,
        "base_url": row.base_url,
        "model": row.model,
        "enabled": row.enabled,
        "max_context": row.max_context,
    }
    if payload.name is not None:
        row.name = payload.name
    if payload.base_url is not None:
        row.base_url = payload.base_url
    if payload.model is not None:
        row.model = payload.model
    if payload.max_context is not None:
        row.max_context = payload.max_context
    if payload.max_output is not None:
        row.max_output = payload.max_output
    if payload.supports_json is not None:
        row.supports_json = payload.supports_json
    if payload.supports_stream is not None:
        row.supports_stream = payload.supports_stream
    if payload.enabled is not None:
        row.enabled = payload.enabled
        if not payload.enabled and row.is_default:
            raise AppError(
                "默认模型不能禁用，请先把其他模型设为默认",
                code=ErrorCode.CONFLICT,
                status_code=409,
            )
    if payload.api_key:
        row.api_key_enc = encrypt_secret(payload.api_key)

    after = {
        "name": row.name,
        "base_url": row.base_url,
        "model": row.model,
        "enabled": row.enabled,
        "max_context": row.max_context,
    }
    if before != after:
        await _audit(db, user, "model.update", "model_config", row.id, before, after)

    await db.commit()
    await db.refresh(row)

    plain = ""
    try:
        plain = decrypt_secret(row.api_key_enc)
    except Exception:  # noqa: BLE001
        plain = ""
    return _to_out(row, mask_secret(plain) if plain else "****")


@router.delete(
    "/models/{model_id}",
    summary="删除模型配置",
    dependencies=[Depends(require_perm("config:write"))],
)
async def delete_model(model_id: int, db: DbSession, user: CurrentUser) -> dict:
    row = (
        await db.execute(select(ModelConfig).where(ModelConfig.id == model_id))
    ).scalar_one_or_none()
    if row is None:
        raise AppError("模型配置不存在", code=ErrorCode.NOT_FOUND, status_code=404)
    if row.is_default:
        raise AppError(
            "默认模型不能删除，请先切换默认模型",
            code=ErrorCode.CONFLICT,
            status_code=409,
        )

    await _audit(db, user, "model.delete", "model_config", row.id,
                 {"provider": row.provider, "model": row.model})
    await db.delete(row)
    await db.commit()
    return {"message": "已删除"}


@router.post(
    "/models/{model_id}/set-default",
    response_model=list[ModelConfigOut],
    summary="设为默认模型（全局切换，立即生效）",
    dependencies=[Depends(require_perm("config:write"))],
)
async def set_default_model(
    model_id: int, db: DbSession, user: CurrentUser
) -> list[ModelConfigOut]:
    row = (
        await db.execute(select(ModelConfig).where(ModelConfig.id == model_id))
    ).scalar_one_or_none()
    if row is None:
        raise AppError("模型配置不存在", code=ErrorCode.NOT_FOUND, status_code=404)
    if not row.enabled:
        raise AppError("已禁用的模型不能设为默认", code=ErrorCode.CONFLICT, status_code=409)

    all_rows = (await db.execute(select(ModelConfig))).scalars().all()
    for r in all_rows:
        r.is_default = r.id == model_id

    await _audit(db, user, "model.set_default", "model_config", row.id,
                 None, {"provider": row.provider, "model": row.model})
    await db.commit()
    logger.info("default_model_changed", provider=row.provider, model=row.model, by=user.id)
    return await list_models(db)


@router.post(
    "/models/{model_id}/test",
    response_model=ModelTestResult,
    summary="测试模型连通性（会真实调用一次，产生少量费用）",
    dependencies=[Depends(require_perm("config:write"))],
)
async def test_model(model_id: int, db: DbSession) -> ModelTestResult:
    row = (
        await db.execute(select(ModelConfig).where(ModelConfig.id == model_id))
    ).scalar_one_or_none()
    if row is None:
        raise AppError("模型配置不存在", code=ErrorCode.NOT_FOUND, status_code=404)

    try:
        api_key = decrypt_secret(row.api_key_enc)
    except AppError as exc:
        return ModelTestResult(ok=False, error=exc.message)

    runtime = ModelRuntime(
        provider=row.provider,
        base_url=row.base_url,
        api_key=api_key,
        model=row.model,
        max_context=row.max_context,
        supports_json=row.supports_json,
        supports_stream=row.supports_stream,
        source="db",
    )
    llm = get_llm(runtime=runtime)
    try:
        result = await llm.chat(
            [{"role": "user", "content": "回复 ok 两个字"}], max_tokens=32, temperature=0
        )
    except AppError as exc:
        return ModelTestResult(ok=False, error=exc.message)
    except Exception as exc:  # noqa: BLE001
        return ModelTestResult(ok=False, error=f"{type(exc).__name__}: {exc}")

    return ModelTestResult(
        ok=True,
        latency_ms=result.latency_ms,
        reply=(result.content or "")[:100],
        usage={
            "prompt_tokens": result.prompt_tokens,
            "completion_tokens": result.completion_tokens,
        },
    )


# ---------------- 审计日志 ----------------
@router.get(
    "/audit-logs",
    response_model=list[AuditLogOut],
    summary="审计日志（谁改了什么）",
    dependencies=[Depends(require_perm("audit:read"))],
)
async def list_audit_logs(
    db: DbSession,
    action: str | None = Query(default=None, max_length=64),
    operator_id: int | None = None,
    days: int = Query(default=7, ge=1, le=90),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[AuditLogOut]:
    stmt = select(AuditLog).where(
        AuditLog.created_at >= datetime.now() - timedelta(days=days)
    )
    if action:
        stmt = stmt.where(AuditLog.action.like(f"{action}%"))
    if operator_id:
        stmt = stmt.where(AuditLog.operator_id == operator_id)
    stmt = stmt.order_by(desc(AuditLog.created_at)).limit(limit).offset(offset)
    rows = (await db.execute(stmt)).scalars().all()
    return [AuditLogOut.model_validate(r) for r in rows]


# ---------------- 用量统计 ----------------
@router.get(
    "/usage",
    response_model=UsageSummary,
    summary="Token 用量统计（按场景与模型分组）",
    dependencies=[Depends(require_perm("audit:read"))],
)
async def usage_summary(
    db: DbSession, days: int = Query(default=7, ge=1, le=90)
) -> UsageSummary:
    since = datetime.now() - timedelta(days=days)
    rows = (
        await db.execute(
            select(
                LlmCallLog.scene,
                LlmCallLog.provider,
                LlmCallLog.model,
                func.count().label("calls"),
                func.coalesce(func.sum(LlmCallLog.prompt_tokens), 0),
                func.coalesce(func.sum(LlmCallLog.completion_tokens), 0),
            )
            .where(LlmCallLog.created_at >= since)
            .group_by(LlmCallLog.scene, LlmCallLog.provider, LlmCallLog.model)
            .order_by(desc(func.count()))
        )
    ).all()

    items = [
        UsageStat(
            scene=r[0],
            provider=r[1],
            model=r[2],
            calls=int(r[3]),
            prompt_tokens=int(r[4]),
            completion_tokens=int(r[5]),
        )
        for r in rows
    ]
    return UsageSummary(
        days=days,
        total_calls=sum(i.calls for i in items),
        total_prompt_tokens=sum(i.prompt_tokens for i in items),
        total_completion_tokens=sum(i.completion_tokens for i in items),
        items=items,
    )


@router.get(
    "/usage/daily",
    summary="按天统计调用量（用于趋势图）",
    dependencies=[Depends(require_perm("audit:read"))],
)
async def usage_daily(db: DbSession, days: int = Query(default=14, ge=1, le=90)) -> dict:
    since = datetime.now() - timedelta(days=days)
    day_expr = func.date(LlmCallLog.created_at)
    rows = (
        await db.execute(
            select(
                day_expr.label("d"),
                func.count().label("calls"),
                func.coalesce(func.sum(LlmCallLog.prompt_tokens), 0).label("pt"),
                func.coalesce(func.sum(LlmCallLog.completion_tokens), 0).label("ct"),
                func.sum(case((LlmCallLog.scene == "chat", 1), else_=0)).label("chats"),
            )
            .where(LlmCallLog.created_at >= since)
            .group_by(day_expr)
            .order_by(day_expr)
        )
    ).all()
    return {
        "days": days,
        "items": [
            {
                "date": str(r[0]),
                "calls": int(r[1]),
                "prompt_tokens": int(r[2]),
                "completion_tokens": int(r[3]),
                "chat_calls": int(r[4] or 0),
            }
            for r in rows
        ],
    }


# ---------------- 系统参数 ----------------
@router.get(
    "/settings",
    response_model=list[SettingItem],
    summary="系统参数列表（预留，部分参数尚未接入业务读取）",
    dependencies=[Depends(require_perm("config:read"))],
)
async def list_settings(db: DbSession) -> list[SettingItem]:
    rows = (await db.execute(select(SystemSetting).order_by(SystemSetting.key))).scalars().all()
    return [
        SettingItem(key=r.key, value=r.value, description=r.description) for r in rows
    ]


@router.put(
    "/settings/{key}",
    response_model=SettingItem,
    summary="写入系统参数",
    dependencies=[Depends(require_perm("config:write"))],
)
async def upsert_setting(
    key: str, payload: SettingUpdate, db: DbSession, user: CurrentUser
) -> SettingItem:
    row = await db.get(SystemSetting, key)
    before = {"value": row.value} if row else None
    if row is None:
        row = SystemSetting(
            key=key, value=payload.value, description=payload.description,
            updated_by=user.id,
        )
        db.add(row)
    else:
        row.value = payload.value
        if payload.description is not None:
            row.description = payload.description
        row.updated_by = user.id

    await _audit(db, user, "setting.update", "system_setting", None, before,
                 {"key": key, "value": payload.value})
    await db.commit()
    return SettingItem(key=row.key, value=row.value, description=row.description)


async def _audit(
    db,
    user,
    action: str,
    target_type: str,
    target_id: int | None,
    before: dict | None = None,
    after: dict | None = None,
) -> None:
    db.add(
        AuditLog(
            operator_id=user.id,
            operator_name=user.username,
            action=action,
            target_type=target_type,
            target_id=target_id,
            before=before,
            after=after,
            result="ok",
            created_at=datetime.now(),
        )
    )
