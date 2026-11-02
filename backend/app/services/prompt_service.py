"""提示词管理：内置默认值、变量校验、渲染、DB 读取（带缓存）、版本回滚。

三个关键设计：

1. **变量用 `{{name}}` 双花括号**，不用 Python 的 `{name}`。
   因为提示词里经常出现 JSON 示例（`{"a": 1}`），单花括号会让 `str.format` 直接抛 KeyError，
   而且报错信息只有 "a"，根本看不出是哪段提示词出的问题。

2. **未知变量在校验期就拦下**。`{{contxt}}` 这类拼写错误不会报错，只会让模型收到一个字面量
   `{{contxt}}`，表现为"回答质量莫名变差"——这是提示词管理里最难排查的一类故障。

3. **读失败必须回退内置默认值**。提示词表查不到、数据库抖动、迁移没跑，
   都不该让整个问答功能不可用。
"""

import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ErrorCode
from app.core.logging import get_logger
from app.db.models.prompt import GLOBAL_SCOPE, PromptTemplate, PromptVersion
from app.db.session import SessionLocal

logger = get_logger(__name__)

# ---------------- 模板标识 ----------------
CODE_SYSTEM_QA = "system_qa"           # 基于资料的问答
CODE_DIRECT = "direct_answer"          # 寒暄/无关问题的直接回复
CODE_REWRITE = "query_rewrite"         # 多轮追问的查询改写

# 允许出现的变量。新增变量要同时改这里的白名单和 chat_service 的传参，
# 否则渲染时会被当成"未提供"处理。
ALLOWED_VARS: dict[str, str] = {
    "context": "检索到的资料正文（已带 [1][2] 编号）",
    "question": "用户当前问题",
    "kb_name": "知识库名称",
    "history": "最近若干轮对话（可选）",
    "sources": "命中片段数量",
}

VAR_RE = re.compile(r"\{\{\s*([a-zA-Z_]\w*)\s*\}\}")

# 历史版本保留上限。提示词不是代码，30 版足够回溯，也避免表无限增长。
MAX_VERSIONS = 30
# 单条提示词长度上限（字符）
MAX_CONTENT_LEN = 8000
# 缓存 TTL。多进程部署时各进程独立缓存，30 秒内可能读到旧值，对提示词可接受。
CACHE_TTL_SECONDS = 30


# ---------------- 内置默认值 ----------------
DEFAULT_PROMPTS: dict[str, dict[str, Any]] = {
    CODE_SYSTEM_QA: {
        "name": "知识库问答",
        "description": "基于检索资料回答用户问题，要求标注引用编号",
        "variables": ["question", "context", "kb_name"],
        "content": """你是企业知识库问答助手。请严格依据下面提供的资料回答问题。

要求：
1. 只使用资料中的信息，不要编造资料里没有的内容。
2. 每个关键结论后标注来源编号，例如 [1]、[2]，编号必须来自资料前的编号。
3. 如果资料不足以回答，直接说明"根据现有资料无法回答"，并指出还缺什么信息。
4. 用简洁中文回答，不要复述问题，不要输出"根据资料"这类套话。
5. 不要提及"资料[1]"这类表述，直接在句末标 [1] 即可。""",
    },
    CODE_DIRECT: {
        "name": "寒暄/无关问题回复",
        "description": "判定为寒暄或与知识库无关时使用，不检索、不编造",
        "variables": ["question"],
        "content": """你是企业知识库问答助手。用户发来的是简短寒暄或与知识库无关的内容。
请礼貌简短地回应，并引导用户提出具体的业务问题。不要编造任何业务信息。""",
    },
    CODE_REWRITE: {
        "name": "查询改写",
        "description": "多轮追问时把省略指代的问题补全为独立可检索的查询",
        "variables": ["question"],
        "content": """把用户的最新问题改写为一个独立、完整、可用于检索的查询。

要求：
1. 结合对话历史补全省略的主语和指代（如"那二线城市呢"→"二线城市出差住宿标准"）。
2. 只输出改写后的查询本身，不要解释、不要引号、不要前缀。
3. 若问题本身已经完整，原样输出。""",
    },
}

_CACHE: dict[tuple[str, int], tuple[datetime, dict[str, Any]]] = {}


# ---------------- 变量与渲染 ----------------
def extract_vars(content: str) -> list[str]:
    """提取模板中出现的变量名，按首次出现顺序去重。"""
    seen: list[str] = []
    for m in VAR_RE.finditer(content or ""):
        name = m.group(1)
        if name not in seen:
            seen.append(name)
    return seen


