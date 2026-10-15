"""Pure event-to-line rendering for the line-oriented CellWiki terminal client.

Everything here is side-effect free: functions take Product API payloads and
return Rich renderables or plain strings. The terminal app owns printing,
scrolling and state; this module owns wording, styles and bounded previews.
"""

from __future__ import annotations

from typing import Any

from rich.text import Text


TERMINAL_STATUSES = {
    "succeeded",
    "failed",
    "cancelled",
    "unfinished",
    "rejected",
}


def event_line(event: dict[str, Any]) -> Text | None:
    """Render one non-streaming event as a single line.

    ``message_delta`` / ``reasoning_delta`` / ``final_response`` are handled by
    the streaming path and return ``None`` here.
    """

    event_type = str(event.get("type") or "")
    message = str(event.get("message") or "")
    data = event.get("data") or {}

    if event_type == "tool_started":
        name = str(data.get("tool_name") or "?")
        return Text(f"\u25cf {message or name}")
    if event_type == "tool_completed":
        return Text(f"  \u2514 {message or 'completed'}", style="dim")
    if event_type == "tool_failed":
        return Text(f"  \u2514 {message or 'failed'}", style="red")
    if event_type == "run_status":
        status = str(data.get("status") or "")
        if status in TERMINAL_STATUSES:
            return Text(f"[run] {status}", style="dim")
        return None
    if event_type == "usage_updated":
        return None
    if event_type == "context_compaction_started":
        return Text("\u2026 compacting context", style="dim")
    if event_type == "context_compaction_completed":
        return Text("\u2026 context compaction finished", style="dim")
    if event_type == "progress":
        progress = event.get("progress")
        suffix = f" ({progress}%)" if isinstance(progress, int) else ""
        return Text(f"\u2026 {message or 'working'}{suffix}", style="dim")
    if event_type in {
        "task_confirmation_required",
        "review_required",
        "changeset_ready",
        "verification",
        "subagent_started",
        "subagent_completed",
    }:
        return Text(f"\u2026 {message or event_type}", style="dim")
    if event_type == "error":
        return Text(f"error: {message}", style="red")
    return None


def question_lines(question: dict[str, Any]) -> list[Text]:
    """Render one ``ask_user_question`` gate as inline numbered options."""

    lines = [
        Text("CellWiki needs your decision", style="bold"),
        Text(str(question.get("question") or "")),
    ]
    for index, option in enumerate(question.get("options") or [], start=1):
        label = str(option.get("label") or "").strip()
        if not label:
            continue
        description = str(option.get("description") or "").strip()
        text = f"  {index}. {label}"
        if description:
            text += f" \u2014 {description}"
        lines.append(Text(text, style="cyan") if option.get("recommended") else Text(text))
    lines.append(
        Text(
            "Answer with an option number or free text; Esc skips "
            "(the run pauses unfinished).",
            style="dim",
        )
    )
    return lines


def approval_lines(
    diff_id: str,
    patch: str,
    *,
    preview_lines: int = 60,
) -> list[Text]:
    """Render a pending-diff approval prompt with a bounded patch preview."""

    files = _diff_files(patch)
    added, removed = _diff_counts(patch)
    lines = [Text(f"Pending diff {diff_id}", style="bold")]
    if files:
        shown = ", ".join(files[:8])
        if len(files) > 8:
            shown += f" \u2026 (+{len(files) - 8} more)"
        lines.append(Text(f"files: {shown}", style="dim"))
    if added or removed:
        lines.append(Text(f"changes: +{added} -{removed}", style="dim"))
    body = patch.splitlines()
    for line in body[:preview_lines]:
        lines.append(_diff_text(line))
    if len(body) > preview_lines:
        lines.append(
            Text(
                f"\u2026 {len(body) - preview_lines} more lines "
                "\u2014 choose 3 to view the full diff",
                style="dim",
            )
        )
    lines.append(
        Text("1 accept \u00b7 2 reject \u00b7 3 view full diff \u00b7 Esc later", style="bold")
    )
    return lines


