"""Provider-aware prompt cache policy for the v2 model transcript."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from cellwiki.domain.model_provider import (
    WIRE_PROTOCOL_ANTHROPIC,
    WIRE_PROTOCOL_RESPONSES,
    normalize_wire_protocol,
)

CacheMode = Literal["off", "implicit", "explicit"]

_OFFICIAL_OPENAI_HOSTS = {"api.openai.com"}
FALLBACK_MODEL_INPUT_TOKENS = 65_536


@dataclass(frozen=True)
class PromptCachePolicy:
    """Resolved cache behavior for one coordinator model."""

    mode: CacheMode
    protocol: str
    max_breakpoints: int
    provider_native_compaction: bool
    compact_threshold: int
    breakpoint_key: str
    model_input_tokens: int
    input_window_source: Literal["configured", "fallback"]
    effective_context_limit: int

    @property
    def tool_result_breakpoints(self) -> int:
        return max(0, self.max_breakpoints - 1) if self.mode == "explicit" else 0

    def allows_explicit_breakpoints(self) -> bool:
        return self.mode == "explicit"


def _normalized_mode(value: Any, default: CacheMode) -> CacheMode:
    raw = str(value or "auto").strip().lower()
    if raw == "auto":
        return default
    if raw not in {"off", "implicit", "explicit"}:
        raise ValueError("cache_mode must be one of auto, off, implicit, explicit")
    return raw  # type: ignore[return-value]


def _official_openai(base_url: str) -> bool:
    if not base_url:
        return True
    try:
        from urllib.parse import urlparse

        host = (urlparse(base_url).hostname or "").lower()
    except Exception:  # noqa: BLE001 - malformed providers fail elsewhere
        return False
    return host in _OFFICIAL_OPENAI_HOSTS


def _supports_native_compaction(model_id: str, base_url: str) -> bool:
    if not _official_openai(base_url):
        return False
    lowered = (model_id or "").strip().lower()
    return lowered.startswith(("gpt-5.3", "gpt-5.6", "gpt-6"))


def resolve_prompt_cache_policy(
    *,
    protocol: str,
    model_id: str,
    base_url: str = "",
    request_overrides: dict[str, Any] | None = None,
    model_input_tokens: int | None = None,
    fallback_input_tokens: int = FALLBACK_MODEL_INPUT_TOKENS,
    context_max_tokens: int = 512_000,
    auto_compact_ratio: float = 0.8,
) -> PromptCachePolicy:
    """Resolve cache mode and the single compaction threshold for one run.

    The model name is intentionally not consulted for window resolution. A
    provider catalog entry declares its input capacity; a legacy configuration
    may do the same through ``OPENAI_MAX_INPUT_TOKENS``. When neither is
    present, the policy uses one conservative process-wide fallback.
    """

    protocol = normalize_wire_protocol(protocol)
    overrides = dict(request_overrides or {})
    if protocol == WIRE_PROTOCOL_RESPONSES:
        default_mode: CacheMode = (
            "explicit"
            if _official_openai(base_url)
            and (model_id or "").strip().lower().startswith(("gpt-5.6", "gpt-6"))
            else "implicit"
        )
    elif protocol == WIRE_PROTOCOL_ANTHROPIC:
        default_mode = "explicit"
    else:
        default_mode = "implicit"
    mode = _normalized_mode(overrides.pop("cache_mode", "auto"), default_mode)

    if fallback_input_tokens <= 0:
        raise ValueError("fallback_input_tokens must be positive")
    if context_max_tokens <= 0:
        raise ValueError("context_max_tokens must be positive")
    if not 0.0 < auto_compact_ratio <= 1.0:
        raise ValueError("auto_compact_ratio must be between 0 and 1")

    input_window_source: Literal["configured", "fallback"] = (
        "configured" if model_input_tokens is not None else "fallback"
    )
    resolved_input_window = (
        model_input_tokens
        if model_input_tokens is not None
        else fallback_input_tokens
    )
    if resolved_input_window <= 0:
        raise ValueError("model_input_tokens must be positive")
    effective_limit = min(context_max_tokens, resolved_input_window)
    compact_threshold = max(1_024, int(effective_limit * auto_compact_ratio))

    native_compaction = (
        mode != "off"
        and protocol == WIRE_PROTOCOL_RESPONSES
        and _supports_native_compaction(model_id, base_url)
    )
    if mode != "off" and protocol == WIRE_PROTOCOL_RESPONSES:
        breakpoint_key = "prompt_cache_breakpoint" if mode == "explicit" else ""
    elif mode != "off" and protocol == WIRE_PROTOCOL_ANTHROPIC:
        breakpoint_key = "cache_control" if mode == "explicit" else ""
    else:
        breakpoint_key = ""

    return PromptCachePolicy(
        mode=mode,
        protocol=protocol,
        max_breakpoints=4 if mode == "explicit" else 0,
        provider_native_compaction=native_compaction,
        compact_threshold=compact_threshold,
        breakpoint_key=breakpoint_key,
        model_input_tokens=resolved_input_window,
        input_window_source=input_window_source,
        effective_context_limit=effective_limit,
    )


__all__ = [
    "CacheMode",
    "FALLBACK_MODEL_INPUT_TOKENS",
    "PromptCachePolicy",
    "resolve_prompt_cache_policy",
]
