"""API Key 加密存储。

为什么不能明文存：数据库备份、开发机连库、日志误打都会泄露厂商密钥，
而这类密钥通常带账户余额权限，泄露直接等于财产损失。

方案：用 SECRET_KEY 派生 Fernet 对称密钥。优点是不引入额外配置项；
代价是**轮换 SECRET_KEY 会导致已存密钥无法解密**——所以换 key 前必须重新录入模型配置。
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings
from app.core.errors import AppError, ErrorCode
from app.core.logging import get_logger

logger = get_logger(__name__)


def _fernet() -> Fernet:
    digest = hashlib.sha256(settings.secret_key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(plain: str) -> str:
    if not plain:
        return ""
    return _fernet().encrypt(plain.encode("utf-8")).decode("ascii")


def decrypt_secret(cipher: str) -> str:
    if not cipher:
        return ""
    try:
        return _fernet().decrypt(cipher.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        logger.error("api_key_decrypt_failed")
        raise AppError(
            "模型密钥解密失败（SECRET_KEY 可能已更换），请重新录入该模型的 API Key",
            code=ErrorCode.MODEL_NOT_CONFIGURED,
            status_code=500,
        ) from exc


def mask_secret(plain: str, keep: int = 4) -> str:
    """脱敏展示：sk-czaw5abcd... → sk-czaw5****abcd"""
    if not plain:
        return ""
    if len(plain) <= keep * 2:
        return "*" * len(plain)
    return f"{plain[:keep]}****{plain[-keep:]}"
