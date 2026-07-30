"""Shared runtime value types that do not import the runtime manager."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TypeAlias

from langgraph.types import Command

from cellwiki.domain.runs import AgentEventType


AgentInput: TypeAlias = str | list[dict[str, str]] | Command | None


@dataclass(frozen=True)
class RuntimeSignalLike:
    type: AgentEventType
    message: str = ""
    progress: int | None = None
    data: dict[str, Any] = field(default_factory=dict)
    model_call_id: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    tool_calls: int = 0
