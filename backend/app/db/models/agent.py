"""智能体模型：把模型、知识库、提示词、检索参数封装成一个可发布的整体。

设计要点：
1. prompt_overrides 存 JSON 而不是复用 prompt_templates——大部分智能体用全局提示词
   就够，为少数覆盖者建版本表是过度设计；真要回滚，改回来再保存一次即可。
2. provider/model 为空表示"跟随全局默认"，后台切换默认模型时智能体自动跟上。
3. is_published 是前台可见的唯一开关；删除是软删，历史会话仍可回看。
"""

from sqlalchemy import JSON, BigInteger, Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PKMixin, SoftDeleteMixin, TimestampMixin

# 提示词覆盖允许的 key，与 prompt_service.DEFAULT_PROMPTS 对齐
AGENT_PROMPT_KEYS = ("system_qa", "direct_answer", "query_rewrite")


class Agent(Base, PKMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "agents"

    name: Mapped[str] = mapped_column(String(96), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    emoji: Mapped[str] = mapped_column(String(8), nullable=False, default="🤖")

    # 绑定的知识库；提问时按此检索，用户不再自行选库
    kb_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    # 对话模型；空 = 跟随全局默认
    provider: Mapped[str | None] = mapped_column(String(32))
    model: Mapped[str | None] = mapped_column(String(96))

    # 提示词覆盖 {"system_qa": "..."}；key 校验见 AGENT_PROMPT_KEYS
    prompt_overrides: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    # 检索参数：非空覆盖知识库级配置
    retrieve_config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # 生成参数
    gen_settings: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # 全员可用。二期扩展 agent_members 按人授权
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    owner_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)

    __table_args__ = ()
