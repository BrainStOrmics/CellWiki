# =============================================================================
# 待审 diff 审批单元（B 包）契约测试 —— 段基线重锚 / 收口闭环 / 判定留存
# =============================================================================
# 对应 design 提案 2026-09-18-pending-diff-approval-units.md（B1/B2/B3）：
# B1 重试/续跑段重锚 snapshot_commit，发布基线取"段起始快照与既有基线中
# 较新者"——重试旧 run 不得把段间其他会话的提交装进审批单元（2026-09-18
# 事故形态）；B2 发布前无条件版本化（堵"有提交但树仍脏"缺口）+ 版本化
# 失败给出可操作 ERROR 事件；B3 删会话保留已判定单元 tombstone，
# log.md 条目附 diff_id。P3（已暂存删除 fatal）回归在 test_agent_runtime.py。
# =============================================================================

from __future__ import annotations

import json
import sqlite3
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from cellwiki.domain.pending_diff import PendingDiff, PendingDiffStatus
from cellwiki.domain.runs import (
    AgentErrorType,
    AgentEventType,
    AgentRun,
    AgentRunOutcome,
    AgentRunStatus,
)
from cellwiki.services.agent_runtime import AgentRuntimeManager, RuntimeSignal
from cellwiki.services.git_executor import GitExecutor
from cellwiki.services.runtime_store import RuntimeStore, ThreadDeletionBlockedError
from cellwiki.services.workspace_maintenance import _log_entry

