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
from cellwiki.domain.contracts import ApprovalPolicy, WikiAgentContext
from cellwiki.agent.tools import (
    build_commit_tool,
    build_final_answer_tool,
    build_ingest_tools,
    build_lint_tools,
    build_memory_tools,
    build_read_tools,
    build_rebase_tool,
)
from cellwiki.services.pipeline import KnowledgePipelineHarness


# ---------------------------------------------------------------------------
# 系统提示词 —— 定义 CellWiki 协调器智能体的行为边界
# 约束：只读查询使用 query-agent，导入使用 ingest-agent；
# 任何知识变更必须经过 commit_change_set 确认；
# 外部研究结果必须经过注册→导入→ChangeSet→人工审批的完整流程。
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """You are the CellWiki coordinator for a scientific knowledge base.

Never claim a formal knowledge change succeeded until
commit_change_set returns a committed result. Every extraction or curation
change must follow the configured project approval policy; auto-approved changes
still require a ChangeSet and CentralWriter. Do not treat scratch files as CellWiki
content. If evidence is missing, say so and recommend registering a source.
Reject wins; no publish.
Route query to query-agent; ingest/re-ingest to ingest-agent; and lint or external
papers to lint-agent with run_broad_lint. delegate exactly one specialist task;
never launch parallel tasks or generic reconnaissance. The coordinator handles approval,
rejection, revision, and rebase. External research is not a separate agent.
When a reviewer supplies correction comments for an ingest proposal, use
request_ingest_revision to preserve the feedback and prepare a new same-source
ChangeSet. Never mutate or reuse the original ChangeSet.
If a proposal reports a stale base, use rebase_change_set and surface any
overlapping target conflicts instead of silently overwriting them.

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
HARNESS_PROMPT = """You are a CellWiki agent. Use only the visible CellWiki tools.
Ground scientific claims in exact page IDs returned by tools, identify missing
evidence, and never invent citations. Knowledge changes must come from registered
sources, be prepared as immutable ChangeSets, and pass the configured approval
policy before commit. For ingest, report the ChangeSet ID, evidence gaps, and conflicts;
never publish directly. External research is candidate evidence only: report its
provenance and access or review warnings, and never let it alter formal knowledge
directly. Governed memory is workflow context, never scientific evidence; do not
store private reasoning. Return concise results appropriate to your assigned role.
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

    def _filter_request(self, request: Any) -> Any:
        filtered_tools = [
            tool
            for tool in request.tools
            if getattr(tool, "name", None) not in self._blocked_tools
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
    ingest_tools: list,
    research_tools: list | None = None,
    lint_tools: list | None = None,
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
    # 定义三个核心子智能体
    specs: list[dict[str, Any]] = [
        {
            "name": "query-agent",           # 知识问答智能体
            "description": "Answer questions from published CellWiki pages with citations.",
            "system_prompt": read_only_prompt,
            "model": model,
            "tools": query_tools,
            "middleware": [_CellWikiToolBoundaryMiddleware()],
            "interrupt_on": {},
        },
        {
            "name": "ingest-agent",          # 导入智能体（可写，但仅限 ChangeSet）
            "description": "Analyze a registered source and prepare an immutable ChangeSet.",
            "system_prompt": (
                "Analyze only registered sources. Use prepare_ingest_change_set for a new "
                "proposal or request_ingest_revision when reviewer comments must be applied. "
                "Return the ChangeSet ID, evidence gaps, and conflicts. You cannot publish changes."
            ),
            "model": model,
            "tools": [*read_tools, *ingest_tools],  # 导入智能体拥有更多工具
            "middleware": [_CellWikiToolBoundaryMiddleware()],
            "interrupt_on": {},
        },
    ]
    if lint_tools:
        # Lint must enter through run_broad_lint, which acquires the project
        # lease and captures the whole-library snapshot before reporting state.
        # Lint owns the whole-project snapshot. Keeping read tools off this
        # surface prevents follow-up file reads from racing with that lease or
        # inviting generic filesystem tool calls after the governed report is
        # already complete.
        lint_pipeline_tools = [
            tool
            for tool in lint_tools
            if getattr(tool, "name", None) != "inspect_knowledge_quality"
        ]
        specs.append(
            {
                "name": "lint-agent",
                "description": "Inspect formal knowledge quality and prepare governed Lint ChangeSets.",
                "system_prompt": (
                    "Inspect the complete CellWiki formal state before reporting findings. "
                    "For any broad or local quality request, call run_broad_lint exactly once "
                    "as the only inspection tool call; its response already contains the "
                    "whole-project snapshot and quality report. Do not call any read tool, "
                    "generic filesystem tool, or issue parallel tool calls after it returns. "
                    "When the user requests external research, include a "
                    "focused external_query so candidates are registered with provenance. "
                    "Use propose_lint_fix only for deterministic auto-fixable findings. "
                    "Never apply a ChangeSet."
                ),
                "model": model,
                "tools": lint_pipeline_tools,
                "middleware": [_CellWikiToolBoundaryMiddleware(append_reminder=True)],
                "interrupt_on": {},
            }
        )
    return specs


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
    return build_openai_chat_model(configuration)


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
    ingest_tools = build_ingest_tools(root)
    lint_tools = build_lint_tools(root)
    # The coordinator delegates evidence work to specialist subagents. Keeping
    # read tools off the top-level request makes that ownership boundary explicit.
    coordinator_tools: list[Any] = []
    if settings.enable_agent_memory:
        # 启用记忆：召回 + 提交候选
        recall_memory, propose_memory = build_memory_tools(root)
        read_tools.append(recall_memory)
        coordinator_tools.extend((recall_memory, propose_memory))
    # 提交工具（ChangeSet 提交）
    commit_tool = build_commit_tool(root)
    rebase_tool = build_rebase_tool(root)
    final_answer_tool = build_final_answer_tool(root)
    # 检查点器：默认使用 InMemorySaver，除非传入了外部检查点器
    active_checkpointer = (
        InMemorySaver() if checkpointer is _DEFAULT_CHECKPOINTER else checkpointer
    )
    approval_interrupt = (
        {}
        if KnowledgePipelineHarness(root).approval_policy() is ApprovalPolicy.AUTO_ALL
        else {"commit_change_set": {"allowed_decisions": ["approve", "reject"]}}
    )
    # 组装 Deep Agent
    return create_deep_agent(
        name="cellwiki-agent",
        model=coordinator_model,
        system_prompt=SYSTEM_PROMPT,
        tools=[*coordinator_tools, rebase_tool, commit_tool, final_answer_tool],
        middleware=[_CellWikiToolBoundaryMiddleware()],
        # Deep Agents 在运行时接受文档化的字典规格；
        # 其当前的类型包将此参数缩小为内部 TypedDict 类，因此需要 cast
        subagents=cast(
            Any,
            build_subagent_specs(
                coordinator_model,
                read_tools,
                ingest_tools,
                lint_tools=lint_tools,
            ),
        ),
        backend=StateBackend(),
        checkpointer=active_checkpointer,
        context_schema=WikiAgentContext,
        # Manual policy pauses before publication; auto_all keeps the same write
        # boundary but lets CentralWriter obtain the policy decision itself.
        interrupt_on=cast(Any, approval_interrupt),
    )


# ---------------------------------------------------------------------------
# LangGraph Agent Server 使用的工厂函数
# 服务端拥有自己的持久化层，因此传入 checkpointer=False
# ---------------------------------------------------------------------------
def create_server_graph():
    """Factory used by LangGraph Agent Server, which owns persistence."""
    return build_wiki_agent(checkpointer=False)
