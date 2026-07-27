# =============================================================================
# Lint LangGraph 子图 —— 自修复的 Lint 检查管线
# =============================================================================
# 对 CellWiki 知识库运行扫描-分类-修复-复检循环。
# 检测索引不匹配、断链 Wiki 链接和审计违规，然后自动修复或排队等待人工审查。
# 支持最大迭代次数限制，防止无限修复循环。
# =============================================================================

"""Lint LangGraph subgraph: self-healing lint pipeline.

Runs a scan-classify-fix-recheck loop over the CellWiki knowledge base.
Detects index mismatches, broken wikilinks, and audit violations, then
either auto-fixes them or queues them for manual review.

Usage:
    from cellwiki.lint_graph import build_lint_graph, run_lint
    result = run_lint(auto_fix=True)
"""

import logging
import re

from langgraph.graph import StateGraph, END

from cellwiki.legacy.graphs.checkpointer import get_checkpointer
from cellwiki.legacy.graphs.states import LintState

logger = logging.getLogger(__name__)


def scan_all(state: LintState) -> dict:
    """Run all lint checks. Reuses existing audit.py logic."""
    issues = []

    try:
        # Use existing audit if available
        from cellwiki.legacy.audit import run_audit as audit_run
        audit_results = audit_run()

        for category, category_issues in audit_results.items():
            for issue in category_issues:
                severity = issue.get("severity", "LOW")
                issues.append({
                    "type": category,
                    "cell_type": issue.get("cell_type", ""),
                    "detail": issue.get("detail", ""),
                    "severity": severity,
                    # Only missing_cl_id and orphan_subpopulations have safe automated fixes;
                    # other categories (e.g. schema violations) require human judgment.
                    "auto_fixable": category in ("missing_cl_id", "orphan_subpopulations"),
                })
    except Exception as e:
        issues.append({
            "type": "audit_error",
            "detail": f"Audit failed: {str(e)}",
            "severity": "HIGH",
            "auto_fixable": False,
        })

    # Additional checks specific to v2.0 structure

    # Check README.md consistency
    from cellwiki.config import settings
    index_path = settings.wiki_dir / "README.md"
    if index_path.exists():
        index_content = index_path.read_text(encoding="utf-8")
        ct_dir = settings.wiki_cell_types_dir
        if ct_dir.exists():
            actual_files = {f.stem for f in ct_dir.glob("*.md")}
            # Check if all files are mentioned in index
            # Both [[f]] (wikilink) and (f.md) (markdown link) are valid link formats.
            for f in actual_files:
                if f"[{f}]" not in index_content and f"({f}.md)" not in index_content:
                    issues.append({
                        "type": "index_mismatch",
                        "detail": f"{f} exists but not in README.md",
                        "severity": "MEDIUM",
                        "auto_fixable": True,
                    })

    # Check for broken wikilinks
    # O(n*m) scan over pages x subdirectories; acceptable for wiki-scale (hundreds of pages),
    # but a pre-built link index would be preferable for larger knowledge bases.
    for subdir in ["cell_types", "marker_genes", "tissues", "diseases", "methods", "trajectories"]:
        dir_path = settings.wiki_dir / subdir
        if dir_path.exists():
            for page_file in dir_path.glob("*.md"):
                content = page_file.read_text(encoding="utf-8")
                links = re.findall(r'\[\[(.+?)\]\]', content)
                for link in links:
                    # Check if linked page exists
                    found = False
                    for check_subdir in ["cell_types", "marker_genes", "tissues", "diseases", "methods", "trajectories"]:
                        if (settings.wiki_dir / check_subdir / f"{link}.md").exists():
                            found = True
                            break
                    # "log" and "contradictions" are synthetic wikilinks used in templates,
                    # not actual page names — skip them to avoid false positives.
                    if not found and link not in ("log", "contradictions"):
                        issues.append({
                            "type": "broken_link",
                            "page": page_file.stem,
                            "link": link,
                            "detail": f"[[{link}]] in {page_file.stem} points to non-existent page",
                            "severity": "LOW",
                            "auto_fixable": True,
                        })

    return {"issues": issues}


def classify_issues(state: LintState) -> dict:
    """Classify issues into auto-fixable vs manual review."""
    issues = state.get("issues", [])

    auto_fixable = []
    manual_review = []

    for issue in issues:
        if issue.get("auto_fixable", False):
            auto_fixable.append(issue)
        else:
            manual_review.append(issue)

    return {
        "auto_fixable": auto_fixable,
        "manual_review": manual_review,
        # Status drives the graph's conditional edge: "fixing" routes to auto_fix,
        # "review_queue" routes straight to manual review.
        "status": "fixing" if auto_fixable else "review_queue",
    }


