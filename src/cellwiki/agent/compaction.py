# -*- coding: utf-8 -*-
"""CellWiki compaction middleware: watermark check, LLM summary, overflow recovery.

This middleware owns the compaction *decision* for the coordinator graph. The
runtime remains the only *writer* of the model transcript: the middleware
reports a compaction through the custom stream channel, and the runtime persists
the summary plus retained tail as the new transcript boundary. This module never
touches SQLite.

Contract (2026-09-22 alignment work; see the accepted design proposal):

- the watermark is checked before every model call (``before_model``);
- watermark = ``count_tokens_approximately(use_usage_metadata_scaling=True)``
  over the graph messages: it anchors on the most recent AI message's reported
  ``usage_metadata`` and estimates the delta after it;
- threshold = ``effective_limit - COMPACTION_RESERVE_TOKENS`` (absolute
  reserve, never a window ratio);
- the summary is one nested LLM call on the coordinator model, tagged
  ``cellwiki:summarizer`` so the runtime strips it from the outward stream;
- the deterministic six-category summary is the fallback; three consecutive
  LLM failures trip a per-thread breaker until one succeeds again;
- provider overflow errors compact and retry the step once, and the graph
  state is only rewritten when the retry succeeds;
- provider-native compaction models skip this middleware entirely.
"""
from __future__ import annotations

from dataclasses import dataclass
import logging
import uuid
from typing import Any

from langchain.agents.middleware import AgentMiddleware, ExtendedModelResponse
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.messages.modifier import RemoveMessage
from langchain_core.messages.utils import count_tokens_approximately
from langgraph.types import Command

from cellwiki.services.model_transcript import (
    PRUNED_TOOL_PLACEHOLDER,
    PRUNE_PROTECTED_TOOLS,
)
from cellwiki.services.prompt_layers import calibration_ratio, summarize_excerpts

logger = logging.getLogger(__name__)

REMOVE_ALL_MESSAGES = "__remove_all__"
SUMMARIZER_TAG = "cellwiki:summarizer"
SUMMARIZER_ROLE = "summarizer"
SUMMARY_MAX_OUTPUT_TOKENS = 20_000
SUMMARY_INPUT_SOFT_LIMIT = 380_000
SUMMARY_PTL_ATTEMPTS = 3
COMPACTION_FAILURE_LIMIT = 3
SUMMARY_MESSAGE_ID = "compaction-summary"
SUMMARY_MESSAGE_PREFIX = "[Compacted context]"
SUMMARY_RESUME_INSTRUCTION = (
    "Resume from the Next steps section. Do not restart completed discovery "
    "unless the summary explicitly marks it incomplete."
)
MICROCOMPACT_KEEP_RECENT = 5
MICROCOMPACT_MIN_CHARS = 100
MICROCOMPACT_MIN_REPLACEMENTS = 20
POST_COMPACT_TOOL_RESULT_CHAR_LIMIT = 12_000


@dataclass(frozen=True)
class MessageGroup:
    """One indivisible prompt group used for safe compaction boundaries."""

    start: int
    end: int
    tokens: float


@dataclass(frozen=True)
class MicrocompactReplacement:
    """One tool result rewritten to the stable placeholder."""

    tool_call_id: str
    name: str
    text: str


@dataclass(frozen=True)
class CompactionOutcome:
    """Result of one full summary compaction."""

    messages: list[BaseMessage]
    tail: list[BaseMessage]
    summary: str
    source: str
    usage: dict[str, int]
    boundary_type: str
    forced: bool
    pre_tokens: int
    post_tokens: int
    tail_tokens: int
    retained_groups: int
    ptl_attempts: int

SUMMARY_SYSTEM_PROMPT = (
    "You compact an agent conversation into a structured handoff summary. "
    "Respond in the language of the conversation. Keep every section header, "
    "even when empty. Preserve exact file paths, page ids, commit subjects, "
    "commands, error strings and identifiers verbatim. Do not mention the "
    "summarization process."
)

SUMMARY_TEMPLATE = """Output exactly the Markdown structure below and keep the section order.

## Objective
## Constraints and preferences
## Completed (pages changed, commits)
## In progress
## Blocked and open
## Key decisions
## Next steps
## Evidence and file paths

Rules:
- Keep every section, even when empty (write "(none)").
- Long-lived instructions from the user must be carried over verbatim, not paraphrased.
- Prefer terse bullets over prose.
- Preserve exact path/symbol/commit/identifier strings.
"""

