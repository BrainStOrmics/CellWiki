# =============================================================================
# 智能体应用组装 —— 单一顶级协调器的构建工厂
# =============================================================================
# 本模块负责组装 CellWiki 智能体的核心组件：构建 LLM 模型、创建子智能体
# 规格（只读查询、导入、质量检查）、将工具注册到协调器，并最终组装为
# LangGraph 可执行的智能体应用。
# =============================================================================

"""Assembly of the single top-level Agentic CellWiki coordinator."""

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
from cellwiki.agent.tools import (
    build_attachment_tools,
    build_final_answer_tool,
    build_ingest_tools,
    build_lint_tools,
    build_memory_tools,
    build_read_tools,
)


# ---------------------------------------------------------------------------
# 系统提示词 —— 定义 CellWiki 协调器智能体的行为边界
# 约束：只读查询使用 query-agent，导入使用 ingest-agent；
# 任何知识变更必须经过 commit_change_set 确认；
# 外部研究结果必须经过注册→导入→ChangeSet→人工审批的完整流程。
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """You are the Model-led CellWiki coordinator for a scientific knowledge base.

Every natural-language request enters this coordinator. Decide what the user is
trying to accomplish from the request and the supplied runtime context, make a
short internal plan, and call only the visible CellWiki tools needed for that plan.
The available profiles cover published-Wiki query, source ingest, quality Lint, and
candidate-only external research. Do not route the user to a separate typed-task
form or ask them to provide an internal run ID.

When the runtime supplies a cellwiki_attachment_context block, treat references
such as "this paper" or "this article" as the attached files. Always inspect the
current attachments before answering an attachment-grounded question. The
attachment tools resolve the current thread automatically; never provide or ask
for a thread_id and never invent a placeholder such as "current".
When the runtime supplies a cellwiki_page_context block, treat its page_id as the
current explicitly referenced published Wiki page. For questions about that page,
call read_wiki_page with that exact page_id before answering; do not replace the
page-scoped request with an unbounded project search.
Reading an attachment is not source registration. For questions such as "what
does this paper mention?", answer from the attachment and set knowledge_scope to
attachment. Call register_attachment_as_source or ingest tools only when the
current user explicitly asks to register, import, or ingest the attachment.
If the user explicitly says not to register, ingest, or create a ChangeSet, treat that as a constraint on actions
rather than a request for a workflow explanation;
answer the attachment question directly unless they ask about the workflow.

Ingest, revision, and Lint repair tools only prepare immutable candidate ChangeSets.
They never publish formal Wiki knowledge. After a ChangeSet is prepared, summarize
what will change and wait for the runtime's single human approval boundary. Never
call or invent a publication tool, never modify files directly, and never claim a
ChangeSet was committed before the runtime reports CentralWriter verification. If a
required source, page, or scope is missing, ask a concise clarification rather than
guessing. External research results are candidate sources only and must not be
treated as formal Wiki evidence until the governed source and approval workflow
completes.

For ingest, source_id means the canonical identifier returned as source.source_id
by register_attachment_as_source or the source registry. content_hash is only a
deduplication hash; never use it as a source_id and never construct a src_ ID by
prefixing a full content hash.

Delegate a bounded evidence question to query-agent when useful; never launch
parallel tasks or generic reconnaissance. For product-operation explanations or
clarification questions, answer directly, set knowledge_scope to general, and do
not invent knowledge citations.

For evidence questions, citations must use exact page_id values returned by
CellWiki tools; include source_id and a section locator when they are available.
Never invent a citation merely to increase confidence. Finish every answer by
calling submit_agent_answer exactly once; do not return the final answer as
plain text.

Governed memory contains prior task outcomes, not scientific truth. It may guide
workflow continuity but must never be cited as evidence. Never store chain of
thought or private reasoning. External research results are candidates only:
they must become registered sources, pass ingest, produce a ChangeSet, and pass
the configured approval policy before they can affect formal Wiki knowledge.
"""

# Deep Agents' stock prompt describes a general coding workspace. CellWiki has
# narrower governed tools, so every coordinator and subagent shares this base.
HARNESS_PROMPT = """You are a governed CellWiki agent. Use only the visible CellWiki
domain tools and the current runtime context. Query tools read published knowledge;
ingest and Lint tools create candidate ChangeSets; research tools create candidate
sources. Ground scientific claims in exact page IDs returned by tools, identify
missing evidence, and never invent citations. Candidate ChangeSets are not formal
knowledge until the runtime's approval, CentralWriter, and Verification boundary
completes. Never use generic filesystem, shell, or publication tools. Governed
memory is workflow context, never scientific evidence; do not store private
reasoning. Return concise results appropriate to your assigned role.
"""

