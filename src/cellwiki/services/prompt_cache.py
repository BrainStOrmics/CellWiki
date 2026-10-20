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
# 压缩预留：摘要输出 20,000 + 缓冲 13,000。绝对值、不随窗口缩放——
# 与业界通用 Agent（Claude Code 20K 输出 + 13K 缓冲）同口径。
COMPACTION_RESERVE_TOKENS = 33_000
SUMMARY_OUTPUT_TOKENS = 20_000
POST_COMPACT_SAFETY_TOKENS = 4_000
DEFAULT_RETAINED_TOKENS = 32_768


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
    retained_tokens: int = 8_536
    summary_output_tokens: int = SUMMARY_OUTPUT_TOKENS
    summary_input_tokens: int = 45_536

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
    retained_tokens: int = DEFAULT_RETAINED_TOKENS,
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
    # 绝对值预留：窗口 − 33K（20K 摘要输出 + 13K 缓冲）。下限 1,024 只防御
    # 极小窗口把阈值压成负数。最小档 200K 下阈值为 167K。
    compact_threshold = max(1_024, int(effective_limit - COMPACTION_RESERVE_TOKENS))
    summary_output_tokens = SUMMARY_OUTPUT_TOKENS
    summary_input_tokens = max(1_024, effective_limit - summary_output_tokens)
    # post-compact prompt = summary + retained tail。tail 必须给摘要输出和下一次
    # 调用的安全缓冲留出空间；窗口很小时自动退化为 summary-only。
    retained_cap = max(
        0,
        compact_threshold - summary_output_tokens - POST_COMPACT_SAFETY_TOKENS,
    )
    resolved_retained_tokens = max(0, min(retained_tokens, retained_cap))

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
        retained_tokens=resolved_retained_tokens,
        summary_output_tokens=summary_output_tokens,
        summary_input_tokens=summary_input_tokens,
    )


__all__ = [
    "COMPACTION_RESERVE_TOKENS",
    "CacheMode",
    "DEFAULT_RETAINED_TOKENS",
    "FALLBACK_MODEL_INPUT_TOKENS",
    "POST_COMPACT_SAFETY_TOKENS",
    "PromptCachePolicy",
    "SUMMARY_OUTPUT_TOKENS",
    "resolve_prompt_cache_policy",
]