SHORTER_HINT = "\nYour previous answer was truncated: produce a shorter version that fits.\n"

UPDATE_RULES = """The <previous-summary> is the authoritative baseline for everything before the conversation above. Merge it with the new conversation:

- Carry forward objectives, constraints, user directives, decisions and open threads from the previous summary even when the new conversation does not mention them.
- Where the conversation conflicts with the previous summary, the conversation wins: state the corrected fact and drop the old claim.
- Move finished work from "In progress" to "Completed".
- Update "Objective" and "Next steps" to reflect the current state.
- Nothing dropped from the previous summary can be recovered later: only drop what is finished and no longer needed.
"""

OVERFLOW_HINTS = (
    "context length",
    "context_length_exceeded",
    "prompt is too long",
    "prompt_too_long",
    "too many tokens",
    "maximum context",
    "max context",
    "exceeds the context window",
    "input is too long",
    "reduce the length",
)

_TRUNCATION_REASONS = {"max_tokens", "length", "max_output_tokens"}


def is_overflow_error(error: BaseException) -> bool:
    """Classify a provider error as a context-window overflow.

    Tool-pairing 400s (the 2026-09-16 incident class) are explicitly excluded:
    a transcript-structure error must never trigger a compaction retry.
    """

    code = ""
    for attr in ("code", "status_code_retry", "body"):
        value = getattr(error, attr, None)
        if value is not None:
            code += f" {value}"
    text = f"{code} {error}".lower()
    if "tool_calls" in text or "tool_call_id" in text:
        return False
    return any(hint in text for hint in OVERFLOW_HINTS)


def _text_of(message: Any) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                for key in ("text", "content"):
                    value = block.get(key)
                    if isinstance(value, str):
                        parts.append(value)
        return "\n".join(parts)
    return ""


def _serialize_for_summary(messages: list[BaseMessage], *, aggressive: bool = False) -> str:
    """Render the compacted prefix for the summarizer prompt.

    Recent tool results stay verbatim; older ones collapse to a placeholder
    because tool output dominates byte volume while handoff facts live in user
    and assistant text plus tool_call arguments. ``aggressive`` keeps no tool
    results and truncates each message, for the retry after an overflow.
    """

    lines: list[str] = []
    tool_results = [m for m in messages if isinstance(m, ToolMessage)]
    kept_ids = set() if aggressive else {id(m) for m in tool_results[-3:]}
    for message in messages:
        role = getattr(message, "type", "unknown")
        if isinstance(message, ToolMessage):
            name = getattr(message, "name", None) or "tool"
            if id(message) in kept_ids:
                lines.append(f"[tool result: {name}]\n{_text_of(message)}")
            else:
                lines.append(f"[old tool result elided: {name}]")
            continue
        if isinstance(message, AIMessage):
            text = _text_of(message)
            calls = getattr(message, "tool_calls", None) or []
            rendered_calls = ", ".join(
                f"{call.get('name')}({call.get('args')})"
                for call in calls
                if isinstance(call, dict)
            )
            if rendered_calls:
                text = (
                    f"{text}\n[tool calls: {rendered_calls}]"
                    if text
                    else f"[tool calls: {rendered_calls}]"
                )
            if aggressive:
                text = text[:4_000]
            lines.append(f"[assistant]\n{text}")
            continue
        text = _text_of(message)
        if aggressive:
            text = text[:2_000]
        lines.append(f"[{role}]\n{text}")
    return "\n\n".join(lines)


def summary_prompt_text(
    messages: list[BaseMessage],
    previous_summary: str | None,
    *,
    aggressive: bool = False,
    shorter: bool = False,
) -> str:
    body = _serialize_for_summary(messages, aggressive=aggressive)
    if previous_summary:
        prompt = (
            f"<conversation>\n{body}\n</conversation>\n\n"
            f"<previous-summary>\n{previous_summary}\n</previous-summary>\n\n"
            f"{SUMMARY_TEMPLATE}\n{UPDATE_RULES}"
        )
    else:
        prompt = f"<conversation>\n{body}\n</conversation>\n\n{SUMMARY_TEMPLATE}"
    if shorter:
        prompt += SHORTER_HINT
    return prompt


def summarize_calibration(measured: int, messages: list[BaseMessage]) -> float:
    """Measured/estimated ratio used to cost each retained record.

    Reuses the existing clamping contract (0.5–4.0); a missing measurement
    yields 1.0, i.e. the plain estimate.
    """

    if measured <= 0 or not messages:
        return 1.0
    estimate = count_tokens_approximately(messages)
    return calibration_ratio(measured, estimate)


