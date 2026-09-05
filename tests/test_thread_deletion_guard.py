# =============================================================================
# 线程删除护栏测试 —— 活动 run 与未判定审批单元不得被删除抹掉
# =============================================================================
# as-built：`RuntimeStore.delete_thread` 无条件 `DELETE FROM pending_diffs`，
# 对"未判定审批单元 / 活动 run"没有任何护栏。于是删线程成了绕过阻断式审批的
# 后门（待确认 diff 直接消失），也会把正在执行的 worker 的写入目标抽走。
# 本文件锁定：护栏拒绝删除并给出可诊断错误，API 映射为 409；真终态且无未判定
# 单元的线程仍可删除。
# =============================================================================

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cellwiki.api.app import create_app
from cellwiki.domain.pending_diff import PendingDiff, PendingDiffStatus
from cellwiki.domain.runs import (
    AgentErrorType,
    AgentRun,
    AgentRunOutcome,
    AgentRunStatus,
)
from cellwiki.services.agent_runtime import AgentRuntimeManager
from cellwiki.services.runtime_store import (
    RuntimeStore,
    ThreadDeletionBlockedError,
)


def _run(run_id: str, thread_id: str = "thread_guard") -> AgentRun:
    return AgentRun(run_id=run_id, thread_id=thread_id, input_message="inspect")


def _pending_unit(diff_id: str, run_id: str, thread_id: str = "thread_guard") -> PendingDiff:
    return PendingDiff(
        diff_id=diff_id,
        run_id=run_id,
        thread_id=thread_id,
        project_id="cellwiki",
        snapshot_commit="aaa1111",
        head_commit="bbb2222",
        commits=["bbb2222"],
        files=["wiki/x.md"],
        status=PendingDiffStatus.PENDING,
    )


def test_delete_thread_is_blocked_while_a_run_is_active(tmp_path: Path):
    store = RuntimeStore(tmp_path)
    store.create_run(_run("run_active"))
    store.transition("run_active", AgentRunStatus.RUNNING, message="Started.")

    with pytest.raises(ThreadDeletionBlockedError) as blocked:
        store.delete_thread("thread_guard")

    # 拒绝必须是可诊断的：错误里点名阻塞者，用户才知道要先做什么。
    assert "run_active" in str(blocked.value)
    assert store.get_run("run_active").status is AgentRunStatus.RUNNING
    assert [item["thread_id"] for item in store.list_threads()] == ["thread_guard"]


def test_delete_thread_is_blocked_by_an_undecided_approval_unit(tmp_path: Path):
    """未判定审批单元是阻断式门禁；删线程不得成为绕过它的后门。"""
    store = RuntimeStore(tmp_path)
    store.create_run(_run("run_decided"))
    store.transition("run_decided", AgentRunStatus.RUNNING, message="Started.")
    store.transition("run_decided", AgentRunStatus.WAITING_APPROVAL, message="Awaiting review.")
    store.save_pending_diff(_pending_unit("diff_run_decided_1", "run_decided"))

    with pytest.raises(ThreadDeletionBlockedError) as blocked:
        store.delete_thread("thread_guard")

    assert "diff_run_decided_1" in str(blocked.value)
    assert (
        store.get_pending_diff("diff_run_decided_1").status is PendingDiffStatus.PENDING
    )


def test_delete_thread_is_blocked_by_an_unfinished_run(tmp_path: Path):
    """unfinished 仍可续跑，删掉它等于丢弃用户的可恢复工作。"""
    store = RuntimeStore(tmp_path)
    store.create_run(_run("run_paused"))
    store.transition("run_paused", AgentRunStatus.RUNNING, message="Started.")
    store.transition(
        "run_paused",
        AgentRunStatus.UNFINISHED,
        error_type=AgentErrorType.BUDGET,
        error_message="budget exhausted",
        message="Paused.",
    )

    with pytest.raises(ThreadDeletionBlockedError):
        store.delete_thread("thread_guard")

    assert store.get_run("run_paused").status is AgentRunStatus.UNFINISHED


def test_delete_thread_allows_a_settled_conversation(tmp_path: Path):
    """护栏只收紧不封锁：真终态且无未判定单元的线程仍可删除。"""
    store = RuntimeStore(tmp_path)
    store.create_run(_run("run_done"))
    store.transition("run_done", AgentRunStatus.RUNNING, message="Started.")
    store.finalize_run(
        "run_done", AgentRunOutcome(status=AgentRunStatus.SUCCEEDED, message="Done.")
    )
    store.save_pending_diff(_pending_unit("diff_run_done_1", "run_done"))
    store.update_pending_diff(
        "diff_run_done_1", status=PendingDiffStatus.ACCEPTED, resolution="accepted"
    )

    assert store.delete_thread("thread_guard") == 1
    assert store.list_runs(thread_id="thread_guard") == []
    assert store.list_pending_diffs(run_id="run_done") == []


def test_delete_thread_allows_a_zero_run_placeholder(tmp_path: Path):
    store = RuntimeStore(tmp_path)
    store.create_thread("thread_placeholder")

    assert store.delete_thread("thread_placeholder") == 0


def test_delete_thread_endpoint_reports_a_blocked_deletion_as_409(tmp_path: Path):
    manager = AgentRuntimeManager(tmp_path)
    try:
        client = TestClient(create_app(tmp_path, agent_runtime=manager))
        store = manager.store
        store.create_run(_run("run_live", "thread_api"))
        store.transition("run_live", AgentRunStatus.RUNNING, message="Started.")

        response = client.delete("/api/agent/threads/thread_api")

        assert response.status_code == 409, response.text
        assert "run_live" in response.json()["detail"]
        assert store.get_run("run_live").status is AgentRunStatus.RUNNING
    finally:
        manager.close()


def test_delete_thread_endpoint_still_deletes_a_settled_conversation(tmp_path: Path):
    manager = AgentRuntimeManager(tmp_path)
    try:
        client = TestClient(create_app(tmp_path, agent_runtime=manager))
        store = manager.store
        store.create_run(_run("run_settled", "thread_settled"))
        store.transition("run_settled", AgentRunStatus.RUNNING, message="Started.")
        store.finalize_run(
            "run_settled",
            AgentRunOutcome(status=AgentRunStatus.SUCCEEDED, message="Done."),
        )

        response = client.delete("/api/agent/threads/thread_settled")

        assert response.status_code == 200, response.text
        assert response.json()["deleted_runs"] == 1
    finally:
        manager.close()
