"""业务枚举。

统一用 StrEnum（str 子类）：既能在代码里做类型约束，
又能被 SQLAlchemy 直接写入 VARCHAR 列，读出来用 `DocStatus(row.status)` 还原，
不需要 MySQL 的 ENUM 类型（加值要 ALTER TABLE，运维不友好）。
"""

from enum import StrEnum


class DocStatus(StrEnum):
    PENDING = "pending"          # 已上传，等待解析
    PARSING = "parsing"          # 解析中
    SPLITTING = "splitting"      # 切片中
    EMBEDDING = "embedding"      # 向量化中
    READY = "ready"              # 可用
    FAILED = "failed"            # 失败
    NO_TEXT_LAYER = "no_text_layer"  # 扫描件/无文本层，需 OCR（当前不支持）


class IngestTaskType(StrEnum):
    PARSE = "parse"
    REINDEX = "reindex"          # 全库或单文档重建
    DELETE = "delete"


class IngestTaskStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELED = "canceled"


class KbMemberRole(StrEnum):
    OWNER = "owner"    # 可上传/删除文档、触发重建、邀请成员；仍不能进后台改全局参数
    VIEWER = "viewer"  # 只能检索与问答


class ChatRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class LlmScene(StrEnum):
    EMBEDDING = "embedding"
    CHAT = "chat"
    RERANK = "rerank"
    QUERY_REWRITE = "query_rewrite"
