# =============================================================================
# Agent 工具注册表 —— "Agent 能干什么"的唯一事实源
# =============================================================================
# 本模块只承载工具名与规范顺序，不承载工具实现，也不导入 langchain_core：
# domain/ 是无依赖叶子层，agent/ 与 services/ 都从它派生。
#
# 历史缺陷（2026-09-21）：工具清单曾在五处独立手写（executor 白名单、
# executor 规范顺序、app.excluded_tools、提示词散文、前端 TOOL_CARDS），
# 任一处漏改即复发。其中 app.py 的框架排除清单按名字无条件删除工具、
# 不区分来源，把白名单自己的 ls / delete_file 一起删掉了：白名单声明 14 个，
# 模型实际只见 12 个。
# =============================================================================

"""Single source of truth for the CellWiki agent tool surface."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentToolSpec:
    """One model-visible CellWiki tool: its name and its surface category."""

    name: str
    category: str


# 规范顺序 = 模型请求里的工具顺序，参与 tool_schema_fingerprint 与稳定前缀；
# 顺序即注册顺序，改顺序等于改缓存指纹，须按 ADR-0014 的预期变更对待。
AGENT_TOOL_SPECS: tuple[AgentToolSpec, ...] = (
    AgentToolSpec("glob", "File"),
    AgentToolSpec("grep", "File"),
    AgentToolSpec("read_file", "File"),
    AgentToolSpec("write_file", "File"),
    AgentToolSpec("edit_file", "File"),
    AgentToolSpec("delete_file", "File"),
    AgentToolSpec("rename_file", "File"),
    AgentToolSpec("git", "Git"),
    AgentToolSpec("run_powershell", "Shell"),
    AgentToolSpec("lint_knowledge_base", "Lint"),
    AgentToolSpec("ask_user_question", "Question"),
    AgentToolSpec("read_attachment", "Context"),
    AgentToolSpec("promote_attachment", "Source"),
)

# 白名单（allowlist）：模型可见的 CellWiki 自有工具名。
AGENT_VISIBLE_TOOL_NAMES: frozenset[str] = frozenset(
    spec.name for spec in AGENT_TOOL_SPECS
)

# 规范顺序元组（注册顺序）。
CANONICAL_TOOL_ORDER: tuple[str, ...] = tuple(spec.name for spec in AGENT_TOOL_SPECS)

# 提示词里逐字列出的工具名清单（逗号分隔，规范顺序）。
AGENT_TOOL_NAMES_TEXT: str = ", ".join(CANONICAL_TOOL_ORDER)


# 关于“框架通用工具”的边界（2026-09-21 复核后的结论，别再引入第二层）：
# 本注册表**不**再声明 excluded_tools。曾有一段 HarnessProfile.excluded_tools =
# {write_todos, ls, task, execute}，本机七格隔离实验（每格独立进程，避免框架
# register_harness_profile 的 additive merge 把“清空”并回去）证明它零独有职责：
# - profile 匹配时栈序为 boundary(14->13) -> _ToolExclusionMiddleware(13->13)，
#   框架排除排在边界之后，轮到它已无活可干；task/execute/write_todos 根本不会被注入
#   （task 由 general_purpose_subagent 关闭、TodoList 由 excluded_middleware 移除）。
# - ls 被 allowlist 重复覆盖；只有 allowlist 与 excluded_tools 同时撤掉，ls 才会漏进
#   请求（14 个工具）。
# - profile 不匹配任何注册项时，框架排除中间件根本不安装，上游原始面是 16 个工具
#   （含 ls/task/write_todos），此时**只有** _CellWikiToolBoundaryMiddleware 的
#   allowlist 在兜底，剥离到 13 个。
# 因此 allowlist 是唯一承重防线，调用拦截（wrap_tool_call/awrap_tool_call）是零成本的
# 最后一道；两者都在 agent/app.py。

__all__ = [
    "AGENT_TOOL_NAMES_TEXT",
    "AGENT_TOOL_SPECS",
    "AGENT_VISIBLE_TOOL_NAMES",
    "CANONICAL_TOOL_ORDER",
    "AgentToolSpec",
]
