"""全局配置。所有可变参数集中在此，禁止在业务代码里散落魔法值。"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---------- 应用 ----------
    app_name: str = "RAG 知识库系统"
    app_env: Literal["dev", "test", "prod"] = "dev"
    debug: bool = True
    api_v1_prefix: str = "/api/v1"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    # ---------- 安全 ----------
    secret_key: str = "dev-only-change-me"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    bcrypt_rounds: int = 12
    login_max_fail: int = 5
    login_lock_seconds: int = 900

    # ---------- MySQL ----------
    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_user: str = "rag"
    mysql_password: str = "rag_pass"
    mysql_db: str = "rag"
    mysql_pool_size: int = 10
    mysql_max_overflow: int = 20
    mysql_echo: bool = False
    mysql_allow_startup_without_db: bool = True

    # ---------- Redis ----------
    redis_host: str = "127.0.0.1"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: str = ""
    celery_broker_db: int = 1
    celery_backend_db: int = 2

    # ---------- Milvus ----------
    milvus_host: str = "127.0.0.1"
    milvus_port: int = 19530
    milvus_collection: str = "rag_chunks"
    milvus_index_type: str = "HNSW"
    milvus_metric_type: str = "COSINE"
    milvus_vector_dim: int = 1024

    # ---------- MinIO ----------
    minio_endpoint: str = "127.0.0.1:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "rag-docs"
    minio_secure: bool = False

    # ---------- Embedding / Rerank ----------
    dashscope_api_key: str = ""
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    embedding_model: str = "text-embedding-v4"
    embedding_dim: int = 1024
    embedding_batch_size: int = 10
    embedding_concurrency: int = 5
    rerank_enabled: bool = True
    rerank_model: str = "gte-rerank-v2"

    # ---------- 对话模型 ----------
    default_chat_provider: Literal["deepseek", "mimo"] = "deepseek"
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_model: str = "deepseek-chat"
    mimo_api_key: str = ""
    mimo_base_url: str = ""
    mimo_model: str = ""

    # ---------- 检索默认值 ----------
    retrieve_top_k: int = 30
    rerank_top_n: int = 8
    score_threshold: float = 0.2
    chunk_size: int = 512
    chunk_overlap: int = 64

    # ---------- 上传 ----------
    max_file_size_mb: int = 200
    max_kb_total_mb: int = 1024
    allowed_extensions: list[str] = Field(
        default_factory=lambda: ["pdf", "docx", "doc", "md", "txt", "xlsx", "xls", "csv"]
    )
    # celery: 投递给 worker（生产）；inline: 进程内异步执行（本地开发，重启会丢任务）
    ingest_mode: Literal["celery", "inline"] = "celery"

    # ---------- 日志与可观测 ----------
    log_level: str = "INFO"
    log_json: bool = False
    langfuse_enabled: bool = False
    langfuse_host: str = ""
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""

    # ---------- 派生属性 ----------
    @property
    def mysql_dsn(self) -> str:
        return (
            f"mysql+aiomysql://{self.mysql_user}:{self.mysql_password}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_db}?charset=utf8mb4"
        )

    @property
    def mysql_dsn_sync(self) -> str:
        """Alembic 迁移使用同步驱动。"""
        return (
            f"mysql+pymysql://{self.mysql_user}:{self.mysql_password}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_db}?charset=utf8mb4"
        )

    @property
    def redis_url(self) -> str:
        auth = f":{self.redis_password}@" if self.redis_password else ""
        return f"redis://{auth}{self.redis_host}:{self.redis_port}/{self.redis_db}"

    @property
    def is_prod(self) -> bool:
        return self.app_env == "prod"

    @field_validator("secret_key")
    @classmethod
    def _check_secret(cls, v: str) -> str:
        if len(v) < 16:
            raise ValueError("SECRET_KEY 长度不足 16 位，生产环境请使用随机 48 字节字符串")
        return v

    def validate_for_prod(self) -> list[str]:
        """生产环境启动自检，返回致命问题列表。"""
        problems: list[str] = []
        if not self.is_prod:
            return problems
        if "dev-only" in self.secret_key:
            problems.append("SECRET_KEY 仍为开发默认值")
        if not self.dashscope_api_key:
            problems.append("未配置 DASHSCOPE_API_KEY，无法进行向量化")
        if self.default_chat_provider == "deepseek" and not self.deepseek_api_key:
            problems.append("默认对话模型为 deepseek 但未配置 DEEPSEEK_API_KEY")
        if self.default_chat_provider == "mimo" and not self.mimo_api_key:
            problems.append("默认对话模型为 mimo 但未配置 MIMO_API_KEY")
        if self.mysql_allow_startup_without_db:
            problems.append("生产环境不应允许数据库缺失时启动")
        return problems


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
