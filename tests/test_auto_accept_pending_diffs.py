# =============================================================================
# 自动接受待确认 diff（用户授权的代判）契约测试
# =============================================================================
# 对应 design 提案 2026-09-21-auto-accept-pending-diffs.md 与 ADR-0007 决策 2
# 修订：策略开启时，run 以 succeeded / unfinished 收尾后的发布由系统代发接受；
# failed 与其他终态保持待判（人工兜底，门禁照常）。判定来源必须可辨——单元
# data.resolved_by、log.md 标题 `accepted (auto)`、删会话后的 tombstone 列。
# 策略关闭时行为逐字不变，由既有审批单元契约测试（test_pending_diff_approval_units.py
# 与 test_agent_runtime.py）平行回归。
# =============================================================================

from __future__ import annotations

import sqlite3
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from cellwiki.config import settings
from cellwiki.domain.pending_diff import PendingDiff, PendingDiffStatus
from cellwiki.domain.runs import (
    AgentEventType,
    AgentRun,
    AgentRunOutcome,
    AgentRunStatus,
    RunBudget,
)
from cellwiki.services.agent_runtime import (
    AgentRunInProgressError,
    AgentRuntimeManager,
    RuntimeSignal,
)
from cellwiki.services.runtime_store import RuntimeStore
from cellwiki.services.workspace_maintenance import _log_entry, verdict_label

from tests.test_agent_runtime import (
    WAIT_TIMEOUT,
    _context,
    _prepared_workspace,
    _wait_for_maintenance_subject,
    _wait_for_segment_finish,
    _wait_for_status,
)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout


class _CommitOnce:
    """每次执行写一个不同的文件内容并提交；正常收尾（SUCCEEDED）。

    内容带序号：同一个工作区连续两个 run 都产生真实提交，用于验证门禁已开。
    """

    def __init__(self, repo: Path, name: str = "note.md") -> None:
        self.repo = repo
        self.name = name
        self.runs = 0

    def execute(self, *, thread_id, message, context) -> Any:
        self.runs += 1
        (self.repo / self.name).write_text(f"content {self.runs}\n", encoding="utf-8")
        _git(self.repo, "add", self.name)
        _git(self.repo, "commit", "-m", f"note {self.runs}")
        yield RuntimeSignal(
            type=AgentEventType.MESSAGE_DELTA,
            message="写好了",
            data={},
            model_call_id="model_call_1",
            input_tokens=10,
            output_tokens=10,
        )


class _CommitThenOverrun:
    """先提交一份改动，再耗尽模型调用预算：中断态的收尾发布由段尾兜底完成。"""

    def __init__(self, repo: Path, name: str = "partial.md") -> None:
        self.repo = repo
        self.name = name
        self.runs = 0

    def execute(self, *, thread_id, message, context) -> Any:
        self.runs += 1
        (self.repo / self.name).write_text(f"半成品 {self.runs}\n", encoding="utf-8")
        _git(self.repo, "add", self.name)
        _git(self.repo, "commit", "-m", "partial note")
        for index in range(6):
            yield RuntimeSignal(
                type=AgentEventType.MESSAGE_DELTA,
                message="token",
                data={},
                model_call_id=f"model_call_{index}",
                input_tokens=10,
                output_tokens=10,
            )


class _CommitThenFail:
    """提交改动后抛异常：run 落 FAILED，单元必须留给人看。"""

    def __init__(self, repo: Path, name: str = "doomed.md") -> None:
        self.repo = repo
        self.name = name

    def execute(self, *, thread_id, message, context) -> Any:
        (self.repo / self.name).write_text("会失败的改动\n", encoding="utf-8")
        _git(self.repo, "add", self.name)
        _git(self.repo, "commit", "-m", "doomed note")
        yield RuntimeSignal(
            type=AgentEventType.MESSAGE_DELTA,
            message="开始",
            data={},
            model_call_id="model_call_1",
        )
        raise RuntimeError("adapter exploded")


def _wait_for_unit(
    manager: AgentRuntimeManager, run_id: str, status: PendingDiffStatus
) -> PendingDiff:
    deadline = time.monotonic() + WAIT_TIMEOUT
    while time.monotonic() < deadline:
        diffs = manager.store.list_pending_diffs(run_id=run_id)
        if diffs and diffs[0].status is status:
            return diffs[0]
        time.sleep(0.02)
    got = [d.status.value for d in manager.store.list_pending_diffs(run_id=run_id)]
    raise AssertionError(f"diff for {run_id} did not reach {status}: {got}")