def full_diff_lines(patch: str, *, limit: int = 400) -> list[Text]:
    """Render the full patch, bounded to a terminal-friendly line count."""

    body = patch.splitlines()
    lines = [_diff_text(line) for line in body[:limit]]
    if len(body) > limit:
        lines.append(Text(f"\u2026 {len(body) - limit} more lines truncated", style="dim"))
    return lines


def thread_lines(threads: list[dict[str, Any]], *, limit: int = 20) -> list[Text]:
    """Render the ``/resume`` session picker entries."""

    lines: list[Text] = []
    for index, thread in enumerate(threads[:limit], start=1):
        title = str(thread.get("title") or thread.get("thread_id") or "Conversation")
        status = str(thread.get("latest_status") or "no runs")
        updated = str(thread.get("updated_at") or "")[:16]
        lines.append(Text(f"  {index}. {title}  [{status}] {updated}"))
    return lines


def message_lines(messages: list[dict[str, Any]], *, limit: int = 20) -> list[Text]:
    """Render persisted transcript messages for a resumed session."""

    lines: list[Text] = []
    for message in messages[-limit:]:
        role = str(message.get("role") or "")
        content = str(message.get("content") or "")
        if not content:
            continue
        if role == "user":
            lines.append(Text(f"> {content}", style="bold"))
        elif role == "assistant":
            lines.append(Text(f"CellWiki: {content}"))
    return lines


def model_label(catalog: dict[str, Any] | None) -> str:
    """Return the default provider/model label from the sanitized catalog."""

    selection = (catalog or {}).get("default_selection") or {}
    model_id = str(selection.get("model_id") or "")
    provider_id = str(selection.get("provider_id") or "")
    if model_id and provider_id:
        return f"{provider_id}/{model_id}"
    if model_id:
        return model_id
    return "legacy .env"


def context_label(payload: dict[str, Any] | None) -> str:
    """Return the toolbar context-usage label."""

    if not payload:
        return ""
    used = int(payload.get("used_tokens") or 0)
    if used <= 0:
        return ""
    return f"ctx {used / 1000:.0f}k"


def run_summary(run: dict[str, Any]) -> Text:
    """Render the terminal run summary line."""

    status = str(run.get("status") or "unknown")
    usage = run.get("usage") or {}
    input_tokens = int(usage.get("input_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or 0)
    elapsed = float(usage.get("elapsed_seconds") or 0.0)
    parts = [f"run {run.get('run_id') or '?'}: {status}"]
    if input_tokens or output_tokens:
        parts.append(f"tokens {input_tokens}/{output_tokens}")
    if elapsed:
        parts.append(f"{elapsed:.1f}s")
    message = str(run.get("error_message") or "")
    style = "red" if status == "failed" else "dim"
    text = " \u00b7 ".join(parts)
    if message and status == "failed":
        text += f" \u2014 {message}"
    return Text(text, style=style)


def usage_label(event: dict[str, Any]) -> str:
    """Return the toolbar usage label from a ``usage_updated`` event."""

    data = event.get("data") or {}
    cumulative = data.get("cumulative") or {}
    input_tokens = int(cumulative.get("input_tokens") or 0)
    output_tokens = int(cumulative.get("output_tokens") or 0)
    if not (input_tokens or output_tokens):
        return ""
    return f"tokens {input_tokens}/{output_tokens}"


def _diff_files(patch: str) -> list[str]:
    files: list[str] = []
    for line in patch.splitlines():
        if line.startswith("diff --git "):
            parts = line.split()
            if len(parts) >= 4:
                path = parts[3]
                if path.startswith("b/"):
                    path = path[2:]
                if path not in files:
                    files.append(path)
    return files


def _diff_counts(patch: str) -> tuple[int, int]:
    added = removed = 0
    for line in patch.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    return added, removed


def _diff_line_style(line: str) -> str | None:
    if line.startswith("+") and not line.startswith("+++"):
        return "green"
    if line.startswith("-") and not line.startswith("---"):
        return "red"
    if line.startswith(("@@", "diff --git", "index ", "---", "+++")):
        return "dim"
    return None


def _diff_text(line: str) -> Text:
    style = _diff_line_style(line)
    return Text(line, style=style) if style else Text(line)
