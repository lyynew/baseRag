"""提示词模板与版本快照。

为什么单独建表而不是丢进 system_settings（KV）：
1. 提示词要按知识库覆盖（同一 code，不同 kb 各一份），KV 表达不了；
2. 提示词要能回滚——它是效果最敏感的配置，改一个标点都可能让引用准确率掉一截；
3. 要有版本号写入 `llm_call_logs`，事后才能回答"这条答得差是因为换了提示词还是换了模型"。

kb_id 用 0 表示全局而不是 NULL：MySQL 的唯一索引对 NULL 不去重，
用 NULL 会出现同一 code 存出多条"全局"记录，而且不报错。
"""

from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PKMixin, TimestampMixin

# 全局模板的 kb_id 哨兵值
GLOBAL_SCOPE = 0


class PromptTemplate(Base, PKMixin, TimestampMixin):
    """当前生效的提示词。同一 code 同一作用域只有一行。"""

    __tablename__ = "prompt_templates"

    code: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="模板标识，如 system_qa"
    )
    kb_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=GLOBAL_SCOPE, comment="0=全局，其余为知识库覆盖"
    )
    name: Mapped[str] = mapped_column(String(96), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # 声明模板里用到的变量，保存时据此校验，避免 {{contxt}} 这种拼错静默留存
    variables: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    description: Mapped[str | None] = mapped_column(String(255))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_by: Mapped[int | None] = mapped_column(BigInteger)

    __table_args__ = (
        UniqueConstraint("code", "kb_id", name="uk_prompt_code_kb"),
        Index("ix_prompt_code", "code"),
    )


class PromptVersion(Base, PKMixin):
    """每次保存/回滚写入一份完整快照，用于对比与回滚。"""

    __tablename__ = "prompt_versions"

    code: Mapped[str] = mapped_column(String(64), nullable=False)
    kb_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=GLOBAL_SCOPE)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    variables: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    note: Mapped[str | None] = mapped_column(String(255), comment="变更说明")
    created_by: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("code", "kb_id", "version", name="uk_prompt_ver"),
        Index("ix_prompt_ver_created", "created_at"),
    )


__all__ = ["PromptTemplate", "PromptVersion", "GLOBAL_SCOPE"]
