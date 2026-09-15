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
from langchain_openai import ChatOpenAI

from cellwiki.adapters.openai_model import (
    build_model_from_spec,
    build_openai_chat_model,
)
from cellwiki.adapters.openai_reasoning_bridge import attach_reasoning_stream_bridge
from cellwiki.config import Settings, settings
from cellwiki.domain.model_provider import (
    WIRE_PROTOCOL_RESPONSES,
    normalize_wire_protocol,
)
from cellwiki.domain.model_providers import ResolvedModelSpec
from cellwiki.domain.contracts import WikiAgentContext
from cellwiki.agent.executor import (
    WHITELISTED_TOOL_NAMES,
    build_attachment_tools,
    build_workspace_tools,
    canonical_tool_sort_key,
    tool_schema_fingerprint,
)
from cellwiki.agent.question_tool import build_question_tool
from cellwiki.services.checkpoints import build_checkpointer
from cellwiki.services.prompt_cache import (
    PromptCachePolicy,
    resolve_prompt_cache_policy,
)
from cellwiki.services.prompt_layers import (
    LAYER_A_TEXT,
    resolve_declared_window,
    schema_prompt_block,
)
from cellwiki.services.prompt_runtime import current_prompt_run_context
from cellwiki.services.subagents import SubagentRegistry, build_delegation_tools
from cellwiki.agent.source_tools import build_source_tools
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

CELLWIKI_BOUNDARY_REMINDER = (
    "CellWiki tool boundary: only the whitelisted CellWiki tools are "
    "available (ls, read_file, write_file, edit_file, glob, grep, git, "
    "run_powershell, delete_file, rename_file, lint_knowledge_base, "
    "ask_user_question, read_attachment). Generic "
    "deep-agent tools such as execute, bash, task, write_todos, and "
    "move_folder are unavailable. Emit calls only for tool schemas "
    "visible in this request."
)


def stable_system_prompt_text(schema_version: int, schema_contract_hash: str) -> str:
    """Return the exact stable prefix used for cache hash and diagnostics."""

    return (
        f"{LAYER_A_TEXT}\n\n{HARNESS_PROMPT}\n\n{CELLWIKI_BOUNDARY_REMINDER}"
        f"\n\n{schema_prompt_block(schema_version, schema_contract_hash)}"
    )


def prompt_cache_policy_for_spec(spec: ResolvedModelSpec) -> PromptCachePolicy:
    return resolve_prompt_cache_policy(
        protocol=spec.protocol,
        model_id=spec.model_id,
        base_url=spec.base_url,
        request_overrides=spec.request_overrides,
        declared_window=resolve_declared_window(spec.model_id),
        context_max_tokens=settings.agent_context_max_tokens,
        output_reserve_tokens=settings.agent_context_output_reserve_tokens,
        auto_compact_ratio=settings.agent_context_auto_compact_ratio,
    )


def prompt_cache_policy_for_settings(
    configuration: Settings = settings,
) -> PromptCachePolicy:
    return resolve_prompt_cache_policy(
        protocol=configuration.openai_api_protocol,
        model_id=configuration.openai_model,
        base_url=configuration.openai_base_url,
        request_overrides={},
        declared_window=resolve_declared_window(configuration.openai_model),
        context_max_tokens=configuration.agent_context_max_tokens,
        output_reserve_tokens=configuration.agent_context_output_reserve_tokens,
        auto_compact_ratio=configuration.agent_context_auto_compact_ratio,
    )


def _cache_model_options(
    policy: PromptCachePolicy,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]] | None]:
    cache_options = (
        {"mode": "explicit"}
        if policy.protocol == WIRE_PROTOCOL_RESPONSES and policy.mode == "explicit"
        else None
    )
    context_management = (
        [{"type": "compaction", "compact_threshold": policy.compact_threshold}]
        if policy.provider_native_compaction and policy.compact_threshold
        else None
    )
    return cache_options, context_management


def build_coordinator_tools(
    root: Path,
    registry: SubagentRegistry | None = None,
) -> list[Any]:
    tools: list[Any] = [
        *build_workspace_tools(root),
        *build_lint_tools(root),
        *build_attachment_tools(),
        *build_source_tools(root),
        *build_question_tool(),
        *build_delegation_tools(registry or SubagentRegistry()),
    ]
    return sorted(
        tools,
        key=lambda tool: canonical_tool_sort_key(str(getattr(tool, "name", "") or "")),
    )


