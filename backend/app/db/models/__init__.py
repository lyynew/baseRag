"""模型汇总。

Alembic 通过 `from app.db.models import *` 发现所有表，新增模型务必在此登记，
否则 autogenerate 会漏表。
"""

from app.db.models.agent import Agent
from app.db.models.auth import Permission, Role, RolePermission, User, UserRole
from app.db.models.chat import (
    AuditLog,
    ChatMessage,
    ChatSession,
    DocumentVersion,
    LlmCallLog,
    ModelConfig,
    SystemSetting,
)
from app.db.models.knowledge import Chunk, Document, IngestTask, KbMember, KnowledgeBase
from app.db.models.prompt import PromptTemplate, PromptVersion

__all__ = [
    # 智能体
    "Agent",
    # 认证与权限
    "User",
    "Role",
    "Permission",
    "UserRole",
    "RolePermission",
    # 知识库
    "KnowledgeBase",
    "KbMember",
    "Document",
    "Chunk",
    "IngestTask",
    # 会话与系统
    "ChatSession",
    "ChatMessage",
    "ModelConfig",
    "LlmCallLog",
    "AuditLog",
    "SystemSetting",
    "DocumentVersion",
    # 提示词
    "PromptTemplate",
    "PromptVersion",
]
