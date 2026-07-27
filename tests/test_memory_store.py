# =============================================================================
# 记忆存储测试 —— 验证项目隔离、去重、冲突和 FTS 召回
# =============================================================================

"""Governance tests for project isolation, deduplication, conflicts, and FTS recall."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from cellwiki.domain.memory import MemoryCandidate, MemoryKind, MemoryStatus
from cellwiki.services.memory import MemoryStore


def _candidate(candidate_id: str, content: str, *, project: str = "cellwiki", key: str | None = None):
    return MemoryCandidate(
        candidate_id=candidate_id,
        project_id=project,
        kind=MemoryKind.STABLE,
        content=content,
        key=key,
        confidence=0.9,
        tags=["workflow"],
    )


def test_memory_admission_deduplicates_and_surfaces_key_conflicts(tmp_path: Path):
    store = MemoryStore(tmp_path)
    first = store.admit(_candidate("candidate_1", "Use evidence cards for review.", key="review-style"))
    duplicate = store.admit(_candidate("candidate_2", "Use evidence cards for review.", key="review-style"))
    conflict = store.admit(_candidate("candidate_3", "Hide evidence cards during review.", key="review-style"))

    assert duplicate.memory_id == first.memory_id
    assert conflict.status == MemoryStatus.CONFLICT
    assert conflict.conflicts_with == [first.memory_id]
    assert [item.memory_id for item in store.list("cellwiki")] == [first.memory_id]


def test_memory_recall_never_crosses_project_and_respects_budget(tmp_path: Path):
    store = MemoryStore(tmp_path)
    local = store.admit(_candidate("local", "Regulatory T cell evidence workflow", project="cellwiki"))
    store.admit(_candidate("other", "Regulatory T cell secret project", project="other"))

    recalled, event = store.recall("cellwiki", "Regulatory T cell", token_budget=12)

    assert [item.memory_id for item in recalled] == [local.memory_id]
    assert event.project_id == "cellwiki"
    assert event.estimated_tokens <= 12
    assert "secret project" not in recalled[0].content


def test_expiry_and_index_rebuild_do_not_touch_wiki(tmp_path: Path):
    wiki = tmp_path / "wiki" / "cell_types" / "cell.md"
    wiki.parent.mkdir(parents=True)
    wiki.write_text("formal truth", encoding="utf-8")
    store = MemoryStore(tmp_path)
    expired = MemoryCandidate(
        candidate_id="expired",
        project_id="cellwiki",
        kind=MemoryKind.EPISODE,
        content="Past run summary",
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    record = store.admit(expired)

    assert store.expire("cellwiki") == 1
    assert store.get("cellwiki", record.memory_id).status == MemoryStatus.EXPIRED
    assert store.rebuild_index() == 0
    assert wiki.read_text(encoding="utf-8") == "formal truth"


def test_memory_contract_rejects_hidden_reasoning_payload():
    with pytest.raises(ValueError, match="hidden reasoning"):
        _candidate("bad", "Hidden reasoning: private chain of thought")

