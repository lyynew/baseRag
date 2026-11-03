"""知识库与文档相关模型。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ChunkConfigIn(BaseModel):
    """切片参数。默认值必须与 app/services/chunker.py 的 ChunkConfig 保持一致——
    两处不一致会导致"后台配了 400，实际按 512 切"这种极难排查的问题。"""

    strategy: str = Field(
        default="recursive",
        pattern="^(recursive|markdown_header|fixed|delimiter)$",
        description="delimiter 表示严格按自定义标记切分",
    )
    chunk_size: int = Field(default=512, ge=100, le=4000, description="单位：字符")
    chunk_overlap: int = Field(default=64, ge=0, le=1000)
    # 只合并真正的碎片（如孤立标题行）。设过大会把正常小节吞进上一块，导致章节归属错乱
    min_chunk_size: int = Field(default=30, ge=0, le=1000)

    # 结构块保护：代码/表格/列表/引用整体不切碎
    keep_table_intact: bool = True
    keep_code_intact: bool = True
    keep_list_intact: bool = True
    keep_quote_intact: bool = True
    # 结构块允许超出 chunk_size 的倍数，超过才内部分片
    block_max_ratio: float = Field(default=2.0, ge=1.0, le=5.0)
    # 标题注入与相邻小块合并
    keep_heading: bool = True
    merge_adjacent: bool = True

    # 自定义标记策略
    delimiter: str | None = Field(
        default=None, max_length=64, description="如 <!-- chunk --> 或 ## "
    )
    keep_delimiter: bool = True

    separators: list[str] | None = None


class RetrieveConfigIn(BaseModel):
    top_k: int = Field(default=30, ge=1, le=100)
    rerank_top_n: int = Field(default=8, ge=1, le=30)
    score_threshold: float = Field(default=0.2, ge=0, le=1)
    rerank_enabled: bool = True


class KbCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = None
    sensitivity: str = Field(default="normal", pattern="^(normal|confidential)$")
    chunk_config: ChunkConfigIn = Field(default_factory=ChunkConfigIn)
    retrieve_config: RetrieveConfigIn = Field(default_factory=RetrieveConfigIn)


class KbUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = None
    sensitivity: str | None = Field(default=None, pattern="^(normal|confidential)$")
    chunk_config: ChunkConfigIn | None = None
    retrieve_config: RetrieveConfigIn | None = None


class KbOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    owner_id: int
    embedding_model: str
    embedding_dim: int
    chunk_config: dict
    retrieve_config: dict
    sensitivity: str
    doc_count: int
    chunk_count: int
    total_size_bytes: int
    created_at: datetime
    updated_at: datetime
    # 当前用户在库里的角色：owner / viewer / admin（管理员的全局视角）
    my_role: str | None = None


class KbMemberAdd(BaseModel):
    user_id: int
    role: str = Field(default="viewer", pattern="^(owner|viewer)$")


class KbMemberOut(BaseModel):
    user_id: int
    username: str
    nickname: str | None
    role: str


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kb_id: int
    name: str
    file_ext: str
    file_size: int
    status: str
    error_msg: str | None
    no_text_layer: bool
    page_count: int
    char_count: int
    chunk_count: int
    created_at: datetime
    updated_at: datetime


class IngestTaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kb_id: int
    doc_id: int | None
    task_type: str
    status: str
    progress: int
    total_items: int
    processed_items: int
    error_msg: str | None
    started_at: datetime | None
    finished_at: datetime | None


class UploadResult(BaseModel):
    document: DocumentOut
    task: IngestTaskOut
    duplicated: bool = False


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    top_k: int | None = Field(default=None, ge=1, le=50)
    rerank: bool = True


class SearchHit(BaseModel):
    chunk_id: int
    doc_id: int
    doc_name: str | None = None
    content: str
    score: float
    vector_score: float | None = None
    section_path: str | None = None


class SearchResponse(BaseModel):
    query: str
    hits: list[SearchHit]
    vector_hits: int
    rerank_applied: bool
    tokens: int = 0