def _wait_for_maintenance_marker(
    manager: AgentRuntimeManager, run_id: str
) -> PendingDiff:
    """等维护回执写进单元 data：接受先落状态，维护随后才跑，两者不同批。"""
    deadline = time.monotonic() + WAIT_TIMEOUT
    while time.monotonic() < deadline:
        diff = manager.store.list_pending_diffs(run_id=run_id)[0]
        if diff.data.get("maintenance"):
            return diff
        time.sleep(0.02)
    raise AssertionError(f"maintenance marker missing for {run_id}")


def test_auto_accept_disabled_keeps_unit_pending(tmp_path: Path):
    """默认关闭：单元保持待判，无来源标记、无判定条目、无维护 commit。"""
    repo = _prepared_workspace(tmp_path)
    manager = AgentRuntimeManager(repo, adapter=_CommitOnce(repo))
    try:
        started = manager.start(
            thread_id="t_off",
            message="写一页",
            context=_context("t_off"),
        )
        _wait_for_status(manager, started.run_id, {AgentRunStatus.SUCCEEDED})
        _wait_for_segment_finish(manager, started.run_id)

        diff = _wait_for_unit(manager, started.run_id, PendingDiffStatus.PENDING)
        assert "resolved_by" not in diff.data
        log = (repo / "log.md").read_text(encoding="utf-8")
        assert f"accepted | run {started.run_id}" not in log
        # 收尾的强制 lint 快照本身也带维护 commit（verdict=lint）；要断言的是
        # 没有"接受"那一次维护。
        subjects = _git(repo, "log", "--format=%s")
        assert "(accepted)" not in subjects
    finally:
        manager.close()


def test_auto_accept_on_success_accepts_and_reopens_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """开关开启 + 成功收尾：单元被代判接受，审计可辨，门禁不再阻断下一轮。"""
    monkeypatch.setattr(settings, "auto_accept_pending_diffs", True)
    repo = _prepared_workspace(tmp_path)
    manager = AgentRuntimeManager(repo, adapter=_CommitOnce(repo))
    try:
        started = manager.start(
            thread_id="t_auto",
            message="写一页",
            context=_context("t_auto"),
        )
        _wait_for_status(manager, started.run_id, {AgentRunStatus.SUCCEEDED})
        diff = _wait_for_unit(manager, started.run_id, PendingDiffStatus.ACCEPTED)

        assert diff.data["resolved_by"] == "auto"
        assert diff.data["auto_accept"]["policy"] == "succeeded+unfinished"
        decided = _wait_for_maintenance_marker(manager, started.run_id)
        assert decided.data["maintenance"]["status"] == "ok"
        assert decided.data["maintenance"]["verdict"] == "accept"
        assert _wait_for_maintenance_subject(
            repo, f"after run {started.run_id} (accepted)"
        ), "接受后必须产生系统维护 commit"
        log = (repo / "log.md").read_text(encoding="utf-8")
        assert f"accepted (auto) | run {started.run_id}" in log

        # 门禁不再阻断：同一工作区立刻能起第二个 run（有未判定单元时 start 会 409）。
        follow_up = manager.start(
            thread_id="t_auto_next",
            message="再写一页",
            context=_context("t_auto_next"),
        )
        _wait_for_status(manager, follow_up.run_id, {AgentRunStatus.SUCCEEDED})
        _wait_for_unit(manager, follow_up.run_id, PendingDiffStatus.ACCEPTED)
    finally:
        manager.close()


