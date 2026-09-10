# =============================================================================
# 选中文本真注入 —— ADR-0007 决策 11 修订（工作单裁决 #3）
# =============================================================================
# build_layer_b_snapshot 是纯函数，单元测试只能证明它"愿意"渲染选中文本。这三条锁
# 证明 run 真的把 context.selected_text 送到了模型面前：真实产品图 + 假模型，
# 检查进入模型的 SystemMessage 里那一份 Run context snapshot。
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


def _layer_b_seen_by_model(model: _RecordingFakeModel) -> str:
    """取出进入模型的那份 Layer B 快照。Layer A 也是 SystemMessage，靠标题区分。"""
    assert model.seen, "the fake model was never called"
    for message in model.seen[0]:
        text = _text(message)
        if type(message).__name__ == "SystemMessage" and "Run context snapshot" in text:
            return text
    raise AssertionError("Layer B snapshot never reached the model")


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
    deadline = time.monotonic() + WAIT_TIMEOUT
    while time.monotonic() < deadline:
        if manager.store.get_run(run.run_id).status in TERMINAL:
            break
        time.sleep(0.02)
    else:
        raise AssertionError(f"run {run.run_id} never finished")
    return _layer_b_seen_by_model(model)


def test_selected_text_reaches_the_model_inside_layer_b(tmp_path: Path):
    layer_b = _run_with_selection(tmp_path, "FOXP3 marks regulatory T cells.")

    assert "user selected this text on the page:" in layer_b
    assert "FOXP3 marks regulatory T cells." in layer_b
    assert "current run goal (question): 这段说得对吗" in layer_b


def test_overlong_selection_arrives_bounded_with_its_marker(tmp_path: Path):
    # 片段必须唯一：周期性文本会让"上界之外"的切片也出现在保留的前缀里。
    selection = "".join(f"[{index:05d}]" for index in range(700))   # 4900 字符
    layer_b = _run_with_selection(tmp_path, selection)

    assert selection[:2_000] in layer_b
    assert selection[2_500:2_600] not in layer_b
    assert "…[selected text truncated]" in layer_b
    assert "current run goal (question): 这段说得对吗" in layer_b


def test_run_without_a_selection_injects_no_selection_block(tmp_path: Path):
    layer_b = _run_with_selection(tmp_path, None)

    assert "user selected this text on the page" not in layer_b
    assert "current run goal (question): 这段说得对吗" in layer_b
