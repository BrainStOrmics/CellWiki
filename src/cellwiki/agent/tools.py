# =============================================================================
# 智能体工具 —— 工作区版 CellWiki 协调器的工具集
# =============================================================================
# 阶段 1 提供最小确定性工具：工作区只读检查、知识库 Lint（只报告）、
# 纯文本最终回答。阶段 3 将把文件/Glob/Grep/Git/PowerShell 工具放入
# 白名单执行器；阶段 5 将最终回答改为纯文本 + 文件路径引用。
# =============================================================================

"""Coordinator tools for the workspace-based CellWiki agent."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from cellwiki.services.quality import inspect_projection


class FinalAnswerInput(BaseModel):
    """Plain-text final answer with optional workspace-relative file references."""

    answer: str = Field(min_length=1)
    file_paths: list[str] = Field(default_factory=list)


def build_final_answer_tool(project_root: Path) -> BaseTool:
    """Build the coordinator's direct-return plain-text answer boundary."""

    @tool("submit_agent_answer", args_schema=FinalAnswerInput, return_direct=True)
    def submit_agent_answer(answer: str, file_paths: list[str] | None = None) -> str:
        """Finish with a plain-text answer and the workspace-relative files you referenced."""

        normalized_paths: list[str] = []
        for raw in file_paths or []:
            value = str(raw).strip().replace("\\", "/")
            if (
                value
                and not value.startswith(("/", ".."))
                and ":" not in value
                and value not in normalized_paths
            ):
                normalized_paths.append(value)
        return json.dumps(
            {"answer": answer, "file_paths": normalized_paths},
            ensure_ascii=False,
        )

    return submit_agent_answer


def _workspace_markdown_paths(root: Path) -> list[Path]:
    """Return sorted Markdown files under the workspace's wiki directory (if any)."""
    base = root / "wiki"
    if not base.exists():
        return []
    return sorted(path for path in base.rglob("*.md") if path.is_file())


def build_read_tools(project_root: Path) -> list[BaseTool]:
    """Provide bounded workspace overview, search, and page-read tools."""
    root = Path(project_root).resolve()

    @tool("get_project_status")
    def get_project_status() -> str:
        """Return a compact overview of the selected knowledge-base workspace."""
        raw = root / "raw"
        result: dict[str, Any] = {
            "workspace": str(root),
            "wiki_page_count": len(_workspace_markdown_paths(root)),
            "raw_file_count": (
                sum(1 for path in raw.rglob("*") if path.is_file()) if raw.exists() else 0
            ),
            "root_markdown_files": [path.name for path in sorted(root.glob("*.md"))],
        }
        return json.dumps(result, ensure_ascii=False)

    @tool("search_wiki")
    def search_wiki(query: str, limit: int = 10) -> str:
        """Search workspace Markdown titles and bodies; return paths with short snippets."""
        query_lower = str(query or "").strip().lower()
        bounded = max(1, min(int(limit or 10), 20))
        matches: list[dict[str, Any]] = []
        for path in _workspace_markdown_paths(root):
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            title = path.stem
            for line in text.splitlines():
                if line.startswith("# "):
                    title = line.lstrip("# ").strip()
                    break
            score = 2 if query_lower and query_lower in title.lower() else 1
            if not query_lower or query_lower not in text.lower():
                continue
            idx = text.lower().find(query_lower)
            snippet = " ".join(text[max(0, idx - 120) : idx + 240].split())
            matches.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "title": title[:200],
                    "score": score,
                    "snippet": snippet[:400],
                }
            )
            if len(matches) >= bounded:
                break
        matches.sort(key=lambda item: item["score"], reverse=True)
        return json.dumps({"results": matches}, ensure_ascii=False)

    @tool("read_wiki_page")
    def read_wiki_page(page_id: str) -> str:
        """Read one workspace Markdown page by its workspace-relative path."""
        raw_rel = str(page_id or "").strip().replace("\\", "/").lstrip("/")
        candidate = (root / raw_rel).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            return json.dumps(
                {"error": "path_outside_workspace", "page_id": page_id},
                ensure_ascii=False,
            )
        if not candidate.is_file() or candidate.suffix.lower() != ".md":
            return json.dumps(
                {"error": "page_not_found", "page_id": page_id},
                ensure_ascii=False,
            )
        try:
            content = candidate.read_text(encoding="utf-8", errors="replace")
        except OSError as error:
            return json.dumps(
                {"error": "read_failed", "page_id": page_id, "detail": str(error)},
                ensure_ascii=False,
            )
        if len(content) > 20_000:
            content = content[:20_000] + "\n...[truncated]"
        return json.dumps(
            {"path": candidate.relative_to(root).as_posix(), "markdown": content},
            ensure_ascii=False,
        )

    return [get_project_status, search_wiki, read_wiki_page]


def build_lint_tools(project_root: Path) -> list[BaseTool]:
    """Provide the deterministic knowledge-base lint as a report-only tool."""
    root = Path(project_root).resolve()

    @tool("lint_knowledge_base")
    def lint_knowledge_base() -> str:
        """Run the deterministic knowledge-base lint over the workspace (report only, never writes)."""
        try:
            report = inspect_projection(root)
            return json.dumps(report, ensure_ascii=False, default=str)
        except Exception as error:  # lint must never crash an agent run
            return json.dumps(
                {"status": "error", "error": str(error)[:500]},
                ensure_ascii=False,
            )

    return [lint_knowledge_base]