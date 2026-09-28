"""Memory tool-surface and tool behaviour tests (ADR-0016, slice 5)."""

from __future__ import annotations

import json
from pathlib import Path

from cellwiki.agent.memory_tools import build_memory_tools
from cellwiki.config import settings
from cellwiki.domain.agent_tools import (
    CANONICAL_TOOL_ORDER,
    MEMORY_TOOL_NAMES,
    agent_tool_names,
)
from cellwiki.domain.memory import MemoryKind, MemoryTopicFamily
from cellwiki.services.agent_memory import WorkspaceMemoryStore
from cellwiki.services.run_scope import clear_run_scope, set_run_scope
from cellwiki.domain.runs import AgentRun
from cellwiki.services.runtime_store import RuntimeStore


def _tools(root: Path) -> dict[str, object]:
    return {tool.name: tool for tool in build_memory_tools(root)}


def _agent_run(*, run_id: str, thread_id: str) -> AgentRun:
    return AgentRun(
        run_id=run_id, thread_id=thread_id, input_message="记住：逐行判定"
    )


def _seed_entry(root: Path, title: str = "逐行审批") -> str:
    store = RuntimeStore(root)
    memory = WorkspaceMemoryStore(root, store.path)
    entry = memory.upsert_entry(
        memory_id="mem_1",
        kind=MemoryKind.PREFERENCE,
        topic_family=MemoryTopicFamily.RUN_APPROVAL,
        title=title,
        file_name="run-approval.md",
        derived_hash="",
    )
    derived = memory.write_entry_file(entry, "评审时逐行判定 diff，不要整段接受。")
    memory.upsert_entry(
        memory_id="mem_1",
        kind=MemoryKind.PREFERENCE,
        topic_family=MemoryTopicFamily.RUN_APPROVAL,
        title=title,
        file_name="run-approval.md",
        derived_hash=derived,
    )
    return "mem_1"


def test_memory_tools_are_registered_when_enabled(monkeypatch):
    monkeypatch.setattr(settings, "agent_memory_enabled", True)
    names = agent_tool_names(include_memory=True)

    assert names[: len(CANONICAL_TOOL_ORDER)] == CANONICAL_TOOL_ORDER
    assert names[len(CANONICAL_TOOL_ORDER) :] == MEMORY_TOOL_NAMES
    assert "list_memory" in names
    assert "read_memory" in names
    assert "search_memory" in names
    assert "add_ad_hoc_note" in names


def test_memory_tools_absent_when_disabled():
    names = agent_tool_names(include_memory=False)

    assert names == CANONICAL_TOOL_ORDER
    assert "list_memory" not in names
    assert "add_ad_hoc_note" not in names


def test_list_memory_reports_entries(tmp_path: Path):
    _seed_entry(tmp_path)
    tools = _tools(tmp_path)

    payload = json.loads(tools["list_memory"].invoke({}))

    assert payload["count"] == 1
    assert payload["entries"][0]["memory_id"] == "mem_1"
    assert payload["entries"][0]["topic_family"] == MemoryTopicFamily.RUN_APPROVAL.value


def test_read_memory_returns_body(tmp_path: Path):
    _seed_entry(tmp_path)
    tools = _tools(tmp_path)

    payload = json.loads(tools["read_memory"].invoke({"memory_id": "mem_1"}))

    assert payload["title"] == "逐行审批"
    assert "逐行判定 diff" in payload["body"]


def test_read_memory_reports_missing_entry(tmp_path: Path):
    RuntimeStore(tmp_path)
    tools = _tools(tmp_path)

    payload = json.loads(tools["read_memory"].invoke({"memory_id": "mem_missing"}))

    assert payload["status"] == "not_found"


def test_search_memory_finds_matching_line(tmp_path: Path):
    _seed_entry(tmp_path)
    tools = _tools(tmp_path)

    payload = json.loads(tools["search_memory"].invoke({"query": "整段接受"}))

    assert payload["count"] == 1
    assert payload["hits"][0]["memory_id"] == "mem_1"


def test_search_memory_empty_query(tmp_path: Path):
    RuntimeStore(tmp_path)
    tools = _tools(tmp_path)

    payload = json.loads(tools["search_memory"].invoke({"query": "   "}))

    assert payload["status"] == "empty_query"


def test_add_ad_hoc_note_records_candidate(tmp_path: Path):
    runtime = RuntimeStore(tmp_path)
    run = runtime.create_run(
        __import__("cellwiki.domain.runs", fromlist=["AgentRun"]).AgentRun(
            run_id="run_note", thread_id="thread_note", input_message="记住：逐行判定"
        )
    )
    tools = _tools(tmp_path)
    set_run_scope(run.run_id, None)
    try:
        payload = json.loads(
            tools["add_ad_hoc_note"].invoke(
                {
                    "note": "以后都逐行判定 diff，不要整段接受。",
                    "topic_family": MemoryTopicFamily.RUN_APPROVAL.value,
                }
            )
        )
    finally:
        clear_run_scope()

    assert payload["status"] == "recorded"
    memory = WorkspaceMemoryStore(tmp_path, runtime.path)
    candidates = memory.list_candidates()
    assert len(candidates) == 1
    assert candidates[0].origin_run_id == "run_note"
    assert candidates[0].origin_thread_id == "thread_note"
    assert candidates[0].kind == MemoryKind.CONVENTION


def test_add_ad_hoc_note_rejects_unknown_family(tmp_path: Path):
    RuntimeStore(tmp_path)
    tools = _tools(tmp_path)

    payload = json.loads(
        tools["add_ad_hoc_note"].invoke(
            {"note": "记住这一点。", "topic_family": "不存在的家族"}
        )
    )

    assert payload["status"] == "invalid_topic_family"
    assert MemoryTopicFamily.RUN_APPROVAL.value in payload["allowed"]


def test_add_ad_hoc_note_rejects_empty_note(tmp_path: Path):
    RuntimeStore(tmp_path)
    tools = _tools(tmp_path)

    payload = json.loads(
        tools["add_ad_hoc_note"].invoke(
            {"note": "   ", "topic_family": MemoryTopicFamily.EVALUATION.value}
        )
    )

    assert payload["status"] == "empty_note"