def current_watermark(messages: list[BaseMessage]) -> int:
    """Anchor + delta watermark over the graph messages."""

    if not messages:
        return 0
    return count_tokens_approximately(messages, use_usage_metadata_scaling=True)


def message_groups(
    messages: list[BaseMessage],
    *,
    calibration: float = 1.0,
) -> list[MessageGroup]:
    """Group a message chain without splitting tool calls from their results.

    Every non-tool message starts a group; all immediately following tool results
    stay in that group. A leading orphan tool result is retained in the first
    group so it can never become the start of a safe tail.
    """

    if not messages:
        return []
    boundaries = [
        index for index, message in enumerate(messages) if not isinstance(message, ToolMessage)
    ]
    if not boundaries or boundaries[0] != 0:
        boundaries.insert(0, 0)
    groups: list[MessageGroup] = []
    for position, start in enumerate(boundaries):
        end = boundaries[position + 1] if position + 1 < len(boundaries) else len(messages)
        tokens = sum(
            count_tokens_approximately([messages[index]])
            for index in range(start, end)
        ) * max(0.01, calibration)
        groups.append(MessageGroup(start=start, end=end, tokens=tokens))
    return groups


def find_tail_start(
    messages: list[BaseMessage],
    retained_tokens: int,
    *,
    calibration: float = 1.0,
) -> int:
    """Pick the newest complete message groups that fit the retained budget.

    Assistant messages and their following tool results are one indivisible
    group. The tail may therefore start with an assistant message, but never
    with an orphan tool result. Zero means either the whole history fits or no
    complete group fits; callers that already crossed the watermark treat zero
    as a summary-only compaction.
    """

    if not messages:
        return 0
    groups = message_groups(messages, calibration=calibration)
    used = 0.0
    start = len(messages)
    for group in reversed(groups):
        if used + group.tokens > retained_tokens:
            if start == len(messages):
                return 0
            break
        start = group.start
        used += group.tokens
    return start if start > 0 else 0


def build_compacted_messages(
    messages: list[BaseMessage],
    summary: str,
    *,
    retained_tokens: int,
    calibration: float = 1.0,
) -> tuple[list[BaseMessage], list[BaseMessage]]:
    """Build the add_messages replacement list plus the retained tail."""

    tail_start = find_tail_start(messages, retained_tokens, calibration=calibration)
    summary_message = HumanMessage(
        id=SUMMARY_MESSAGE_ID,
        content=(
            f"{SUMMARY_MESSAGE_PREFIX}\n{SUMMARY_RESUME_INSTRUCTION}\n\n{summary}"
        ),
    )
    tail = list(messages[tail_start:]) if tail_start > 0 else []
    return [RemoveMessage(id=REMOVE_ALL_MESSAGES), summary_message, *tail], tail


def estimate_messages_tokens(
    messages: list[BaseMessage],
    *,
    calibration: float = 1.0,
) -> int:
    """Estimate a rewritten message view with the measured/estimated ratio."""

    if not messages:
        return 0
    return int(
        round(
            count_tokens_approximately(messages, use_usage_metadata_scaling=False)
            * max(0.01, calibration)
        )
    )


def microcompact_messages(
    messages: list[BaseMessage],
    *,
    keep_recent: int = MICROCOMPACT_KEEP_RECENT,
    min_replacements: int = 1,
) -> tuple[list[BaseMessage], list[MicrocompactReplacement]]:
    """Clear old tool results without changing message count or call pairing."""

    tool_indices = [
        index for index, message in enumerate(messages) if isinstance(message, ToolMessage)
    ]
    candidates = [
        index
        for index in tool_indices
        if str(getattr(messages[index], "name", "") or "") not in PRUNE_PROTECTED_TOOLS
    ]
    to_clear = candidates[:-keep_recent] if keep_recent > 0 else candidates
    if not to_clear:
        return messages, []
    compacted = list(messages)
    replacements: list[MicrocompactReplacement] = []
    for index in to_clear:
        message = messages[index]
        if not isinstance(message, ToolMessage) or len(_text_of(message)) <= MICROCOMPACT_MIN_CHARS:
            continue
        if _text_of(message) == PRUNED_TOOL_PLACEHOLDER:
            continue
        compacted[index] = message.model_copy(update={"content": PRUNED_TOOL_PLACEHOLDER})
        replacements.append(
            MicrocompactReplacement(
                tool_call_id=str(getattr(message, "tool_call_id", "") or ""),
                name=str(getattr(message, "name", "") or "tool"),
                text=PRUNED_TOOL_PLACEHOLDER,
            )
        )
    if len(replacements) < max(1, min_replacements):
        return messages, []
    return compacted, replacements


