from pathlib import Path

from cellwiki.domain.runs import AgentEventType, AgentRun
from cellwiki.services.conversation_context import ConversationContextView
from cellwiki.services.runtime_store import RuntimeStore


def test_conversation_context_uses_only_observable_messages(tmp_path: Path):
    store = RuntimeStore(tmp_path)
    first = AgentRun(
        run_id="run_first",
        thread_id="thread_context",
        input_message="上次检查结果是什么？",
    )
    store.create_run(first)
    store.append_event(
        first.run_id,
        AgentEventType.TOOL_COMPLETED,
        message='{"raw":"large technical payload"}',
        data={"node": "PatchToolCallsMiddleware", "metadata": {"cancelled": True}},
    )
    store.append_message(
        thread_id=first.thread_id,
        run_id=first.run_id,
        role="assistant",
        content="上次运行失败，没有完成检查。",
        data={"answer": "上次运行失败，没有完成检查。"},
    )
    second = AgentRun(
        run_id="run_second",
        thread_id="thread_context",
        input_message="那现在呢？",
    )
    store.create_run(second)

    messages = ConversationContextView(store).build(
        thread_id="thread_context",
        current_run_id=second.run_id,
        current_content="那现在呢？",
    )
    rendered = "\n".join(str(message["content"]) for message in messages)

    assert [message["role"] for message in messages] == ["user", "assistant", "user"]
    assert "PatchToolCallsMiddleware" not in rendered
    assert "large technical payload" not in rendered
    assert "上次运行失败" in rendered