def validate_content(content: str) -> list[str]:
    """校验模板内容，返回声明的变量列表。非法时抛 400。

    只允许白名单变量：不是限制自由度，而是防止拼错后静默失效。
    """
    if not content or not content.strip():
        raise AppError(
            "提示词内容不能为空", code=ErrorCode.VALIDATION_ERROR, status_code=400
        )
    if len(content) > MAX_CONTENT_LEN:
        raise AppError(
            f"提示词过长（{len(content)} 字符），上限 {MAX_CONTENT_LEN}",
            code=ErrorCode.VALIDATION_ERROR,
            status_code=400,
        )

    used = extract_vars(content)
    unknown = [v for v in used if v not in ALLOWED_VARS]
    if unknown:
        allowed = "、".join(f"{{{{{k}}}}}" for k in ALLOWED_VARS)
        raise AppError(
            f"提示词中含未知变量：{'、'.join(f'{{{{{v}}}}}' for v in unknown)}。"
            f"可用变量：{allowed}",
            code=ErrorCode.VALIDATION_ERROR,
            status_code=400,
        )
    return used


def render(content: str, values: dict[str, Any]) -> str:
    """把 {{var}} 替换为实际值。

    未提供值的变量原样保留——这比抛异常更安全：问答链路不该因为少传一个可选变量就崩，
    而且保留原样在日志里一眼能看出是哪个变量没给。
    """

    def _sub(m: re.Match[str]) -> str:
        key = m.group(1)
        if key in values and values[key] is not None:
            return str(values[key])
        return m.group(0)

    return VAR_RE.sub(_sub, content or "")


# ---------------- 读取（带缓存 + 兜底） ----------------
def _cache_get(code: str, kb_id: int) -> dict[str, Any] | None:
    item = _CACHE.get((code, kb_id))
    if not item:
        return None
    ts, payload = item
    if (datetime.now(UTC) - ts).total_seconds() > CACHE_TTL_SECONDS:
        _CACHE.pop((code, kb_id), None)
        return None
    return payload


def invalidate(code: str | None = None, kb_id: int | None = None) -> None:
    """写操作后清缓存，让改动立即生效。

    不按 kb 精细清理：写操作频率极低（一天几次），
    而漏清一条缓存会导致"改完提示词没生效"这种极难自证的问题。
    宁可整体失效，也不要精确到出错。
    """
    if code is None:
        _CACHE.clear()
        return
    for key in [k for k in _CACHE if k[0] == code]:
        _CACHE.pop(key, None)


def _builtin(code: str) -> dict[str, Any]:
    d = DEFAULT_PROMPTS.get(code)
    if d is None:
        raise AppError(
            f"未知的提示词标识：{code}", code=ErrorCode.NOT_FOUND, status_code=404
        )
    return {
        "code": code,
        "kb_id": GLOBAL_SCOPE,
        "name": d["name"],
        "content": d["content"],
        "variables": list(d["variables"]),
        "description": d["description"],
        "version": 0,
        "source": "builtin",
    }


async def get_effective(
    code: str, kb_id: int | None = None, db: AsyncSession | None = None
) -> dict[str, Any]:
    """取生效的提示词：知识库覆盖 → 全局 → 内置默认。

    任何异常都退回内置默认，保证问答不因提示词表故障而不可用。
    """
    if code not in DEFAULT_PROMPTS:
        raise AppError(f"未知的提示词标识：{code}", code=ErrorCode.NOT_FOUND, status_code=404)

    kb = int(kb_id or GLOBAL_SCOPE)
    cached = _cache_get(code, kb)
    if cached:
        return cached

    try:
        async def _query(session: AsyncSession) -> dict[str, Any] | None:
            # 只取本 kb 与全局两条候选，kb 级优先
            stmt = (
                select(PromptTemplate)
                .where(
                    PromptTemplate.code == code,
                    PromptTemplate.kb_id.in_([kb, GLOBAL_SCOPE]),
                    PromptTemplate.is_active.is_(True),
                )
                .order_by(desc(PromptTemplate.kb_id != GLOBAL_SCOPE))
                .limit(1)
            )
            row = (await session.execute(stmt)).scalars().first()
            if row is None:
                return None
            return {
                "code": row.code,
                "kb_id": row.kb_id,
                "name": row.name,
                "content": row.content,
                "variables": list(row.variables or []),
                "description": row.description,
                "version": row.version,
                "source": "global" if row.kb_id == GLOBAL_SCOPE else "kb",
            }

        if db is not None:
            payload = await _query(db)
        else:
            async with SessionLocal() as session:
                payload = await _query(session)
    except Exception as exc:  # noqa: BLE001  提示词读不到不能让问答不可用
        logger.warning("prompt_load_failed", code=code, kb_id=kb, error=str(exc))
        return _builtin(code)

    if payload is None:
        payload = _builtin(code)

    # 按请求作用域缓存：kb=5 命中全局记录时也缓存到 (code, 5)，避免每次都回表
    _CACHE[(code, kb)] = (datetime.now(UTC), payload)
    return payload


