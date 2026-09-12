# =============================================================================
# 运行时存储测试 —— 验证运行时状态存储的正确性
# =============================================================================

from pathlib import Path
import json
import shutil
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from cellwiki.domain.pending_diff import PendingDiff, PendingDiffStatus
from cellwiki.domain.runs import (
    AgentErrorType,
    AgentEventType,
    AgentRun,
    AgentRunOutcome,
    AgentRunStatus,
    AgentSpan,
)
from cellwiki.services.runtime_store import (
    InvalidRunTransitionError,
    RuntimeStore,
    TerminalRunError,
)


def _unit(diff_id: str, status: PendingDiffStatus = PendingDiffStatus.PENDING) -> PendingDiff:
    return PendingDiff(
        diff_id=diff_id,
        run_id="run_units",
        thread_id="thread_units",
        project_id="cellwiki",
        snapshot_commit="abc1234",
        head_commit="def5678",
        commits=["def5678"],
        files=["wiki/x.md"],
        status=status,
    )


def test_pending_diff_units_are_write_once(tmp_path: Path):
    """审批单元 = 一行一次判定：pending 行可就地刷新，已判定行不可复用/不可回退。"""
    store = RuntimeStore(tmp_path)
    run = AgentRun(run_id="run_units", thread_id="thread_units", input_message="x")
    store.create_run(run)

    # 插入单元 1（pending），question 挂起后续跑就地刷新同一行。
    store.save_pending_diff(_unit("diff_run_units_1"))
    refreshed = store.save_pending_diff(
        _unit("diff_run_units_1").model_copy(update={"head_commit": "9999aaa"})
    )
    assert store.get_pending_diff("diff_run_units_1").head_commit == "9999aaa"
    # 就地刷新保留原 created_at（单元顺序稳定）。
    assert refreshed.created_at == store.get_pending_diff("diff_run_units_1").created_at

    # 判定后该行只写一次：不得被重发布覆盖回 pending。
    store.update_pending_diff(
        "diff_run_units_1", status=PendingDiffStatus.ACCEPTED, resolution="accepted"
    )
    with pytest.raises(InvalidRunTransitionError):
        store.save_pending_diff(_unit("diff_run_units_1"))
    # 已判定记录不能被重新置为 pending。
    with pytest.raises(InvalidRunTransitionError):
        store.update_pending_diff("diff_run_units_1", status=PendingDiffStatus.PENDING)
    assert store.get_pending_diff("diff_run_units_1").status == PendingDiffStatus.ACCEPTED

    # 下一单元是独立新行，二者并存。
    store.save_pending_diff(_unit("diff_run_units_2"))
    ids = {d.diff_id for d in store.list_pending_diffs(run_id="run_units")}
    assert ids == {"diff_run_units_1", "diff_run_units_2"}



def test_runtime_store_persists_runs_and_orders_events_across_instances(tmp_path: Path):
    first = RuntimeStore(tmp_path)
    run = AgentRun(run_id="run_persisted", thread_id="thread_one", input_message="hello")
    first.create_run(run)
    first.transition("run_persisted", AgentRunStatus.RUNNING, message="Started.")
    first.append_event("run_persisted", AgentEventType.PROGRESS, progress=25)

    # A fresh repository instance models a Product API process restart.
    second = RuntimeStore(tmp_path)
    restored = second.get_run("run_persisted")
    events = second.list_events("run_persisted")

    assert restored.status == AgentRunStatus.RUNNING
    assert [event.sequence for event in events] == [1, 2, 3]
    assert [event.type for event in events[:2]] == [
        AgentEventType.RUN_STATUS,
        AgentEventType.RUN_STATUS,
    ]
    assert second.list_runs(thread_id="thread_one") == [restored]


def test_runtime_store_releases_sqlite_file_handle_after_operations(tmp_path: Path):
    project_root = tmp_path / "disposable_project"
    store = RuntimeStore(project_root)

    store.list_runs()
    shutil.rmtree(project_root)

    assert not project_root.exists()