def coordinator_tool_schema_hash(
    root: Path,
    registry: SubagentRegistry | None = None,
) -> str:
    return tool_schema_fingerprint(build_coordinator_tools(root, registry))

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
    def __init__(
        self,
        *,
        append_reminder: bool = False,
        cache_policy: PromptCachePolicy | None = None,
    ):
        self.append_reminder = append_reminder
        self.cache_policy = cache_policy

    @staticmethod
    def _content_blocks(content: Any) -> list[dict[str, Any]]:
        if isinstance(content, list):
            blocks: list[dict[str, Any]] = []
            for block in content:
                if isinstance(block, dict):
                    blocks.append(dict(block))
                else:
                    blocks.append({"type": "text", "text": str(block)})
            return blocks
        return [{"type": "text", "text": str(content or "")}]

    def _explicit_marker(self) -> tuple[str, dict[str, str]] | None:
        if self.cache_policy is None or not self.cache_policy.allows_explicit_breakpoints():
            return None
        if self.cache_policy.breakpoint_key == "prompt_cache_breakpoint":
            return "prompt_cache_breakpoint", {"mode": "explicit"}
        if self.cache_policy.breakpoint_key == "cache_control":
            return "cache_control", {"type": "ephemeral"}
        return None

    def _apply_cache_markers(self, request: Any) -> Any:
        system_message = request.system_message
        prompt_context = current_prompt_run_context()
        marker = self._explicit_marker()
        if isinstance(system_message, SystemMessage) and (prompt_context or marker):
            blocks = self._content_blocks(system_message.content)
            for block in blocks:
                block.pop("prompt_cache_breakpoint", None)
                block.pop("cache_control", None)
            if prompt_context:
                blocks.append(
                    {
                        "type": "text",
                        "text": schema_prompt_block(
                            prompt_context.schema_version,
                            prompt_context.schema_contract_hash,
                        ),
                    }
                )
            if marker and blocks:
                blocks[-1][marker[0]] = marker[1]
            system_message = system_message.model_copy(update={"content": blocks})

        messages = list(request.messages)
        if marker and self.cache_policy is not None and messages:
            count = self.cache_policy.tool_result_breakpoints
            tool_indices = [
                index
                for index, message in enumerate(messages)
                if isinstance(message, ToolMessage)
            ]
            selected = set(tool_indices[-count:]) if count else set()
            for index in selected:
                message = messages[index]
                blocks = self._content_blocks(message.content)
                if blocks:
                    blocks[-1][marker[0]] = marker[1]
                messages[index] = message.model_copy(update={"content": blocks})
        return request.override(
            tools=request.tools,
            system_message=system_message,
            messages=messages,
        )

    @staticmethod
    def _tool_name(tool: Any) -> str | None:
        if isinstance(tool, dict):
            function = tool.get("function")
            if isinstance(function, dict):
                return cast(str | None, function.get("name"))
            return cast(str | None, tool.get("name"))
        return cast(str | None, getattr(tool, "name", None))

    def _filter_request(self, request: Any) -> Any:
        filtered_tools = sorted(
            (
                tool
                for tool in request.tools
                if self._tool_name(tool) in self._allowed_tools
            ),
            key=lambda tool: canonical_tool_sort_key(self._tool_name(tool) or ""),
        )
        system_message = request.system_message
        if self.append_reminder and isinstance(system_message, SystemMessage):
            content = system_message.content
            if isinstance(content, str):
                content = f"{content}\n\n{CELLWIKI_BOUNDARY_REMINDER}"
            else:
                content = [
                    *content,
                    {"type": "text", "text": CELLWIKI_BOUNDARY_REMINDER},
                ]
            system_message = system_message.model_copy(update={"content": content})
        request = request.override(tools=filtered_tools, system_message=system_message)
        return self._apply_cache_markers(request)

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
    """Keep the Deep Agents harness limited to CellWiki-owned capabilities.

    Deep Agents 按模型的 ``ls_provider``（ChatOpenAI 为 ``openai``、
    ChatAnthropic 为 ``anthropic``）匹配已注册的 profile；两种 provider
    都要注册，否则原生 Anthropic 模型会落到空 profile，通用工具与
    TodoListMiddleware 就会进入协调器请求。
    """

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
    for provider in ("openai", "anthropic"):
        register_harness_profile(provider, profile)
        register_harness_profile(f"{provider}:{model_name}", profile)


