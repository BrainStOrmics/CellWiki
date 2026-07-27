# =============================================================================
# 运行时存储测试 —— 验证运行时状态存储的正确性
# =============================================================================

from pathlib import Path

import pytest

from cellwiki.domain.runs import AgentEventType, AgentRun, AgentRunStatus
from cellwiki.services.runtime_store import InvalidRunTransitionError, RuntimeStore


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


def test_runtime_store_rejects_invalid_state_transition(tmp_path: Path):
    store = RuntimeStore(tmp_path)
    store.create_run(AgentRun(run_id="run_terminal", thread_id="thread_one"))
    store.transition("run_terminal", AgentRunStatus.RUNNING)
    store.transition("run_terminal", AgentRunStatus.SUCCEEDED)

    with pytest.raises(InvalidRunTransitionError):
        store.transition("run_terminal", AgentRunStatus.RUNNING)


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

    assert store.delete_thread("thread_delete") == 1
    assert store.list_messages("thread_delete") == []
    assert store.list_runs(thread_id="thread_delete") == []
    assert [run.run_id for run in store.list_runs(thread_id="thread_keep")] == ["run_other"]


def test_runtime_store_backfills_messages_from_legacy_run_and_final_event(tmp_path: Path):
    store = RuntimeStore(tmp_path)
    store.create_run(
        AgentRun(run_id="run_legacy", thread_id="thread_legacy", input_message="old question")
    )
    store.append_event(
        "run_legacy",
        AgentEventType.FINAL_RESPONSE,
        message="old answer",
        data={"confidence": "medium"},
    )

    # Simulate the database shape produced before agent_messages was introduced.
    with store._connect() as connection:
        connection.execute("DELETE FROM agent_messages WHERE thread_id = ?", ("thread_legacy",))

    upgraded = RuntimeStore(tmp_path)
    assert [(item["role"], item["content"]) for item in upgraded.list_messages("thread_legacy")] == [
        ("user", "old question"),
        ("assistant", "old answer"),
    ]


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