def bound_post_compact_tool_results(
    messages: list[BaseMessage],
    *,
    limit: int = POST_COMPACT_TOOL_RESULT_CHAR_LIMIT,
) -> list[BaseMessage]:
    """Keep recent tool context useful without letting it consume the whole tail."""

    bounded = list(messages)
    for index, message in enumerate(messages):
        if not isinstance(message, ToolMessage):
            continue
        text = _text_of(message)
        if len(text) <= limit:
            continue
        head = max(0, int(limit * 0.75))
        tail = max(0, limit - head)
        replacement = (
            f"{text[:head]}\n\n"
            f"[tool result trimmed for compaction tail: {len(text)} chars total; "
            f"full result remains in the run audit]\n\n"
            f"{text[-tail:] if tail else ''}"
        )
        bounded[index] = message.model_copy(update={"content": replacement})
    return bounded


def serialize_tail_records(tail: list[BaseMessage]) -> list[dict[str, Any]]:
    """Serialize retained tail messages into transcript record dicts.

    The runtime persists these verbatim after the new compaction boundary, so
    the next run replays exactly what this run's model saw (cache-first
    invariant). Only user/assistant/tool messages are retained: the summary
    message is persisted separately as the boundary itself.
    """

    records: list[dict[str, Any]] = []
    for message in tail:
        if isinstance(message, ToolMessage):
            records.append(
                {
                    "kind": "tool_result",
                    "role": "tool",
                    "content": {
                        "text": _text_of(message),
                        "tool_call_id": getattr(message, "tool_call_id", None) or None,
                        "name": getattr(message, "name", None) or "tool",
                    },
                    "tool_call_id": getattr(message, "tool_call_id", None) or None,
                    "name": getattr(message, "name", None) or "tool",
                }
            )
            continue
        if isinstance(message, AIMessage):
            calls = getattr(message, "tool_calls", None) or []
            records.append(
                {
                    "kind": "assistant",
                    "role": "assistant",
                    "content": {
                        "text": _text_of(message),
                        "tool_calls": [
                            {
                                "name": str(call.get("name") or ""),
                                "args": call.get("args") or {},
                                "id": str(call.get("id") or ""),
                            }
                            for call in calls
                            if isinstance(call, dict)
                        ],
                    },
                }
            )
            continue
        text = _text_of(message)
        if not text:
            continue
        records.append({"kind": "user", "role": "user", "content": {"text": text}})
    return records


def latest_summary_text(messages: list[BaseMessage]) -> str | None:
    """Find the most recent compaction summary carried in the message list."""

    def summary_body(text: str) -> str:
        return (
            text.removeprefix(SUMMARY_MESSAGE_PREFIX)
            .strip()
            .removeprefix(SUMMARY_RESUME_INSTRUCTION)
            .strip()
        )

    for message in messages:
        if getattr(message, "id", None) == SUMMARY_MESSAGE_ID:
            text = _text_of(message)
            if text:
                return summary_body(text)
        text = _text_of(message)
        if text.startswith(SUMMARY_MESSAGE_PREFIX):
            return summary_body(text)
    return None


def _usage_of(response: Any) -> dict[str, int]:
    metadata = getattr(response, "usage_metadata", None) or {}
    if not isinstance(metadata, dict):
        return {}
    usage: dict[str, int] = {}
    for source, target in (
        ("input_tokens", "input_tokens"),
        ("output_tokens", "output_tokens"),
        ("total_tokens", "total_tokens"),
    ):
        value = metadata.get(source)
        if isinstance(value, int) and value:
            usage[target] = value
    details = metadata.get("input_token_details")
    if isinstance(details, dict):
        cached = details.get("cache_read")
        if isinstance(cached, int) and cached:
            usage["cached_input_tokens"] = cached
    return usage