# 哨兵对象，用于区分"未传入检查点器"和"传入了 None"
_DEFAULT_CHECKPOINTER = object()


class _CellWikiToolBoundaryMiddleware(AgentMiddleware):
    """Keep generic filesystem tools out of every CellWiki model request.

    Deep Agents normally injects filesystem tools into both the coordinator and
    its declarative subagents. The registered HarnessProfile also excludes
    them, but this local boundary is deliberately defense in depth because
    provider-built model instances do not always preserve profile filtering
    across nested subagent graphs.
    """

    name = "cellwiki_tool_boundary"
    _blocked_tools = frozenset(
        {
            "write_todos",
            "ls",
            "read_file",
            "write_file",
            "edit_file",
            "glob",
            "grep",
        }
    )
    _read_only_attachment_mutating_tools = frozenset(
        {
            "register_attachment_as_source",
            "prepare_ingest_change_set",
            "request_ingest_revision",
            "run_broad_lint",
            "propose_lint_fix",
            "rebase_change_set",
            "commit_change_set",
        }
    )
    _boundary_reminder = (
        "CellWiki tool boundary: the built-in deep-agent filesystem tools "
        "ls, read_file, write_file, edit_file, glob, grep, and write_todos are "
        "unavailable, even if an earlier generic workspace prompt describes them. "
        "Emit calls only for tool schemas visible in this request. After a governed "
        "pipeline tool returns its complete report, stop tool use and report from "
        "that payload."
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

    @classmethod
    def _is_read_only_attachment_context(cls, request: Any) -> bool:
        runtime = getattr(request, "runtime", None)
        context = getattr(runtime, "context", None)
        if isinstance(context, WikiAgentContext):
            return bool(context.attachment_ids) and not context.allow_attachment_promotion
        if isinstance(context, dict):
            return bool(context.get("attachment_ids")) and not bool(
                context.get("allow_attachment_promotion", False)
            )
        return False

    def _filter_request(self, request: Any) -> Any:
        blocked_tools = set(self._blocked_tools)
        if self._is_read_only_attachment_context(request):
            blocked_tools.update(self._read_only_attachment_mutating_tools)
        filtered_tools = [
            tool
            for tool in request.tools
            if self._tool_name(tool) not in blocked_tools
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

        if request.tool_call.get("name") in self._blocked_tools:
            return self._blocked_tool_response(request)
        return handler(request)

    async def awrap_tool_call(self, request: Any, handler: Any) -> Any:
        """Async counterpart of ``wrap_tool_call`` for the desktop runtime."""

        if request.tool_call.get("name") in self._blocked_tools:
            return self._blocked_tool_response(request)
        return await handler(request)


@lru_cache(maxsize=None)
def _register_cellwiki_harness_profile(model_name: str) -> None:
    """Keep the Deep Agents harness limited to CellWiki-owned capabilities."""
    # CellWiki persists knowledge through governed tools, so generic filesystem
    # and TODO tools only enlarge provider requests without serving the product.
    profile = HarnessProfile(
        base_system_prompt=HARNESS_PROMPT,
        # Deep Agents otherwise auto-injects its generic filesystem-oriented
        # fallback when no explicit general-purpose spec is supplied.
        general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
        excluded_tools=frozenset(
            {
                "write_todos",
                "ls",
                "read_file",
                "write_file",
                "edit_file",
                "glob",
                "grep",
            }
        ),
        excluded_middleware=frozenset({cast(Any, TodoListMiddleware)}),
        tool_description_overrides={
            "task": (
                "Delegate one bounded task to a CellWiki specialist. "
                "Choose from:\n\n{available_agents}"
            )
        },
    )
    # The provider-level registration also covers supported pre-built
    # ChatOpenAI instances whose model name differs from the configured default.
    register_harness_profile("openai", profile)
    register_harness_profile(f"openai:{model_name}", profile)


# ---------------------------------------------------------------------------
# 构建子智能体规格列表
# 定义三种核心子智能体：
# - query-agent: 知识问答
# - ingest-agent: 来源导入
# - lint-agent: 质量检查与外部知识刷新
# 每种子智能体有自己的系统提示词、工具集和响应格式。
# ---------------------------------------------------------------------------
def build_subagent_specs(
    model: BaseChatModel | str,
    read_tools: list,
) -> list[dict[str, Any]]:
    # 只读子智能体的共享提示词：严格限定在只读工具范围内工作
    read_only_prompt = (
        "Work only from the supplied CellWiki read tools. Return concise findings "
        "with exact page IDs and identify missing evidence. Every factual finding must "
        "be traceable to a page returned by read_wiki_page. Never propose that a write succeeded."
    )
    query_tools = [
        tool for tool in read_tools if getattr(tool, "name", None) != "get_change_set"
    ]
    return [
        {
            "name": "query-agent",           # 知识问答智能体
            "description": "Answer questions from published CellWiki pages with citations.",
            "system_prompt": read_only_prompt,
            "model": model,
            "tools": query_tools,
            "middleware": [_CellWikiToolBoundaryMiddleware()],
            "interrupt_on": {},
        },
    ]


# ---------------------------------------------------------------------------
# 构建 LLM 模型实例
# 使用 ChatOpenAI 以兼容 OpenAI 及第三方提供商（Ollama、vLLM 等）。
# 关键配置：
# - temperature=0 确保输出的确定性
# - 禁用 tool_calling 流式传输，因为自定义提供商经常发送格式错误的
#   部分工具调用流；非流式工具调用能保持稳定的图执行步骤
# ---------------------------------------------------------------------------
def build_model(configuration: Settings = settings) -> BaseChatModel:
    _register_cellwiki_harness_profile(configuration.openai_model)
    return build_openai_chat_model(configuration, purpose="coordinator")


# ---------------------------------------------------------------------------
# 构建完整的 Wiki 智能体
# 组装协调器智能体，包含：
# 1. LLM 模型（ChatOpenAI 兼容）
# 2. 只读工具（项目状态、搜索、页面读取）
# 3. 导入工具（ChangeSet 准备）
# 4. 记忆工具（可选，根据配置启用）
# 5. 研究工具（可选，根据配置启用）
# 6. 提交工具（ChangeSet 提交）
# 7. 子智能体（query-agent、ingest-agent、lint-agent）
# 8. 检查点器（状态持久化）
# 返回 Deep Agent 实例，可直接用于 LangGraph 执行。
# ---------------------------------------------------------------------------
def build_wiki_agent(
    project_root: Path | None = None,
    model: BaseChatModel | str | None = None,
    checkpointer=_DEFAULT_CHECKPOINTER,
):
    # 解析项目根目录
    root = Path(project_root or settings.project_root).resolve()
    _register_cellwiki_harness_profile(settings.openai_model)
    # 如果未指定模型，使用默认构建
    coordinator_model = model or build_model()
    # 构建工具集
    read_tools = build_read_tools(root)
    # The coordinator owns the product decision loop. Domain tools stay visible
    # at this level so the model can choose query, ingest, or lint from the
    # user's natural-language request; only bounded evidence work is delegated.
    coordinator_tools: list[Any] = [
        *read_tools,
        *build_attachment_tools(root),
        *build_ingest_tools(root),
        *build_lint_tools(root),
    ]
    if settings.enable_agent_memory:
        # 启用记忆：召回 + 提交候选
        recall_memory, propose_memory = build_memory_tools(root)
        read_tools.append(recall_memory)
        coordinator_tools.extend((recall_memory, propose_memory))
    final_answer_tool = build_final_answer_tool(root)
    # 检查点器：默认使用 InMemorySaver，除非传入了外部检查点器
    active_checkpointer = (
        InMemorySaver() if checkpointer is _DEFAULT_CHECKPOINTER else checkpointer
    )
    # 组装 Deep Agent
    return create_deep_agent(
        name="cellwiki-agent",
        model=coordinator_model,
        system_prompt=SYSTEM_PROMPT,
        tools=[*coordinator_tools, final_answer_tool],
        middleware=[_CellWikiToolBoundaryMiddleware()],
        # Deep Agents 在运行时接受文档化的字典规格；
        # 其当前的类型包将此参数缩小为内部 TypedDict 类，因此需要 cast
        subagents=cast(
            Any,
            build_subagent_specs(
                coordinator_model,
                read_tools,
            ),
        ),
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
