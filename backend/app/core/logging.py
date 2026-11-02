"""结构化日志。每条日志带 trace_id，贯穿 前端 → API → Celery → 模型调用。"""

import logging
import sys
import uuid
from contextvars import ContextVar

import structlog

trace_id_var: ContextVar[str] = ContextVar("trace_id", default="-")


def new_trace_id() -> str:
    return uuid.uuid4().hex[:16]


def set_trace_id(tid: str | None = None) -> str:
    tid = tid or new_trace_id()
    trace_id_var.set(tid)
    return tid


def get_trace_id() -> str:
    return trace_id_var.get()


def _add_trace_id(_logger, _method, event_dict: dict) -> dict:
    event_dict.setdefault("trace_id", trace_id_var.get())
    return event_dict


def _supports_color() -> bool:
    """Windows 下 ConsoleRenderer 上色需要 colorama，没装就退化为无色，避免启动即崩。"""
    if not sys.stdout.isatty():
        return False
    if sys.platform == "win32":
        try:
            import colorama  # noqa: F401
        except ImportError:
            return False
    return True


def setup_logging(level: str = "INFO", json_output: bool = False) -> None:
    """初始化日志。开发环境彩色可读，生产环境 JSON 便于采集。"""
    log_level = getattr(logging, level.upper(), logging.INFO)

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
    )
    # 降低第三方库噪音
    for noisy in ("httpx", "httpcore", "pymilvus", "urllib3", "aiomysql"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    renderer = (
        structlog.processors.JSONRenderer(ensure_ascii=False)
        if json_output
        else structlog.dev.ConsoleRenderer(colors=_supports_color())
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S", utc=False),
            _add_trace_id,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = "app"):
    return structlog.get_logger(name)
