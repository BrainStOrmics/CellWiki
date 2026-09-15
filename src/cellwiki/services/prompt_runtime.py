"""Per-run prompt metadata consumed by the model-call middleware."""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass


@dataclass(frozen=True)
class PromptRunContext:
    """Stable workspace metadata that belongs before the cached breakpoint."""

    schema_version: int
    schema_contract_hash: str
    transcript_epoch: int
    cache_prefix_hash: str
    cache_mode: str


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
    "PromptRunContext",
    "current_prompt_run_context",
    "reset_prompt_run_context",
    "set_prompt_run_context",
]
