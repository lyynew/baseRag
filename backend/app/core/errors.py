"""统一错误处理。

约定：
- 业务异常一律抛 AppError 子类，不直接 raise HTTPException（除框架层）
- 前端永远只看到 {code, message, trace_id}，看不到 Python 堆栈
- 每个错误都可在日志中按 trace_id 检索
"""

from enum import StrEnum
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.logging import get_logger, get_trace_id

logger = get_logger(__name__)


class ErrorCode(StrEnum):
    # 通用
    OK = "OK"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    NOT_FOUND = "NOT_FOUND"
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
    CONFLICT = "CONFLICT"
    TOO_MANY_REQUESTS = "TOO_MANY_REQUESTS"

    # 认证 1xxx
    UNAUTHORIZED = "UNAUTHORIZED"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    TOKEN_INVALID = "TOKEN_INVALID"
    BAD_CREDENTIALS = "BAD_CREDENTIALS"
    ACCOUNT_LOCKED = "ACCOUNT_LOCKED"
    ACCOUNT_DISABLED = "ACCOUNT_DISABLED"

    # 权限 2xxx
    FORBIDDEN = "FORBIDDEN"

    # 知识库 3xxx
    KB_NOT_FOUND = "KB_NOT_FOUND"
    KB_QUOTA_EXCEEDED = "KB_QUOTA_EXCEEDED"
    DOC_NOT_FOUND = "DOC_NOT_FOUND"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    UNSUPPORTED_FILE_TYPE = "UNSUPPORTED_FILE_TYPE"
    NO_TEXT_LAYER = "NO_TEXT_LAYER"          # 扫描件无文本层
    PARSE_FAILED = "PARSE_FAILED"
    REINDEX_REQUIRED = "REINDEX_REQUIRED"

    # 模型 4xxx
    MODEL_NOT_CONFIGURED = "MODEL_NOT_CONFIGURED"
    MODEL_CALL_FAILED = "MODEL_CALL_FAILED"
    MODEL_RATE_LIMITED = "MODEL_RATE_LIMITED"
    EMBEDDING_DIM_MISMATCH = "EMBEDDING_DIM_MISMATCH"

    # 检索 5xxx
    RETRIEVE_FAILED = "RETRIEVE_FAILED"


class AppError(Exception):
    """业务异常基类。"""

    code: ErrorCode = ErrorCode.INTERNAL_ERROR
    status_code: int = 500
    message: str = "服务内部错误"

    def __init__(
        self,
        message: str | None = None,
        *,
        code: ErrorCode | None = None,
        status_code: int | None = None,
        detail: Any = None,
    ) -> None:
        self.message = message or self.message
        self.code = code or self.code
        self.status_code = status_code or self.status_code
        self.detail = detail
        super().__init__(self.message)


class NotFoundError(AppError):
    code = ErrorCode.NOT_FOUND
    status_code = 404
    message = "资源不存在"


class ConflictError(AppError):
    code = ErrorCode.CONFLICT
    status_code = 409
    message = "资源冲突"


class ValidationError(AppError):
    code = ErrorCode.VALIDATION_ERROR
    status_code = 422
    message = "参数校验失败"


class UnauthorizedError(AppError):
    code = ErrorCode.UNAUTHORIZED
    status_code = 401
    message = "未登录或登录已失效"


class ForbiddenError(AppError):
    code = ErrorCode.FORBIDDEN
    status_code = 403
    message = "没有权限执行该操作"


class RateLimitError(AppError):
    code = ErrorCode.TOO_MANY_REQUESTS
    status_code = 429
    message = "请求过于频繁，请稍后再试"


class ModelCallError(AppError):
    code = ErrorCode.MODEL_CALL_FAILED
    status_code = 502
    message = "模型服务调用失败"


def _payload(code: str, message: str, detail: Any = None) -> dict[str, Any]:
    body: dict[str, Any] = {"code": code, "message": message, "trace_id": get_trace_id()}
    if detail is not None:
        body["detail"] = detail
    return body


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        logger.warning(
            "app_error",
            code=str(exc.code),
            status=exc.status_code,
            message=exc.message,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=_payload(str(exc.code), exc.message, exc.detail),
        )

    # FastAPI/Starlette 自带的 404、405 等也要统一成 {code, message, trace_id}
    from starlette.exceptions import HTTPException as StarletteHTTPException

    _http_code_map = {
        400: (ErrorCode.VALIDATION_ERROR, "请求参数错误"),
        401: (ErrorCode.UNAUTHORIZED, "未登录或登录已失效"),
        403: (ErrorCode.FORBIDDEN, "没有权限执行该操作"),
        404: (ErrorCode.NOT_FOUND, "接口或资源不存在"),
        405: (ErrorCode.METHOD_NOT_ALLOWED, "请求方法不被允许"),
        429: (ErrorCode.TOO_MANY_REQUESTS, "请求过于频繁，请稍后再试"),
    }

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code, default_msg = _http_code_map.get(
            exc.status_code, (ErrorCode.INTERNAL_ERROR, "请求处理失败")
        )
        message = exc.detail if isinstance(exc.detail, str) and exc.detail else default_msg
        return JSONResponse(
            status_code=exc.status_code,
            content=_payload(str(code), message),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {"field": ".".join(str(x) for x in e["loc"][1:]), "msg": e["msg"]}
            for e in exc.errors()
        ]
        logger.info("validation_error", errors=errors)
        return JSONResponse(
            status_code=422,
            content=_payload(str(ErrorCode.VALIDATION_ERROR), "参数校验失败", errors),
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(
            "unhandled_error",
            path=str(request.url.path),
            method=request.method,
            error_type=type(exc).__name__,
        )
        return JSONResponse(
            status_code=500,
            content=_payload(str(ErrorCode.INTERNAL_ERROR), "服务内部错误，请联系管理员"),
        )
