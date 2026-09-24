"""Per-run prompt metadata consumed by the model-call middleware."""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from datetime import datetime
from queue import SimpleQueue


@dataclass(frozen=True)
class ModelRequestFingerprint:
    """Opaque request-prefix comparison data; contains no prompt content."""

    request_hash: str
    request_item_count: int
    previous_request_hash: str | None
    previous_request_item_count: int
    common_prefix_item_count: int
    previous_request_is_prefix: bool
    request_started_at: datetime


@dataclass(frozen=True)
class PromptRunContext:
    """Per-run metadata shared with model middleware and runtime accounting."""

    schema_version: int
    schema_contract_hash: str
    transcript_epoch: int
    cache_prefix_hash: str
    cache_mode: str
    thread_id: str = ""
    request_fingerprint_sink: SimpleQueue[ModelRequestFingerprint] = field(
        default_factory=SimpleQueue, compare=False, repr=False
    )


_CURRENT: ContextVar[PromptRunContext | None] = ContextVar(
    "cellwiki_prompt_run_context",
    default=None,
)


def set_prompt_run_context(context: PromptRunContext) -> Token[PromptRunContext | None]:
    return _CURRENT.set(context)


def current_prompt_run_context() -> PromptRunContext | None:
    return _CURRENT.get()


def reset_prompt_run_context(token: Token[PromptRunContext | None]) -> None:
    _CURRENT.reset(token)


__all__ = [
    "ModelRequestFingerprint",
    "PromptRunContext",
    "current_prompt_run_context",
    "reset_prompt_run_context",
    "set_prompt_run_context",
]
