"""提示词管理相关请求/响应模型。"""

from datetime import datetime

from pydantic import BaseModel, Field


class PromptOut(BaseModel):
    code: str
    kb_id: int = 0
    name: str
    content: str
    variables: list[str] = Field(default_factory=list)
    description: str | None = None
    version: int = 0
    source: str = "global"
    is_customized: bool = False
    updated_at: datetime | None = None
    updated_by: int | None = None


class PromptUpdate(BaseModel):
    content: str = Field(description="模板正文，变量用 {{name}} 形式")
    name: str | None = Field(default=None, max_length=96)
    description: str | None = Field(default=None, max_length=255)
    note: str | None = Field(default=None, max_length=255, description="变更说明，写入版本历史")


class PromptPreviewIn(BaseModel):
    content: str | None = Field(default=None, description="不传则用当前生效内容")
    values: dict[str, str] = Field(default_factory=dict, description="变量样例值")


class PromptPreviewOut(BaseModel):
    rendered: str
    variables: list[str]
    missing: list[str] = Field(description="模板中声明但未提供值的变量")
    chars: int
    tokens_estimate: int
    version: int


class PromptTestIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    content: str | None = Field(default=None, description="不传则用当前生效提示词")
    kb_id: int | None = Field(default=None, description="提供则真实检索该库作为资料")


class PromptTestOut(BaseModel):
    answer: str
    model: str
    provider: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int
    sources: int = 0
    rendered_system: str = ""
    version: int = 0


class PromptVersionOut(BaseModel):
    version: int
    content: str
    variables: list[str] = Field(default_factory=list)
    note: str | None = None
    created_by: int | None = None
    created_at: datetime | None = None


class PromptVarMeta(BaseModel):
    name: str
    desc: str
