"""智能体相关请求/响应模型。"""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.db.models.agent import AGENT_PROMPT_KEYS


class AgentIn(BaseModel):
    name: str = Field(min_length=1, max_length=96)
    description: str | None = None
    emoji: str = Field(default="🤖", max_length=8)
    kb_ids: list[int] = Field(min_length=1, description="至少绑定一个知识库")
    provider: str | None = Field(default=None, max_length=32, description="空 = 全局默认")
    model: str | None = Field(default=None, max_length=96)
    prompt_overrides: dict[str, str] = Field(default_factory=dict)
    retrieve_config: dict = Field(default_factory=dict)
    gen_settings: dict = Field(default_factory=dict)
    is_published: bool = False
    is_public: bool = True

    @field_validator("prompt_overrides")
    @classmethod
    def _check_prompt_keys(cls, v: dict[str, str]) -> dict[str, str]:
        bad = [k for k in v if k not in AGENT_PROMPT_KEYS]
        if bad:
            allowed = "、".join(AGENT_PROMPT_KEYS)
            raise ValueError(f"未知的提示词标识：{'、'.join(bad)}，允许：{allowed}")
        return v


class AgentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=96)
    description: str | None = None
    emoji: str | None = Field(default=None, max_length=8)
    kb_ids: list[int] | None = None
    provider: str | None = None
    model: str | None = None
    prompt_overrides: dict[str, str] | None = None
    retrieve_config: dict | None = None
    gen_settings: dict | None = None
    is_published: bool | None = None
    is_public: bool | None = None

    @field_validator("prompt_overrides")
    @classmethod
    def _check_prompt_keys(cls, v: dict[str, str] | None) -> dict[str, str] | None:
        if v is None:
            return v
        bad = [k for k in v if k not in AGENT_PROMPT_KEYS]
        if bad:
            allowed = "、".join(AGENT_PROMPT_KEYS)
            raise ValueError(f"未知的提示词标识：{'、'.join(bad)}，允许：{allowed}")
        return v


class AgentOut(BaseModel):
    id: int
    name: str
    description: str | None
    emoji: str
    kb_ids: list[int]
    kb_names: list[str] = Field(default_factory=list)
    provider: str | None
    model: str | None
    prompt_overrides: dict[str, str]
    retrieve_config: dict
    gen_settings: dict
    is_published: bool
    is_public: bool
    session_count: int = 0
    message_count: int = 0
    owner_id: int
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AgentBrief(BaseModel):
    """前台列表用，不暴露内部配置。"""

    id: int
    name: str
    description: str | None
    emoji: str
    kb_count: int
    model: str | None = None
    is_public: bool


class AgentTestIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class AgentTestOut(BaseModel):
    answer: str
    model: str
    provider: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int
    sources: int
    citations: list[dict] = Field(default_factory=list)
    # 实际使用的 system 前若干字，便于确认覆盖生效
    system_prompt_head: str = ""
