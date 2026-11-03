"""v1 路由汇总。新增业务模块在这里挂载。

健康检查不在此处：它挂在根路径 /health（供 K8s 探针与运维使用），见 app/main.py。
"""

from fastapi import APIRouter

from app.api.v1 import admin, agents, auth, chat, documents, kb, prompts, users

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["认证"])
api_router.include_router(agents.public_router, prefix="/agents", tags=["智能体"])
api_router.include_router(kb.router, prefix="/kb", tags=["知识库"])
api_router.include_router(documents.router, prefix="/kb", tags=["文档"])
api_router.include_router(chat.router, prefix="/chat", tags=["问答"])
api_router.include_router(users.router, tags=["用户与角色"])
api_router.include_router(admin.router, prefix="/admin", tags=["后台配置"])
api_router.include_router(agents.admin_router, prefix="/admin/agents", tags=["智能体"])
api_router.include_router(prompts.router, prefix="/admin/prompts", tags=["提示词"])
