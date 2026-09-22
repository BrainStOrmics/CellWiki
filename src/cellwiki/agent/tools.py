# =============================================================================
# 智能体工具 —— 工作区版 CellWiki 协调器的工具集
# =============================================================================
# 确定性工具：知识库 Lint（只报告，与发布门禁共用同一实现）。
# 文件/Glob/Grep/Git/PowerShell 工具在 agent/executor.py；工具名与规范顺序的
# 唯一定义在 domain/agent_tools.py。
# 2026-09-22：get_project_status / search_wiki / read_wiki_page 退役——它们自
# 2026-08-23 git 治理重构后就没有调用者，也不在注册表里。
# =============================================================================

"""Coordinator tools for the workspace-based CellWiki agent."""

from __future__ import annotations

import json
from pathlib import Path

from langchain_core.tools import BaseTool, tool
from cellwiki.services.quality import inspect_projection
from cellwiki.services.run_scope import changed_paths_for_scope


def build_lint_tools(project_root: Path) -> list[BaseTool]:
    """Provide the deterministic knowledge-base lint as a report-only tool."""
    root = Path(project_root).resolve()

    @tool("lint_knowledge_base")
    def lint_knowledge_base() -> str:
        """Run the deterministic knowledge-base lint over the workspace (report only, never writes).

        Inside a run the report covers the pages this run changed, matching the
        publish gate; outside a run only the schema contract is validated.
        """
        try:
            report = inspect_projection(root, changed_paths=changed_paths_for_scope(root))
            return json.dumps(report, ensure_ascii=False, default=str)
        except Exception as error:  # lint must never crash an agent run
            return json.dumps(
                {"status": "error", "error": str(error)[:500]},
                ensure_ascii=False,
            )

    return [lint_knowledge_base]