async def render_for(
    code: str,
    values: dict[str, Any],
    kb_id: int | None = None,
    db: AsyncSession | None = None,
) -> tuple[str, int]:
    """渲染提示词，返回 (文本, 版本号)。版本号要写进 llm_call_logs 便于事后归因。"""
    tpl = await get_effective(code, kb_id, db=db)
    return render(tpl["content"], values), int(tpl["version"])


# ---------------- 写操作 ----------------
async def list_templates(db: AsyncSession) -> list[dict[str, Any]]:
    """列出所有内置模板的全局配置（知识库覆盖另行查询）。"""
    rows = (
        await db.execute(
            select(PromptTemplate).where(PromptTemplate.kb_id == GLOBAL_SCOPE)
        )
    ).scalars().all()
    by_code = {r.code: r for r in rows}

    out: list[dict[str, Any]] = []
    for code, d in DEFAULT_PROMPTS.items():
        row = by_code.get(code)
        if row is None:
            out.append({**_builtin(code), "is_customized": False, "updated_at": None})
        else:
            out.append(
                {
                    "code": code,
                    "kb_id": GLOBAL_SCOPE,
                    "name": row.name,
                    "content": row.content,
                    "variables": list(row.variables or []),
                    "description": row.description,
                    "version": row.version,
                    "source": "global",
                    "is_customized": row.content != d["content"],
                    "updated_at": row.updated_at,
                    "updated_by": row.updated_by,
                }
            )
    return out


async def list_kb_overrides(db: AsyncSession, kb_id: int | None = None) -> list[dict[str, Any]]:
    stmt = select(PromptTemplate).where(PromptTemplate.kb_id != GLOBAL_SCOPE)
    if kb_id:
        stmt = stmt.where(PromptTemplate.kb_id == kb_id)
    rows = (await db.execute(stmt.order_by(PromptTemplate.kb_id))).scalars().all()
    return [
        {
            "code": r.code,
            "kb_id": r.kb_id,
            "name": r.name,
            "content": r.content,
            "variables": list(r.variables or []),
            "version": r.version,
            "is_active": r.is_active,
        }
        for r in rows
    ]