from tests.test_agent_runtime import (
    _assert_clean_except_system,
    _context,
    _prepared_workspace,
    _wait_for_diff,
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


def _commit_file(repo: Path, name: str, content: str = "x\n") -> str:
    (repo / name).write_text(content, encoding="utf-8")
    _git(repo, "add", name)
    _git(repo, "commit", "-m", f"add {name}")
    return GitExecutor(repo).current_head()


def _store_run(
    store: RuntimeStore,
    run_id: str,
    thread_id: str = "thread_units",
    *,
    snapshot: str | None = None,
) -> AgentRun:
    run = AgentRun(
        run_id=run_id,
        thread_id=thread_id,
        input_message="inspect the wiki",
        snapshot_commit=snapshot,
    )
    store.create_run(run)
    return run


def _drive_to_unfinished(store: RuntimeStore, run_id: str) -> None:
    store.transition(run_id, AgentRunStatus.RUNNING, message="Started.")
    store.transition(
        run_id,
        AgentRunStatus.UNFINISHED,
        error_type=AgentErrorType.BUDGET,
        error_message="budget exhausted",
        message="Paused.",
    )


# ---- B1：段开始重锚 snapshot_commit ----


def test_claim_methods_reanchor_snapshot_commit(tmp_path: Path):
    """只有 claim_retry 重锚段基线（retry = 有界重放，旧段未判定内容按段圈定
    不回灌，2026-09-18 事故形态）；claim_resume_unfinished / claim_resume 刻意
    不重锚——同一 run 续跑的未判定工作与工程侧修复必须留在审批视野内。"""
    store = RuntimeStore(tmp_path)

    _store_run(store, "run_retry", snapshot="old1111")
    _drive_to_unfinished(store, "run_retry")
    claimed = store.claim_retry("run_retry", snapshot_commit="new2222")
    assert claimed.snapshot_commit == "new2222"
    assert store.get_run("run_retry").snapshot_commit == "new2222"

    # 降级路径：git 读头失败（调用方传 None/缺省）时保持旧快照。
    _store_run(store, "run_degraded", snapshot="old7777")
    _drive_to_unfinished(store, "run_degraded")
    claimed = store.claim_retry("run_degraded")
    assert claimed.snapshot_commit == "old7777"

    _store_run(store, "run_resume", snapshot="old3333")
    _drive_to_unfinished(store, "run_resume")
    resumed = store.claim_resume_unfinished("run_resume")
    assert resumed.snapshot_commit == "old3333", "resume 不重锚"
    assert store.get_run("run_resume").snapshot_commit == "old3333"

    _store_run(store, "run_approve", snapshot="old5555")
    store.transition("run_approve", AgentRunStatus.RUNNING, message="Started.")
    store.transition(
        "run_approve", AgentRunStatus.WAITING_APPROVAL, message="Awaiting approval."
    )
    approved = store.claim_resume("run_approve", decision="approve")
    assert approved.snapshot_commit == "old5555", "审批续跑不重锚"
    assert store.get_run("run_approve").snapshot_commit == "old5555"


class _IdleAdapter:
    def execute(self, *, thread_id, message, context) -> Any:
        raise AssertionError("adapter must not run in this test")
        yield  # pragma: no cover


def _decided_unit(
    store: RuntimeStore,
    run_id: str,
    thread_id: str,
    *,
    snapshot: str,
    head: str,
) -> None:
    store.save_pending_diff(
        PendingDiff(
            diff_id=f"diff_{run_id}_1",
            run_id=run_id,
            thread_id=thread_id,
            snapshot_commit=snapshot,
            head_commit=head,
            commits=[head, snapshot],
            files=["f1.md"],
            status=PendingDiffStatus.ACCEPTED,
            resolved_at=datetime.now(UTC),
        )
    )


def test_resolve_publish_target_prefers_newer_segment_anchor(tmp_path: Path):
    """新单元基线 = 段起始快照与上一单元 head 中较新者（判定分支）。"""
    repo = _prepared_workspace(tmp_path)
    _commit_file(repo, "f1.md")
    c1 = GitExecutor(repo).current_head()
    _commit_file(repo, "f2.md")
    c2 = GitExecutor(repo).current_head()
    _commit_file(repo, "f3.md")
    c3 = GitExecutor(repo).current_head()

    manager = AgentRuntimeManager(repo, adapter=_IdleAdapter())
    try:
        run = _store_run(manager.store, "run_anchor", snapshot=c3)
        _decided_unit(manager.store, "run_anchor", "thread_units", snapshot=c1, head=c2)
        # 段锚 c3 晚于上一单元 head c2（段间有提交）：用它把外来提交挡在外面。
        _diff_id, _index, baseline = manager._resolve_publish_target(
            manager.store.get_run("run_anchor")
        )
        assert baseline == c3
        # 段锚早于上一单元 head（同段连续发布）：维持链式基线。
        manager.store.update_run(run.model_copy(update={"snapshot_commit": c1}))
        _diff_id, _index, baseline = manager._resolve_publish_target(
            manager.store.get_run("run_anchor")
        )
        assert baseline == c2
    finally:
        manager.close()


def test_resolve_publish_target_refresh_also_uses_newer_anchor(tmp_path: Path):
    """就地刷新分支同样受段锚约束：待判定单元的旧快照不得把段间外来提交
    刷进同一行（2026-09-18 事故的真实形态）。"""
    repo = _prepared_workspace(tmp_path)
    _commit_file(repo, "f1.md")
    c1 = GitExecutor(repo).current_head()
    _commit_file(repo, "f2.md")
    c2 = GitExecutor(repo).current_head()

    manager = AgentRuntimeManager(repo, adapter=_IdleAdapter())
    try:
        _store_run(manager.store, "run_refresh", snapshot=c2)
        manager.store.save_pending_diff(
            PendingDiff(
                diff_id="diff_run_refresh_1",
                run_id="run_refresh",
                thread_id="thread_units",
                snapshot_commit=c1,
                head_commit=c1,
                commits=[c1],
                files=["f1.md"],
                status=PendingDiffStatus.PENDING,
            )
        )
        # 段锚 c2 晚于待判定单元的基线 c1：刷新基线前移到段起点。
        _diff_id, _index, baseline = manager._resolve_publish_target(
            manager.store.get_run("run_refresh")
        )
        assert baseline == c2
        # 同段内（锚未变）：行为与旧规则一致，基线保持单元自身快照。
        manager.store.update_run(
            manager.store.get_run("run_refresh").model_copy(
                update={"snapshot_commit": c1}
            )
        )
        _diff_id, _index, baseline = manager._resolve_publish_target(
            manager.store.get_run("run_refresh")
        )
        assert baseline == c1
    finally:
        manager.close()


# ---- B1：端到端事故形态——重试不得吞段间外来提交 ----


class _TwoSegmentCommitter:
    """段 1 提交后超时失败（可重试）；段 2 再提交后正常收尾。"""

    def __init__(self, repo: Path) -> None:
        self.repo = repo
        self.calls = 0

    def execute(self, *, thread_id, message, context) -> Any:
        self.calls += 1
        if self.calls == 1:
            (self.repo / "seg1.md").write_text("seg1\n", encoding="utf-8")
            _git(self.repo, "add", "seg1.md")
            _git(self.repo, "commit", "-m", "seg1 work")
            raise RuntimeError("model request timed out")
        (self.repo / "seg2.md").write_text("seg2\n", encoding="utf-8")
        _git(self.repo, "add", "seg2.md")
        _git(self.repo, "commit", "-m", "seg2 work")
        yield RuntimeSignal(type=AgentEventType.MESSAGE_DELTA, message="ok", data={})


def test_retry_does_not_sweep_foreign_commits_into_approval_unit(tmp_path: Path):
    """事故回归：旧 run 失败 → 另一会话提交 → 重试 → 发布的审批单元只含
    重试段自己的提交，不含外来提交，也不含失败段未判定的旧提交。"""
    repo = _prepared_workspace(tmp_path)
    adapter = _TwoSegmentCommitter(repo)
    manager = AgentRuntimeManager(repo, adapter=adapter)
    try:
        started = manager.start(
            thread_id="t_units_retry",
            message="two segments",
            context=_context("t_units_retry"),
        )
        _wait_for_status(manager, started.run_id, {AgentRunStatus.FAILED})
        unit1 = _wait_for_diff(manager, started.run_id)[0]
        assert "seg1.md" in unit1.files

        (repo / "foreign.md").write_text("foreign\n", encoding="utf-8")
        _git(repo, "add", "foreign.md")
        _git(repo, "commit", "-m", "foreign session work")
        foreign_sha = GitExecutor(repo).current_head()

        manager.retry(started.run_id)
        _wait_for_status(manager, started.run_id, {AgentRunStatus.SUCCEEDED})
        # 就地刷新发生在段尾发布（SUCCEEDED 落定之后），轮询等它完成。
        deadline = time.monotonic() + 20.0
        refreshed = _wait_for_diff(manager, started.run_id)[0]
        while "seg2.md" not in refreshed.files and time.monotonic() < deadline:
            time.sleep(0.02)
            refreshed = _wait_for_diff(manager, started.run_id)[0]
        assert refreshed.diff_id == unit1.diff_id
        assert "seg2.md" in refreshed.files
        assert "seg1.md" not in refreshed.files, "失败段未判定内容按段圈定不回灌"
        assert "foreign.md" not in refreshed.files, "外来提交不得进审批单元"
        assert foreign_sha not in refreshed.commits
        assert len(refreshed.commits) == 1, "单元只应包含重试段自己的提交"
        assert refreshed.snapshot_commit == foreign_sha, "基线重锚到段起点"
    finally:
        manager.close()


# ---- B2：发布前无条件版本化 + 可操作失败事件 ----


def test_publish_versions_dirty_tree_even_with_existing_commits(tmp_path: Path):
    """收口缺口回归：段里已有 commit、树仍脏（直写未提交文件）时，发布单元
    必须同时包含已提交内容与收口产生的 wip 内容，脏文件不得游离在审批外。"""
    repo = _prepared_workspace(tmp_path)

    class CommitThenDirty:
        def execute(self, *, thread_id, message, context) -> Any:
            (repo / "committed.md").write_text("committed\n", encoding="utf-8")
            _git(repo, "add", "committed.md")
            _git(repo, "commit", "-m", "agent commit")
            (repo / "dirty.md").write_text("dirty\n", encoding="utf-8")
            yield RuntimeSignal(
                type=AgentEventType.MESSAGE_DELTA, message="写好了", data={}
            )

    manager = AgentRuntimeManager(repo, adapter=CommitThenDirty())
    try:
        started = manager.start(
            thread_id="t_units_dirty",
            message="commit then dirty",
            context=_context("t_units_dirty"),
        )
        _wait_for_status(manager, started.run_id, {AgentRunStatus.SUCCEEDED})
        diff = _wait_for_diff(manager, started.run_id)[0]
        assert "committed.md" in diff.files
        assert "dirty.md" in diff.files, "未提交文件必须被收口进审批单元"
        _assert_clean_except_system(repo)
    finally:
        manager.close()


def test_versioning_failure_emits_actionable_error_event(tmp_path: Path):
    """版本化收口失败：run 落 unfinished 之外，另有带 auto_version_failed
    载荷与操作指引的 ERROR 事件，用户不再是干巴巴的"已中断"。"""
    repo = _prepared_workspace(tmp_path)
    lock = repo / ".git" / "index.lock"
    lock.write_bytes(b"")

    class WriterWithoutCommit:
        def execute(self, *, thread_id, message, context) -> Any:
            (repo / "locked.md").write_text("dirty", encoding="utf-8")
            yield RuntimeSignal(
                type=AgentEventType.MESSAGE_DELTA, message="写好了", data={}
            )

    manager = AgentRuntimeManager(repo, adapter=WriterWithoutCommit())
    try:
        started = manager.start(
            thread_id="t_units_lock",
            message="写但不提交",
            context=_context("t_units_lock"),
        )
        _wait_for_status(manager, started.run_id, {AgentRunStatus.UNFINISHED})
        events = manager.store.list_events(started.run_id)
        failures = [
            event
            for event in events
            if event.type is AgentEventType.ERROR
            and isinstance(event.data, dict)
            and event.data.get("reason") == "auto_version_failed"
        ]
        assert failures, "版本化失败必须留可操作事件"
        remediation = failures[0].data.get("remediation")
        assert isinstance(remediation, list) and remediation
        assert any("重试" in str(item) for item in remediation)
    finally:
        manager.close()


# ---- B3：删会话保留已判定单元 tombstone ----


def _tombstone_rows(store: RuntimeStore) -> list[sqlite3.Row]:
    with sqlite3.connect(store.path) as connection:
        connection.row_factory = sqlite3.Row
        return connection.execute(
            "SELECT * FROM pending_diff_tombstones"
        ).fetchall()


def test_delete_thread_keeps_decided_units_as_tombstones(tmp_path: Path):
    store = RuntimeStore(tmp_path)
    _store_run(store, "run_tomb", thread_id="thread_tomb")
    store.transition("run_tomb", AgentRunStatus.RUNNING, message="Started.")
    store.finalize_run(
        "run_tomb", AgentRunOutcome(status=AgentRunStatus.SUCCEEDED, message="Done.")
    )
    store.save_pending_diff(
        PendingDiff(
            diff_id="diff_run_tomb_1",
            run_id="run_tomb",
            thread_id="thread_tomb",
            snapshot_commit="aaa1111",
            head_commit="bbb2222",
            commits=["bbb2222", "aaa1111"],
            files=["wiki/a.md", "wiki/b.md", "wiki/c.md"],
            status=PendingDiffStatus.ACCEPTED,
            resolved_at=datetime.now(UTC),
            data={"revert_commits": ["ccc3333"]},
        )
    )

    assert store.delete_thread("thread_tomb") == 1

    rows = _tombstone_rows(store)
    assert len(rows) == 1
    row = rows[0]
    assert row["diff_id"] == "diff_run_tomb_1"
    assert row["verdict"] == PendingDiffStatus.ACCEPTED.value
    assert json.loads(row["commits"]) == ["bbb2222", "aaa1111"]
    assert row["files_count"] == 3
    assert json.loads(row["files_summary"]) == ["wiki/a.md", "wiki/b.md", "wiki/c.md"]
    assert json.loads(row["revert_commits"]) == ["ccc3333"]
    # 级联删除照旧：runs 与 pending diffs 消失，判定摘要在 tombstone 存活。
    assert store.list_runs(thread_id="thread_tomb") == []
    assert store.list_pending_diffs() == []


def test_delete_thread_with_pending_unit_still_blocked(tmp_path: Path):
    """未判定单元仍被护栏拦截，tombstone 不产生。"""
    store = RuntimeStore(tmp_path)
    _store_run(store, "run_blocked", thread_id="thread_blocked")
    store.save_pending_diff(
        PendingDiff(
            diff_id="diff_run_blocked_1",
            run_id="run_blocked",
            thread_id="thread_blocked",
            snapshot_commit="aaa1111",
            head_commit="bbb2222",
            commits=["bbb2222"],
            files=["wiki/a.md"],
            status=PendingDiffStatus.PENDING,
        )
    )

    with pytest.raises(ThreadDeletionBlockedError):
        store.delete_thread("thread_blocked")

    assert _tombstone_rows(store) == []
    assert store.get_pending_diff("diff_run_blocked_1").status is (
        PendingDiffStatus.PENDING
    )


# ---- B3：log.md 人读条目附 diff_id ----


def test_log_entry_includes_diff_id():
    diff = PendingDiff(
        diff_id="diff_run_x_1",
        run_id="run_x",
        thread_id="thread_x",
        commits=["bbb2222", "aaa1111"],
        files=["alpha-cell.md"],
    )
    entry = _log_entry("accepted", "run_x", None, diff)
    assert "- diff: diff_run_x_1" in entry
    assert "commits:" in entry

    unfinished = _log_entry("unfinished", "run_x", None, None, note="budget_or_timeout")
    assert "- diff:" not in unfinished