# ---------------------------------------------------------------------------
# 构建 LLM 模型实例
# OpenAI 形状用 ChatOpenAI（兼容 Ollama、vLLM 等），原生 Anthropic 协议
# 用 ChatAnthropic（adapters/anthropic_model.py）。temperature=0 保证确定性。
# 三种线协议（responses / chat_completions / anthropic）默认都开启逐 token
# 流式，AGENT_STREAMING=0 一键回退为整块返回：coordinator 请求永远携带工具，
# disable_streaming="tool_calling" 会在 HTTP 层直接退化为阻塞式单响应，正文与
# 思考整块到达（design/archive/2026-09-15-three-protocol-token-streaming.md）。
# 推理增量按协议分工，但最终都落到运行时的 reasoning_delta：
# - responses：网关的非标准 response.reasoning_text.delta 由 reasoning bridge
#   翻译成 langchain 可识别的标准摘要事件；
# - chat_completions：langchain-openai 不提取 delta.reasoning_content，由
#   adapters/openai_reasoning_content.py 的 provider 子类补进 additional_kwargs；
# - anthropic：langchain-anthropic 已把 thinking_delta 还原为原生
#   {"type": "thinking"} 内容块，运行时 _reasoning_text 直接映射。
# ---------------------------------------------------------------------------
def build_model(configuration: Settings = settings) -> BaseChatModel:
    _register_cellwiki_harness_profile(configuration.openai_model)
    # 三种线协议都流式构建；AGENT_STREAMING=0 是唯一的回退开关。
    streaming = bool(configuration.agent_streaming)
    policy = prompt_cache_policy_for_settings(configuration)
    prompt_cache_options, context_management = _cache_model_options(policy)
    model = build_openai_chat_model(
        configuration,
        purpose="coordinator",
        disable_streaming=False if streaming else "tool_calling",
        stream_usage=True if streaming else None,
        prompt_cache_options=prompt_cache_options,
        context_management=context_management,
    )
    if streaming and normalize_wire_protocol(
        configuration.openai_api_protocol
    ) == WIRE_PROTOCOL_RESPONSES:
        # 推理事件桥只认 Responses 的 SSE 形状；该分支的工厂返回必为 ChatOpenAI。
        attach_reasoning_stream_bridge(cast(ChatOpenAI, model))
    return model


# ---------------------------------------------------------------------------
# 供应商目录选中链路的协调器模型构建
# 语义与 build_model 逐项一致（流式开关、reasoning bridge、HarnessProfile），
# 唯一差别是模型配置来自本次 run 解析出的供应商目录条目而非全局 settings。
# ---------------------------------------------------------------------------
def build_coordinator_model(spec: ResolvedModelSpec) -> BaseChatModel:
    _register_cellwiki_harness_profile(spec.model_id)
    # 语义与 build_model 一致；流式开关只看 AGENT_STREAMING。
    streaming = bool(settings.agent_streaming)
    policy = prompt_cache_policy_for_spec(spec)
    prompt_cache_options, context_management = _cache_model_options(policy)
    model = build_model_from_spec(
        spec,
        purpose="coordinator",
        disable_streaming=False if streaming else "tool_calling",
        stream_usage=True if streaming else None,
        prompt_cache_options=prompt_cache_options,
        context_management=context_management,
    )
    if streaming and normalize_wire_protocol(spec.protocol) == WIRE_PROTOCOL_RESPONSES:
        # 推理事件桥只认 Responses 的 SSE 形状；该分支的工厂返回必为 ChatOpenAI。
        attach_reasoning_stream_bridge(cast(ChatOpenAI, model))
    return model


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
    cache_policy: PromptCachePolicy | None = None,
):
    # 解析项目根目录
    root = Path(project_root or settings.workspace_root).resolve()
    _register_cellwiki_harness_profile(settings.openai_model)
    # 如果未指定模型，使用默认构建
    coordinator_model = model or build_model()
    # 构建工具集：工作区工具 + 确定性 lint 报告 + 交互工具
    coordinator_tools = build_coordinator_tools(root, registry)
    # ADR-0010 决策 1/14：产品图默认落 SqliteSaver（data/runtime/checkpoints.sqlite），
    # 与 cellwiki.db 分文件；AGENT_CHECKPOINTER=inmemory 只是短期回滚闸。
    # 显式传入的 checkpointer 原样生效。
    active_checkpointer = (
        build_checkpointer(root) if checkpointer is _DEFAULT_CHECKPOINTER else checkpointer
    )
    # 组装 Deep Agent
    return create_deep_agent(
        name="cellwiki-agent",
        model=coordinator_model,
        system_prompt=SYSTEM_PROMPT,
        tools=coordinator_tools,
        middleware=[
            _CellWikiToolBoundaryMiddleware(
                append_reminder=True,
                cache_policy=cache_policy,
            )
        ],
        backend=StateBackend(),
        checkpointer=active_checkpointer,
        context_schema=WikiAgentContext,
        interrupt_on={},
    )
