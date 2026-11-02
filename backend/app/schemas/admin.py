"""后台管理相关模型（用户、角色、模型配置、系统参数、审计）。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.auth import PASSWORD_PATTERN


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str
    nickname: str | None = Field(default=None, max_length=64)
    email: str | None = Field(default=None, max_length=128)
    phone: str | None = Field(default=None, max_length=32)
    role_codes: list[str] = Field(default_factory=lambda: ["user"])

    @field_validator("password")
    @classmethod
    def _check_pwd(cls, v: str) -> str:
        if not PASSWORD_PATTERN.match(v):
            raise ValueError("密码需 8~64 位，且同时包含字母和数字")
        return v


class UserUpdate(BaseModel):
    nickname: str | None = Field(default=None, max_length=64)
    email: str | None = Field(default=None, max_length=128)
    phone: str | None = Field(default=None, max_length=32)
    is_active: bool | None = None
    role_codes: list[str] | None = None


class ResetPasswordRequest(BaseModel):
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _check_pwd(cls, v: str) -> str:
        if not PASSWORD_PATTERN.match(v):
            raise ValueError("密码需 8~64 位，且同时包含字母和数字")
        return v


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    nickname: str | None = None
    email: str | None = None
    phone: str | None = None
    is_active: bool
    is_superuser: bool
    roles: list[str] = []
    last_login_at: datetime | None = None
    last_login_ip: str | None = None
    locked_until: datetime | None = None
    created_at: datetime


class PermissionOut(BaseModel):
    code: str
    name: str
    group_name: str


class RoleOut(BaseModel):
    id: int
    code: str
    name: str
    description: str | None = None
    is_builtin: bool
    permissions: list[str] = []
    user_count: int = 0


class RoleUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=64)
    description: str | None = None
    permissions: list[str] | None = Field(default=None, description="完整权限码列表（覆盖式）")


# ---------------- 模型配置 ----------------
class ModelConfigIn(BaseModel):
    provider: str = Field(pattern="^(deepseek|mimo|qwen|openai|other)$")
    name: str = Field(min_length=1, max_length=64)
    base_url: str = Field(min_length=1, max_length=255)
    api_key: str = Field(min_length=1, max_length=255)
    model: str = Field(min_length=1, max_length=96)
    max_context: int = Field(default=32768, ge=1024, le=1048576)
    max_output: int = Field(default=4096, ge=256, le=65536)
    supports_json: bool = True
    supports_stream: bool = True
    enabled: bool = True


class ModelConfigUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=64)
    base_url: str | None = Field(default=None, max_length=255)
    api_key: str | None = Field(default=None, max_length=255, description="留空表示不修改")
    model: str | None = Field(default=None, max_length=96)
    max_context: int | None = Field(default=None, ge=1024, le=1048576)
    max_output: int | None = Field(default=None, ge=256, le=65536)
    supports_json: bool | None = None
    supports_stream: bool | None = None
    enabled: bool | None = None


class ModelConfigOut(BaseModel):
    id: int
    provider: str
    name: str
    base_url: str
    api_key_masked: str
    model: str
    max_context: int
    max_output: int
    supports_json: bool
    supports_stream: bool
    enabled: bool
    is_default: bool
    created_at: datetime


class ModelTestResult(BaseModel):
    ok: bool
    latency_ms: int = 0
    reply: str = ""
    error: str = ""
    usage: dict = {}


# ---------------- 系统参数 ----------------
class SettingItem(BaseModel):
    key: str
    value: dict
    description: str | None = None


class SettingUpdate(BaseModel):
    value: dict
    description: str | None = None


# ---------------- 审计与用量 ----------------
class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    operator_id: int | None
    operator_name: str | None
    action: str
    target_type: str | None
    target_id: int | None
    before: dict | None
    after: dict | None
    ip: str | None
    result: str
    created_at: datetime


class UsageStat(BaseModel):
    scene: str
    provider: str
    model: str
    calls: int
    prompt_tokens: int
    completion_tokens: int


class UsageSummary(BaseModel):
    days: int
    total_calls: int
    total_prompt_tokens: int
    total_completion_tokens: int
    items: list[UsageStat] = []
