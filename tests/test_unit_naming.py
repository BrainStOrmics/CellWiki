# =============================================================================
# 审批单元与会话命名（展示性元数据）契约测试
# =============================================================================
# 对应 design 提案 2026-09-22-unit-and-thread-naming.md 与实施计划
# docs/process/plans/2026-09-22-unit-and-thread-naming.md：发布后自动命名
# （一次性结构化调用 + 确定性回退），失败只落 data.unit_title_error 与服务
# 日志，**不阻塞**发布与判定；同一服务给会话幂等命名一次（title_source）。
# =============================================================================

from __future__ import annotations

import json
import sqlite3
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from cellwiki.api.app import create_app
from cellwiki.domain.pending_diff import PendingDiff, PendingDiffStatus
from cellwiki.domain.runs import AgentRun, AgentRunOutcome, AgentRunStatus
from cellwiki.services.agent_runtime import AgentRuntimeManager
from cellwiki.services.runtime_store import RuntimeStore
from cellwiki.services.unit_naming import (
    PROMPT_MAX_CHARS,
    TITLE_MAX_CHARS,
    UnitNamingService,
    _parse_title_payload,
)

from tests.test_agent_runtime import (
    WAIT_TIMEOUT,
    _context,
    _prepared_workspace,
    _wait_for_segment_finish,
    _wait_for_status,
)
from tests.test_auto_accept_pending_diffs import _CommitOnce


class _NoModelCatalog:
    """目录里没有任何供应商：`resolve()` 返回 None（无 key/无模型场景）。"""

    def resolve(self, selection: Any = None) -> None:
        return None


class _FakeCompleter:
    """可编程的命名调用替身：按序返回脚本，记录收到的 prompt。"""

    def __init__(self, *responses: Any) -> None:
        self.responses = list(responses)
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if not self.responses:
            return json.dumps({"title": "默认标题", "summary": "默认摘要"})
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def _git_commit(repo: Path, name: str, content: str, message: str) -> str:
    import subprocess

    (repo / name).write_text(content, encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", name], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", message], check=True, capture_output=True
    )
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()


def _service(
    repo: Path, completer: Any, *, catalog: Any = None
) -> tuple[UnitNamingService, RuntimeStore]:
    store = RuntimeStore(repo)
    service = UnitNamingService(
        repo,
        store,
        catalog if catalog is not None else _NoModelCatalog(),
        completer=completer,
    )
    return service, store


def _store_run(store: RuntimeStore, run_id: str, thread_id: str, message: str) -> None:
    store.create_run(
        AgentRun(run_id=run_id, thread_id=thread_id, input_message=message)
    )
    store.transition(run_id, AgentRunStatus.RUNNING, message="Started.")
    store.finalize_run(
        run_id, AgentRunOutcome(status=AgentRunStatus.SUCCEEDED, message="Done.")
    )


def _save_unit(
    store: RuntimeStore,
    *,
    diff_id: str,
    run_id: str,
    thread_id: str,
    commits: list[str],
    files: list[str] | None = None,
) -> PendingDiff:
    unit = PendingDiff(
        diff_id=diff_id,
        run_id=run_id,
        thread_id=thread_id,
        snapshot_commit=None,
        head_commit=commits[0] if commits else None,
        commits=commits,
        files=files if files is not None else ["wiki/cell_types/a.md"],
        insertions=3,
        deletions=1,
    )
    store.save_pending_diff(unit)
    return unit


def _wait_for_unit_data(
    store: RuntimeStore, diff_id: str, key: str, timeout: float = WAIT_TIMEOUT
) -> PendingDiff:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        unit = store.get_pending_diff(diff_id)
        if unit.data.get(key) is not None:
            return unit
        time.sleep(0.02)
    raise AssertionError(f"unit {diff_id} never got data[{key!r}]")


