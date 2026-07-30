"""Build bounded multi-turn context from the durable observable transcript."""

from __future__ import annotations

from cellwiki.services.runtime_store import RuntimeStore


class ConversationContextView:
    """Exclude framework state while preserving recent user-visible conversation."""

    MAX_MESSAGES = 12
    MAX_APPROXIMATE_TOKENS = 6_000
    _CHARS_PER_TOKEN = 4

    def __init__(self, store: RuntimeStore):
        self.store = store

    def build(
        self,
        *,
        thread_id: str,
        current_run_id: str,
        current_content: str,
    ) -> list[dict[str, str]]:
        durable = self.store.list_context_messages(thread_id)
        prepared: list[dict[str, str]] = []
        for item in durable:
            content = (
                current_content
                if item["run_id"] == current_run_id and item["role"] == "user"
                else item["content"]
            )
            prepared.append({"role": item["role"], "content": content})

        character_budget = self.MAX_APPROXIMATE_TOKENS * self._CHARS_PER_TOKEN
        selected: list[dict[str, str]] = []
        used = 0
        for item in reversed(prepared):
            if len(selected) >= self.MAX_MESSAGES:
                break
            remaining = character_budget - used
            if remaining <= 0:
                break
            content = item["content"]
            if len(content) > remaining:
                content = content[-remaining:]
            selected.append({"role": item["role"], "content": content})
            used += len(content)
        selected.reverse()
        return selected


__all__ = ["ConversationContextView"]
