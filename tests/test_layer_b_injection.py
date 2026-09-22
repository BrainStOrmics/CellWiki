# =============================================================================
# 选中文本真注入
# =============================================================================
# `build_turn_context` 是纯函数，单元测试只能证明它"愿意"渲染选中文本。这四条锁
# 证明 run 真的把 context.selected_text 送到了模型面前：真实产品图 + 假模型。
#
# 2026-09-22（legacy 组装器退役）前，这四条跑在 `AGENT_PROMPT_TRANSCRIPT=legacy`
# 下，断言的是 legacy 形状——一份独立的 `SystemMessage`，标题 `Run context
# snapshot`。v2 没有那个系统消息：turn context 是**当前用户消息的尾部**
# （`## Run context`）。因此断言随之改到 v2 形状；覆盖本身（选中文本进模型 +
# 位置锁）一条不减。
# =============================================================================

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import Field

from cellwiki.agent.app import build_wiki_agent
from cellwiki.domain.contracts import WikiAgentContext
from cellwiki.domain.runs import AgentRunStatus
from cellwiki.services.agent_runtime import AgentRuntimeManager

WAIT_TIMEOUT = 20.0

TERMINAL = {
    AgentRunStatus.SUCCEEDED,
    AgentRunStatus.FAILED,
    AgentRunStatus.CANCELLED,
    AgentRunStatus.REJECTED,
    AgentRunStatus.UNFINISHED,
}


class _RecordingFakeModel(BaseChatModel):
    """记录每次进入模型的 messages，然后直接回答（不联网、不调真实 provider）。"""

    seen: list[list[Any]] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "recording-fake"

    def bind_tools(self, tools, **kwargs):
        return self

    def _bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="ok"))])

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        self.seen.append(list(messages))
        yield ChatGenerationChunk(message=AIMessageChunk(content="已回答"))


def _text(message: Any) -> str:
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    return " ".join(str(part) for part in content)


def _turn_context_seen_by_model(model: _RecordingFakeModel) -> str:
    """取出进入模型的 turn context：v2 里它是当前用户消息的尾部。"""

    assert model.seen, "the fake model was never called"
    messages = model.seen[0]
    assert type(messages[-1]).__name__ == "HumanMessage", _shape(messages)
    text = _text(messages[-1])
    assert "## Run context" in text, _shape(messages)
    return text


def _shape(messages: list[Any]) -> str:
    return str([(type(message).__name__, _text(message)[:24]) for message in messages])


def _finish_run(manager: AgentRuntimeManager, run: Any) -> None:
    deadline = time.monotonic() + WAIT_TIMEOUT
    while time.monotonic() < deadline:
        if manager.store.get_run(run.run_id).status in TERMINAL:
            return
        time.sleep(0.02)
    raise AssertionError(f"run {run.run_id} never finished")


def _run_with_selection(root: Path, selected_text: str | None) -> str:
    page = root / "wiki" / "cell_types" / "a.md"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text("# Alpha cell\n", encoding="utf-8")
    model = _RecordingFakeModel()
    manager = AgentRuntimeManager(root, adapter=build_wiki_agent(root, model=model))
    thread_id = "thread_selection"
    run = manager.start(
        thread_id=thread_id,
        message="这段说得对吗",
        context=WikiAgentContext(
            project_id="cellwiki",
            thread_id=thread_id,
            selected_text=selected_text,
        ),
    )
    _finish_run(manager, run)
    return _turn_context_seen_by_model(model)


def test_selected_text_reaches_the_model_inside_the_turn_context(tmp_path: Path):
    context = _run_with_selection(tmp_path, "FOXP3 marks regulatory T cells.")

    assert "user selected this text on the page:" in context
    assert "FOXP3 marks regulatory T cells." in context
    assert "intent hint: question" in context


def test_overlong_selection_arrives_bounded_with_its_marker(tmp_path: Path):
    # 片段必须唯一：周期性文本会让"上界之外"的切片也出现在保留的前缀里。
    selection = "".join(f"[{index:05d}]" for index in range(700))   # 4900 字符
    context = _run_with_selection(tmp_path, selection)

    assert selection[:2_000] in context
    assert selection[2_500:2_600] not in context
    assert "…[selected text truncated]" in context


def test_run_without_a_selection_injects_no_selection_block(tmp_path: Path):
    context = _run_with_selection(tmp_path, None)

    assert "user selected this text on the page" not in context
    assert "intent hint: question" in context


def test_turn_context_rides_the_last_user_message_after_history(tmp_path: Path):
    # 位置锁（2026-09-15，2026-09-22 改到 v2 形状）：动态上下文每轮都变，必须排在
    # 历史之后——排在历史前会让 provider 的逐字节前缀缓存从它处断掉，其后的整段
    # 历史每轮重算（真机对照：跨 run 只剩静态头 ≈2K token 命中）。v2 里它不再是
    # 独立系统消息，而是当前用户消息的尾部：唯一的 SystemMessage 只装稳定前缀，
    # 历史之后紧跟的那条消息就是"本次提问 + 本次上下文"。跑同一个 thread 两轮，
    # 对第二轮 run 的第一次模型调用断言消息序列的形状。工作区不放页面：不符合
    # schema 的页面会让第一轮以 unfinished 收尾，占着串行门禁，第二轮就起不来。
    (tmp_path / "wiki").mkdir()
    model = _RecordingFakeModel()
    manager = AgentRuntimeManager(tmp_path, adapter=build_wiki_agent(tmp_path, model=model))
    thread_id = "thread_position"
    first = manager.start(
        thread_id=thread_id,
        message="第一问",
        context=WikiAgentContext(project_id="cellwiki", thread_id=thread_id),
    )
    _finish_run(manager, first)
    calls_after_first_run = len(model.seen)
    second = manager.start(
        thread_id=thread_id,
        message="第二问",
        context=WikiAgentContext(project_id="cellwiki", thread_id=thread_id),
    )
    _finish_run(manager, second)

    messages = model.seen[calls_after_first_run]
    shape = _shape(messages)
    # 稳定前缀仍是唯一一条系统消息，且不再携带任何 run 动态上下文。
    system_messages = [
        message for message in messages if type(message).__name__ == "SystemMessage"
    ]
    assert len(system_messages) == 1, f"expected exactly one system message: {shape}"
    assert "Run context" not in _text(system_messages[0]), shape
    # 动态上下文紧跟在历史之后：末尾是"本次提问 + 本次上下文"的用户消息。
    tail = _text(messages[-1])
    assert type(messages[-1]).__name__ == "HumanMessage", shape
    assert "第二问" in tail and "## Run context" in tail, shape
    # 它前面是上一轮的助手回答，而不是静态系统提示或列表开头。
    assert _text(messages[-2]) == "已回答", f"turn context is not behind history: {shape}"