def _wait_for_unit(
    store: RuntimeStore, run_id: str, timeout: float = WAIT_TIMEOUT
) -> PendingDiff:
    """等发布发生（run 终态早于发布落库，两者不同批）。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        diffs = store.list_pending_diffs(run_id=run_id)
        if diffs:
            return diffs[0]
        time.sleep(0.02)
    raise AssertionError(f"run {run_id} never published a unit")


def _wait_for_unit_status(
    store: RuntimeStore,
    diff_id: str,
    status: PendingDiffStatus,
    timeout: float = WAIT_TIMEOUT,
) -> PendingDiff:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        unit = store.get_pending_diff(diff_id)
        if unit.status is status:
            return unit
        time.sleep(0.02)
    raise AssertionError(f"unit {diff_id} never reached {status}")


# ---- 确定性回退标题 ----


def test_fallback_title_prefers_subject_then_thread_then_files(tmp_path: Path):
    repo = _prepared_workspace(tmp_path)
    service, store = _service(repo, _FakeCompleter())

    real = _git_commit(repo, "note.md", "x\n", "ingest: expand 5 sources to 130 pages")
    _store_run(store, "run_a", "t_a", "把 raw 里的 24 篇论文做成页面")
    unit = _save_unit(
        store, diff_id="diff_run_a_1", run_id="run_a", thread_id="t_a", commits=[real]
    )
    assert service.fallback_title(unit) == "ingest: expand 5 sources to 130 pages"

    # 自动版本化提交描述不了内容：退到会话标题（确定性派生）。
    wip = _git_commit(repo, "note2.md", "y\n", "wip(agent): auto-version changes")
    store.append_message(
        thread_id="t_a",
        run_id="run_a",
        role="user",
        content="把 raw 里的 24 篇论文做成页面",
        data={},
    )
    wip_unit = _save_unit(
        store, diff_id="diff_run_b_1", run_id="run_a", thread_id="t_a", commits=[wip]
    )
    assert service.fallback_title(wip_unit) == "把 raw 里的 24 篇论文做成页面"

    # 没有会话标题也没有可用 subject：退到变更面。
    bare = _save_unit(
        store, diff_id="diff_run_c_1", run_id="run_a", thread_id="t_bare", commits=[wip]
    )
    assert service.fallback_title(bare) == "变更 1 文件 +3/−1"


# ---- 命名成功与失败落点 ----


def test_name_pending_diff_records_title_and_prompt_is_bounded(tmp_path: Path):
    repo = _prepared_workspace(tmp_path)
    sha = _git_commit(repo, "note.md", "x\n", "ingest: expand 5 sources")
    completer = _FakeCompleter(
        "```json\n"
        + json.dumps({"title": "扩到 130 页", "summary": "把 24 篇论文展开成页面"})
        + "\n```",
    )
    service, store = _service(repo, completer)
    _store_run(store, "run_named", "t_named", "把 raw 里的论文做成页面")
    _save_unit(
        store,
        diff_id="diff_run_named_1",
        run_id="run_named",
        thread_id="t_named",
        commits=[sha],
    )

    service.name_pending_diff("diff_run_named_1")

    unit = store.get_pending_diff("diff_run_named_1")
    assert unit.data["unit_title"] == "扩到 130 页"
    assert unit.data["unit_summary"] == "把 24 篇论文展开成页面"
    assert unit.data["unit_title_source"] == "publish"
    assert unit.data["unit_title_model"] == "injected"
    assert unit.data["unit_title_at"]
    assert unit.data["unit_title_error"] is None

    prompt = completer.prompts[0]
    assert "把 raw 里的论文做成页面" in prompt
    assert "ingest: expand 5 sources" in prompt
    assert len(prompt) <= PROMPT_MAX_CHARS


def test_name_pending_diff_without_model_records_error(tmp_path: Path):
    repo = _prepared_workspace(tmp_path)
    sha = _git_commit(repo, "note.md", "x\n", "note")
    service, store = _service(repo, None)  # 无 completer：走目录默认模型
    _store_run(store, "run_nomodel", "t_nomodel", "写一页")
    _save_unit(
        store,
        diff_id="diff_run_nomodel_1",
        run_id="run_nomodel",
        thread_id="t_nomodel",
        commits=[sha],
    )

    service.name_pending_diff("diff_run_nomodel_1")

    unit = store.get_pending_diff("diff_run_nomodel_1")
    assert "unit_title" not in unit.data
    assert "default model" in unit.data["unit_title_error"]


def test_name_pending_diff_failure_is_recorded_not_raised(tmp_path: Path):
    repo = _prepared_workspace(tmp_path)
    sha = _git_commit(repo, "note.md", "x\n", "note")
    service, store = _service(repo, _FakeCompleter(RuntimeError("provider exploded")))
    _store_run(store, "run_fail", "t_fail", "写一页")
    _save_unit(
        store, diff_id="diff_run_fail_1", run_id="run_fail", thread_id="t_fail", commits=[sha]
    )

    service.name_pending_diff("diff_run_fail_1")  # 不抛

    unit = store.get_pending_diff("diff_run_fail_1")
    assert "unit_title" not in unit.data
    assert "provider exploded" in unit.data["unit_title_error"]


# ---- 会话命名 ----


def test_name_thread_once_is_idempotent(tmp_path: Path):
    repo = _prepared_workspace(tmp_path)
    completer = _FakeCompleter(json.dumps({"title": "论文批量建页"}))
    service, store = _service(repo, completer)
    _store_run(store, "run_t1", "t_thread", "把 24 篇论文做成页面")
    store.append_message(
        thread_id="t_thread",
        run_id="run_t1",
        role="user",
        content="把 24 篇论文做成页面",
        data={},
    )
    assert store.get_thread_title_state("t_thread") == (
        "把 24 篇论文做成页面",
        "derived",
    )

    service.name_thread_once("t_thread")
    service.name_thread_once("t_thread")  # 幂等：第二次不再调用模型

    assert store.get_thread_title_state("t_thread") == ("论文批量建页", "llm")
    assert len(completer.prompts) == 1


def test_name_thread_once_skips_threads_without_settled_run(tmp_path: Path):
    repo = _prepared_workspace(tmp_path)
    completer = _FakeCompleter(json.dumps({"title": "不该发生"}))
    service, store = _service(repo, completer)
    store.create_run(
        AgentRun(run_id="run_queued", thread_id="t_queued", input_message="排队中")
    )

    service.name_thread_once("t_queued")

    assert completer.prompts == []
    assert store.get_thread_title_state("t_queued") is not None


def test_title_source_column_upgrade(tmp_path: Path):
    """旧库缺 title_source 列时由守卫 ALTER 补上（重开 store 即触发）。"""
    store = RuntimeStore(tmp_path)
    with sqlite3.connect(store.path) as connection:
        connection.execute("ALTER TABLE agent_threads DROP COLUMN title_source")
    reopened = RuntimeStore(tmp_path)
    with sqlite3.connect(reopened.path) as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(agent_threads)")
        }
    assert "title_source" in columns


# ---- 发布链路：不阻塞 + 物化回退标题 + 去重 ----


class _BlockingCompleter:
    """第一次调用会卡在事件上：用来证明命名不阻塞发布与判定。"""

    def __init__(self, gate: threading.Event) -> None:
        self.gate = gate
        self.calls = 0

    def __call__(self, prompt: str) -> str:
        self.calls += 1
        self.gate.wait(WAIT_TIMEOUT)
        return json.dumps({"title": "命名完成", "summary": "摘要"})


def test_publish_queues_naming_without_blocking_the_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    repo = _prepared_workspace(tmp_path)
    gate = threading.Event()
    completer = _BlockingCompleter(gate)
    manager = AgentRuntimeManager(repo, adapter=_CommitOnce(repo))
    manager._naming = UnitNamingService(
        repo, manager.store, manager._model_catalog, completer=completer
    )
    try:
        started = manager.start(
            thread_id="t_naming", message="写一页", context=_context("t_naming")
        )
        _wait_for_status(manager, started.run_id, {AgentRunStatus.SUCCEEDED})
        _wait_for_segment_finish(manager, started.run_id)

        # 命名仍被卡住，但单元、回退标题与 run 终态都已落定：门禁不受影响。
        unit = manager.store.list_pending_diffs(run_id=started.run_id)[0]
        assert "unit_title" not in unit.data
        assert unit.data["unit_title_fallback"] == "note 1"
        assert manager._named_units  # 已入队

        gate.set()
        named = _wait_for_unit_data(manager.store, unit.diff_id, "unit_title")
        assert named.data["unit_title"] == "命名完成"
        assert named.data["unit_title_source"] == "publish"
    finally:
        gate.set()
        manager.close()


# ---- 判定与命名的时序：晚到的命名不得丢 ----


def test_patch_pending_diff_data_keeps_the_verdict(tmp_path: Path):
    """命名写回只并 data：模型调用期间单元可能已被判定，判定字段不动。"""
    repo = _prepared_workspace(tmp_path)
    sha = _git_commit(repo, "note.md", "x\n", "note")
    store = RuntimeStore(repo)
    _store_run(store, "run_patch", "t_patch", "写一页")
    _save_unit(
        store,
        diff_id="diff_run_patch_1",
        run_id="run_patch",
        thread_id="t_patch",
        commits=[sha],
    )
    # 命名任务在模型调用之前读到的副本：写回时判定已经落定。
    stale = store.get_pending_diff("diff_run_patch_1")
    store.update_pending_diff(
        "diff_run_patch_1",
        status=PendingDiffStatus.ACCEPTED,
        resolution="accepted",
        data={"resolved_by": "auto"},
    )

    patched = store.patch_pending_diff_data(
        stale.diff_id, {"unit_title": "晚到的标题"}
    )

    assert patched.status is PendingDiffStatus.ACCEPTED
    assert patched.resolution == "accepted"
    assert patched.data["resolved_by"] == "auto"
    assert patched.data["unit_title"] == "晚到的标题"


def test_naming_lands_after_auto_accept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """自动接受开启时单元发布即被代判：晚到的命名仍必须落库并显示。"""
    from cellwiki.config import settings

    monkeypatch.setattr(settings, "auto_accept_pending_diffs", True)
    repo = _prepared_workspace(tmp_path)
    gate = threading.Event()
    manager = AgentRuntimeManager(repo, adapter=_CommitOnce(repo))
    manager._naming = UnitNamingService(
        repo, manager.store, manager._model_catalog, completer=_BlockingCompleter(gate)
    )
    try:
        started = manager.start(
            thread_id="t_auto_naming", message="写一页", context=_context("t_auto_naming")
        )
        _wait_for_status(manager, started.run_id, {AgentRunStatus.SUCCEEDED})
        unit = _wait_for_unit(manager.store, started.run_id)
        _wait_for_unit_status(manager.store, unit.diff_id, PendingDiffStatus.ACCEPTED)

        gate.set()
        named = _wait_for_unit_data(manager.store, unit.diff_id, "unit_title")
        assert named.data["unit_title"] == "命名完成"
        assert named.status is PendingDiffStatus.ACCEPTED
        assert named.data["resolved_by"] == "auto"
    finally:
        gate.set()
        manager.close()


# ---- 重新生成端点 ----


def test_rename_endpoint_regenerates_for_decided_units(tmp_path: Path):
    repo = _prepared_workspace(tmp_path)
    sha = _git_commit(repo, "note.md", "x\n", "ingest: expand 5 sources")
    store = RuntimeStore(repo)
    _store_run(store, "run_rename", "t_rename", "写一页")
    store.save_pending_diff(
        PendingDiff(
            diff_id="diff_run_rename_1",
            run_id="run_rename",
            thread_id="t_rename",
            commits=[sha],
            files=["wiki/a.md"],
            status=PendingDiffStatus.ACCEPTED,
            resolution="accepted",
            resolved_at=datetime.now(UTC),
            data={"resolved_by": "auto"},
        )
    )
    manager = AgentRuntimeManager(repo, adapter=None)
    manager._naming = UnitNamingService(
        repo,
        manager.store,
        _NoModelCatalog(),
        completer=_FakeCompleter(json.dumps({"title": "历史单元补名"})),
    )
    client = TestClient(create_app(repo, agent_runtime=manager))
    try:
        response = client.post("/api/pending-diffs/diff_run_rename_1/rename")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == PendingDiffStatus.ACCEPTED.value
        assert body["data"]["resolved_by"] == "auto"  # 判定来源不被覆盖
        assert body["data"]["unit_title"] == "历史单元补名"
        assert body["data"]["unit_title_source"] == "manual_regen"

        missing = client.post("/api/pending-diffs/diff_does_not_exist/rename")
        assert missing.status_code == 404
    finally:
        manager.close()


# ---- 解析与截断 ----


def test_parse_title_payload_tolerates_prose_and_truncates():
    title, summary = _parse_title_payload(
        '这是结果：{"title": "' + "题" * 40 + '", "summary": "摘要"} 完毕'
    )
    assert len(title) <= TITLE_MAX_CHARS

    with pytest.raises(ValueError):
        _parse_title_payload('{"summary": "没有标题"}')