def test_auto_accept_on_unfinished_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """开关开启 + 预算耗尽（unfinished）：段尾兜底发布之后代判接受。"""
    monkeypatch.setattr(settings, "auto_accept_pending_diffs", True)
    repo = _prepared_workspace(tmp_path)
    manager = AgentRuntimeManager(repo, adapter=_CommitThenOverrun(repo))
    try:
        started = manager.start(
            thread_id="t_overrun",
            message="跑到预算耗尽",
            context=_context("t_overrun"),
            budget=RunBudget(max_model_calls=2),
        )
        _wait_for_status(manager, started.run_id, {AgentRunStatus.UNFINISHED})
        diff = _wait_for_unit(manager, started.run_id, PendingDiffStatus.ACCEPTED)
        assert diff.data["resolved_by"] == "auto"
        # 单元先落 ACCEPTED、维护（写 log.md）随后才完成，读人读条目要等回执。
        _wait_for_maintenance_marker(manager, started.run_id)

        log = (repo / "log.md").read_text(encoding="utf-8")
        assert f"unfinished | run {started.run_id}" in log
        assert f"accepted (auto) | run {started.run_id}" in log

        # 单元判完了，但中断的 run 本身仍占着串行门（不变式 7：继续还是放弃由
        # 用户决定）——自动接受解决的是审批单元，不是中断的 run。
        with pytest.raises(AgentRunInProgressError):
            manager.start(
                thread_id="t_overrun_next",
                message="中断的 run 还占着门",
                context=_context("t_overrun_next"),
            )
        manager.cancel(started.run_id)
        follow_up = manager.start(
            thread_id="t_overrun_next",
            message="放弃中断的 run 之后继续用",
            context=_context("t_overrun_next"),
        )
        _wait_for_status(manager, follow_up.run_id, {AgentRunStatus.SUCCEEDED})
    finally:
        manager.close()


def test_auto_accept_skips_failed_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """开关开启 + FAILED：单元保持待判、无来源标记、门禁照常生效。"""
    monkeypatch.setattr(settings, "auto_accept_pending_diffs", True)
    repo = _prepared_workspace(tmp_path)
    manager = AgentRuntimeManager(repo, adapter=_CommitThenFail(repo))
    try:
        started = manager.start(
            thread_id="t_failed",
            message="会失败的一次",
            context=_context("t_failed"),
        )
        _wait_for_status(manager, started.run_id, {AgentRunStatus.FAILED})
        _wait_for_segment_finish(manager, started.run_id)

        diff = _wait_for_unit(manager, started.run_id, PendingDiffStatus.PENDING)
        assert "resolved_by" not in diff.data
        log = (repo / "log.md").read_text(encoding="utf-8")
        assert "accepted (auto)" not in log
        with pytest.raises(AgentRunInProgressError):
            manager.start(
                thread_id="t_failed_next",
                message="被门禁挡住",
                context=_context("t_failed_next"),
            )
    finally:
        manager.close()


def test_auto_accept_skips_suspended_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """挂起（WAITING_CONFIRMATION）不是终态：挂起发布不判定，单元留到终态。

    段尾收尾对挂起段同样会跑一次代判入口，这里的断言同时钉住那条路径。
    """
    monkeypatch.setattr(settings, "auto_accept_pending_diffs", True)
    manager = AgentRuntimeManager(_prepared_workspace(tmp_path))
    try:
        manager.store.create_run(
            AgentRun(
                run_id="run_suspended",
                thread_id="t_suspended",
                input_message="先问一句",
            )
        )
        manager.store.transition("run_suspended", AgentRunStatus.RUNNING, message="Started.")
        manager.store.transition(
            "run_suspended", AgentRunStatus.WAITING_CONFIRMATION, message="Asking."
        )
        manager.store.save_pending_diff(
            PendingDiff(
                diff_id="diff_run_suspended_1",
                run_id="run_suspended",
                thread_id="t_suspended",
                commits=["aaa1111"],
                files=["wiki/a.md"],
            )
        )

        assert manager._maybe_auto_accept_pending_diff("run_suspended") is None
        unit = manager.store.get_pending_diff("diff_run_suspended_1")
        assert unit.status is PendingDiffStatus.PENDING
        assert "resolved_by" not in unit.data
    finally:
        manager.close()


def test_auto_accept_failure_keeps_gate_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """代判失败不吞：单元保持待判、留下可操作事件，人工作为兜底。"""
    monkeypatch.setattr(settings, "auto_accept_pending_diffs", True)
    repo = _prepared_workspace(tmp_path)
    manager = AgentRuntimeManager(repo, adapter=_CommitOnce(repo))
    try:

        def boom(diff_id: str, **kwargs: Any) -> PendingDiff:
            raise RuntimeError("store unavailable")

        monkeypatch.setattr(manager, "accept_pending_diff", boom)
        started = manager.start(
            thread_id="t_boom",
            message="写一页",
            context=_context("t_boom"),
        )
        _wait_for_status(manager, started.run_id, {AgentRunStatus.SUCCEEDED})
        _wait_for_segment_finish(manager, started.run_id)

        diff = _wait_for_unit(manager, started.run_id, PendingDiffStatus.PENDING)
        assert "resolved_by" not in diff.data
        failures = [
            event
            for event in manager.store.list_events(started.run_id)
            if (event.data or {}).get("kind") == "auto_accept_failed"
        ]
        assert failures, "代判失败必须留下 auto_accept_failed 事件"
        assert "manual review" in failures[0].message
        assert failures[0].data["remediation"]
        with pytest.raises(AgentRunInProgressError):
            manager.start(
                thread_id="t_boom_next",
                message="门禁仍然生效",
                context=_context("t_boom_next"),
            )
    finally:
        manager.close()