def test_history_projection_settles_running_steps_from_terminal_status(tmp_path: Path):
    store = RuntimeStore(tmp_path)
    run = AgentRun(
        run_id="run_settled_history",
        thread_id="thread_settled_history",
        input_message="inspect",
    )
    store.create_run(run)
    store.transition(run.run_id, AgentRunStatus.RUNNING)
    store.append_event(
        run.run_id,
        AgentEventType.TOOL_STARTED,
        message="Reading page.",
        data={"tool_name": "read_wiki_page"},
    )
    store.append_message(
        thread_id=run.thread_id,
        run_id=run.run_id,
        role="assistant",
        content="Provider timed out.",
    )
    store.finalize_run(
        run.run_id,
        AgentRunOutcome(
            status=AgentRunStatus.FAILED,
            message="Run failed.",
            error_type=AgentErrorType.TIMEOUT,
            error_message="Provider timed out.",
        ),
    )

    assistant = next(
        message
        for message in store.list_messages(run.thread_id)
        if message["role"] == "assistant"
    )
    assert assistant["data"]["process"][0]["phase"] == "failed"


def test_runtime_store_rejects_invalid_state_transition(tmp_path: Path):
    store = RuntimeStore(tmp_path)
    store.create_run(AgentRun(run_id="run_terminal", thread_id="thread_one"))
    store.transition("run_terminal", AgentRunStatus.RUNNING)
    store.transition("run_terminal", AgentRunStatus.SUCCEEDED)

    with pytest.raises(InvalidRunTransitionError):
        store.transition("run_terminal", AgentRunStatus.RUNNING)


def test_runtime_store_finalizes_failure_atomically_and_only_once(tmp_path: Path):
    store = RuntimeStore(tmp_path)
    store.create_run(AgentRun(run_id="run_failed", thread_id="thread_one"))
    store.transition("run_failed", AgentRunStatus.RUNNING)

    outcome = AgentRunOutcome(
        status=AgentRunStatus.FAILED,
        message="Run failed.",
        error_type=AgentErrorType.TIMEOUT,
        error_message="provider timed out",
        retryable=True,
    )
    first = store.finalize_run("run_failed", outcome)
    second = store.finalize_run("run_failed", outcome)
    events = store.list_events("run_failed")

    assert first == second
    assert first.finished_at is not None
    assert [event.type for event in events[-2:]] == [
        AgentEventType.ERROR,
        AgentEventType.RUN_STATUS,
    ]
    assert events[-1].data == {
        "status": "failed",
        "terminal": True,
        "error_type": "timeout",
        "error_message": "provider timed out",
        "retryable": True,
        "finished_at": first.finished_at.isoformat(),
    }
    assert sum(
        event.type == AgentEventType.RUN_STATUS and event.data.get("terminal") is True
        for event in events
    ) == 1

    with pytest.raises(TerminalRunError):
        store.append_event("run_failed", AgentEventType.PROGRESS, message="too late")


def test_runtime_store_persists_thread_messages_and_deletes_the_whole_thread(tmp_path: Path):
    store = RuntimeStore(tmp_path)
    store.create_run(
        AgentRun(run_id="run_message", thread_id="thread_delete", input_message="hello")
    )
    store.append_message(
        thread_id="thread_delete",
        run_id="run_message",
        role="assistant",
        content="answer",
        data={"citations": [{"page_id": "t_cell"}]},
    )
    store.create_run(AgentRun(run_id="run_other", thread_id="thread_keep", input_message="keep"))

    messages = store.list_messages("thread_delete")
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert messages[1]["data"] == {"citations": [{"page_id": "t_cell"}]}

    # 删除护栏只放行已收敛的会话（见 tests/test_thread_deletion_guard.py）：
    # 新建 run 停在 QUEUED，先落到终态再删。
    store.transition("run_message", AgentRunStatus.RUNNING, message="Started.")
    store.finalize_run(
        "run_message",
        AgentRunOutcome(status=AgentRunStatus.SUCCEEDED, message="Done."),
    )
    assert store.delete_thread("thread_delete") == 1
    assert store.list_messages("thread_delete") == []
    assert store.list_runs(thread_id="thread_delete") == []
    assert [run.run_id for run in store.list_runs(thread_id="thread_keep")] == ["run_other"]