def auto_fix(state: LintState) -> dict:
    """Keep the legacy graph read-only; governed repairs now use a ChangeSet proposal."""

    remaining = [
        {
            **issue,
            "fix_error": (
                "Direct lint mutation is disabled. Propose a ChangeSet through "
                "LintFixService and apply it with CentralWriter after approval."
            ),
        }
        for issue in state.get("auto_fixable", [])
    ]
    return {
        "fixes_applied": [],
        "remaining_issues": remaining,
        # Set iteration to max so the recheck loop sees no remaining budget and exits.
        "iteration": state.get("max_iterations", 0),
        "status": "rechecking",
    }


def recheck(state: LintState) -> dict:
    """Re-scan after fixes to check for remaining issues."""
    # Re-run scan
    scan_result = scan_all(state)
    new_issues = scan_result.get("issues", [])

    # Classify again
    auto_fixable = [i for i in new_issues if i.get("auto_fixable", False)]
    manual_review = [i for i in new_issues if not i.get("auto_fixable", False)]

    return {
        "issues": new_issues,
        "auto_fixable": auto_fixable,
        "manual_review": manual_review,
        "remaining_issues": new_issues,
        "iteration": state.get("iteration", 0) + 1,
        # The "-1" accounts for iteration being incremented at the end of this function;
        # without it, the loop would exit one iteration earlier than expected.
        "status": "done" if (not auto_fixable or state.get("iteration", 0) >= state.get("max_iterations", 3) - 1) else "fixing",
    }


def route_after_recheck(state: LintState) -> str:
    """Decide whether to continue fixing or end."""
    has_auto = any(i.get("auto_fixable", False) for i in state.get("remaining_issues", []))
    max_iter = state.get("max_iterations", 3)
    current_iter = state.get("iteration", 0)

    if has_auto and current_iter < max_iter:
        return "auto_fix"
    return "review_queue"


def review_queue(state: LintState) -> dict:
    """Generate manual review queue for non-auto-fixable issues."""
    manual = state.get("manual_review", [])
    remaining = state.get("remaining_issues", [])
    fixes = state.get("fixes_applied", [])

    return {
        "status": "done",
        "summary": {
            "total_issues": len(state.get("issues", [])),
            "fixes_applied": len(fixes),
            "remaining_for_review": len(manual + remaining),
            "iterations": state.get("iteration", 0),
        },
    }


def build_lint_graph():
    """Build and compile the lint StateGraph."""
    workflow = StateGraph(LintState)

    workflow.add_node("scan_all", scan_all)
    workflow.add_node("classify_issues", classify_issues)
    workflow.add_node("auto_fix", auto_fix)
    workflow.add_node("recheck", recheck)
    workflow.add_node("review_queue", review_queue)

    workflow.set_entry_point("scan_all")
    workflow.add_edge("scan_all", "classify_issues")

    # Branch: if classify_issues found auto-fixable items, enter the fix loop; otherwise skip to review.
    workflow.add_conditional_edges("classify_issues",
        lambda s: "auto_fix" if s.get("auto_fixable") else "review_queue",
        {"auto_fix": "auto_fix", "review_queue": "review_queue"},
    )

    workflow.add_edge("auto_fix", "recheck")

    # Recheck loop: keep re-running auto_fix until no issues remain or max_iterations is hit.
    workflow.add_conditional_edges("recheck", route_after_recheck, {
        "auto_fix": "auto_fix",
        "review_queue": "review_queue",
    })

    workflow.add_edge("review_queue", END)

    return workflow.compile(checkpointer=get_checkpointer())


def run_lint(auto_fix: bool = True, max_iterations: int = 3):
    """Run the lint pipeline."""
    graph = build_lint_graph()

    initial: LintState = {
        "issues": [],
        "auto_fixable": [],
        "manual_review": [],
        "fixes_applied": [],
        "remaining_issues": [],
        "iteration": 0,
        # Setting max_iterations to 0 when auto_fix is False disables the fix loop entirely,
        # so the graph routes straight to review_queue after the first scan-classify pass.
        "max_iterations": max_iterations if auto_fix else 0,
        "status": "scanning",
    }

    result = graph.invoke(initial)
    return result

