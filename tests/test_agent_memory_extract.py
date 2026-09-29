"""Workspace-memory extraction tests (ADR-0016, slice 2)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from cellwiki.domain.memory import MemoryCandidateStatus, MemoryKind, MemoryTopicFamily
from cellwiki.domain.runs import AgentRun
from cellwiki.services.agent_memory import WorkspaceMemoryStore
from cellwiki.services.agent_memory_extract import (
    MemoryExtractionService,
    TOOL_RESULT_FILE_MAX_CHARS,
    TOOL_RESULT_MAX_FILES,
    has_signal,
)
from cellwiki.services.runtime_store import RuntimeStore


class _Catalog:
    """No default model: tests drive extraction through the injected completer."""

    def resolve(self):
        return None


class _NoopThread:
    """Stand-in for ``threading.Thread`` so schedule() stays deterministic."""

    def __init__(self, **_kwargs) -> None:
        pass

    def start(self) -> None:
        return None


class _FakeModel:
    root_client = None

    def __init__(self, text: str) -> None:
        self._text = text

    def invoke(self, _prompt: str):
        return SimpleNamespace(text=self._text)


def _service(
    tmp_path: Path,
    *,
    completer=None,
    model_spec_for_run=None,
    debounce_minutes: int = 10,
    sleep=None,
) -> tuple[MemoryExtractionService, WorkspaceMemoryStore]:
    store = RuntimeStore(tmp_path)
    memory = WorkspaceMemoryStore(tmp_path, store.path)
    service = MemoryExtractionService(
        tmp_path,
        store,
        memory,
        _Catalog(),  # type: ignore[arg-type]
        completer=completer,
        model_spec_for_run=model_spec_for_run,
        debounce_minutes=debounce_minutes,
        sleep=sleep or (lambda _seconds: None),
    )
    return service, memory


def _enable(monkeypatch, *, enabled: bool = True, generate: bool = True) -> None:
    import cellwiki.config as config_module

    monkeypatch.setattr(config_module.settings, "agent_memory_enabled", enabled)
    monkeypatch.setattr(config_module.settings, "agent_memory_generate", generate)


def test_signal_gate_matches_preferences_and_corrections():
    assert has_signal("记住：评审时逐行判定")
    assert has_signal("以后不要自动接受 diff")
    assert has_signal("下次先跑 lint")
    assert has_signal("please remember that tests need redis")
    assert has_signal("don't do that again")


def test_signal_gate_skips_plain_queries():
    assert not has_signal("这个页面写了什么")
    assert not has_signal("lint 结果怎么样")
    assert not has_signal("show me the lint report")
    assert not has_signal("")
    assert not has_signal("帮我看一下 wiki/cell_types 下有多少页")


def test_disabled_memory_does_not_schedule(monkeypatch, tmp_path: Path):
    _enable(monkeypatch, enabled=False)
    service, memory = _service(
        tmp_path, completer=lambda prompt: json.dumps({"candidates": []})
    )

    service.notify_run_settled("run_1", "thread_1", "记住：逐行判定")

    assert memory.list_candidates(status=None) == []


def test_extraction_persists_valid_candidates(monkeypatch, tmp_path: Path):
    _enable(monkeypatch)
    response = json.dumps(
        {
            "candidates": [
                {
                    "kind": "preference",
                    "topic_family": MemoryTopicFamily.RUN_APPROVAL.value,
                    "title": "逐行判定 diff",
                    "body": "用户偏好逐行判定审批单元。",
                    "source_refs": ["run:run_1"],
                },
                {
                    "kind": "not-a-kind",
                    "topic_family": MemoryTopicFamily.RUN_APPROVAL.value,
                    "title": "应当被丢弃",
                    "body": "kind 非法。",
                },
                {
                    "kind": "lesson",
                    "topic_family": "不存在的家族",
                    "title": "也应当被丢弃",
                    "body": "家族非法。",
                },
            ]
        }
    )
    service, memory = _service(tmp_path, completer=lambda prompt: response)

    created = service.extract("thread_1", ["run_1"])

    assert [candidate.kind for candidate in created] == [MemoryKind.PREFERENCE]
    pending = memory.list_candidates()
    assert len(pending) == 1
    assert pending[0].origin_run_id == "run_1"
    assert pending[0].origin_thread_id == "thread_1"
    assert pending[0].source_refs == ["run:run_1"]


def test_extraction_no_signal_produces_nothing(monkeypatch, tmp_path: Path):
    _enable(monkeypatch)
    calls: list[str] = []

    def completer(prompt: str) -> str:
        calls.append(prompt)
        return json.dumps({"candidates": []})

    service, memory = _service(tmp_path, completer=completer)

    service.notify_run_settled("run_1", "thread_1", "这个页面写了什么")

    assert calls == []
    assert memory.list_candidates(status=None) == []


def test_extraction_daily_limit_blocks_further_runs(monkeypatch, tmp_path: Path):
    _enable(monkeypatch)
    import cellwiki.config as config_module

    monkeypatch.setattr(config_module.settings, "agent_memory_daily_extractions", 1)
    response = json.dumps(
        {
            "candidates": [
                {
                    "kind": "lesson",
                    "topic_family": MemoryTopicFamily.EVALUATION.value,
                    "title": "先跑确定性变体",
                    "body": "评估卷先跑确定性变体。",
                }
            ]
        }
    )
    service, memory = _service(tmp_path, completer=lambda prompt: response)

    first = service.extract("thread_1", ["run_1"])
    second = service.extract("thread_1", ["run_2"])

    assert len(first) == 1
    assert second == []
    assert len(memory.list_candidates(status=None)) == 1


def test_extraction_daily_limit_survives_a_new_service_instance(
    monkeypatch, tmp_path: Path
):
    _enable(monkeypatch)
    import cellwiki.config as config_module

    monkeypatch.setattr(config_module.settings, "agent_memory_daily_extractions", 1)
    response = json.dumps(
        {
            "candidates": [
                {
                    "kind": "lesson",
                    "topic_family": MemoryTopicFamily.EVALUATION.value,
                    "title": "先跑确定性变体",
                    "body": "评估卷先跑确定性变体。",
                }
            ]
        }
    )
    first_service, memory = _service(tmp_path, completer=lambda prompt: response)
    second_service, _ = _service(tmp_path, completer=lambda prompt: response)

    assert len(first_service.extract("thread_1", ["run_1"])) == 1
    assert second_service.extract("thread_2", ["run_2"]) == []
    assert memory.extraction_count(datetime.now(UTC).date().isoformat()) == 1


def test_extraction_uses_the_origin_run_model(monkeypatch, tmp_path: Path):
    _enable(monkeypatch)
    import cellwiki.services.agent_memory_extract as extract_module

    run_spec = SimpleNamespace(provider_id="run-provider", model_id="run-model")
    seen: list[object] = []

    def factory(spec, **_kwargs):
        seen.append(spec)
        return _FakeModel(json.dumps({"candidates": []}))

    monkeypatch.setattr(extract_module, "build_model_from_spec", factory)
    service, _memory = _service(
        tmp_path,
        model_spec_for_run=lambda _run_id: run_spec,
    )

    service.extract("thread_1", ["run_1"])

    assert seen == [run_spec]


def test_extraction_falls_back_to_catalog_model(monkeypatch, tmp_path: Path):
    _enable(monkeypatch)
    import cellwiki.services.agent_memory_extract as extract_module

    default_spec = SimpleNamespace(provider_id="default", model_id="default-model")
    seen: list[object] = []

    class _DefaultCatalog:
        def resolve(self):
            return default_spec

    def factory(spec, **_kwargs):
        seen.append(spec)
        return _FakeModel(json.dumps({"candidates": []}))

    monkeypatch.setattr(extract_module, "build_model_from_spec", factory)
    service, _memory = _service(
        tmp_path,
        model_spec_for_run=lambda _run_id: None,
    )
    service.catalog = _DefaultCatalog()  # type: ignore[assignment]

    service.extract("thread_1", ["run_1"])

    assert seen == [default_spec]


def test_extraction_tolerates_malformed_model_output(monkeypatch, tmp_path: Path):
    _enable(monkeypatch)
    service, memory = _service(
        tmp_path, completer=lambda prompt: "这不是 JSON，只是散文。"
    )

    created = service.extract("thread_1", ["run_1"])

    assert created == []
    assert memory.list_candidates(status=None) == []


def test_debounce_window_keeps_one_pending_extraction_per_thread(
    monkeypatch, tmp_path: Path
):
    """同线程多次触发只保留一个待处理窗口，run 列表按序累积。"""

    _enable(monkeypatch)
    monkeypatch.setattr(
        "cellwiki.services.agent_memory_extract.threading.Thread",
        lambda **kwargs: _NoopThread(),
    )
    service, _memory = _service(
        tmp_path, completer=lambda prompt: json.dumps({"candidates": []})
    )

    service.schedule("thread_1", "run_1")
    service.schedule("thread_1", "run_2")
    service.schedule("thread_1", "run_1")

    with service._lock:  # noqa: SLF001 - white-box assertion of the window state
        assert list(service._pending_runs["thread_1"]) == ["run_1", "run_2"]
        assert "thread_1" in service._pending_at


def test_disabled_memory_never_records_a_window(monkeypatch, tmp_path: Path):
    _enable(monkeypatch, enabled=False)
    monkeypatch.setattr(
        "cellwiki.services.agent_memory_extract.threading.Thread",
        lambda **kwargs: _NoopThread(),
    )
    service, _memory = _service(tmp_path)

    service.schedule("thread_1", "run_1")

    with service._lock:  # noqa: SLF001
        assert service._pending_runs == {}
        assert service._pending_at == {}


def test_candidates_do_not_enter_prompt_path(tmp_path: Path):
    store = RuntimeStore(tmp_path)
    memory = WorkspaceMemoryStore(tmp_path, store.path)
    memory.add_candidate(
        kind=MemoryKind.LESSON,
        topic_family=MemoryTopicFamily.WIKI_CONTENT,
        title="页面先写 Evidence",
        body="生成页面时必须保留 Evidence 列。",
        origin_run_id="run_1",
        origin_thread_id="thread_1",
    )

    assert memory.read_summary() == ""


def test_extraction_reads_bounded_tool_result_sidecars(
    monkeypatch, tmp_path: Path
):
    _enable(monkeypatch)
    sidecar_root = tmp_path / "data" / "runtime" / "tool-results"
    current = sidecar_root / "run_1"
    other = sidecar_root / "run_2"
    current.mkdir(parents=True)
    other.mkdir(parents=True)
    for index in range(TOOL_RESULT_MAX_FILES + 1):
        (current / f"call_{index}.txt").write_text(
            f"SIDE_CAR_{index} " + ("x" * (TOOL_RESULT_FILE_MAX_CHARS // 8)),
            encoding="utf-8",
        )
    (other / "call_other.txt").write_text(
        "OTHER_RUN_SECRET", encoding="utf-8"
    )
    prompts: list[str] = []

    def completer(prompt: str) -> str:
        prompts.append(prompt)
        return json.dumps({"candidates": []})

    service, _memory = _service(tmp_path, completer=completer)
    RuntimeStore(tmp_path).create_run(
        AgentRun(
            run_id="run_1",
            thread_id="thread_1",
            input_message="记住：读取工具侧车",
        )
    )
    service.extract("thread_1", ["run_1"])

    assert len(prompts) == 1
    for index in range(TOOL_RESULT_MAX_FILES):
        assert f"SIDE_CAR_{index}" in prompts[0]
    assert f"SIDE_CAR_{TOOL_RESULT_MAX_FILES}" not in prompts[0]
    assert "OTHER_RUN_SECRET" not in prompts[0]


def test_mark_candidate_status_transitions(tmp_path: Path):
    store = RuntimeStore(tmp_path)
    memory = WorkspaceMemoryStore(tmp_path, store.path)
    candidate = memory.add_candidate(
        kind=MemoryKind.CONVENTION,
        topic_family=MemoryTopicFamily.PROMPT_CONTEXT,
        title="摘要不进稳定前缀",
        body="记忆摘要只进 Turn Context。",
        origin_run_id="run_1",
        origin_thread_id="thread_1",
    )

    memory.mark_candidate(candidate.memory_id, MemoryCandidateStatus.REJECTED)

    assert memory.list_candidates() == []
    all_rows = memory.list_candidates(status=None)
    assert all_rows[0].status == MemoryCandidateStatus.REJECTED