async def save(
    db: AsyncSession,
    *,
    code: str,
    content: str,
    name: str | None = None,
    description: str | None = None,
    kb_id: int = GLOBAL_SCOPE,
    note: str | None = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    """保存提示词（不存在则创建），版本号 +1 并留快照。"""
    if code not in DEFAULT_PROMPTS:
        raise AppError(f"未知的提示词标识：{code}", code=ErrorCode.NOT_FOUND, status_code=404)

    used = validate_content(content)
    row = (
        await db.execute(
            select(PromptTemplate).where(
                PromptTemplate.code == code, PromptTemplate.kb_id == kb_id
            )
        )
    ).scalars().first()

    if row is None:
        is_new = True
        row = PromptTemplate(
            code=code,
            kb_id=kb_id,
            name=name or DEFAULT_PROMPTS[code]["name"],
            content=content,
            variables=used,
            description=description or DEFAULT_PROMPTS[code]["description"],
            version=1,
            is_active=True,
            updated_by=user_id,
        )
        db.add(row)
    else:
        is_new = False
        row.content = content
        row.variables = used
        if name:
            row.name = name
        if description is not None:
            row.description = description
        row.updated_by = user_id

    await db.flush()

    # 版本号要在「模板行」与「历史表」中取 max 后再 +1：
    # 只靠 row.version+1 会与历史表撞车（历史已有 v3，而模板行被重建后从 v1 开始），
    # 表现为保存时报 Duplicate entry，报错信息完全看不出是版本号冲突。
    max_hist = (
        await db.execute(
            select(func.max(PromptVersion.version)).where(
                PromptVersion.code == code, PromptVersion.kb_id == kb_id
            )
        )
    ).scalar() or 0
    version = 1 if is_new else max(int(row.version or 0), int(max_hist)) + 1
    version = max(version, int(max_hist) + 1)
    row.version = version

    db.add(
        PromptVersion(
            code=code,
            kb_id=kb_id,
            version=version,
            content=content,
            variables=used,
            note=note,
            created_by=user_id,
        )
    )
    await _trim_versions(db, code, kb_id)
    await db.commit()
    invalidate(code, kb_id if kb_id != GLOBAL_SCOPE else None)

    logger.info("prompt_saved", code=code, kb_id=kb_id, version=row.version)
    return {
        "code": row.code,
        "kb_id": row.kb_id,
        "version": row.version,
        "variables": used,
    }


async def _trim_versions(db: AsyncSession, code: str, kb_id: int) -> None:
    """只保留最近 MAX_VERSIONS 版，避免表无限增长。"""
    ids = (
        await db.execute(
            select(PromptVersion.id)
            .where(PromptVersion.code == code, PromptVersion.kb_id == kb_id)
            .order_by(desc(PromptVersion.version))
        )
    ).scalars().all()
    if len(ids) > MAX_VERSIONS:
        await db.execute(delete(PromptVersion).where(PromptVersion.id.in_(ids[MAX_VERSIONS:])))


async def reset(
    db: AsyncSession, *, code: str, kb_id: int = GLOBAL_SCOPE, user_id: int | None = None
) -> dict[str, Any]:
    """恢复出厂默认。

    不删除模板行，而是把内置内容作为**新版本**写回去。原因有两个：
    1. 删行会让下一次保存从 v1 开始，与历史表已有的 v1 撞唯一约束，直接报错；
    2. "谁在什么时候恢复了默认"本身是有价值的审计线索，删掉就查不到了。
    """
    if code not in DEFAULT_PROMPTS:
        raise AppError(f"未知的提示词标识：{code}", code=ErrorCode.NOT_FOUND, status_code=404)

    exists = (
        await db.execute(
            select(PromptTemplate.id).where(
                PromptTemplate.code == code, PromptTemplate.kb_id == kb_id
            )
        )
    ).scalars().first()
    if exists is None:
        invalidate(code)
        return {"code": code, "kb_id": kb_id, "reset": True, "version": 0}

    saved = await save(
        db,
        code=code,
        content=DEFAULT_PROMPTS[code]["content"],
        kb_id=kb_id,
        note="恢复出厂默认",
        user_id=user_id,
    )
    logger.info("prompt_reset", code=code, kb_id=kb_id, version=saved["version"])
    return {"code": code, "kb_id": kb_id, "reset": True, "version": saved["version"]}


async def list_versions(
    db: AsyncSession, *, code: str, kb_id: int = GLOBAL_SCOPE, limit: int = 30
) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(PromptVersion)
            .where(PromptVersion.code == code, PromptVersion.kb_id == kb_id)
            .order_by(desc(PromptVersion.version))
            .limit(limit)
        )
    ).scalars().all()
    return [
        {
            "version": r.version,
            "content": r.content,
            "variables": list(r.variables or []),
            "note": r.note,
            "created_by": r.created_by,
            "created_at": r.created_at,
        }
        for r in rows
    ]


async def rollback(
    db: AsyncSession,
    *,
    code: str,
    version: int,
    kb_id: int = GLOBAL_SCOPE,
    user_id: int | None = None,
) -> dict[str, Any]:
    """回滚到指定版本。

    注意：回滚不是把版本号改回去，而是把旧内容作为**新版本**提交。
    否则历史会被覆盖，出问题时无法再往前追溯。
    """
    row = (
        await db.execute(
            select(PromptVersion).where(
                PromptVersion.code == code,
                PromptVersion.kb_id == kb_id,
                PromptVersion.version == version,
            )
        )
    ).scalars().first()
    if row is None:
        raise AppError(
            f"版本 v{version} 不存在", code=ErrorCode.NOT_FOUND, status_code=404
        )

    return await save(
        db,
        code=code,
        content=row.content,
        kb_id=kb_id,
        note=f"回滚自 v{version}",
        user_id=user_id,
    )


async def ensure_seed(db: AsyncSession, user_id: int | None = None) -> int:
    """初始化内置提示词到库中（幂等）。已有自定义内容不会被覆盖。"""
    created = 0
    for code, d in DEFAULT_PROMPTS.items():
        exists = (
            await db.execute(
                select(PromptTemplate.id).where(
                    PromptTemplate.code == code, PromptTemplate.kb_id == GLOBAL_SCOPE
                )
            )
        ).scalars().first()
        if exists:
            continue
        db.add(
            PromptTemplate(
                code=code,
                kb_id=GLOBAL_SCOPE,
                name=d["name"],
                content=d["content"],
                variables=list(d["variables"]),
                description=d["description"],
                version=1,
                is_active=True,
                updated_by=user_id,
            )
        )
        db.add(
            PromptVersion(
                code=code,
                kb_id=GLOBAL_SCOPE,
                version=1,
                content=d["content"],
                variables=list(d["variables"]),
                note="初始化内置默认值",
                created_by=user_id,
            )
        )
        created += 1
    if created:
        await db.commit()
        invalidate()
    return created
