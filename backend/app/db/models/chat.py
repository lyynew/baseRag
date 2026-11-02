"""会话、消息、模型配置、审计与调用日志。"""

from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PKMixin, SoftDeleteMixin, TimestampMixin
from app.db.models.enums import ChatRole


class ChatSession(Base, PKMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "chat_sessions"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="新对话")
    kb_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list, comment="绑定的知识库")
    chat_provider: Mapped[str | None] = mapped_column(String(32))
    chat_model: Mapped[str | None] = mapped_column(String(64))
    # 滚动摘要：历史超阈值时把最老的几轮压成摘要，避免 token 无限增长
    summary: Mapped[str | None] = mapped_column(Text)
    summary_upto_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    message_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (Index("ix_session_user", "user_id", "is_deleted", "updated_at"),)


class ChatMessage(Base, PKMixin):
    __tablename__ = "chat_messages"

    session_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False, comment="会话内递增序号")
    role: Mapped[ChatRole] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(LONGTEXT, nullable=False)

    citations: Mapped[list] = mapped_column(JSON, nullable=False, default=list,
                                            comment="[{chunk_id, doc_id, page, score}]")
    # 检索快照：没有它就无法判断"是没检到"还是"检到了但模型没用"
    retrieval_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    provider: Mapped[str | None] = mapped_column(String(32))
    model: Mapped[str | None] = mapped_column(String(64))
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ttft_ms: Mapped[int | None] = mapped_column(Integer, comment="首 token 耗时")
    feedback: Mapped[int | None] = mapped_column(comment="1 赞 -1 踩")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("session_id", "seq", name="uq_msg_session_seq"),
        Index("ix_msg_session", "session_id", "created_at"),
    )


class ModelConfig(Base, PKMixin, TimestampMixin):
    """模型配置。后台可切换 DeepSeek / MiMo，无需改代码或重启。"""

    __tablename__ = "model_configs"

    provider: Mapped[str] = mapped_column(String(32), nullable=False, comment="deepseek | mimo")
    name: Mapped[str] = mapped_column(String(64), nullable=False, comment="展示名")
    base_url: Mapped[str] = mapped_column(String(255), nullable=False)
    api_key_enc: Mapped[str] = mapped_column(String(512), nullable=False, comment="加密存储")
    model: Mapped[str] = mapped_column(String(96), nullable=False)
    max_context: Mapped[int] = mapped_column(Integer, nullable=False, default=32768)
    max_output: Mapped[int] = mapped_column(Integer, nullable=False, default=4096)
    supports_json: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    supports_stream: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (UniqueConstraint("provider", "model", name="uq_model_provider_model"),)


class LlmCallLog(Base, PKMixin):
    """所有模型调用的审计与成本统计。按模型分别累计，不同 tokenizer 不可混算。"""

    __tablename__ = "llm_call_logs"

    scene: Mapped[str] = mapped_column(String(24), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(96), nullable=False)
    ref_type: Mapped[str | None] = mapped_column(String(32))
    ref_id: Mapped[int | None] = mapped_column(BigInteger)
    user_id: Mapped[int | None] = mapped_column(BigInteger)

    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 提示词归因：回答质量出问题时，要能区分「换了模型」还是「改了提示词」
    prompt_code: Mapped[str | None] = mapped_column(String(64))
    prompt_version: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ok")
    error_msg: Mapped[str | None] = mapped_column(String(512))
    trace_id: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_llm_log_created", "created_at"),)


class AuditLog(Base, PKMixin):
    """后台操作审计。改切片参数会触发全量重建并产生费用，必须可追溯。"""

    __tablename__ = "audit_logs"

    operator_id: Mapped[int | None] = mapped_column(BigInteger)
    operator_name: Mapped[str | None] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64), nullable=False, comment="如 kb.update_config")
    target_type: Mapped[str | None] = mapped_column(String(32))
    target_id: Mapped[int | None] = mapped_column(BigInteger)
    before: Mapped[dict | None] = mapped_column(JSON)
    after: Mapped[dict | None] = mapped_column(JSON)
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(255))
    result: Mapped[str] = mapped_column(String(16), nullable=False, default="ok")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_audit_created", "created_at"),)


class SystemSetting(Base, TimestampMixin):
    """全局参数（KV）。前台后台读取，避免改配置要重启。"""

    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(96), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, nullable=False)
    description: Mapped[str | None] = mapped_column(String(255))
    updated_by: Mapped[int | None] = mapped_column(BigInteger)


class DocumentVersion(Base):
    """预留：文档版本。当前默认覆盖式更新，此表暂不启用。"""

    __tablename__ = "document_versions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    doc_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )


__all__ = [
    "ChatSession",
    "ChatMessage",
    "ModelConfig",
    "LlmCallLog",
    "AuditLog",
    "SystemSetting",
    "DocumentVersion",
]
