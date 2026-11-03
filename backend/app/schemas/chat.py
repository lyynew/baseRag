"""问答相关模型。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SessionCreate(BaseModel):
    agent_id: int = Field(description="所属智能体，知识库由智能体决定，用户不选")
    title: str | None = Field(default=None, max_length=100)


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    kb_ids: list[int]
    agent_id: int | None = None
    chat_provider: str | None = None
    chat_model: str | None = None
    message_count: int
    created_at: datetime
    updated_at: datetime


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    session_id: int
    seq: int
    role: str
    content: str
    citations: list = []
    provider: str | None = None
    model: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    ttft_ms: int | None = None
    feedback: int | None = None
    created_at: datetime


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class Citation(BaseModel):
    index: int
    chunk_id: int
    doc_id: int
    score: float = 0
    snippet: str = ""


class AskResponse(BaseModel):
    message_id: int
    session_id: int
    answer: str
    citations: list[Citation] = []
    model: str
    usage: dict = {}
    latency_ms: int = 0
    retrieval: dict = {}


class FeedbackRequest(BaseModel):
    feedback: int | None = Field(default=None, ge=-1, le=1, description="1 赞 / -1 踩 / null 取消")
