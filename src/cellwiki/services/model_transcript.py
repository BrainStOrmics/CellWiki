"""Render the append-only model transcript into provider-neutral messages."""

from __future__ import annotations

from typing import Any

from cellwiki.services.prompt_layers import summarize_excerpts

CHARS_PER_TOKEN = 4


def _text(record: dict[str, Any]) -> str:
    content = record.get("content")
    if isinstance(content, dict):
        text = content.get("text")
        if isinstance(text, str):
            return text
    return str(record.get("content_text") or "")


def estimate_transcript_tokens(records: list[dict[str, Any]]) -> int:
    return max(0, sum(len(_text(record)) for record in records) // CHARS_PER_TOKEN)


def summarize_transcript(records: list[dict[str, Any]]) -> str:
    """Build the deterministic fallback compaction summary."""

    excerpts = [f"{record.get('role', '?')}: {_text(record)}" for record in records]
    return summarize_excerpts(excerpts)


def split_for_compaction(
    records: list[dict[str, Any]], *, retained_tokens: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split active records into the summarized prefix and retained tail."""

    tail: list[dict[str, Any]] = []
    used = 0
    for record in reversed(records):
        tokens = estimate_transcript_tokens([record])
        if tail and used + tokens > retained_tokens:
            break
        tail.append(record)
        used += tokens
    tail.reverse()
    return records[: len(records) - len(tail)], tail


def render_model_messages(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge semantic records into the exact message order sent to the graph.

    User and run_context are adjacent records but one user message. This keeps
    Anthropic's single-system-message invariant and makes the turn context a
    tail attachment rather than a second system prompt.

    Tool calls and results are normalized into adjacent pairs. The append-only
    store can legitimately contain a synthetic result after a later user
    message when an interrupted question is repaired by Deep Agents; providers
    reject that raw order, so rendering restores the protocol-valid pairing.
    """

    results_by_call: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        if str(record.get("kind") or "") != "tool_result":
            continue
        call_id = str(record.get("tool_call_id") or "")
        if call_id:
            results_by_call.setdefault(call_id, []).append(record)

    consumed_results: set[str] = set()
    messages: list[dict[str, Any]] = []
    index = 0
    while index < len(records):
        record = records[index]
        kind = str(record.get("kind") or "")
        content = record.get("content")
        if kind == "user":
            text = _text(record)
            next_record = records[index + 1] if index + 1 < len(records) else None
            if next_record is not None and str(next_record.get("kind")) == "run_context":
                context_text = _text(next_record)
                if context_text:
                    text = f"{text}\n\n{context_text}" if text else context_text
                index += 1
            messages.append({"role": "user", "content": text})
        elif kind == "run_context":
            context_text = _text(record)
            if context_text:
                messages.append({"role": "user", "content": context_text})
        elif kind == "assistant":
            text = ""
            tool_calls: list[dict[str, Any]] = []
            if isinstance(content, dict):
                text = str(content.get("text") or "")
                raw_calls = content.get("tool_calls")
                if isinstance(raw_calls, list):
                    tool_calls = [call for call in raw_calls if isinstance(call, dict)]
            message: dict[str, Any] = {"role": "assistant", "content": text}
            if tool_calls:
                message["tool_calls"] = tool_calls
            messages.append(message)
            for tool_call in tool_calls:
                call_id = str(tool_call.get("id") or "")
                tool_name = str(tool_call.get("name") or "tool")
                candidates = results_by_call.get(call_id, [])
                result = next(
                    (
                        candidate
                        for candidate in candidates
                        if str(candidate.get("message_id") or "")
                        not in consumed_results
                    ),
                    None,
                )
                if result is not None:
                    consumed_results.add(str(result.get("message_id") or ""))
                    messages.append(
                        {
                            "role": "tool",
                            "content": _text(result),
                            "tool_call_id": result.get("tool_call_id"),
                            "name": result.get("name"),
                        }
                    )
                else:
                    messages.append(_synthetic_tool_result(call_id, tool_name))
        elif kind == "tool_result":
            # A tool result is emitted next to its assistant tool_call above.
            # Results without a matching active assistant call are ignored:
            # emitting a bare tool message is itself protocol-invalid.
            pass
        elif kind == "compaction":
            item = content.get("item") if isinstance(content, dict) else None
            if isinstance(item, dict):
                messages.append({"role": "assistant", "content": [item]})
            else:
                summary = _text(record) or "Compacted history."
                messages.append(
                    {"role": "user", "content": f"[Compacted context]\n{summary}"}
                )
        index += 1
    return messages


def _synthetic_tool_result(call_id: str, tool_name: str) -> dict[str, Any]:
    """Build the deterministic repair result used for an orphan tool call."""

    if tool_name == "ask_user_question":
        text = (
            f"Tool call ask_user_question with id {call_id} was cancelled - "
            "another message came in before it could be completed."
        )
    else:
        text = (
            f"Tool call {tool_name} with id {call_id} was cancelled or did not "
            "produce a result."
        )
    return {
        "role": "tool",
        "content": text,
        "tool_call_id": call_id,
        "name": tool_name,
    }


__all__ = [
    "estimate_transcript_tokens",
    "render_model_messages",
    "split_for_compaction",
    "summarize_transcript",
]
