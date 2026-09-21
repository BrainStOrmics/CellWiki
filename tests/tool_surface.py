"""Shared probe: the tool names a real compiled CellWiki graph sends to the model.

为什么需要它：只看 `WHITELISTED_TOOL_NAMES` 或中间件常量都测不出工具面缺陷——
2026-09-21 的缺陷正是"常量说 14 个、模型请求只带 12 个"。这里用 BaseChatModel
替身捕获 `bind_tools` 的实参，也就是真实编译图真正绑给模型的工具清单。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import Field

from cellwiki.agent.app import build_wiki_agent


def _name_of(tool: Any) -> str | None:
    if isinstance(tool, dict):
        function = tool.get("function")
        if isinstance(function, dict):
            return function.get("name")
        return tool.get("name")
    return getattr(tool, "name", None)


class _ToolSurfaceProbeModel(BaseChatModel):
    """Records the tool names of every ``bind_tools`` call, then answers.

    ``ls_provider`` 决定框架能否匹配已注册的 HarnessProfile；不匹配时框架自己的
    工具排除中间件不安装，正好用来验证 allowlist 是否单独承重。
    """

    bound_tool_names: list[list[str]] = Field(default_factory=list)
    ls_provider: str = "openai"

    @property
    def _llm_type(self) -> str:
        return "tool-surface-probe"

    def _get_ls_params(self, **kwargs: Any) -> dict[str, str]:
        return {"ls_provider": self.ls_provider, "ls_model_name": "build-only"}

    def bind_tools(self, tools: Any, **kwargs: Any) -> "_ToolSurfaceProbeModel":
        names = [_name_of(tool) for tool in tools]
        self.bound_tool_names.append(sorted(str(name) for name in names))
        return self

    def _bind_tools(self, tools: Any, **kwargs: Any) -> "_ToolSurfaceProbeModel":
        return self.bind_tools(tools, **kwargs)

    def _generate(
        self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any
    ) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="ok"))])

    def _stream(
        self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any
    ):
        yield ChatGenerationChunk(message=AIMessageChunk(content="ok"))


def model_visible_tool_names(
    workspace_root: Path, *, ls_provider: str = "openai"
) -> set[str]:
    """Run one real graph turn and return the tool names bound for the model."""

    model = _ToolSurfaceProbeModel(ls_provider=ls_provider)
    graph = build_wiki_agent(workspace_root, model=model, checkpointer=None)
    graph.invoke({"messages": [HumanMessage(content="工具面探针")]})

    assert model.bound_tool_names, "the compiled graph never bound tools to the model"
    first = model.bound_tool_names[0]
    # 多次绑定时工具面必须一致：不一致意味着请求间工具漂移。
    for names in model.bound_tool_names:
        assert names == first, f"tool surface drifted between requests: {model.bound_tool_names}"
    return set(first)
