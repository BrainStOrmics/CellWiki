"""Provider wire protocol values shared without importing runtime configuration."""

from __future__ import annotations

from typing import Literal, cast


WIRE_PROTOCOL_CHAT_COMPLETIONS = "chat_completions"
WIRE_PROTOCOL_RESPONSES = "responses"
# 原生 Anthropic Messages API（非 OpenAI 兼容）；工厂在 adapters/anthropic_model.py。
WIRE_PROTOCOL_ANTHROPIC = "anthropic"
WireProtocol = Literal["chat_completions", "responses", "anthropic"]
SUPPORTED_WIRE_PROTOCOLS = frozenset(
    {
        WIRE_PROTOCOL_CHAT_COMPLETIONS,
        WIRE_PROTOCOL_RESPONSES,
        WIRE_PROTOCOL_ANTHROPIC,
    }
)


def normalize_wire_protocol(value: str) -> WireProtocol:
    """Validate the explicit wire protocol without importing provider SDKs."""

    normalized = value.strip().lower()
    if normalized not in SUPPORTED_WIRE_PROTOCOLS:
        supported = ", ".join(sorted(SUPPORTED_WIRE_PROTOCOLS))
        raise ValueError(f"API protocol must be one of: {supported}")
    return cast(WireProtocol, normalized)
