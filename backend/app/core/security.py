"""密码哈希与 JWT。

选择直接用 bcrypt 库而不是 passlib：passlib 1.7.4 与 bcrypt 4.x 存在已知兼容告警，
且项目已不再是维护活跃状态，直接调用 bcrypt 更可控。
"""

from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import bcrypt
import jwt

from app.core.config import settings
from app.core.errors import AppError, ErrorCode

TokenType = Literal["access", "refresh"]

# bcrypt 只处理前 72 字节，超长密码需先校验，避免"密码被静默截断"
BCRYPT_MAX_BYTES = 72


def hash_password(password: str) -> str:
    raw = password.encode("utf-8")
    if len(raw) > BCRYPT_MAX_BYTES:
        raise AppError(
            "密码过长（超过 72 字节），请使用更短的密码",
            code=ErrorCode.VALIDATION_ERROR,
            status_code=422,
        )
    return bcrypt.hashpw(raw, bcrypt.gensalt(rounds=settings.bcrypt_rounds)).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8")[:BCRYPT_MAX_BYTES], hashed.encode())
    except (ValueError, TypeError):
        return False


def _create_token(subject: str | int, token_type: TokenType, expires: timedelta) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + expires).timestamp()),
        "jti": f"{token_type}-{subject}-{int(now.timestamp() * 1000)}",
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def create_access_token(user_id: int) -> str:
    return _create_token(
        user_id, "access", timedelta(minutes=settings.access_token_expire_minutes)
    )


def create_refresh_token(user_id: int) -> str:
    return _create_token(user_id, "refresh", timedelta(days=settings.refresh_token_expire_days))


def decode_token(token: str, expected_type: TokenType) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
    except jwt.ExpiredSignatureError as exc:
        raise AppError(
            "登录已过期，请重新登录", code=ErrorCode.TOKEN_EXPIRED, status_code=401
        ) from exc
    except jwt.InvalidTokenError as exc:
        raise AppError("凭证无效", code=ErrorCode.TOKEN_INVALID, status_code=401) from exc

    if payload.get("type") != expected_type:
        raise AppError("凭证类型错误", code=ErrorCode.TOKEN_INVALID, status_code=401)
    return payload


def token_remaining_seconds(payload: dict[str, Any]) -> int:
    exp = int(payload.get("exp", 0))
    return max(0, exp - int(datetime.now(UTC).timestamp()))
