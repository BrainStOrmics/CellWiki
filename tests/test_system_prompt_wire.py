"""Wire-level locks for the coordinator system prompt (2026-10-14).

背景（2026-10-14 实测捕获）：deepagents 的 FilesystemMiddleware 会向 system
追加一段通用文件系统说明（宣告 `ls`、路径必须以 `/` 开头等），与 CellWiki 的
allowlist 和工作区相对路径契约互相矛盾；同时 Layer A 与工具边界文本固化在
"关闭记忆"的 13 工具版本，与开启记忆时 17 个工具的请求面脱节。

本文件用真实产品图（build_wiki_agent + 真实 deepagents 中间件栈）加记录型
模型锁住三件事：

1. 框架文件系统块在请求发出前被整块移除；
2. system 文本的工具名清单 == 有效允许清单（跟随 AGENT_MEMORY_ENABLED）；
3. system 的各 text block 以空行连接后，逐字等于 stable_system_prompt_text
   （缓存前缀指纹与上下文构成估算使用的文本）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import Field

from cellwiki.agent.app import build_wiki_agent, stable_system_prompt_text
from cellwiki.config import settings
from cellwiki.domain.agent_tools import MEMORY_TOOL_NAMES, agent_tool_names
from cellwiki.services.prompt_runtime import (
    PromptRunContext,
    reset_prompt_run_context,
    set_prompt_run_context,
)

SCHEMA_HASH = "wire-test-hash"


class _WireRecordingModel(BaseChatModel):
    """记录真实图请求的假模型：不联网，记录 system 与绑定工具名。"""

    seen: list[list[Any]] = Field(default_factory=list)
    bound: list[str] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "wire-recording-fake"

    def _get_ls_params(self, stop: list[str] | None = None, **kwargs: Any) -> dict[str, Any]:
        # 必须命中 CellWiki 注册在 provider 键 "openai" 上的 HarnessProfile，
        # 否则 HARNESS_PROMPT 与框架中间件排除都不生效，wire 形状会与产品不同。
        return {"ls_provider": "openai", "ls_model_name": "wire-test-model"}

    def bind_tools(self, tools: Any, **kwargs: Any) -> "_WireRecordingModel":
        self.bound = [str(getattr(tool, "name", "") or "") for tool in tools]
        return self

    def _bind_tools(self, tools: Any, **kwargs: Any) -> "_WireRecordingModel":
        return self.bind_tools(tools, **kwargs)

    def _generate(self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any):
        self.seen.append(list(messages))
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="ok"))])

    def _stream(self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any):
        self.seen.append(list(messages))
        yield ChatGenerationChunk(message=AIMessageChunk(content="ok"))


def _blocks(system_message: Any) -> list[str]:
    content = system_message.content
    if isinstance(content, str):
        return [content]
    return [
        str(block.get("text") or "")
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    ]


@pytest.mark.parametrize("include_memory", [True, False])
def test_wire_system_prompt_matches_the_effective_tool_surface(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, include_memory: bool
) -> None:
    monkeypatch.setattr(settings, "agent_memory_enabled", include_memory)
    model = _WireRecordingModel()
    agent = build_wiki_agent(tmp_path, model=model, checkpointer=None)
    token = set_prompt_run_context(
        PromptRunContext(
            schema_version=2,
            schema_contract_hash=SCHEMA_HASH,
            transcript_epoch=0,
            cache_prefix_hash="wire-test",
            cache_mode="implicit",
        )
    )
    try:
        agent.invoke(
            {"messages": [HumanMessage(content="你好")]},
            config={"configurable": {"thread_id": "wire-test-thread"}},
        )
    finally:
        reset_prompt_run_context(token)

    assert model.seen, "the recording model was never called"
    system_message = model.seen[0][0]
    assert type(system_message).__name__ == "SystemMessage"
    blocks = _blocks(system_message)
    joined = "\n\n".join(blocks)

    # 1) 框架通用文件系统块在发出前被移除
    assert "## Filesystem Tools" not in joined
    assert "All file paths must start with a /" not in joined
    assert "## Following Conventions" not in joined

    # 2) 工具名清单 == 有效工具面，且与实际绑定的工具数组一致
    expected_names = list(agent_tool_names(include_memory))
    for name in expected_names:
        assert name in joined, name
    for name in MEMORY_TOOL_NAMES:
        assert (name in joined) is include_memory, name
    assert model.bound == expected_names

    # 3) system 文本与稳定前缀指纹文本逐字一致（schema 块为独立 block 追加）
    assert joined == stable_system_prompt_text(2, SCHEMA_HASH)
