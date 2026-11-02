"""认证相关请求/响应模型。"""

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

PASSWORD_PATTERN = re.compile(r"^(?=.*[A-Za-z])(?=.*\d).{8,64}$")


def _validate_password(v: str) -> str:
    if not PASSWORD_PATTERN.match(v):
        raise ValueError("密码需 8~64 位，且同时包含字母和数字")
    return v


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64, examples=["admin"])
    password: str = Field(min_length=6, max_length=64, examples=["Admin@123"])


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="access_token 有效期（秒）")


class RoleBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    name: str


class UserInfo(BaseModel):
    """登录后返回给前端的信息，权限码用于前端动态路由与按钮级控制。"""

    id: int
    username: str
    nickname: str | None = None
    email: str | None = None
    avatar: str | None = None
    is_superuser: bool
    roles: list[RoleBrief] = []
    permissions: list[str] = []


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(min_length=6, max_length=64)
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _check_new(cls, v: str) -> str:
        return _validate_password(v)


class CreateUserRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str
    nickname: str | None = Field(default=None, max_length=64)
    email: str | None = Field(default=None, max_length=128)
    role_codes: list[str] = Field(default_factory=lambda: ["user"])

    @field_validator("password")
    @classmethod
    def _check_pwd(cls, v: str) -> str:
        return _validate_password(v)
