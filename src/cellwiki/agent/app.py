# =============================================================================
# 智能体应用组装 —— 单一顶级协调器的构建工厂（工作区版）
# =============================================================================
# 组装 CellWiki 协调器：构建 LLM 模型、注册白名单工具、挂载工具边界
# 中间件，并组装为 LangGraph 可执行的 Deep Agent。此处按
# spec 注册表接入顺序委托的子 Agent；v1 注册表为空时不暴露委托工具。
# =============================================================================

"""Assembly of the single top-level workspace-based CellWiki coordinator."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from collections import OrderedDict
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse
from typing import Any, cast

from deepagents import (
    GeneralPurposeSubagentProfile,
    HarnessProfile,
    create_deep_agent,
    register_harness_profile,
)
from deepagents.backends import StateBackend
from deepagents.middleware.summarization import SummarizationMiddleware
from langchain.agents.middleware import AgentMiddleware, TodoListMiddleware
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
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
from cellwiki.domain.agent_tools import agent_tool_names_text
from cellwiki.agent.executor import (
    WHITELISTED_TOOL_NAMES,
    build_attachment_tools,
    build_workspace_tools,
    canonical_tool_sort_key,
    effective_whitelist,
    tool_schema_fingerprint,
)
from cellwiki.agent.memory_tools import build_memory_tools
from cellwiki.agent.question_tool import build_question_tool
from cellwiki.services.checkpoints import build_checkpointer
from cellwiki.services.prompt_cache import (
    PromptCachePolicy,
    resolve_prompt_cache_policy,
)
from cellwiki.services.prompt_layers import (
    layer_a_text,
    schema_prompt_block,
)
from cellwiki.agent.compaction import CellWikiCompactionMiddleware
from cellwiki.services.prompt_runtime import (
    ModelRequestFingerprint,
    current_prompt_run_context,
)
from cellwiki.services.subagents import SubagentRegistry, build_delegation_tools
from cellwiki.agent.source_tools import build_source_tools
from cellwiki.agent.tools import build_lint_tools


# ---------------------------------------------------------------------------
# 系统提示词 —— 定义 CellWiki 协调器的工作区行为边界
# 提示词覆盖只读检查、Lint 报告、git 与文件工具，按 Layer A/B/C 分层组装；
# 工具面与提示词必须同步更新。
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = layer_a_text(include_memory=False)

# Deep Agents' stock prompt describes a general coding workspace. CellWiki has
# narrower governed tools, so the coordinator shares this base harness prompt.
HARNESS_PROMPT = """You are CewiPilot, a governed CellWiki agent. Use only the
visible CellWiki tools and the current runtime context. Workspace inspection and
lint tools are read-only; the runtime owns git versioning and the pending-diff
approval boundary. Never use generic filesystem, shell, or publication tools.
Return concise results appropriate to your assigned role.
"""

# 可用清单仍由注册表生成（手写清单会与代码脱节：2026-09-21 修复前这里列着模型
# 根本看不到的 ls）。
# “不可用”清单改回独立散文常量、文本逐字保持不变：它描述的是框架通用工具的
# 风险面，不是 CellWiki 自己的注册表；从注册表派生会在它们脱钩后把提醒变成
# 空词，而且会改变稳定前缀与 cache_prefix_hash。
def boundary_reminder(include_memory: bool = False) -> str:
    """Tool-boundary reminder whose available list matches the live tool surface."""

    return (
        "CellWiki tool boundary: only the whitelisted CellWiki tools are "
        f"available ({agent_tool_names_text(include_memory)}). Generic "
        "deep-agent tools such as execute, ls, task, write_todos are "
        "unavailable. Emit calls only for tool schemas visible in this request."
    )


CELLWIKI_BOUNDARY_REMINDER = boundary_reminder(include_memory=False)


def stable_system_prompt_text(schema_version: int, schema_contract_hash: str) -> str:
    """Return the exact stable prefix used for cache hash and diagnostics."""

    include_memory = settings.agent_memory_enabled
    return (
        f"{layer_a_text(include_memory)}\n\n{HARNESS_PROMPT}\n\n"
        f"{boundary_reminder(include_memory)}"
        f"\n\n{schema_prompt_block(schema_version, schema_contract_hash)}"
    )


def prompt_cache_policy_for_spec(spec: ResolvedModelSpec) -> PromptCachePolicy:
    return resolve_prompt_cache_policy(
        protocol=spec.protocol,
        model_id=spec.model_id,
        base_url=spec.base_url,
        request_overrides=spec.request_overrides,
        model_input_tokens=spec.max_input_tokens,
        context_max_tokens=settings.agent_context_max_tokens,
    )


def prompt_cache_policy_for_settings(
    configuration: Settings = settings,
) -> PromptCachePolicy:
    return resolve_prompt_cache_policy(
        protocol=configuration.openai_api_protocol,
        model_id=configuration.openai_model,
        base_url=configuration.openai_base_url,
        request_overrides={},
        model_input_tokens=configuration.openai_max_input_tokens,
        context_max_tokens=configuration.agent_context_max_tokens,
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
        *build_memory_tools(root),
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

    这是**唯一承重的工具面防线**（2026-09-21 七格隔离实验结论）：Deep Agents 会往
    协调器注入通用文件系统工具，而模型实例并不总能命中已注册的 HarnessProfile
    ——**不命中时框架自己的工具排除中间件根本不安装**，上游会把 ls / task / write_todos
    一起交上来（实测 16 个工具）。那一格靠的就是本地 allowlist，所以它不是
    可选的“多一层”。

    历史说明：HarnessProfile.excluded_tools 已于 2026-09-21 退役（它零独有职责，且曾把
    白名单自己的 ls / delete_file 删掉）；同名命中不到 profile 时框架排除不生效，这正是
    本边界存在的理由。未登记的工具名由本类的调用拦截（wrap_tool_call）兜底。
    """

    name = "cellwiki_tool_boundary"
    # 白名单（allowlist）：只有这些 CellWiki 自有工具名能进入模型请求；其余
    # 框架工具一律在这里被剥离（请求面过滤），模型若仍发出越权调用，
    # 由 wrap_tool_call / awrap_tool_call 拦下并返回可恢复错误。
    _allowed_tools = WHITELISTED_TOOL_NAMES
    def __init__(
        self,
        *,
        append_reminder: bool = False,
        cache_policy: PromptCachePolicy | None = None,
        reasoning_replay: str = "none",
    ):
        # Allowlist 跟随当前进程开关：关闭记忆时记忆工具不进入请求面。
        self._allowed_tools = effective_whitelist()
        self.append_reminder = append_reminder
        self.cache_policy = cache_policy
        # none：请求里的 assistant 消息压平成跨 run 重建后的形状（丢弃
        # reasoning 与服务端 item id）；opaque：保留 provider 的 opaque
        # reasoning 块，供支持该通道的端点续接前缀。默认 none。
        self.reasoning_replay = reasoning_replay
        self._fingerprint_key = secrets.token_bytes(32)
        self._previous_request_items: OrderedDict[str, tuple[str, tuple[str, ...]]] = (
            OrderedDict()
        )

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

    @staticmethod
    def _request_message_payload(message: Any) -> Any:
        if hasattr(message, "model_dump"):
            return message.model_dump(
                mode="json",
                exclude={"id", "response_metadata", "usage_metadata"},
            )
        return message

    @staticmethod
    def _request_tool_payload(tool: Any) -> Any:
        if isinstance(tool, dict):
            return tool
        args_schema = getattr(tool, "args_schema", None)
        schema = (
            args_schema.model_json_schema()
            if args_schema is not None and hasattr(args_schema, "model_json_schema")
            else {}
        )
        return {
            "name": str(getattr(tool, "name", "") or ""),
            "description": str(getattr(tool, "description", "") or ""),
            "schema": schema,
        }

    @staticmethod
    def _model_identity(model: Any) -> dict[str, str]:
        model_name = str(
            getattr(model, "model_name", None)
            or getattr(model, "model", None)
            or type(model).__name__
        )
        base_url = str(
            getattr(model, "openai_api_base", None)
            or getattr(model, "base_url", None)
            or ""
        )
        host = (urlparse(base_url).hostname or "").lower() if base_url else ""
        if isinstance(model, ChatOpenAI):
            protocol = (
                "responses"
                if bool(getattr(model, "use_responses_api", False))
                else "chat_completions"
            )
        elif type(model).__module__.startswith("langchain_anthropic"):
            protocol = "anthropic"
        else:
            protocol = type(model).__module__ + "." + type(model).__name__
        return {"model": model_name, "host": host, "protocol": protocol}

    def _fingerprint_request(self, request: Any) -> ModelRequestFingerprint:
        context = current_prompt_run_context()
        system_message = request.system_message
        components: list[dict[str, Any]] = [
            {
                "kind": "identity",
                "stable_prefix_hash": context.cache_prefix_hash if context else "",
                "transcript_epoch": context.transcript_epoch if context else 0,
                "cache_mode": context.cache_mode if context else "",
                **self._model_identity(request.model),
            },
            {
                "kind": "system",
                "message": (
                    self._request_message_payload(system_message)
                    if system_message is not None
                    else None
                ),
            },
            {
                "kind": "tools",
                "tools": [self._request_tool_payload(tool) for tool in request.tools],
            },
        ]
        components.extend(
            {"kind": "message", "message": self._request_message_payload(message)}
            for message in request.messages
        )
        item_hashes = tuple(
            hmac.new(
                self._fingerprint_key,
                json.dumps(
                    component,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    default=str,
                ).encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
            for component in components
        )
        thread_id = context.thread_id if context else ""
        previous = self._previous_request_items.get(thread_id) if thread_id else None
        previous_hash, previous_items = previous if previous else ("", ())
        common = 0
        for old_item, new_item in zip(previous_items, item_hashes):
            if old_item != new_item:
                break
            common += 1
        request_hash = hmac.new(
            self._fingerprint_key,
            "\n".join(item_hashes).encode("ascii"),
            hashlib.sha256,
        ).hexdigest()[:32]
        if thread_id:
            self._previous_request_items[thread_id] = (request_hash, item_hashes)
            self._previous_request_items.move_to_end(thread_id)
            while len(self._previous_request_items) > 128:
                self._previous_request_items.popitem(last=False)
        fingerprint = ModelRequestFingerprint(
            request_hash=request_hash,
            request_item_count=len(item_hashes),
            previous_request_hash=previous_hash or None,
            previous_request_item_count=len(previous_items),
            common_prefix_item_count=common,
            previous_request_is_prefix=bool(previous_items)
            and common == len(previous_items),
            request_started_at=datetime.now(UTC),
        )
        if context is not None:
            context.request_fingerprint_sink.put(fingerprint)
        return fingerprint

    @staticmethod
    def _flatten_assistant_content(message: Any) -> Any:
        """Collapse Responses-style assistant content to the rebuilt transcript shape.

        run 内产生的 assistant 消息把 reasoning、text 与 function_call 都放进
        ``content`` 列表，跨 run 重建后只剩纯文本加 ``tool_calls``。两者在 wire
        上必须逐项一致，否则 provider 的 prefix cache 会在中间 assistant 处断开
        （2026-09-24 诊断：公共前缀停在第 21 条 assistant）。

        这里只改本次请求的副本：图内 state、checkpoint、UI 的 ``reasoning_delta``
        事件都不受影响。

        含 provider-native compaction item 的消息整条跳过：opaque item 是
        ADR-0014 决策 7 允许跨 run 重放的例外，压平会把它丢掉。

        ``name`` 一并清空：图内消息带协调器名（``cellwiki-agent``），重建形状
        没有；Responses 序列化会显式丢弃该字段（不影响 wire），但请求指纹用
        ``model_dump`` 比对，留着会让诊断把已命中的前缀报成不匹配。
        """

        if not isinstance(message, AIMessage) or not isinstance(message.content, list):
            return message
        if any(
            isinstance(block, dict) and block.get("type") == "compaction"
            for block in message.content
        ):
            return message
        text = "".join(
            str(block.get("text") or "")
            for block in message.content
            if isinstance(block, dict)
            and block.get("type") in ("text", "output_text")
        )
        return message.model_copy(update={"content": text, "name": None})

    @staticmethod
    def _drop_empty_thinking_blocks(message: Any) -> Any:
        """Drop signature-only thinking blocks that the provider refuses to replay.

        DeepSeek 的 Anthropic 兼容端点在个别轮次只流回"签名 + tool_use"、没有
        thinking 正文的退化块（2026-10-14 实测：git commit 轮）。回放时它被序列化为
        只有 ``type`` 与 ``signature`` 的块，服务端反序列化要求 ``thinking`` 字段，
        整个请求以 422（missing field `thinking`）被拒、run 必挂。带正文的签名块是
        Anthropic 的回传契约（整体剥离会 400），不在清理范围——只丢没有正文的块。
        这里只改本次请求的副本：图内 state、checkpoint、UI 的 ``reasoning_delta``
        事件都不受影响。
        """

        if not isinstance(message, AIMessage) or not isinstance(message.content, list):
            return message
        kept = [
            block
            for block in message.content
            if not (
                isinstance(block, dict)
                and block.get("type") == "thinking"
                and not str(block.get("thinking") or "").strip()
            )
        ]
        if len(kept) == len(message.content):
            return message
        if not kept:
            return message.model_copy(update={"content": ""})
        return message.model_copy(update={"content": kept})

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
        protocol = self._model_identity(request.model).get("protocol")
        if self.reasoning_replay == "none" and protocol == "responses":
            request = request.override(
                messages=[
                    self._flatten_assistant_content(message)
                    for message in request.messages
                ]
            )
        elif protocol == "anthropic":
            # 有效性守卫，与回放策略无关：退化（无正文）thinking 块任何模式下都
            # 不可回放，语义与 Responses 压平里"空文本块被丢弃"一致。
            request = request.override(
                messages=[
                    self._drop_empty_thinking_blocks(message)
                    for message in request.messages
                ]
            )
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



class _ModelRequestDiagnosticsMiddleware(AgentMiddleware):
    """Fingerprint the final request after compaction and tool-boundary rewrites."""

    name = "cellwiki_model_request_diagnostics"

    def __init__(self, fingerprinter: _CellWikiToolBoundaryMiddleware):
        self._fingerprinter = fingerprinter

    def wrap_model_call(self, request: Any, handler: Any) -> Any:
        self._fingerprinter._fingerprint_request(request)
        return handler(request)

    async def awrap_model_call(self, request: Any, handler: Any) -> Any:
        self._fingerprinter._fingerprint_request(request)
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
        # excluded_tools 已退役（2026-09-21）：本机七格隔离实验（每格独立进程）证明
        # 它零独有职责——stack 里 _ToolExclusionMiddleware 排在边界中间件之后，轮到它时工具面已是 13个；
        # task 由 general_purpose_subagent 关闭、TodoList 由 excluded_middleware 移除，都不靠它。
        # 反而是它在 2026-09-21 把白名单自己的 ls / delete_file 一起删掉。
        # profile 不匹配任何注册项时它根本不安装，那时靠的是
        # _CellWikiToolBoundaryMiddleware 的 allowlist（唯一承重防线）。
        # 详情与实测结论见 domain/agent_tools.py 文末。
        excluded_middleware=frozenset(
            {
                cast(Any, TodoListMiddleware),
                cast(Any, SummarizationMiddleware),
            }
        ),
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
# 思考整块到达。
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
# ---------------------------------------------------------------------------
def build_wiki_agent(
    project_root: Path | None = None,
    model: BaseChatModel | str | None = None,
    checkpointer=_DEFAULT_CHECKPOINTER,
    registry: SubagentRegistry | None = None,
    cache_policy: PromptCachePolicy | None = None,
    compaction_baseline_provider: Any = None,
    reasoning_replay: str = "none",
):
    """组装协调器 Deep Agent：模型 + 工具面 + 提示词 + checkpointer + 中间件。

    ``checkpointer`` 传默认哨兵时按工作区装配（默认 SqliteSaver，可退回内存）；
    显式传入的实例原样使用。

    中间件顺序 = [工具边界, 压缩]：工具边界必须最外层，压缩只在白名单工具面
    上工作；压缩中间件持有水位判定与 LLM 摘要，runtime 持有唯一写入权。
    ``compaction_baseline_provider`` 是 ``callable(thread_id) -> int``，供压缩
    中间件在 run 首次模型调用时拿到跨 run 的 provider 实测 prompt 基线（图状态
    的 usage 锚点只覆盖本 run 内产生的 AI 消息）。
    """
    root = Path(project_root or settings.workspace_root).resolve()
    _register_cellwiki_harness_profile(settings.openai_model)
    coordinator_model = model or build_model()
    # 构建工具集：工作区工具 + 确定性 lint 报告 + 交互工具
    coordinator_tools = build_coordinator_tools(root, registry)
    # 产品图默认落 SqliteSaver（data/runtime/checkpoints.sqlite），
    # 与 cellwiki.db 分文件；AGENT_CHECKPOINTER=inmemory 只是短期回滚闸。
    # 显式传入的 checkpointer 原样生效。
    active_checkpointer = (
        build_checkpointer(root) if checkpointer is _DEFAULT_CHECKPOINTER else checkpointer
    )
    tool_boundary = _CellWikiToolBoundaryMiddleware(
        append_reminder=True,
        cache_policy=cache_policy,
        reasoning_replay=reasoning_replay,
    )
    return create_deep_agent(
        name="cellwiki-agent",
        model=coordinator_model,
        system_prompt=SYSTEM_PROMPT,
        tools=coordinator_tools,
        middleware=[
            tool_boundary,
            CellWikiCompactionMiddleware(
                model=coordinator_model,
                threshold=(
                    cache_policy.compact_threshold if cache_policy else 1_024
                ),
                retained_tokens=settings.agent_context_retained_tokens,
                provider_native=bool(
                    cache_policy and cache_policy.provider_native_compaction
                ),
                baseline_provider=compaction_baseline_provider,
            ),
            _ModelRequestDiagnosticsMiddleware(tool_boundary),
        ],
        backend=StateBackend(),
        checkpointer=active_checkpointer,
        context_schema=WikiAgentContext,
        interrupt_on={},
    )
