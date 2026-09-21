"""Contract tests for the v2 cache-first model transcript."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessageChunk, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import Field

from cellwiki.agent.app import build_wiki_agent
from cellwiki.domain.contracts import WikiAgentContext
from cellwiki.domain.runs import AgentEventType, AgentRun, AgentRunStatus
from cellwiki.services.agent_runtime import AgentRuntimeManager
from cellwiki.services.model_transcript import render_model_messages
from cellwiki.services.prompt_cache import PromptCachePolicy, resolve_prompt_cache_policy
from cellwiki.services.runtime_store import RuntimeStore

WAIT_TIMEOUT = 30.0
TERMINAL = {
    AgentRunStatus.SUCCEEDED,
    AgentRunStatus.FAILED,
    AgentRunStatus.CANCELLED,
    AgentRunStatus.REJECTED,
    AgentRunStatus.UNFINISHED,
}


class _TranscriptModel(BaseChatModel):
    """Records every model request and can perform one tool call first."""

    model_name: str = "gpt-4.1"
    tool_calls_remaining: int = 0
    seen: list[list[Any]] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "transcript-recording-fake"

    def _get_ls_params(self, **kwargs: Any) -> dict[str, Any]:
        return {"ls_provider": "openai", "ls_model_name": self.model_name}

    def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
        return self

    def _bind_tools(self, tools: Any, **kwargs: Any) -> Any:
        return self

    def _generate(
        self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any
    ) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=AIMessageChunk(content="done"))])

    def _stream(
        self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any
    ):
        self.seen.append(list(messages))
        if self.tool_calls_remaining > 0:
            self.tool_calls_remaining -= 1
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content="",
                    tool_calls=[
                        {
                            "name": "ls",
                            "args": {"path": "."},
                            "id": "call_1",
                            "type": "tool_call",
                        }
                    ],
                )
            )
            return
        yield ChatGenerationChunk(message=AIMessageChunk(content="done"))


class _UsageReportingModel(_TranscriptModel):
    """Reports provider usage so the runtime can record the real prompt size."""

    reported_input_tokens: int = 5_000

    def _stream(
        self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any
    ):
        self.seen.append(list(messages))
        yield ChatGenerationChunk(
            message=AIMessageChunk(
                id="call_measured",
                content="done",
                usage_metadata={
                    "input_tokens": self.reported_input_tokens,
                    "output_tokens": 8,
                    "total_tokens": self.reported_input_tokens + 8,
                },
            )
        )


def _wait(manager: AgentRuntimeManager, run: AgentRun) -> AgentRun:
    deadline = time.monotonic() + WAIT_TIMEOUT
    while time.monotonic() < deadline:
        current = manager.store.get_run(run.run_id)
        if current.status in TERMINAL:
            return current
        time.sleep(0.02)
    raise AssertionError(f"run {run.run_id} did not finish")


def _manager(tmp_path: Path, model: _TranscriptModel) -> AgentRuntimeManager:
    return AgentRuntimeManager(tmp_path, adapter=build_wiki_agent(tmp_path, model=model))


def _turn(manager: AgentRuntimeManager, thread_id: str, message: str) -> AgentRun:
    run = manager.start(
        thread_id=thread_id,
        message=message,
        context=WikiAgentContext(project_id="cellwiki", thread_id=thread_id),
    )
    finished = _wait(manager, run)
    assert finished.status == AgentRunStatus.SUCCEEDED, finished.error_message
    return finished


def _text(message: Any) -> str:
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    return str(content)


def _cache_prefix_signature(message: Any) -> tuple[Any, ...]:
    """Provider-visible payload without LangChain-local message ids."""

    return (
        type(message).__name__,
        getattr(message, "content", None),
        tuple(getattr(message, "tool_calls", []) or []),
        getattr(message, "tool_call_id", None),
        getattr(message, "name", None),
    )


def test_v2_turn_context_is_a_user_tail_without_duplicate_goal(tmp_path: Path):
    model = _TranscriptModel()
    manager = _manager(tmp_path, model)
    try:
        _turn(manager, "thread_v2_tail", "第一问")
    finally:
        manager.close()

    messages = model.seen[0]
    system_messages = [
        message for message in messages if type(message).__name__ == "SystemMessage"
    ]
    assert len(system_messages) == 1
    assert "contract_hash" in _text(system_messages[0])
    assert type(messages[-1]).__name__ == "HumanMessage"
    assert "第一问" in _text(messages[-1])
    assert "## Run context" in _text(messages[-1])
    assert "Run context snapshot" not in _text(messages[-1])
    assert "recent transcript" not in _text(messages[-1])
    assert "current run goal" not in _text(messages[-1])


def test_v2_second_turn_prefix_contains_the_first_turn(tmp_path: Path):
    model = _TranscriptModel()
    manager = _manager(tmp_path, model)
    try:
        _turn(manager, "thread_v2_prefix", "第一问")
        first_request = list(model.seen[-1])
        _turn(manager, "thread_v2_prefix", "第二问")
        second_request = list(model.seen[-1])
    finally:
        manager.close()

    assert [
        _cache_prefix_signature(message)
        for message in second_request[: len(first_request)]
    ] == [_cache_prefix_signature(message) for message in first_request]
    assert "第二问" in _text(second_request[-1])


def test_v2_tool_result_is_replayed_in_the_next_run(tmp_path: Path):
    model = _TranscriptModel(tool_calls_remaining=1)
    manager = _manager(tmp_path, model)
    try:
        _turn(manager, "thread_v2_tool", "列出文件")
        first_run_records = manager.store.list_model_messages("thread_v2_tool")
        kinds = [record["kind"] for record in first_run_records]
        assert "assistant" in kinds
        assert "tool_result" in kinds
        _turn(manager, "thread_v2_tool", "继续")
    finally:
        manager.close()

    second_run_request = model.seen[-1]
    tool_messages = [
        message for message in second_run_request if isinstance(message, ToolMessage)
    ]
    assert len(tool_messages) == 1
    assert tool_messages[0].tool_call_id == "call_1"
    assert "results" in _text(tool_messages[0])


def test_v2_anthropic_format_keeps_one_system_message(tmp_path: Path):
    from langchain_anthropic.chat_models import _format_messages

    model = _TranscriptModel()
    manager = _manager(tmp_path, model)
    try:
        _turn(manager, "thread_v2_anthropic", "第一问")
        _turn(manager, "thread_v2_anthropic", "第二问")
    finally:
        manager.close()

    system, formatted = _format_messages(model.seen[-1])
    assert system is not None
    assert all(item.get("role") != "system" for item in formatted)


def test_cache_policy_defaults_and_override():
    responses = resolve_prompt_cache_policy(
        protocol="responses",
        model_id="gpt-5.6-sol",
        base_url="",
    )
    assert responses.mode == "explicit"
    assert responses.provider_native_compaction is True
    assert responses.breakpoint_key == "prompt_cache_breakpoint"
    assert responses.tool_result_breakpoints == 3
    assert responses.input_window_source == "fallback"
    assert responses.model_input_tokens == 65_536
    assert responses.effective_context_limit == 65_536
    assert responses.compact_threshold == 52_428

    gateway = resolve_prompt_cache_policy(
        protocol="responses",
        model_id="custom-model",
        base_url="https://example.invalid/v1",
    )
    assert gateway.mode == "implicit"
    assert gateway.provider_native_compaction is False

    anthropic = resolve_prompt_cache_policy(
        protocol="anthropic",
        model_id="claude-sonnet-4-6",
    )
    assert anthropic.mode == "explicit"
    assert anthropic.breakpoint_key == "cache_control"

    chat = resolve_prompt_cache_policy(
        protocol="chat_completions",
        model_id="gpt-4.1",
    )
    assert chat.mode == "implicit"
    assert chat.breakpoint_key == ""
    # Model names are not consulted for window resolution: GPT-4.1 and an
    # unknown id receive the same conservative fallback.
    unknown = resolve_prompt_cache_policy(
        protocol="chat_completions",
        model_id="unknown-model",
    )
    assert unknown.model_input_tokens == chat.model_input_tokens
    assert unknown.input_window_source == "fallback"

    configured = resolve_prompt_cache_policy(
        protocol="chat_completions",
        model_id="gpt-4o",
        model_input_tokens=128_000,
        context_max_tokens=512_000,
    )
    assert configured.model_input_tokens == 128_000
    assert configured.input_window_source == "configured"
    assert configured.effective_context_limit == 128_000
    assert configured.compact_threshold == 102_400

    off = resolve_prompt_cache_policy(
        protocol="anthropic",
        model_id="claude-sonnet-4-6",
        request_overrides={"cache_mode": "off"},
    )
    assert off.mode == "off"
    assert off.compact_threshold == 52_428


def test_explicit_cache_markers_cover_static_prefix_and_tool_result(tmp_path: Path):
    model = _TranscriptModel(tool_calls_remaining=1)
    policy = PromptCachePolicy(
        mode="explicit",
        protocol="responses",
        max_breakpoints=4,
        provider_native_compaction=False,
        compact_threshold=52_428,
        breakpoint_key="prompt_cache_breakpoint",
        model_input_tokens=65_536,
        input_window_source="fallback",
        effective_context_limit=65_536,
    )
    manager = AgentRuntimeManager(
        tmp_path,
        adapter=build_wiki_agent(tmp_path, model=model, cache_policy=policy),
    )
    try:
        _turn(manager, "thread_v2_markers", "列出文件")
    finally:
        manager.close()

    system_blocks = model.seen[0][0].content
    assert isinstance(system_blocks, list)
    assert system_blocks[-1]["prompt_cache_breakpoint"] == {"mode": "explicit"}
    tool_message = next(
        message for message in model.seen[1] if isinstance(message, ToolMessage)
    )
    assert isinstance(tool_message.content, list)
    assert tool_message.content[-1]["prompt_cache_breakpoint"] == {"mode": "explicit"}


def test_local_compaction_emits_visible_context_events(
    tmp_path: Path, monkeypatch: Any
) -> None:
    manager = _manager(tmp_path, _TranscriptModel())
    run = AgentRun(
        run_id="run_compact_events",
        thread_id="thread_compact_events",
        input_message="new question",
        transcript_version=2,
    )
    try:
        manager.store.create_run(run)
        manager.store.bootstrap_model_transcript(
            run.thread_id, exclude_run_id=run.run_id
        )
        manager.store.append_model_message(
            thread_id=run.thread_id,
            run_id=run.run_id,
            kind="user",
            role="user",
            content={"text": "decision: keep this"},
            message_key="old",
        )
        policy = PromptCachePolicy(
            mode="implicit",
            protocol="chat_completions",
            max_breakpoints=0,
            provider_native_compaction=False,
            compact_threshold=1,
            breakpoint_key="",
            model_input_tokens=65_536,
            input_window_source="fallback",
            effective_context_limit=65_536,
        )
        monkeypatch.setattr(manager, "_cache_policy_for_run", lambda _run: policy)
        monkeypatch.setattr(
            "cellwiki.services.agent_runtime.split_for_compaction",
            lambda records, retained_tokens: (records, []),
        )
        monkeypatch.setattr(
            "cellwiki.services.agent_runtime.summarize_transcript",
            lambda records: "## Compacted history summary\ndecisions:\n- keep",
        )

        manager._prepare_v2_transcript(
            run,
            "new question",
            WikiAgentContext(project_id="cellwiki", thread_id=run.thread_id),
            adapter=object(),
        )

        events = [
            event
            for event in manager.store.list_events(run.run_id)
            if event.type
            in {
                AgentEventType.CONTEXT_COMPACTION_STARTED,
                AgentEventType.CONTEXT_COMPACTION_COMPLETED,
            }
        ]
        assert [event.type for event in events] == [
            AgentEventType.CONTEXT_COMPACTION_STARTED,
            AgentEventType.CONTEXT_COMPACTION_COMPLETED,
        ]
        assert events[1].data["mode"] == "local"
        assert events[1].data["changed"] is True
    finally:
        manager.close()


def _compaction_events(manager: AgentRuntimeManager, run_id: str) -> list[Any]:
    return [
        event
        for event in manager.store.list_events(run_id)
        if event.type
        in {
            AgentEventType.CONTEXT_COMPACTION_STARTED,
            AgentEventType.CONTEXT_COMPACTION_COMPLETED,
        }
    ]


def _patch_compaction_policy(
    monkeypatch: Any, manager: AgentRuntimeManager, *, threshold: int
) -> None:
    policy = PromptCachePolicy(
        mode="implicit",
        protocol="chat_completions",
        max_breakpoints=0,
        provider_native_compaction=False,
        compact_threshold=threshold,
        breakpoint_key="",
        model_input_tokens=1_000_000,
        input_window_source="configured",
        effective_context_limit=1_000_000,
    )
    monkeypatch.setattr(manager, "_cache_policy_for_run", lambda _run: policy)
    monkeypatch.setattr(
        "cellwiki.services.agent_runtime.split_for_compaction",
        lambda records, retained_tokens: (records, []),
    )
    monkeypatch.setattr(
        "cellwiki.services.agent_runtime.summarize_transcript",
        lambda records: "## Compacted history summary\ndecisions:\n- keep",
    )


def test_measured_prompt_tokens_drive_compaction_before_the_estimate(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """回归：中文/工具结果多时 chars/4 估算只有真实值的零头，压缩必须看真实值。"""

    model = _UsageReportingModel(reported_input_tokens=5_000)
    manager = _manager(tmp_path, model)
    try:
        _turn(manager, "thread_measured", "first question")
        assert manager.store.last_prompt_tokens("thread_measured") == 5_000

        run = AgentRun(
            run_id="run_measured",
            thread_id="thread_measured",
            input_message="second question",
            transcript_version=2,
        )
        manager.store.create_run(run)
        _patch_compaction_policy(monkeypatch, manager, threshold=4_096)
        manager._prepare_v2_transcript(
            run,
            "second question",
            WikiAgentContext(project_id="cellwiki", thread_id="thread_measured"),
            adapter=object(),
        )
        events = _compaction_events(manager, run.run_id)
        assert [event.type for event in events] == [
            AgentEventType.CONTEXT_COMPACTION_STARTED,
            AgentEventType.CONTEXT_COMPACTION_COMPLETED,
        ]
        # 估算远低于阈值，触发只能来自真实值
        assert events[0].data["estimated_tokens"] < 4_096
        assert events[0].data["measured_tokens"] == 5_000
        assert events[1].data["measured_tokens"] == 5_000
        assert events[1].data["changed"] is True
    finally:
        manager.close()


def test_compaction_stays_quiet_without_measurement_and_small_estimate(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """老 thread 无真实记录时退回估算；估算没到阈值就不压缩。"""

    manager = _manager(tmp_path, _TranscriptModel())
    run = AgentRun(
        run_id="run_no_measure",
        thread_id="thread_no_measure",
        input_message="question",
        transcript_version=2,
    )
    try:
        manager.store.create_run(run)
        manager.store.append_model_message(
            thread_id=run.thread_id,
            run_id=run.run_id,
            kind="user",
            role="user",
            content={"text": "a short question"},
            message_key="old",
        )
        assert manager.store.last_prompt_tokens(run.thread_id) is None
        _patch_compaction_policy(monkeypatch, manager, threshold=409_600)
        manager._prepare_v2_transcript(
            run,
            "question",
            WikiAgentContext(project_id="cellwiki", thread_id=run.thread_id),
            adapter=object(),
        )
        assert _compaction_events(manager, run.run_id) == []
    finally:
        manager.close()


def test_record_prompt_tokens_overwrites_so_the_baseline_can_fall(tmp_path: Path) -> None:
    """压缩后 prompt 缩小，基线必须能回落，否则会连环触发压缩。"""

    store = RuntimeStore(tmp_path)
    assert store.last_prompt_tokens("thread_baseline") is None
    store.record_prompt_tokens("thread_baseline", 500_000)
    assert store.last_prompt_tokens("thread_baseline") == 500_000
    store.record_prompt_tokens("thread_baseline", 12_000)
    assert store.last_prompt_tokens("thread_baseline") == 12_000


def test_transcript_compaction_boundary_hides_earlier_messages(tmp_path: Path):
    store = RuntimeStore(tmp_path)
    run = AgentRun(run_id="run_boundary", thread_id="thread_boundary", input_message="u")
    store.create_run(run)
    store.bootstrap_model_transcript("thread_boundary", exclude_run_id=run.run_id)
    store.append_model_message(
        thread_id="thread_boundary",
        run_id=run.run_id,
        kind="user",
        role="user",
        content={"text": "old"},
        message_key="user",
    )
    store.append_model_message(
        thread_id="thread_boundary",
        run_id=run.run_id,
        kind="compaction",
        role="user",
        content={"text": "summary", "provider": "local"},
        message_key="compaction:1",
        new_epoch=True,
    )
    store.append_model_message(
        thread_id="thread_boundary",
        run_id=run.run_id,
        kind="user",
        role="user",
        content={"text": "new"},
        message_key="retained:user",
    )
    records = store.list_model_messages("thread_boundary")
    assert [record["kind"] for record in records] == ["compaction", "user"]
    assert [record["content_text"] for record in records] == ["summary", "new"]
    assert store.current_transcript_epoch("thread_boundary") == 1


def test_render_reorders_late_tool_result_after_its_assistant_call():
    records = [
        {
            "message_id": "assistant-1",
            "kind": "assistant",
            "role": "assistant",
            "content": {
                "text": "",
                "tool_calls": [
                    {
                        "name": "ask_user_question",
                        "args": {"question": "继续吗？"},
                        "id": "call_1",
                    }
                ],
            },
            "content_text": "",
            "tool_call_id": None,
            "name": None,
        },
        {
            "message_id": "user-1",
            "kind": "user",
            "role": "user",
            "content": {"text": "你准备怎么改？"},
            "content_text": "你准备怎么改？",
            "tool_call_id": None,
            "name": None,
        },
        {
            "message_id": "tool-1",
            "kind": "tool_result",
            "role": "tool",
            "content": {
                "text": "Tool call ask_user_question was cancelled.",
                "tool_call_id": "call_1",
                "name": "ask_user_question",
            },
            "content_text": "Tool call ask_user_question was cancelled.",
            "tool_call_id": "call_1",
            "name": "ask_user_question",
        },
    ]

    rendered = render_model_messages(records)

    assert [message["role"] for message in rendered] == [
        "assistant",
        "tool",
        "user",
    ]
    assert rendered[0]["tool_calls"][0]["id"] == "call_1"
    assert rendered[1]["tool_call_id"] == "call_1"


def test_render_synthesizes_a_missing_tool_result():
    rendered = render_model_messages(
        [
            {
                "message_id": "assistant-1",
                "kind": "assistant",
                "role": "assistant",
                "content": {
                    "text": "",
                    "tool_calls": [
                        {
                            "name": "ask_user_question",
                            "args": {"question": "继续吗？"},
                            "id": "call_orphan",
                        }
                    ],
                },
                "content_text": "",
                "tool_call_id": None,
                "name": None,
            }
        ]
    )

    assert [message["role"] for message in rendered] == ["assistant", "tool"]
    assert rendered[1]["tool_call_id"] == "call_orphan"
    assert "was cancelled" in rendered[1]["content"]
