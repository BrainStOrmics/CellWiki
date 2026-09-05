# =============================================================================
# 运行门禁测试 —— resume 准入收窄与"单一状态迁移入口"合同
# =============================================================================
# 锁定两条门禁事实：
# 1. `claim_resume_unfinished` 是崩溃恢复入口，只接受 UNFINISHED。它曾用
#    `RUNNING in _TRANSITIONS[current]` 作准入判据，而 QUEUED /
#    WAITING_CONFIRMATION / WAITING_APPROVAL 三者的后继集合都含 RUNNING，
#    于是"待确认 diff 尚未判定"也能被 resume 拉回 RUNNING —— 审批门禁绕过。
#    WAITING_CONFIRMATION 的续跑走 answer_question 专用入口，
#    WAITING_APPROVAL 的合法续跑走 claim_resume（不得被误删）。
# 2. 每条推进 run 状态的路径都必须经过 `_assert_run_transition` 这一个入口，
#    后续阶段新增路径不得各自另写一份合法性判定。
# =============================================================================

from __future__ import annotations

from pathlib import Path

import pytest

from cellwiki.domain.pending_diff import PendingDiff, PendingDiffStatus
from cellwiki.domain.questions import PendingQuestion
from cellwiki.domain.runs import (
    AgentErrorType,
    AgentRun,
    AgentRunOutcome,
    AgentRunStatus,
)
from cellwiki.services import runtime_store as runtime_store_module
from cellwiki.services.runtime_store import (
    ACTIVE_RUN_STATUSES,
    InvalidRunTransitionError,
    RuntimeStore,
)


def _run(run_id: str, thread_id: str = "thread_gates") -> AgentRun:
    return AgentRun(run_id=run_id, thread_id=thread_id, input_message="inspect the wiki")


def _store_with_run_at(
    tmp_path: Path, status: AgentRunStatus, run_id: str = "run_gated"
) -> RuntimeStore:
    """Create one run and drive it to ``status`` through legal transitions."""
    store = RuntimeStore(tmp_path)
    store.create_run(_run(run_id))
    if status is AgentRunStatus.QUEUED:
        return store
    store.transition(run_id, AgentRunStatus.RUNNING, message="Started.")
    if status is AgentRunStatus.RUNNING:
        return store
    if status is AgentRunStatus.UNFINISHED:
        store.transition(
            run_id,
            AgentRunStatus.UNFINISHED,
            error_type=AgentErrorType.BUDGET,
            error_message="budget exhausted",
            message="Paused.",
        )
        return store
    if status is AgentRunStatus.SUCCEEDED:
        store.finalize_run(
            run_id, AgentRunOutcome(status=AgentRunStatus.SUCCEEDED, message="Done.")
        )
        return store
    store.transition(run_id, status, message="Gated.")
    return store


# ---- resume 准入：只接受 UNFINISHED ----


def test_claim_resume_unfinished_accepts_only_the_unfinished_state(tmp_path: Path):
    store = _store_with_run_at(tmp_path, AgentRunStatus.UNFINISHED)

    resumed = store.claim_resume_unfinished("run_gated")

    assert resumed.status is AgentRunStatus.RUNNING
    assert resumed.finished_at is None
    assert resumed.error_type is None


def test_claim_resume_unfinished_cannot_bypass_the_approval_gate(tmp_path: Path):
    """待确认 diff 未判定时，resume 不得把 run 拉回 RUNNING（审批绕过路径）。"""
    store = _store_with_run_at(tmp_path, AgentRunStatus.WAITING_APPROVAL)
    store.save_pending_diff(
        PendingDiff(
            diff_id="diff_run_gated_1",
            run_id="run_gated",
            thread_id="thread_gates",
            project_id="cellwiki",
            snapshot_commit="aaa1111",
            head_commit="bbb2222",
            commits=["bbb2222"],
            files=["wiki/x.md"],
            status=PendingDiffStatus.PENDING,
        )
    )

    with pytest.raises(InvalidRunTransitionError):
        store.claim_resume_unfinished("run_gated")

    # 门禁未松动：run 仍在等待审批，审批单元仍未判定。
    assert store.get_run("run_gated").status is AgentRunStatus.WAITING_APPROVAL
    assert (
        store.get_pending_diff("diff_run_gated_1").status is PendingDiffStatus.PENDING
    )


def test_claim_resume_unfinished_rejects_a_pending_question_run(tmp_path: Path):
    """WAITING_CONFIRMATION 的续跑入口是 answer_question，不是崩溃恢复。"""
    store = _store_with_run_at(tmp_path, AgentRunStatus.WAITING_CONFIRMATION)

    with pytest.raises(InvalidRunTransitionError):
        store.claim_resume_unfinished("run_gated")

    assert store.get_run("run_gated").status is AgentRunStatus.WAITING_CONFIRMATION