def test_runtime_store_persists_message_attachment_references_and_recovers_ids(tmp_path: Path):
    store = RuntimeStore(tmp_path)
    attachment_id = "att_" + "a" * 32
    run = AgentRun(
        run_id="run_attachment_message",
        thread_id="thread_attachment_message",
        input_message="Read the attached paper.",
        attachment_ids=[attachment_id],
    )
    store.create_run(
        run,
        user_message_data={
            "attachments": [
                {
                    "attachment_id": attachment_id,
                    "original_name": "paper.pdf",
                    "media_type": "application/pdf",
                    "content_hash": "sha256:" + "b" * 64,
                    "size_bytes": 128,
                }
            ]
        },
    )

    message = store.list_messages(run.thread_id)[0]

    assert message["data"]["attachments"][0]["attachment_id"] == attachment_id
    assert store.list_thread_attachment_ids(run.thread_id) == [attachment_id]
    assert message["data"]["attachments"][0]["original_name"] == "paper.pdf"
    assert "text" not in message["data"]["attachments"][0]


def test_runtime_store_backfills_messages_from_legacy_run_and_final_event(tmp_path: Path):
    store = RuntimeStore(tmp_path)
    attachment_id = "att_" + "c" * 32
    store.create_run(
        AgentRun(
            run_id="run_legacy",
            thread_id="thread_legacy",
            input_message="old question",
            attachment_ids=[attachment_id],
        )
    )
    store.append_event(
        "run_legacy",
        AgentEventType.FINAL_RESPONSE,
        message="old answer",
        data={"confidence": "medium"},
    )

    # Simulate an old message row that recorded the attachment only on AgentRun.
    with store._connect() as connection:
        connection.execute(
            "UPDATE agent_messages SET data = '{}' WHERE thread_id = ? AND role = 'user'",
            ("thread_legacy",),
        )

    upgraded = RuntimeStore(tmp_path)
    messages = upgraded.list_messages("thread_legacy")
    assert [(item["role"], item["content"]) for item in messages] == [
        ("user", "old question"),
        ("assistant", "old answer"),
    ]
    assert messages[0]["data"]["attachments"] == [{"attachment_id": attachment_id}]


def test_runtime_store_scrubs_retired_payload_fields_from_legacy_rows(tmp_path: Path):
    """删字段升级回归：旧 payload 带退役字段时运行库必须仍能打开。

    严格契约（extra="forbid"）会把带已删字段的行判为非法；启动守卫要在校验
    发生前清掉它，且不损伤同一 payload 的其余字段。
    """
    store = RuntimeStore(tmp_path)
    store.create_run(
        AgentRun(run_id="run_retired", thread_id="thread_retired", input_message="old question")
    )
    store.upsert_span(
        AgentSpan(
            span_id="span_retired",
            run_id="run_retired",
            kind="model",
            name="coordinator",
            status="succeeded",
            started_at=datetime.now(UTC),
            output_tokens=17,
        )
    )

    # 模拟旧版本写下的 payload：usage 与 span 顶部各带一个已退役的 ttft_ms。
    with store._connect() as connection:
        run_payload = json.loads(
            connection.execute(
                "SELECT payload FROM agent_runs WHERE run_id = ?", ("run_retired",)
            ).fetchone()[0]
        )
        run_payload["usage"]["ttft_ms"] = None
        connection.execute(
            "UPDATE agent_runs SET payload = ? WHERE run_id = ?",
            (json.dumps(run_payload), "run_retired"),
        )
        span_payload = json.loads(
            connection.execute(
                "SELECT payload FROM agent_spans WHERE span_id = ?", ("span_retired",)
            ).fetchone()[0]
        )
        span_payload["ttft_ms"] = None
        connection.execute(
            "UPDATE agent_spans SET payload = ? WHERE span_id = ?",
            (json.dumps(span_payload), "span_retired"),
        )
    with pytest.raises(ValidationError):
        AgentRun.model_validate_json(json.dumps(run_payload))

    upgraded = RuntimeStore(tmp_path)

    assert upgraded.get_run("run_retired").input_message == "old question"
    span = upgraded.list_spans("run_retired")[0]
    assert (span.name, span.output_tokens) == ("coordinator", 17)
    with upgraded._connect() as connection:
        assert (
            "ttft_ms"
            not in connection.execute(
                "SELECT payload FROM agent_runs WHERE run_id = ?", ("run_retired",)
            ).fetchone()[0]
        )
        assert (
            "ttft_ms"
            not in connection.execute(
                "SELECT payload FROM agent_spans WHERE span_id = ?", ("span_retired",)
            ).fetchone()[0]
        )
    RuntimeStore(tmp_path)


