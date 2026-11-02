"""知识库、文档、切片、入库任务模型。"""

from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, PKMixin, SoftDeleteMixin, TimestampMixin
from app.db.models.enums import DocStatus, IngestTaskStatus, IngestTaskType, KbMemberRole


class KnowledgeBase(Base, PKMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "knowledge_bases"

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    owner_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)

    # 向量化配置：一旦入库禁止修改，否则必须全量重建
    embedding_model: Mapped[str] = mapped_column(String(64), nullable=False,
                                                 default="text-embedding-v4")
    embedding_dim: Mapped[int] = mapped_column(Integer, nullable=False, default=1024)
    milvus_collection: Mapped[str] = mapped_column(String(128), nullable=False)

    # 切片与检索参数，结构见 docs/01-技术选型清单.md §2.7
    chunk_config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    retrieve_config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    sensitivity: Mapped[str] = mapped_column(
        String(16), nullable=False, default="normal", comment="normal | confidential（禁入公有云）"
    )
    doc_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    members: Mapped[list["KbMember"]] = relationship(
        back_populates="kb", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (Index("ix_kb_owner", "owner_id", "is_deleted"),)


class KbMember(Base, PKMixin, TimestampMixin):
    __tablename__ = "kb_members"

    kb_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    role: Mapped[KbMemberRole] = mapped_column(
        String(16), nullable=False, default=KbMemberRole.VIEWER, comment="owner | viewer"
    )
    granted_by: Mapped[int | None] = mapped_column(BigInteger)

    kb: Mapped[KnowledgeBase] = relationship(back_populates="members")

    __table_args__ = (Index("uq_kb_member", "kb_id", "user_id", unique=True),)


class Document(Base, PKMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "documents"

    kb_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_ext: Mapped[str] = mapped_column(String(16), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False, comment="MinIO 对象键")
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, comment="用于秒传与去重")

    status: Mapped[DocStatus] = mapped_column(
        String(24), nullable=False, default=DocStatus.PENDING
    )
    error_msg: Mapped[str | None] = mapped_column(Text)
    # 无文本层（扫描件）时置 True，前端必须明确提示，不能"静默成功"
    no_text_layer: Mapped[bool] = mapped_column(default=False, nullable=False)

    page_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 入库时的切片参数快照：重切时可对比差异
    chunk_config_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    created_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)

    chunks: Mapped[list["Chunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_doc_kb_status", "kb_id", "status", "is_deleted"),
        Index("ix_doc_sha", "kb_id", "sha256"),
    )


class Chunk(Base, PKMixin):
    __tablename__ = "chunks"

    doc_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    kb_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="冗余，检索过滤用")
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(LONGTEXT, nullable=False)

    char_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 父子切片：子块指向父块 id，检索子块、喂模型用父块
    parent_id: Mapped[int | None] = mapped_column(BigInteger)
    section_path: Mapped[str | None] = mapped_column(String(512), comment="标题层级路径")

    embedded: Mapped[bool] = mapped_column(default=False, nullable=False, comment="是否已向量化")
    milvus_id: Mapped[int | None] = mapped_column(BigInteger, comment="Milvus 主键")
    meta: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    document: Mapped[Document] = relationship(back_populates="chunks")

    __table_args__ = (
        Index("ix_chunk_doc", "doc_id", "chunk_index", unique=True),
        Index("ix_chunk_embedded", "doc_id", "embedded"),
    )


class IngestTask(Base, PKMixin, TimestampMixin):
    __tablename__ = "ingest_tasks"

    kb_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    doc_id: Mapped[int | None] = mapped_column(BigInteger)
    task_type: Mapped[IngestTaskType] = mapped_column(String(24), nullable=False)
    status: Mapped[IngestTaskStatus] = mapped_column(
        String(24), nullable=False, default=IngestTaskStatus.QUEUED
    )

    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="0-100")
    total_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 断点续跑：记录已处理的页/章节，大文件失败重试不必从头来
    checkpoint: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    error_msg: Mapped[str | None] = mapped_column(Text)
    trace_id: Mapped[str | None] = mapped_column(String(32))
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)

    __table_args__ = (Index("ix_task_kb_status", "kb_id", "status"),)