def test_claim_resume_unfinished_rejects_a_queued_run(tmp_path: Path):
    """QUEUED 尚未执行，没有 checkpoint 可续；放行会让 worker 与 claim 抢同一 run。"""
    store = _store_with_run_at(tmp_path, AgentRunStatus.QUEUED)

    with pytest.raises(InvalidRunTransitionError):
        store.claim_resume_unfinished("run_gated")

    assert store.get_run("run_gated").status is AgentRunStatus.QUEUED


def test_claim_resume_still_reopens_a_waiting_approval_run(tmp_path: Path):
    """收窄 resume 不得误删 WAITING_APPROVAL -> RUNNING 的合法审批续跑用途。"""
    store = _store_with_run_at(tmp_path, AgentRunStatus.WAITING_APPROVAL)

    claimed = store.claim_resume("run_gated", decision="approve")

    assert claimed.status is AgentRunStatus.RUNNING


def test_claim_task_confirmation_still_reopens_a_waiting_question_run(tmp_path: Path):
    store = _store_with_run_at(tmp_path, AgentRunStatus.WAITING_CONFIRMATION)

    claimed = store.claim_task_confirmation("run_gated", decision="execute")

    assert claimed.status is AgentRunStatus.RUNNING


# ---- 活动 run 状态集合（删除护栏与串行闸门共用的定义）----


def test_active_run_statuses_cover_every_gated_state(tmp_path: Path):
    """删除护栏的活动集合必须覆盖串行闸门与两个等待态，否则护栏可被绕过。"""
    assert ACTIVE_RUN_STATUSES == frozenset(
        {
            AgentRunStatus.QUEUED,
            AgentRunStatus.RUNNING,
            AgentRunStatus.RETRYING,
            AgentRunStatus.CANCELLING,
            AgentRunStatus.UNFINISHED,
            AgentRunStatus.WAITING_CONFIRMATION,
            AgentRunStatus.WAITING_APPROVAL,
        }
    )
    # 真终态不在活动集合内：它们才是可删除的。
    assert not (
        ACTIVE_RUN_STATUSES
        & {
            AgentRunStatus.SUCCEEDED,
            AgentRunStatus.REJECTED,
            AgentRunStatus.FAILED,
            AgentRunStatus.CANCELLED,
        }
    )


# ---- 单一迁移入口 ----


def _question(run_id: str = "run_gated") -> PendingQuestion:
    return PendingQuestion(
        question_id="q_gates_1",
        run_id=run_id,
        thread_id="thread_gates",
        tool_call_id="call_1",
        question="Which page should I open?",
        options=["index.md"],
        required=True,
    )


def test_every_run_advance_path_routes_through_the_single_transition_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """任何推进 run 状态的路径都必须调用 `_assert_run_transition`。

    把单一入口替换成必定抛错的哨兵：每条路径都必须把哨兵透出来，否则说明
    它自己另写了一份合法性判定（后续阶段新增路径时的回归锁）。
    """

    class _Sentinel(InvalidRunTransitionError):
        pass

    def _always_reject(*args: object, **kwargs: object) -> None:
        raise _Sentinel("single transition gate reached")

    monkeypatch.setattr(
        runtime_store_module, "_assert_run_transition", _always_reject
    )

    store = RuntimeStore(tmp_path)
    store.create_run(_run("run_gate"))

    with pytest.raises(_Sentinel):
        store.transition("run_gate", AgentRunStatus.RUNNING)
    with pytest.raises(_Sentinel):
        store.finalize_run(
            "run_gate", AgentRunOutcome(status=AgentRunStatus.SUCCEEDED, message="Done.")
        )
    with pytest.raises(_Sentinel):
        store.save_pending_question_and_transition(
            _question("run_gate"), message="Waiting."
        )
    with pytest.raises(_Sentinel):
        store.claim_resume_unfinished("run_gate")
    with pytest.raises(_Sentinel):
        store.claim_resume("run_gate", decision="approve")
    with pytest.raises(_Sentinel):
        store.claim_task_confirmation("run_gate", decision="execute")
    with pytest.raises(_Sentinel):
        store.claim_retry("run_gate")


def test_transition_gate_still_rejects_an_illegal_advance(tmp_path: Path):
    """收口到单一入口后，非法迁移仍必须被拒（真终态后继集合为空）。"""
    store = _store_with_run_at(tmp_path, AgentRunStatus.SUCCEEDED)

    with pytest.raises(InvalidRunTransitionError):
        store.transition("run_gated", AgentRunStatus.RUNNING)