def test_reopening_the_store_backfills_streamed_reasoning_into_the_answer(tmp_path: Path):
    """思考块回归（2026-09-11）：旧消息写的时候还不带思考，只在事件流里有；重开会话
    只回放最新一条 run 的事件，所以这些历史 run 的思考块要靠启动回填补进消息记录。

    回填必须幂等：已经带上思考的消息不再动，事件扫描只服务还缺思考的 run。
    """
    store = RuntimeStore(tmp_path)
    store.create_run(
        AgentRun(run_id="run_reasoning", thread_id="thread_reasoning", input_message="q")
    )
    store.append_event("run_reasoning", AgentEventType.REASONING_DELTA, message="先查台账。")
    store.append_event(
        "run_reasoning", AgentEventType.REASONING_DELTA, message="路径不对，改读 index.md。"
    )
    store.append_message(
        thread_id="thread_reasoning",
        run_id="run_reasoning",
        role="assistant",
        content="答案",
        data={"source": "agent_runtime"},
    )

    upgraded = RuntimeStore(tmp_path)
    assert (
        upgraded.list_messages("thread_reasoning")[1]["data"]["reasoning"]
        == "先查台账。路径不对，改读 index.md。"
    )

    # 已带思考的消息不再被回填覆盖，即使事件流之后又多了增量。
    store.append_event("run_reasoning", AgentEventType.REASONING_DELTA, message="后补增量")
    again = RuntimeStore(tmp_path)
    assert (
        again.list_messages("thread_reasoning")[1]["data"]["reasoning"]
        == "先查台账。路径不对，改读 index.md。"
    )


def test_runtime_store_projects_displayable_events_into_assistant_history(tmp_path: Path):
    store = RuntimeStore(tmp_path)
    run = AgentRun(run_id="run_process", thread_id="thread_process", input_message="question")
    store.create_run(run)
    store.append_event(
        run.run_id,
        AgentEventType.TOOL_STARTED,
        message="读取当前 Wiki 页面",
        data={"tool_name": "read_wiki_page"},
    )
    store.append_event(run.run_id, AgentEventType.PROGRESS, message="正在整理证据", progress=60)
    store.append_event(
        run.run_id,
        AgentEventType.TOOL_COMPLETED,
        message="页面读取完成",
        data={"tool_name": "read_wiki_page"},
    )
    store.append_message(
        thread_id=run.thread_id,
        run_id=run.run_id,
        role="assistant",
        content="answer",
        data={},
    )

    history = store.list_messages(run.thread_id)
    assert "process" not in history[0]["data"]
    assert [(step["type"], step["phase"]) for step in history[1]["data"]["process"]] == [
        ("tool_started", "running"),
        ("progress", "completed"),
        ("tool_completed", "completed"),
    ]