class CellWikiCompactionMiddleware(AgentMiddleware):
    """Watermark check, LLM summarization and provider-overflow recovery."""

    def __init__(
        self,
        *,
        model: Any,
        threshold: int,
        retained_tokens: int,
        summary_output_tokens: int = SUMMARY_MAX_OUTPUT_TOKENS,
        summary_input_tokens: int = SUMMARY_INPUT_SOFT_LIMIT,
        microcompact_min_replacements: int = MICROCOMPACT_MIN_REPLACEMENTS,
        effective_context_limit: int = 0,
        window_source: str = "fallback",
        provider_native: bool = False,
        baseline_provider: Any = None,
    ) -> None:
        super().__init__()
        self.model = model
        self.threshold = threshold
        self.retained_tokens = retained_tokens
        self.summary_output_tokens = max(1_024, summary_output_tokens)
        self.summary_input_tokens = max(
            1_024,
            min(SUMMARY_INPUT_SOFT_LIMIT, summary_input_tokens),
        )
        self.microcompact_min_replacements = max(1, microcompact_min_replacements)
        self.effective_context_limit = effective_context_limit
        self.window_source = window_source
        self.provider_native = provider_native
        # Optional callable(thread_id) -> last measured prompt tokens. The graph
        # state only carries usage metadata for AI messages produced inside the
        # current run; the cross-run measurement recorded by the runtime keeps
        # the watermark honest on the first call of a run.
        self.baseline_provider = baseline_provider
        # Per-thread consecutive summarizer failures; trips the deterministic
        # breaker until one LLM summary succeeds again.
        self._failure_counts: dict[str, int] = {}

    # -- summarizer ------------------------------------------------------

    def _invoke_summarizer(self, prompt: str) -> Any:
        bound: Any = self.model
        try:
            bound = self.model.bind(max_tokens=self.summary_output_tokens)
        except Exception:  # noqa: BLE001 - model may not support binding limits
            logger.debug("summarizer max_tokens binding unsupported", exc_info=True)
        return bound.invoke(
            [
                SystemMessage(content=SUMMARY_SYSTEM_PROMPT),
                HumanMessage(content=prompt),
            ],
            config={
                "tags": [SUMMARIZER_TAG],
                "metadata": {"cellwiki_role": SUMMARIZER_ROLE},
            },
        )

    def _summary_prompt_for_budget(
        self,
        messages: list[BaseMessage],
        previous: str | None,
        *,
        aggressive: bool,
        shorter: bool,
    ) -> str:
        """Keep the summarizer prompt within the model's remaining input budget."""

        working = list(messages)
        prompt = summary_prompt_text(
            working,
            previous,
            aggressive=aggressive,
            shorter=shorter,
        )
        while self._prompt_tokens(prompt) > self.summary_input_tokens:
            groups = message_groups(working)
            if len(groups) <= 1:
                break
            working = working[groups[0].end :]
            prompt = summary_prompt_text(
                working,
                previous,
                aggressive=aggressive,
                shorter=shorter,
            )
        if self._prompt_tokens(prompt) > self.summary_input_tokens:
            prompt = summary_prompt_text(
                working,
                previous,
                aggressive=True,
                shorter=shorter,
            )
        if self._prompt_tokens(prompt) > self.summary_input_tokens:
            opening = "<conversation>\n"
            start = prompt.find(opening)
            end = prompt.find("</conversation>", start + len(opening))
            if start >= 0 and end >= 0:
                prefix = prompt[: start + len(opening)]
                suffix = prompt[end:]
                room = max(
                    200,
                    self.summary_input_tokens * 4 - len(prefix) - len(suffix),
                )
                body = _serialize_for_summary(working, aggressive=True)
                if len(body) > room:
                    head = room // 4
                    tail = max(0, room - head)
                    body = (
                        f"{body[:head]}\n[...older summary input omitted...]\n"
                        f"{body[-tail:] if tail else ''}"
                    )
                prompt = f"{prefix}{body}{suffix}"
        return prompt

    @staticmethod
    def _prompt_tokens(prompt: str) -> int:
        return max(1, len(prompt) // 4)

    def _summarize(
        self,
        messages: list[BaseMessage],
        previous: str | None,
        failure_key: str,
    ) -> tuple[str, str, dict[str, int], int]:
        """Return (summary, source, usage, prompt-too-long attempts)."""

        failures = self._failure_counts.get(failure_key, 0)
        ptl_attempts = 0
        if failures < COMPACTION_FAILURE_LIMIT:
            working = list(messages)
            aggressive = False
            shorter = False
            transient_retry = False
            for attempt in range(1, SUMMARY_PTL_ATTEMPTS + 1):
                prompt = self._summary_prompt_for_budget(
                    working,
                    previous,
                    aggressive=aggressive,
                    shorter=shorter,
                )
                try:
                    response = self._invoke_summarizer(prompt)
                except Exception as error:  # noqa: BLE001 - fallback below
                    logger.warning(
                        "summarizer call failed (attempt %d): %s", attempt, error
                    )
                    if is_overflow_error(error):
                        ptl_attempts += 1
                        groups = message_groups(working)
                        if len(groups) > 1 and attempt < SUMMARY_PTL_ATTEMPTS:
                            working = working[groups[0].end :]
                            aggressive = True
                            continue
                    if not transient_retry and attempt < SUMMARY_PTL_ATTEMPTS:
                        transient_retry = True
                        continue
                    break
                text = _text_of(response).strip()
                metadata = getattr(response, "response_metadata", None) or {}
                stop_reason = str(
                    metadata.get("stop_reason") or metadata.get("finish_reason") or ""
                ).lower()
                usage = _usage_of(response)
                if text and stop_reason not in _TRUNCATION_REASONS:
                    self._failure_counts.pop(failure_key, None)
                    return text, "llm", usage, ptl_attempts
                logger.warning(
                    "summarizer output unusable (attempt %d, stop_reason=%s, chars=%d)",
                    attempt,
                    stop_reason or "?",
                    len(text),
                )
                if attempt < SUMMARY_PTL_ATTEMPTS:
                    shorter = stop_reason in _TRUNCATION_REASONS
                    aggressive = aggressive or is_overflow_error(
                        RuntimeError(stop_reason or "empty")
                    )
                    if aggressive:
                        ptl_attempts += 1
                        groups = message_groups(working)
                        if len(groups) > 1:
                            working = working[groups[0].end :]
                    continue
                break
            self._failure_counts[failure_key] = failures + 1
            logger.warning(
                "summarizer falling back to deterministic summary (consecutive failures=%d)",
                failures + 1,
            )
        excerpts = [f"{getattr(m, 'type', '?')}: {_text_of(m)[:400]}" for m in messages]
        summary = summarize_excerpts(excerpts) or "## Objective\n- Continue the active run."
        return summary, "deterministic", {}, ptl_attempts

    # -- helpers ---------------------------------------------------------

    def _emit_custom_signal(
        self,
        kind: str,
        payload: dict[str, Any],
        runtime: Any = None,
    ) -> None:
        writer = getattr(runtime, "stream_writer", None)
        if writer is None:
            try:
                from langgraph.config import get_stream_writer

                writer = get_stream_writer()
            except Exception:  # noqa: BLE001 - the custom channel is best-effort
                logger.debug("custom stream writer unavailable", exc_info=True)
                return
        try:
            writer({"kind": kind, **payload})
        except Exception:  # noqa: BLE001 - the custom channel is best-effort
            logger.debug("custom stream write failed", exc_info=True)

    def _emit_compaction_signal(self, payload: dict[str, Any], runtime: Any = None) -> None:
        self._emit_custom_signal("context_compaction", payload, runtime)

    def _thread_id(self, runtime: Any) -> str:
        context = getattr(runtime, "context", None)
        thread_id = getattr(context, "thread_id", None)
        if thread_id:
            return str(thread_id)
        config = getattr(runtime, "config", None)
        if isinstance(config, dict):
            configurable = config.get("configurable") or {}
            if isinstance(configurable, dict):
                return str(configurable.get("thread_id") or "default")
        return "default"

    def _baseline_floor(self, runtime: Any) -> int:
        if self.baseline_provider is None:
            return 0
        try:
            value = self.baseline_provider(self._thread_id(runtime))
        except Exception:  # noqa: BLE001 - a missing baseline must not break the run
            return 0
        return int(value or 0)

    def _compact_now(
        self,
        messages: list[BaseMessage],
        *,
        reason: str,
        watermark: int,
        failure_key: str,
        compaction_id: str,
        runtime: Any = None,
    ) -> CompactionOutcome:
        calibration = summarize_calibration(watermark, messages)
        previous = latest_summary_text(messages)
        summary, source, usage, ptl_attempts = self._summarize(
            messages,
            previous,
            failure_key,
        )
        working, _replacements = microcompact_messages(messages)
        working = bound_post_compact_tool_results(working)
        new_messages, tail = build_compacted_messages(
            working,
            summary,
            retained_tokens=self.retained_tokens,
            calibration=calibration,
        )
        new_messages, tail = self._shrink_post_compact(
            new_messages,
            tail,
            calibration=calibration,
        )
        tail_tokens = estimate_messages_tokens(tail, calibration=calibration)
        post_tokens = estimate_messages_tokens(new_messages[1:], calibration=calibration)
        groups = message_groups(tail, calibration=calibration)
        boundary_type = self._boundary_type(tail)
        forced = not tail and len(message_groups(messages)) > 1
        self._emit_compaction_signal(
            {
                "phase": "completed",
                "compaction_id": compaction_id,
                "reason": reason,
                "summary_source": source,
                "summary": summary,
                "summary_usage": usage,
                "tail": serialize_tail_records(tail),
                "retained_messages": len(tail),
                "retained_groups": len(groups),
                "boundary_type": boundary_type,
                "forced": forced,
                "pre_tokens": watermark,
                "post_tokens": post_tokens,
                "tail_tokens": tail_tokens,
                "estimated_tokens": watermark,
                "threshold": self.threshold,
                "effective_context_limit": self.effective_context_limit,
                "window_source": self.window_source,
                "ptl_attempts": ptl_attempts,
            },
            runtime,
        )
        return CompactionOutcome(
            messages=new_messages,
            tail=tail,
            summary=summary,
            source=source,
            usage=usage,
            boundary_type=boundary_type,
            forced=forced,
            pre_tokens=watermark,
            post_tokens=post_tokens,
            tail_tokens=tail_tokens,
            retained_groups=len(groups),
            ptl_attempts=ptl_attempts,
        )

    def _shrink_post_compact(
        self,
        messages: list[BaseMessage],
        tail: list[BaseMessage],
        *,
        calibration: float,
    ) -> tuple[list[BaseMessage], list[BaseMessage]]:
        """Drop whole tail groups, then cap the summary, until post < threshold."""

        summary_message = messages[1]
        current_tail = list(tail)
        while current_tail:
            candidate = [messages[0], summary_message, *current_tail]
            if estimate_messages_tokens(candidate[1:], calibration=calibration) < self.threshold:
                return candidate, current_tail
            groups = message_groups(current_tail, calibration=calibration)
            if len(groups) <= 1:
                current_tail = []
                break
            current_tail = current_tail[groups[1].start :]
        candidate = [messages[0], summary_message]
        if estimate_messages_tokens(candidate[1:], calibration=calibration) >= self.threshold:
            max_chars = max(
                512,
                int((self.threshold * 4) / max(0.01, calibration)) - 128,
            )
            content = _text_of(summary_message)
            if len(content) > max_chars:
                content = content[:max_chars] + "\n[summary truncated to fit context budget]"
                summary_message = summary_message.model_copy(update={"content": content})
        return [messages[0], summary_message], []

    @staticmethod
    def _boundary_type(tail: list[BaseMessage]) -> str:
        if not tail:
            return "summary_only"
        first = tail[0]
        if isinstance(first, ToolMessage):
            return "invalid_tool_tail"
        if isinstance(first, AIMessage) and getattr(first, "tool_calls", None):
            return "assistant_group"
        if isinstance(first, AIMessage):
            return "assistant"
        if isinstance(first, HumanMessage):
            return "user"
        return "message_group"

    # -- middleware hooks ------------------------------------------------

    def before_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        if self.provider_native:
            return None
        messages = list(state.get("messages") or [])
        watermark = max(current_watermark(messages), self._baseline_floor(runtime))
        if watermark <= self.threshold:
            return None
        calibration = summarize_calibration(watermark, messages)
        compacted, replacements = microcompact_messages(
            messages,
            min_replacements=self.microcompact_min_replacements,
        )
        if replacements:
            microcompact_tokens = estimate_messages_tokens(
                compacted,
                calibration=calibration,
            )
            if microcompact_tokens < self.threshold:
                self._emit_custom_signal(
                    "context_microcompact",
                    {
                        "pre_tokens": watermark,
                        "post_tokens": microcompact_tokens,
                        "replacements": [
                            {
                                "tool_call_id": replacement.tool_call_id,
                                "name": replacement.name,
                                "text": replacement.text,
                            }
                            for replacement in replacements
                        ],
                        "threshold": self.threshold,
                    },
                    runtime,
                )
                return {
                    "messages": [
                        RemoveMessage(id=REMOVE_ALL_MESSAGES),
                        *compacted,
                    ]
                }
        compaction_id = f"cmp_{uuid.uuid4().hex}"
        self._emit_compaction_signal(
            {
                "phase": "started",
                "compaction_id": compaction_id,
                "reason": "threshold",
                "pre_tokens": watermark,
                "estimated_tokens": watermark,
                "threshold": self.threshold,
                "effective_context_limit": self.effective_context_limit,
                "window_source": self.window_source,
            },
            runtime,
        )
        outcome = self._compact_now(
            messages,
            reason="threshold",
            watermark=watermark,
            failure_key=self._thread_id(runtime),
            compaction_id=compaction_id,
            runtime=runtime,
        )
        if not outcome.messages:
            return None
        return {"messages": outcome.messages}

    async def abefore_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        return self.before_model(state, runtime)

    def _compact_for_overflow(self, request: Any, error: Exception) -> tuple[Any, list[BaseMessage]]:
        """Compact the request in place and return (retry_request, tail)."""

        messages = list(request.messages)
        watermark = current_watermark(messages)
        compaction_id = f"cmp_{uuid.uuid4().hex}"
        self._emit_compaction_signal(
            {
                "phase": "started",
                "compaction_id": compaction_id,
                "reason": "overflow",
                "pre_tokens": watermark,
                "estimated_tokens": watermark,
                "threshold": self.threshold,
                "effective_context_limit": self.effective_context_limit,
                "window_source": self.window_source,
            }
        )
        outcome = self._compact_now(
            messages,
            reason="overflow",
            watermark=watermark,
            failure_key="default",
            compaction_id=compaction_id,
            runtime=request.runtime,
        )
        logger.info("compact-after-overflow retry (retained=%d)", len(outcome.tail))
        if not outcome.messages:
            return None, []
        return request.override(messages=outcome.messages[1:]), outcome.tail

    def wrap_model_call(self, request: Any, handler: Any) -> Any:
        try:
            return handler(request)
        except Exception as error:  # noqa: BLE001 - re-raised unless overflow
            if self.provider_native or not is_overflow_error(error):
                raise
            retry_request, tail = self._compact_for_overflow(request, error)
            if not retry_request:
                raise error
            try:
                response = handler(retry_request)
            except Exception:  # noqa: BLE001 - the original overflow wins
                raise error from None
            command: Command = Command(
                update={"messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES), *retry_request.messages]}
            )
            return ExtendedModelResponse(model_response=response, command=command)

    async def awrap_model_call(self, request: Any, handler: Any) -> Any:
        try:
            return await handler(request)
        except Exception as error:  # noqa: BLE001 - re-raised unless overflow
            if self.provider_native or not is_overflow_error(error):
                raise
            messages = list(request.messages)
            watermark = current_watermark(messages)
            compaction_id = f"cmp_{uuid.uuid4().hex}"
            self._emit_compaction_signal(
                {
                    "phase": "started",
                    "compaction_id": compaction_id,
                    "reason": "overflow",
                    "pre_tokens": watermark,
                    "estimated_tokens": watermark,
                    "threshold": self.threshold,
                    "effective_context_limit": self.effective_context_limit,
                    "window_source": self.window_source,
                }
            )
            outcome = self._compact_now(
                messages,
                reason="overflow",
                watermark=watermark,
                failure_key=self._thread_id(request.runtime),
                compaction_id=compaction_id,
                runtime=request.runtime,
            )
            logger.info("compact-after-overflow retry (retained=%d)", len(outcome.tail))
            if not outcome.messages:
                raise error
            retry_request = request.override(messages=outcome.messages[1:])
            try:
                response = await handler(retry_request)
            except Exception:  # noqa: BLE001 - the original overflow wins
                raise error from None
            command: Command = Command(
                update={
                    "messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES), *retry_request.messages]
                }
            )
            return ExtendedModelResponse(model_response=response, command=command)


__all__ = [
    "COMPACTION_FAILURE_LIMIT",
    "REMOVE_ALL_MESSAGES",
    "SUMMARIZER_ROLE",
    "SUMMARIZER_TAG",
    "SUMMARY_MAX_OUTPUT_TOKENS",
    "SUMMARY_MESSAGE_ID",
    "SUMMARY_MESSAGE_PREFIX",
    "CellWikiCompactionMiddleware",
    "CompactionOutcome",
    "bound_post_compact_tool_results",
    "build_compacted_messages",
    "current_watermark",
    "estimate_messages_tokens",
    "find_tail_start",
    "is_overflow_error",
    "latest_summary_text",
    "message_groups",
    "microcompact_messages",
    "serialize_tail_records",
    "summary_prompt_text",
]
