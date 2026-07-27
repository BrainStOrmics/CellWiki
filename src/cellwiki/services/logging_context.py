# =============================================================================
# 日志上下文管理 —— 为日志记录注入运行关联信息
# =============================================================================
# 通过 ContextVar 和 logging.Filter 实现跨模块的日志上下文传递，
# 使每条日志都能关联到具体的 AgentRun、线程和请求。
# =============================================================================

"""Logging context management for run correlation and structured logging.

Provides ContextVar-based context propagation and a logging filter that
injects run_id, thread_id, project_id, and request_id into log records.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from contextlib import contextmanager
from typing import Iterator


# ---------------------------------------------------------------------------
# 日志上下文变量
# 使用 ContextVar 实现线程安全和异步安全的上下文传递
# ---------------------------------------------------------------------------
_LOG_CONTEXT: ContextVar[dict[str, str]] = ContextVar("cellwiki_log_context", default={})


@contextmanager
def log_context(**kwargs: str) -> Iterator[None]:
    """Temporarily bind logging context fields.
    
    Usage:
        with log_context(run_id="run_123", thread_id="thread_456"):
            logger.info("Processing request")  # Will include run_id and thread_id
    """
    current = _LOG_CONTEXT.get()
    new_context = {**current, **kwargs}
    token = _LOG_CONTEXT.set(new_context)
    try:
        yield
    finally:
        _LOG_CONTEXT.reset(token)


def get_log_context() -> dict[str, str]:
    """Return the current logging context."""
    return _LOG_CONTEXT.get()


class ContextFilter(logging.Filter):
    """Logging filter that injects context fields into log records.
    
    Adds run_id, thread_id, project_id, and request_id to each log record
    if they are present in the current context.
    """
    
    def filter(self, record: logging.LogRecord) -> bool:
        context = _LOG_CONTEXT.get()
        # Add context fields to the record, defaulting to "-" if not present
        record.run_id = context.get("run_id", "-")
        record.thread_id = context.get("thread_id", "-")
        record.project_id = context.get("project_id", "-")
        record.request_id = context.get("request_id", "-")
        return True


def setup_structured_logging(level: str = "INFO") -> None:
    """Configure root logger with structured format and context filter.
    
    This should be called once at application startup, after basic logging
    is configured. It adds a ContextFilter to all handlers and updates the
    format to include context fields.
    """
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    
    # Add context filter to all handlers
    context_filter = ContextFilter()
    for handler in root.handlers:
        handler.addFilter(context_filter)
        # Update format to include context fields
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s [run:%(run_id)s thread:%(thread_id)s]: %(message)s",
            datefmt="%H:%M:%S"
        )
        handler.setFormatter(formatter)
