"""Workspace-memory storage contract tests (ADR-0016, slice 1)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from cellwiki.domain.memory import (
    MemoryCandidateStatus,
    MemoryKind,
    MemoryTopicFamily,
)
from cellwiki.services.agent_memory import (
    MEMORY_SUMMARY_MAX_BYTES,
    MEMORY_SUMMARY_MAX_TOKENS,
    SUMMARY_HEADINGS,
    WorkspaceMemoryStore,
    render_summary,
    validate_summary_body,
)
from cellwiki.services.runtime_store import RuntimeStore


def _memory_columns(path: Path, table: str) -> set[str]:
    connection = sqlite3.connect(path)
    try:
        return {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
    finally:
        connection.close()


def test_runtime_store_creates_memory_tables(tmp_path: Path):
    store = RuntimeStore(tmp_path)

    assert _memory_columns(store.path, "memory_candidates") >= {
        "memory_id",
        "workspace",
        "kind",
        "topic_family",
        "title",
        "body",
        "source_refs",
        "origin_run_id",
        "origin_thread_id",
        "status",
        "derived_hash",
    }
    assert _memory_columns(store.path, "memory_entries") >= {
        "memory_id",
        "workspace",
        "kind",
        "topic_family",
        "title",
        "file_name",
        "origin_thread_id",
        "origin_run_id",
        "source_refs",
        "derived_hash",
        "user_edited",
        "auto_update",
        "usage_count",
    }


def test_memory_schema_guard_is_idempotent(tmp_path: Path):
    store = RuntimeStore(tmp_path)
    first = _memory_columns(store.path, "memory_candidates")

    RuntimeStore(tmp_path)

    assert _memory_columns(store.path, "memory_candidates") == first


def test_extraction_counter_is_persisted_per_workspace_day(tmp_path: Path):
    store = RuntimeStore(tmp_path)
    memory = WorkspaceMemoryStore(tmp_path, store.path)

    assert memory.extraction_count("2026-09-28") == 0
    assert memory.try_consume_extraction_slot("2026-09-28", 1)
    assert memory.extraction_count("2026-09-28") == 1
    assert not memory.try_consume_extraction_slot("2026-09-28", 1)
    assert memory.extraction_count("2026-09-28") == 1

    reopened = WorkspaceMemoryStore(tmp_path, RuntimeStore(tmp_path).path)
    assert not reopened.try_consume_extraction_slot("2026-09-28", 1)
    assert reopened.extraction_count("2026-09-28") == 1


def test_candidate_queue_round_trip(tmp_path: Path):
    RuntimeStore(tmp_path)
    memory = WorkspaceMemoryStore(tmp_path, RuntimeStore(tmp_path).path)

    first = memory.add_candidate(
        kind=MemoryKind.PREFERENCE,
        topic_family=MemoryTopicFamily.RUN_APPROVAL,
        title="评审时先看 diff 行",
        body="用户偏好逐行判定 diff，不要整段接受。",
        origin_run_id="run_1",
        origin_thread_id="thread_1",
        source_refs=["run:run_1"],
    )
    second = memory.add_candidate(
        kind=MemoryKind.LESSON,
        topic_family=MemoryTopicFamily.WORKSPACE_ENV,
        title="lint 门禁失败先看清单",
        body="门禁失败会带明细，先读 gate_issues 再改。",
        origin_run_id="run_2",
        origin_thread_id="thread_1",
    )

    pending = memory.list_candidates()
    assert [candidate.memory_id for candidate in pending] == [
        first.memory_id,
        second.memory_id,
    ]

    memory.mark_candidate(second.memory_id, MemoryCandidateStatus.MERGED)
    remaining = memory.list_candidates()
    assert [candidate.memory_id for candidate in remaining] == [first.memory_id]
    assert memory.list_candidates(status=None)[1].status == (
        MemoryCandidateStatus.MERGED
    )


def test_candidate_workspaces_are_isolated(tmp_path: Path):
    RuntimeStore(tmp_path)
    db = RuntimeStore(tmp_path).path
    other_root = tmp_path / "other"
    other_root.mkdir()
    RuntimeStore(other_root)

    first = WorkspaceMemoryStore(tmp_path, db)
    second = WorkspaceMemoryStore(other_root, RuntimeStore(other_root).path)
    first.add_candidate(
        kind=MemoryKind.CONVENTION,
        topic_family=MemoryTopicFamily.WIKI_CONTENT,
        title="页面先写 Evidence",
        body="生成页面时必须保留 Evidence 列。",
        origin_run_id="run_1",
        origin_thread_id="thread_1",
    )

    assert len(first.list_candidates()) == 1
    assert second.list_candidates() == []


def test_entry_file_records_derived_hash(tmp_path: Path):
    RuntimeStore(tmp_path)
    memory = WorkspaceMemoryStore(tmp_path, RuntimeStore(tmp_path).path)

    entry = memory.upsert_entry(
        memory_id="mem_1",
        kind=MemoryKind.LESSON,
        topic_family=MemoryTopicFamily.EVALUATION,
        title="评估卷先跑确定性变体",
        file_name="eval-deterministic.md",
        derived_hash="",
    )
    derived = memory.write_entry_file(entry, "先跑确定性变体，再上真实模型。")
    memory.upsert_entry(
        memory_id="mem_1",
        kind=MemoryKind.LESSON,
        topic_family=MemoryTopicFamily.EVALUATION,
        title="评估卷先跑确定性变体",
        file_name="eval-deterministic.md",
        derived_hash=derived,
    )

    raw = (memory.memory_dir / "eval-deterministic.md").read_text(encoding="utf-8")
    assert derived in raw
    body = memory.read_entry_body("eval-deterministic.md")
    assert body == "先跑确定性变体，再上真实模型。"
    entry = memory.get_entry("mem_1")
    assert entry is not None
    assert entry.derived_hash == derived
    assert memory.entry_body_matches(entry)


def test_entry_body_matches_detects_manual_edit(tmp_path: Path):
    RuntimeStore(tmp_path)
    memory = WorkspaceMemoryStore(tmp_path, RuntimeStore(tmp_path).path)
    entry = memory.upsert_entry(
        memory_id="mem_edit",
        kind=MemoryKind.LESSON,
        topic_family=MemoryTopicFamily.EVALUATION,
        title="评估卷先跑确定性变体",
        file_name="eval-edited.md",
        derived_hash="",
    )
    derived = memory.write_entry_file(entry, "原始内容。")
    stored = memory.upsert_entry(
        memory_id="mem_edit",
        kind=MemoryKind.LESSON,
        topic_family=MemoryTopicFamily.EVALUATION,
        title="评估卷先跑确定性变体",
        file_name="eval-edited.md",
        derived_hash=derived,
    )
    assert memory.entry_body_matches(stored)

    (memory.memory_dir / "eval-edited.md").write_text(
        (memory.memory_dir / "eval-edited.md").read_text(encoding="utf-8")
        + "\n用户补充的一行。\n",
        encoding="utf-8",
    )

    assert not memory.entry_body_matches(stored)


def test_entry_file_rejects_path_escape(tmp_path: Path):
    RuntimeStore(tmp_path)
    memory = WorkspaceMemoryStore(tmp_path, RuntimeStore(tmp_path).path)

    with pytest.raises(ValueError):
        memory.read_entry_body("../escape.md")


def test_delete_entry_removes_file_and_index_row(tmp_path: Path):
    RuntimeStore(tmp_path)
    memory = WorkspaceMemoryStore(tmp_path, RuntimeStore(tmp_path).path)
    entry = memory.upsert_entry(
        memory_id="mem_del",
        kind=MemoryKind.CONVENTION,
        topic_family=MemoryTopicFamily.PROMPT_CONTEXT,
        title="摘要不进稳定前缀",
        file_name="prompt-summary.md",
        derived_hash="x",
    )
    memory.write_entry_file(entry, "记忆摘要只进 Turn Context。")

    memory.delete_entry("mem_del")

    assert memory.get_entry("mem_del") is None
    assert not (memory.memory_dir / "prompt-summary.md").exists()


def test_delete_by_source_uses_entry_and_candidate_provenance(tmp_path: Path):
    store = RuntimeStore(tmp_path)
    memory = WorkspaceMemoryStore(tmp_path, store.path)
    memory.upsert_entry(
        memory_id="mem_source",
        kind=MemoryKind.PREFERENCE,
        topic_family=MemoryTopicFamily.RUN_APPROVAL,
        title="来源条目",
        file_name="source.md",
        derived_hash="x",
        origin_thread_id="thread_1",
        origin_run_id="run_1",
        source_refs=["thread:thread_1", "run:run_1"],
    )
    memory.upsert_entry(
        memory_id="mem_other",
        kind=MemoryKind.LESSON,
        topic_family=MemoryTopicFamily.EVALUATION,
        title="其他来源",
        file_name="other.md",
        derived_hash="x",
        origin_thread_id="thread_2",
        origin_run_id="run_2",
    )
    memory.add_candidate(
        kind=MemoryKind.PREFERENCE,
        topic_family=MemoryTopicFamily.RUN_APPROVAL,
        title="待合并的同一来源",
        body="同一来源的候选。",
        origin_run_id="run_1",
        origin_thread_id="thread_1",
    )
    memory.write_summary(render_summary(profile="来源清理前的摘要。"))
    memory.write_index("# Memory index\n")

    deleted_entries, deleted_candidates = memory.delete_by_source("thread_1")

    assert (deleted_entries, deleted_candidates) == (1, 1)
    assert memory.get_entry("mem_source") is None
    assert memory.get_entry("mem_other") is not None
    assert memory.list_candidates(status=None) == []
    assert memory.read_summary() == ""
    assert not memory.index_path().exists()


def test_set_entry_auto_update_clears_user_edited(tmp_path: Path):
    RuntimeStore(tmp_path)
    memory = WorkspaceMemoryStore(tmp_path, RuntimeStore(tmp_path).path)
    memory.upsert_entry(
        memory_id="mem_edit",
        kind=MemoryKind.PREFERENCE,
        topic_family=MemoryTopicFamily.RUN_APPROVAL,
        title="单行判定",
        file_name="run-approval.md",
        derived_hash="x",
        user_edited=True,
        auto_update=False,
    )

    memory.set_entry_auto_update("mem_edit", True)

    entry = memory.get_entry("mem_edit")
    assert entry is not None
    assert entry.auto_update is True
    assert entry.user_edited is False


def test_summary_contract_enforced(tmp_path: Path):
    body = render_summary(
        profile="在这个工作区里按证据与审批推进。",
        preferences="- 先看 diff 行再接受。",
        tips="- 门禁失败先读 gate_issues。",
        index="### run 与审批",
    )
    validate_summary_body(body)
    for heading in SUMMARY_HEADINGS:
        assert heading in body
    assert body.splitlines()[0] == "v1"

    with pytest.raises(ValueError):
        validate_summary_body("## User Profile\nmissing version\n")
    with pytest.raises(ValueError):
        validate_summary_body("v1\n\n## User Profile\n")
    with pytest.raises(ValueError):
        validate_summary_body(
            "v1\n"
            + "\n".join(SUMMARY_HEADINGS)
            + "\n"
            + ("x" * MEMORY_SUMMARY_MAX_BYTES)
        )


def test_summary_hard_limits_match_codex_alignment():
    assert MEMORY_SUMMARY_MAX_BYTES == 10_000
    assert MEMORY_SUMMARY_MAX_TOKENS == 2_500


def test_write_summary_persists_and_reads_back(tmp_path: Path):
    RuntimeStore(tmp_path)
    memory = WorkspaceMemoryStore(tmp_path, RuntimeStore(tmp_path).path)
    body = render_summary(profile="工作区协作口径。")

    memory.write_summary(body)

    assert memory.read_summary() == body
    record = memory.summary_record()
    assert record is not None
    assert record.body == body
    assert record.generation > 0