def test_workspace_edit_run_is_decided_after_terminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """合成 workspace_edit run：发布早于终态落定，代判在 finalize 之后。

    `propose_workspace_edit` 是唯一"发布早于 finalize"的路径（agent_runtime
    :3986 发布、:4002 才落 SUCCEEDED）；判定点搬错就会在这里暴露。
    """
    monkeypatch.setattr(settings, "auto_accept_pending_diffs", True)
    repo = _prepared_workspace(tmp_path)
    manager = AgentRuntimeManager(repo)
    try:
        run = manager.propose_workspace_edit("index.md", "# Index\n\n人工编辑\n")
        assert run.status is AgentRunStatus.SUCCEEDED
        diff = manager.store.list_pending_diffs(run_id=run.run_id)[0]
        assert diff.status is PendingDiffStatus.ACCEPTED
        assert diff.data["resolved_by"] == "auto"
    finally:
        manager.close()


def test_tombstone_keeps_resolved_by(tmp_path: Path):
    """删会话后判定来源仍在：tombstone 的 resolved_by 列（升级库走守卫 ALTER）。"""
    store = RuntimeStore(tmp_path)
    store.create_thread("t_tomb_auto")
    # 删会话要求线程里没有活动 run：先落一条终态 run（与既有 tombstone 测试同构）。
    store.create_run(
        AgentRun(
            run_id="run_tomb_auto",
            thread_id="t_tomb_auto",
            input_message="写一页",
        )
    )
    store.transition("run_tomb_auto", AgentRunStatus.RUNNING, message="Started.")
    store.finalize_run(
        "run_tomb_auto",
        AgentRunOutcome(status=AgentRunStatus.SUCCEEDED, message="Done."),
    )
    store.save_pending_diff(
        PendingDiff(
            diff_id="diff_run_tomb_auto_1",
            run_id="run_tomb_auto",
            thread_id="t_tomb_auto",
            commits=["bbb2222"],
            files=["wiki/a.md"],
            status=PendingDiffStatus.ACCEPTED,
            resolved_at=datetime.now(UTC),
            data={"resolved_by": "auto"},
        )
    )
    assert store.delete_thread("t_tomb_auto") == 1
    with sqlite3.connect(store.path) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            "SELECT verdict, resolved_by FROM pending_diff_tombstones"
        ).fetchone()
    assert row["verdict"] == PendingDiffStatus.ACCEPTED.value
    assert row["resolved_by"] == "auto"

    # 升级路径：旧库缺列时由 _ensure_schema 的守卫 ALTER 补上（重开 store 即触发）。
    with sqlite3.connect(store.path) as connection:
        connection.execute("ALTER TABLE pending_diff_tombstones DROP COLUMN resolved_by")
    reopened = RuntimeStore(tmp_path)
    with sqlite3.connect(reopened.path) as connection:
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(pending_diff_tombstones)")
        }
    assert "resolved_by" in columns


def test_verdict_label_marks_auto_accept_only():
    """人读标签：只有代判的接受带 (auto)，拒绝/未完成与人工不接受影响。"""
    auto = PendingDiff(
        diff_id="diff_run_x_1",
        run_id="run_x",
        thread_id="t_x",
        commits=["bbb2222"],
        files=["alpha-cell.md"],
        data={"resolved_by": "auto"},
    )
    manual = PendingDiff(
        diff_id="diff_run_y_1",
        run_id="run_y",
        thread_id="t_y",
        commits=["bbb2222"],
        files=["alpha-cell.md"],
        data={"resolved_by": "user"},
    )
    assert verdict_label("accepted", auto) == "accepted (auto)"
    assert verdict_label("accepted", manual) == "accepted"
    assert verdict_label("rejected", auto) == "rejected"
    assert verdict_label("unfinished", None) == "unfinished"
    assert "accepted (auto) | run run_x" in _log_entry("accepted", "run_x", None, auto)
    assert "accepted (auto)" not in _log_entry("accepted", "run_y", None, manual)
