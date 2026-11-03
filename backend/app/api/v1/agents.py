"""智能体接口：后台 CRUD（/admin/agents）与前台可用列表（/agents）。

放同一个文件是因为它们共享 AgentOut 的组装逻辑；拆两个文件反而要在
schema 和 _to_out 上来回跳。前后台的分界由两个 router 实例体现。
"""

from fastapi import APIRouter, Depends

from app.core.deps import CurrentUser, DbSession, require_perm
from app.db.models.chat import AuditLog
from app.schemas.agent import (
    AgentBrief,
    AgentIn,
    AgentOut,
    AgentTestIn,
    AgentTestOut,
    AgentUpdate,
)
from app.services import agent_service
from app.services.llm import get_llm  # noqa: F401  re-export 供 schema 校验提示

admin_router = APIRouter()
public_router = APIRouter()


async def _audit(db, user, action: str, agent_id: int, after: dict) -> None:
    from datetime import datetime

    db.add(
        AuditLog(
            operator_id=user.id,
            operator_name=user.username,
            action=action,
            target_type="agent",
            target_id=agent_id,
            before=None,
            after=after,
            result="ok",
            created_at=datetime.now(),
        )
    )


# ---------------- 前台 ----------------
@public_router.get(
    "",
    response_model=list[AgentBrief],
    summary="我可用的已发布智能体",
    dependencies=[Depends(require_perm("chat:use"))],
)
async def list_public_agents(db: DbSession, user: CurrentUser) -> list[AgentBrief]:
    return await agent_service.list_agents_public(db, user)


# ---------------- 后台 ----------------
@admin_router.get(
    "",
    response_model=list[AgentOut],
    summary="智能体列表（含草稿与用量）",
    dependencies=[Depends(require_perm("config:read"))],
)
async def list_agents(db: DbSession) -> list[AgentOut]:
    return await agent_service.list_agents_admin(db)


@admin_router.post(
    "",
    response_model=AgentOut,
    summary="创建智能体（草稿）",
    dependencies=[Depends(require_perm("config:write"))],
)
async def create_agent(payload: AgentIn, db: DbSession, user: CurrentUser) -> AgentOut:
    out = await agent_service.create_agent(db, user, payload)
    await _audit(db, user, "agent.create", out.id, {"name": out.name})
    await db.commit()
    return out


@admin_router.get(
    "/{agent_id}",
    response_model=AgentOut,
    summary="智能体详情",
    dependencies=[Depends(require_perm("config:read"))],
)
async def get_agent(agent_id: int, db: DbSession) -> AgentOut:
    agent = await agent_service.get_agent(db, agent_id)
    return await agent_service._to_out(db, agent)  # noqa: SLF001  同模块内复用


@admin_router.patch(
    "/{agent_id}",
    response_model=AgentOut,
    summary="修改智能体（已发布的立即生效，审计留痕）",
    dependencies=[Depends(require_perm("config:write"))],
)
async def update_agent(
    agent_id: int, payload: AgentUpdate, db: DbSession, user: CurrentUser
) -> AgentOut:
    out = await agent_service.update_agent(db, agent_id, payload)
    keys = list(payload.model_dump(exclude_unset=True).keys())
    await _audit(db, user, "agent.update", agent_id, {"keys": keys})
    await db.commit()
    return out


@admin_router.delete(
    "/{agent_id}",
    summary="删除智能体（软删，历史会话保留）",
    dependencies=[Depends(require_perm("config:write"))],
)
async def delete_agent(agent_id: int, db: DbSession, user: CurrentUser) -> dict:
    agent = await agent_service.get_agent(db, agent_id)
    await agent_service.delete_agent(db, agent_id)
    await _audit(db, user, "agent.delete", agent_id, {"name": agent.name})
    await db.commit()
    return {"message": "已删除"}


@admin_router.post(
    "/{agent_id}/publish",
    response_model=AgentOut,
    summary="发布 / 下线",
    dependencies=[Depends(require_perm("config:write"))],
)
async def publish_agent(
    agent_id: int, db: DbSession, user: CurrentUser, published: bool = True
) -> AgentOut:
    out = await agent_service.set_publish(db, agent_id, published)
    await _audit(db, user, "agent.publish" if published else "agent.unpublish", agent_id, {})
    await db.commit()
    return out


@admin_router.post(
    "/{agent_id}/test",
    response_model=AgentTestOut,
    summary="按智能体完整配置试跑（真实调用模型，几百 token）",
    dependencies=[Depends(require_perm("config:write"))],
)
async def test_agent(
    agent_id: int, payload: AgentTestIn, db: DbSession, user: CurrentUser
) -> AgentTestOut:
    return await agent_service.test_agent(db, user, agent_id, payload)
