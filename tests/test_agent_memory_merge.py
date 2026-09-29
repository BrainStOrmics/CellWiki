"""Workspace-memory consolidation tests (ADR-0016, slice 3)."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from cellwiki.domain.memory import MemoryCandidateStatus, MemoryKind, MemoryTopicFamily
from cellwiki.services.agent_memory import WorkspaceMemoryStore
from cellwiki.services.agent_memory_merge import MemoryConsolidationService
from cellwiki.services.runtime_store import RuntimeStore


class _Catalog:
    def __init__(self, *, available: bool = True) -> None:
        self._available = available

    def resolve(self):
        return object() if self._available else None


def _stores(tmp_path: Path) -> tuple[RuntimeStore, WorkspaceMemoryStore]:
    store = RuntimeStore(tmp_path)
    return store, WorkspaceMemoryStore(tmp_path, store.path)


def _seed(
    memory: WorkspaceMemoryStore,
    *,
    title: str = "逐行判定 diff",
    kind: MemoryKind = MemoryKind.PREFERENCE,
) -> None:
    memory.add_candidate(
        kind=kind,
        topic_family=MemoryTopicFamily.RUN_APPROVAL,
        title=title,
        body="用户偏好逐行判定审批单元。",
        origin_run_id="run_1",
        origin_thread_id="thread_1",
        source_refs=["run:run_1"],
    )


def _topic_payload(
    *,
    kind: str = MemoryKind.PREFERENCE.value,
    family: str = MemoryTopicFamily.RUN_APPROVAL.value,
    title: str = "审批偏好",
    file_name: str = "run-approval.md",
    body: str = "逐行判定审批单元，不要整段接受。",
) -> dict:
    return {
        "topics": [
            {
                "kind": kind,
                "topic_family": family,
                "title": title,
                "file_name": file_name,
                "body": body,
            }
        ],
        "summary": {
            "profile": "在这个工作区里按证据与逐行审批推进。",
            "preferences": "- 评审时逐行判定 diff。",
            "tips": "- 门禁失败先读 gate_issues。",
            "index": "### run 与审批\n- 审批偏好: 逐行判定",
        },
    }


def test_consolidate_writes_topic_files_and_summary(tmp_path: Path):
    _store, memory = _stores(tmp_path)
    _seed(memory)
    service = MemoryConsolidationService(
        memory, _Catalog(), completer=lambda prompt: json.dumps(_topic_payload())
    )

    written = service.consolidate()

    assert [entry.file_name for entry in written] == ["run-approval.md"]
    assert (memory.memory_dir / "run-approval.md").is_file()
    summary = memory.read_summary()
    assert summary.splitlines()[0] == "v1"
    assert "## User Preferences" in summary
    assert "逐行判定 diff" in summary
    index = memory.index_path().read_text(encoding="utf-8")
    assert "# Memory index" in index
    assert "# Task Group" in index
    assert "scope: run 与审批" in index
    assert f"applies_to: {memory.workspace_root}" in index
    assert "## Task 1" in index
    assert "- kind: preference" in index
    assert "## User Preferences" in index
    assert "## Reusable Knowledge" in index
    assert memory.list_candidates() == []


def test_consolidate_preserves_all_candidate_kinds(tmp_path: Path):
    for kind in MemoryKind:
        root = tmp_path / kind.value
        root.mkdir()
        _store, memory = _stores(root)
        _seed(memory, kind=kind)
        service = MemoryConsolidationService(
            memory,
            _Catalog(),
            completer=lambda prompt, kind=kind: json.dumps(
                _topic_payload(kind=kind.value)
            ),
        )

        written = service.consolidate()

        assert len(written) == 1
        assert written[0].kind is kind


def test_consolidate_renders_failures_block(tmp_path: Path):
    _store, memory = _stores(tmp_path)
    _seed(memory, kind=MemoryKind.LESSON, title="踩坑记录")
    service = MemoryConsolidationService(
        memory,
        _Catalog(),
        completer=lambda prompt: json.dumps(
            _topic_payload(kind=MemoryKind.LESSON.value, title="踩坑记录")
        ),
    )

    service.consolidate()

    index = memory.index_path().read_text(encoding="utf-8")
    assert "## Failures and How to Do Differently" in index
    assert "踩坑记录" in index


def test_consolidate_marks_candidates_merged(tmp_path: Path):
    _store, memory = _stores(tmp_path)
    _seed(memory)
    service = MemoryConsolidationService(
        memory, _Catalog(), completer=lambda prompt: json.dumps(_topic_payload())
    )

    service.consolidate()

    all_candidates = memory.list_candidates(status=None)
    assert all_candidates
    assert all(
        candidate.status == MemoryCandidateStatus.MERGED for candidate in all_candidates
    )


def test_consolidate_rejects_unknown_topic_family(tmp_path: Path):
    _store, memory = _stores(tmp_path)
    _seed(memory)
    service = MemoryConsolidationService(
        memory,
        _Catalog(),
        completer=lambda prompt: json.dumps(
            _topic_payload(family="不存在的家族")
        ),
    )

    written = service.consolidate()

    assert written == []
    assert memory.list_candidates() == []
    assert memory.read_summary() == ""
    statuses = {
        candidate.status for candidate in memory.list_candidates(status=None)
    }
    assert statuses == {MemoryCandidateStatus.REJECTED}


def test_consolidate_rejects_invalid_file_name(tmp_path: Path):
    _store, memory = _stores(tmp_path)
    _seed(memory)
    service = MemoryConsolidationService(
        memory,
        _Catalog(),
        completer=lambda prompt: json.dumps(
            _topic_payload(file_name="../escape.md")
        ),
    )

    assert service.consolidate() == []
    assert not (memory.memory_dir.parent / "escape.md").exists()


def test_consolidate_rejects_unparsable_output(tmp_path: Path):
    _store, memory = _stores(tmp_path)
    _seed(memory)
    service = MemoryConsolidationService(
        memory, _Catalog(), completer=lambda prompt: "这不是 JSON"
    )

    assert service.consolidate() == []
    assert memory.list_candidates(status=None)[0].status == (
        MemoryCandidateStatus.REJECTED
    )


def test_consolidate_empty_output_keeps_candidates_pending(tmp_path: Path):
    _store, memory = _stores(tmp_path)
    _seed(memory)
    service = MemoryConsolidationService(
        memory, _Catalog(), completer=lambda prompt: "   \n"
    )

    assert service.consolidate() == []
    assert memory.read_summary() == ""
    assert memory.list_candidates()[0].status == MemoryCandidateStatus.PENDING


def test_consolidate_skips_user_edited_files(tmp_path: Path):
    _store, memory = _stores(tmp_path)
    service = MemoryConsolidationService(
        memory, _Catalog(), completer=lambda prompt: json.dumps(_topic_payload())
    )
    _seed(memory)
    service.consolidate()
    # 用户手动改写文件内容，derived_hash 随之失效。
    path = memory.memory_dir / "run-approval.md"
    path.write_text(
        path.read_text(encoding="utf-8") + "\n用户自己补的一行。\n",
        encoding="utf-8",
    )
    _seed(memory, title="再次提取的候选")

    written = service.consolidate()

    assert written == []
    assert "用户自己补的一行。" in path.read_text(encoding="utf-8")


def test_consolidate_rejects_oversized_summary(tmp_path: Path):
    _store, memory = _stores(tmp_path)
    _seed(memory)
    huge = "x" * 10_000
    payload = _topic_payload()
    payload["summary"]["profile"] = huge
    service = MemoryConsolidationService(
        memory, _Catalog(), completer=lambda prompt: json.dumps(payload)
    )

    assert service.consolidate() == []
    assert memory.read_summary() == ""


def test_consolidate_without_model_raises(tmp_path: Path):
    _store, memory = _stores(tmp_path)
    _seed(memory)
    service = MemoryConsolidationService(memory, _Catalog(available=False))

    try:
        service.consolidate()
    except Exception as error:  # noqa: BLE001 - 断言异常类型
        from cellwiki.services.agent_memory_merge import MemoryMergeUnavailable

        assert isinstance(error, MemoryMergeUnavailable)
    else:  # pragma: no cover - 缺失模型时必须抛错
        raise AssertionError("expected MemoryMergeUnavailable")


def test_consolidate_serializes_concurrent_calls(tmp_path: Path):
    _store, memory = _stores(tmp_path)
    _seed(memory)
    started = threading.Event()
    release = threading.Event()
    calls: list[int] = []

    def completer(_prompt: str) -> str:
        calls.append(1)
        started.set()
        assert release.wait(timeout=2)
        return json.dumps(_topic_payload())

    service = MemoryConsolidationService(memory, _Catalog(), completer=completer)
    first = threading.Thread(target=service.consolidate)
    second = threading.Thread(target=service.consolidate)

    first.start()
    assert started.wait(timeout=2)
    second.start()
    time.sleep(0.05)
    assert len(calls) == 1

    release.set()
    first.join(timeout=2)
    second.join(timeout=2)

    assert not first.is_alive()
    assert not second.is_alive()
    assert len(calls) == 1
    assert memory.list_candidates() == []
