# =============================================================================
# 智能体应用组装 —— 单一顶级协调器的构建工厂（工作区版）
# =============================================================================
# 组装 CellWiki 协调器：构建 LLM 模型、注册白名单工具、挂载工具边界
# 中间件，并组装为 LangGraph 可执行的 Deep Agent。阶段 7 会在此处按
# spec 注册表添加顺序委托的子 Agent；v1 注册表为空时不暴露委托工具。
# =============================================================================

"""Assembly of the single top-level workspace-based CellWiki coordinator."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, cast

from deepagents import (
    GeneralPurposeSubagentProfile,
    HarnessProfile,
    create_deep_agent,
    register_harness_profile,
)
from deepagents.backends import StateBackend
from langchain.agents.middleware import AgentMiddleware, TodoListMiddleware
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import SystemMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver

from cellwiki.adapters.openai_model import build_openai_chat_model
from cellwiki.config import Settings, settings
from cellwiki.domain.contracts import WikiAgentContext
from cellwiki.agent.executor import (
    WHITELISTED_TOOL_NAMES,
    build_attachment_tools,
    build_workspace_tools,
)
from cellwiki.agent.question_tool import build_question_tool
from cellwiki.services.prompt_layers import LAYER_A_TEXT
from cellwiki.services.subagents import SubagentRegistry, build_delegation_tools
from cellwiki.agent.ingest_tools import build_ingest_tools
from cellwiki.agent.tools import build_lint_tools


# ---------------------------------------------------------------------------
# 系统提示词 —— 定义 CellWiki 协调器的工作区行为边界
# 阶段 1 只暴露只读检查与 Lint 报告工具；阶段 2/3 加入 git 与文件工具后
# 本提示词会同步更新；阶段 5 将按 Layer A/B/C 分层组装完整提示。
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = LAYER_A_TEXT

# Deep Agents' stock prompt describes a general coding workspace. CellWiki has
# narrower governed tools, so the coordinator shares this base harness prompt.
HARNESS_PROMPT = """You are CewiPilot, a governed CellWiki agent. Use only the
visible CellWiki tools and the current runtime context. Workspace inspection and
lint tools are read-only; the runtime owns git versioning and the pending-diff
approval boundary. Never use generic filesystem, shell, or publication tools.
Return concise results appropriate to your assigned role.
"""

# 哨兵对象，用于区分"未传入检查点器"和"传入了 None"
_DEFAULT_CHECKPOINTER = object()


class _CellWikiToolBoundaryMiddleware(AgentMiddleware):
    """Keep non-whitelisted generic tools out of every CellWiki model request.

    Deep Agents normally injects generic filesystem tools into the coordinator.
    The registered HarnessProfile also excludes them, but this local boundary is
    deliberately defense in depth because provider-built model instances do not
    always preserve profile filtering. The whitelist enforcement is expanded in
    phase 3 when the File/Git/PowerShell tools become CellWiki-owned.
    """

    name = "cellwiki_tool_boundary"
    # 白名单（allowlist）：只有这些 CellWiki 自有工具名能进入模型请求；其余
    # 框架通用工具（execute/bash/task/write_todos/move_folder 等）一律过滤。
    _allowed_tools = WHITELISTED_TOOL_NAMES
    _boundary_reminder = (
        "CellWiki tool boundary: only the whitelisted CellWiki tools are "
        "available (ls, read_file, write_file, edit_file, glob, grep, git, "
        "run_powershell, delete_file, rename_file, lint_knowledge_base, "
        "ask_user_question, read_attachment). Generic "
        "deep-agent tools such as execute, bash, task, write_todos, and "
        "move_folder are unavailable. Emit calls only for tool schemas "
        "visible in this request."
    )

    def __init__(self, *, append_reminder: bool = False):
        self.append_reminder = append_reminder

    @staticmethod
    def _tool_name(tool: Any) -> str | None:
        if isinstance(tool, dict):
            function = tool.get("function")
            if isinstance(function, dict):
                return cast(str | None, function.get("name"))
            return cast(str | None, tool.get("name"))
        return cast(str | None, getattr(tool, "name", None))

    def _filter_request(self, request: Any) -> Any:
        filtered_tools = [
            tool
            for tool in request.tools
            if self._tool_name(tool) in self._allowed_tools
        ]
        system_message = request.system_message
        if self.append_reminder and isinstance(system_message, SystemMessage):
            content = system_message.content
            if isinstance(content, str):
                content = f"{content}\n\n{self._boundary_reminder}"
            else:
                content = [
                    *content,
                    {"type": "text", "text": self._boundary_reminder},
                ]
            system_message = system_message.model_copy(update={"content": content})
        return request.override(tools=filtered_tools, system_message=system_message)

    def wrap_model_call(self, request: Any, handler: Any) -> Any:
        return handler(self._filter_request(request))

    async def awrap_model_call(self, request: Any, handler: Any) -> Any:
        return await handler(self._filter_request(request))

    @classmethod
    def _blocked_tool_response(cls, request: Any) -> ToolMessage:
        """Return a recoverable tool error when a generic tool slips past filtering."""

        tool_name = str(request.tool_call.get("name", "unknown"))
        tool_call_id = str(request.tool_call.get("id", "blocked-tool-call"))
        return ToolMessage(
            content=(
                f"Tool '{tool_name}' is not available to CellWiki agents. "
                "Use the visible CellWiki tools instead of generic filesystem tools."
            ),
            name=tool_name,
            tool_call_id=tool_call_id,
            status="error",
        )

    def wrap_tool_call(self, request: Any, handler: Any) -> Any:
        """Block generic filesystem calls even if a provider emits one anyway."""

        if request.tool_call.get("name") not in self._allowed_tools:
            return self._blocked_tool_response(request)
        return handler(request)

    async def awrap_tool_call(self, request: Any, handler: Any) -> Any:
        """Async counterpart of ``wrap_tool_call`` for the desktop runtime."""

        if request.tool_call.get("name") not in self._allowed_tools:
            return self._blocked_tool_response(request)
        return await handler(request)


@lru_cache(maxsize=None)
def _register_cellwiki_harness_profile(model_name: str) -> None:
    """Keep the Deep Agents harness limited to CellWiki-owned capabilities."""

    profile = HarnessProfile(
        base_system_prompt=HARNESS_PROMPT,
        general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
        # 白名单七工具由 executor 显式注册，名称不放入 excluded_tools，
        # 否则框架会按名称剥离我们的工具注册；通用残留工具继续排除。
        excluded_tools=frozenset(
            {
                "write_todos",
                "ls",
                "task",
                "execute",
                "bash",
                "delete_file",
                "move_file",
                "move_folder",
            }
        ),
        excluded_middleware=frozenset({cast(Any, TodoListMiddleware)}),
    )
    register_harness_profile("openai", profile)
    register_harness_profile(f"openai:{model_name}", profile)


# ---------------------------------------------------------------------------
# 构建 LLM 模型实例
# 使用 ChatOpenAI 以兼容 OpenAI 及第三方提供商（Ollama、vLLM 等）。
# temperature=0 保证确定性；禁用 tool_calling 流式传输，因为自定义
# 提供商经常发送格式错误的部分工具调用流。
# ---------------------------------------------------------------------------
def build_model(configuration: Settings = settings) -> BaseChatModel:
    _register_cellwiki_harness_profile(configuration.openai_model)
    return build_openai_chat_model(configuration, purpose="coordinator")


# ---------------------------------------------------------------------------
# 构建完整的 Wiki 智能体
# 组装协调器：模型 + 只读工具 + Lint 报告工具 + 最终回答工具 + 检查点器。
# 返回 Deep Agent 实例，可直接用于 LangGraph 执行。
# ---------------------------------------------------------------------------
def build_wiki_agent(
    project_root: Path | None = None,
    model: BaseChatModel | str | None = None,
    checkpointer=_DEFAULT_CHECKPOINTER,
    registry: SubagentRegistry | None = None,
):
    # 解析项目根目录
    root = Path(project_root or settings.workspace_root).resolve()
    _register_cellwiki_harness_profile(settings.openai_model)
    # 如果未指定模型，使用默认构建
    coordinator_model = model or build_model()
    # 构建工具集：工作区工具 + 确定性 lint 报告 + 交互工具
    coordinator_tools: list[Any] = [
        *build_workspace_tools(root),
        *build_lint_tools(root),
        *build_attachment_tools(),
        *build_ingest_tools(root),
        *build_question_tool(),
        *build_delegation_tools(registry or SubagentRegistry()),
    ]
    # 检查点器：默认使用 InMemorySaver，除非传入了外部检查点器
    active_checkpointer = (
        InMemorySaver() if checkpointer is _DEFAULT_CHECKPOINTER else checkpointer
    )
    # 组装 Deep Agent
    return create_deep_agent(
        name="cellwiki-agent",
        model=coordinator_model,
        system_prompt=SYSTEM_PROMPT,
        tools=coordinator_tools,
        middleware=[_CellWikiToolBoundaryMiddleware(append_reminder=True)],
        backend=StateBackend(),
        checkpointer=active_checkpointer,
        context_schema=WikiAgentContext,
        interrupt_on={},
    )


# ---------------------------------------------------------------------------
# LangGraph Agent Server 使用的工厂函数
# 服务端拥有自己的持久化层，因此传入 checkpointer=False
# ---------------------------------------------------------------------------
def create_server_graph():
    """Factory used by LangGraph Agent Server, which owns persistence."""
    return build_wiki_agent(checkpointer=False)