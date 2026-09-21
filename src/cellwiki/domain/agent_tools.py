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


# 框架残留排除清单：框架（deepagents/langchain）真实注入、且没有同名 CellWiki
# 工具覆盖的通用工具名，交给 HarnessProfile.excluded_tools 剥离。
#
# 两套惯例的分界（务必看清，别再混）：
# - 这里只放"框架注入且无同名 CellWiki 工具"的残留。框架排除按名字匹配、
#   不区分工具来源，所以任何名字一旦出现在本清单，同名的 CellWiki 工具也会被
#   一起剥掉——这就是 2026-09-21 白名单工具被自己人删掉的根因。
# - 框架同名工具（read_file / write_file / edit_file / glob / grep）刻意不入
#   本清单，改由 _CellWikiToolBoundaryMiddleware 的 allowlist 单层过滤：
#   ToolNode 按名覆盖同名项，放进排除清单只会把 CellWiki 自己的实现删掉。
# - ls 留在本清单：CellWiki 的 ls 已退役（能力由 glob + run_powershell 覆盖），
#   框架同名 ls 失去"被同名工具覆盖"的天然遮蔽，必须显式排除。
FRAMEWORK_EXCLUDED_TOOL_NAMES: frozenset[str] = frozenset(
    {"write_todos", "ls", "task", "execute"}
)

# 不变量：框架排除清单与白名单不得有交集（框架排除按名匹配、不区分来源）。
_OVERLAP = FRAMEWORK_EXCLUDED_TOOL_NAMES & AGENT_VISIBLE_TOOL_NAMES
if _OVERLAP:
    raise RuntimeError(
        "framework excluded_tools and the CellWiki whitelist overlap: "
        f"{sorted(_OVERLAP)}. deepagents strips excluded tools by name without "
        "checking their origin, so listing a whitelisted tool here deletes the "
        "CellWiki tool itself."
    )


__all__ = [
    "AGENT_TOOL_NAMES_TEXT",
    "AGENT_TOOL_SPECS",
    "AGENT_VISIBLE_TOOL_NAMES",
    "CANONICAL_TOOL_ORDER",
    "FRAMEWORK_EXCLUDED_TOOL_NAMES",
    "AgentToolSpec",
]
