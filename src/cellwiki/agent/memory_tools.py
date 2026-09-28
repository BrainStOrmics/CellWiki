# =============================================================================
# 记忆工具 —— 知识库工作区记忆的读取与显式写入（ADR-0016）
# =============================================================================
# 四个工具：
#   list_memory     列出成型记忆（id、家族、标题、文件、是否被用户编辑）
#   read_memory     读一条记忆的正文与 frontmatter
#   search_memory   在记忆正文里做子串搜索，返回命中行与所在文件
#   add_ad_hoc_note 用户明确说"记住/忘记/更正"时写 append-only 候选
# 工具只写 data/runtime/memory/ 与候选表，写不到 wiki/，也不改审批状态。
# =============================================================================

"""Memory tools: list / read / search plus explicit append-only notes."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from langchain_core.tools import BaseTool, tool

from cellwiki.domain.memory import MemoryKind, MemoryTopicFamily
from cellwiki.services.agent_memory import WorkspaceMemoryStore
from cellwiki.services.run_scope import current_run_scope
from cellwiki.services.runtime_store import RuntimeStore

MAX_READ_CHARS = 20_000
MAX_SEARCH_HITS = 50
NOTE_MAX_CHARS = 4_000


def _memory_store(project_root: Path) -> WorkspaceMemoryStore:
    root = Path(project_root).resolve()
    return WorkspaceMemoryStore(root, RuntimeStore(root).path)


def _entry_payload(memory: WorkspaceMemoryStore, entry) -> dict:
    return {
        "memory_id": entry.memory_id,
        "kind": entry.kind.value,
        "topic_family": entry.topic_family.value,
        "title": entry.title,
        "file_name": entry.file_name,
        "user_edited": entry.user_edited,
        "auto_update": entry.auto_update,
        "updated_at": entry.updated_at.isoformat(),
    }


def build_memory_tools(project_root: Path) -> list[BaseTool]:
    """Build the four memory tools bound to one workspace root."""

    root = Path(project_root).resolve()
    memory = _memory_store(root)

    @tool("list_memory")
    def list_memory() -> str:
        """List workspace memories: id, topic family, title, file, edit state.

        Memories record collaboration preferences, conventions, lessons and
        decision pointers. They are not scientific evidence: never cite a
        memory as the source of a page claim.
        """
        entries = [_entry_payload(memory, entry) for entry in memory.list_entries()]
        return json.dumps(
            {"count": len(entries), "entries": entries}, ensure_ascii=False
        )

    @tool("read_memory")
    def read_memory(memory_id: str) -> str:
        """Read one memory by id: frontmatter body plus whether it was user-edited."""
        entry = memory.get_entry(memory_id)
        if entry is None:
            return json.dumps(
                {"status": "not_found", "memory_id": memory_id}, ensure_ascii=False
            )
        body = memory.read_entry_body(entry.file_name)[:MAX_READ_CHARS]
        payload = _entry_payload(memory, entry)
        payload["body"] = body
        return json.dumps(payload, ensure_ascii=False)

    @tool("search_memory")
    def search_memory(query: str) -> str:
        """Search workspace memories for a substring; returns matching files and lines."""
        needle = _collapse(query)
        if not needle:
            return json.dumps({"status": "empty_query"}, ensure_ascii=False)
        lowered = needle.lower()
        hits: list[dict] = []
        for entry in memory.list_entries():
            body = memory.read_entry_body(entry.file_name)
            for line_number, line in enumerate(body.splitlines(), start=1):
                if lowered in line.lower():
                    hits.append(
                        {
                            "memory_id": entry.memory_id,
                            "title": entry.title,
                            "line": line_number,
                            "text": line.strip()[:300],
                        }
                    )
                    break
            if len(hits) >= MAX_SEARCH_HITS:
                break
        return json.dumps(
            {"query": needle, "hits": hits, "count": len(hits)}, ensure_ascii=False
        )

    @tool("add_ad_hoc_note")
    def add_ad_hoc_note(note: str, topic_family: str) -> str:
        """Append one memory note after the user explicitly asks to remember it.

        Use only when the user explicitly says to remember, forget or correct
        something. Provide the note verbatim plus the closest topic family:
        one of wiki 内容维护, raw 与来源, prompt 与上下文, run 与审批,
        评估与测试, 工作区与环境. The note is stored as a candidate and merged
        later; it never edits wiki pages or approval state.
        """
        text = str(note or "").strip()
        if not text:
            return json.dumps({"status": "empty_note"}, ensure_ascii=False)
        family = _resolve_family(topic_family)
        if family is None:
            return json.dumps(
                {
                    "status": "invalid_topic_family",
                    "allowed": [item.value for item in MemoryTopicFamily],
                },
                ensure_ascii=False,
            )
        scope = current_run_scope()
        run_id = scope.run_id if scope else ""
        thread_id = ""
        if run_id:
            try:
                thread_id = RuntimeStore(root).get_run(run_id).thread_id
            except KeyError:
                thread_id = ""
        candidate = memory.add_candidate(
            kind=_infer_kind(text),
            topic_family=family,
            title=_collapse(text)[:120],
            body=text[:NOTE_MAX_CHARS],
            origin_run_id=run_id,
            origin_thread_id=thread_id,
            source_refs=[f"user:{datetime.now(UTC).isoformat()}"],
        )
        return json.dumps(
            {"status": "recorded", "memory_id": candidate.memory_id},
            ensure_ascii=False,
        )

    return [add_ad_hoc_note, list_memory, read_memory, search_memory]


def _collapse(text: str) -> str:
    return " ".join(str(text or "").split())


def _resolve_family(value: str) -> MemoryTopicFamily | None:
    raw = _collapse(value)
    for family in MemoryTopicFamily:
        if family.value == raw:
            return family
    return None


def _infer_kind(note: str) -> MemoryKind:
    lowered = note.lower()
    if any(marker in lowered for marker in ("不要", "禁止", "never", "don't", "forget")):
        return MemoryKind.CONVENTION
    return MemoryKind.PREFERENCE


__all__ = ["MAX_SEARCH_HITS", "build_memory_tools"]
