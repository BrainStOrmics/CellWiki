"""Lint LangGraph subgraph.

Self-healing loop: Scan -> Classify -> Auto-Fix -> Recheck
Defined in MASTER_PLAN.md Section 4.4.

Usage:
    from cellwiki.lint_graph import build_lint_graph, run_lint
    result = run_lint(auto_fix=True)
"""

import json
import logging
import os
import re
import sys
from pathlib import Path

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from graphs.checkpointer import get_checkpointer

_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from graphs.states import LintState

logger = logging.getLogger(__name__)


def scan_all(state: LintState) -> dict:
    """Run all lint checks. Reuses existing audit.py logic."""
    issues = []

    try:
        # Use existing audit if available
        from cellwiki.audit import run_audit as audit_run
        audit_results = audit_run()

        for category, category_issues in audit_results.items():
            for issue in category_issues:
                severity = issue.get("severity", "LOW")
                issues.append({
                    "type": category,
                    "cell_type": issue.get("cell_type", ""),
                    "detail": issue.get("detail", ""),
                    "severity": severity,
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

    # Check index.md consistency
    from cellwiki.config import settings
    index_path = settings.wiki_dir / "index.md"
    if index_path.exists():
        index_content = index_path.read_text(encoding="utf-8")
        ct_dir = settings.wiki_cell_types_dir
        if ct_dir.exists():
            actual_files = {f.stem for f in ct_dir.glob("*.md")}
            # Check if all files are mentioned in index
            for f in actual_files:
                if f"[[{f}]]" not in index_content:
                    issues.append({
                        "type": "index_mismatch",
                        "detail": f"{f} exists but not in index.md",
                        "severity": "MEDIUM",
                        "auto_fixable": True,
                    })

    # Check for broken wikilinks
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
        "status": "fixing" if auto_fixable else "review_queue",
    }


def auto_fix(state: LintState) -> dict:
    """Apply auto-fixable repairs."""
    from cellwiki.config import settings

    fixes_applied = []
    remaining = []

    for issue in state.get("auto_fixable", []):
        fix_type = issue.get("type", "")

        try:
            if fix_type == "index_mismatch":
                # Rebuild index
                from cellwiki.wiki import generate_index_page
                generate_index_page()
                fixes_applied.append(f"Rebuilt index.md")

            elif fix_type == "broken_link":
                # Remove broken wikilink from page
                page = issue.get("page", "")
                link = issue.get("link", "")
                page_path = None
                for subdir in ["cell_types", "marker_genes", "tissues", "diseases", "methods", "trajectories"]:
                    p = settings.wiki_dir / subdir / f"{page}.md"
                    if p.exists():
                        page_path = p
                        break

                if page_path:
                    content = page_path.read_text(encoding="utf-8")
                    content = content.replace(f"[[{link}]]", f"~~[[{link}]]~~ _(page not found)_")
                    page_path.write_text(content, encoding="utf-8")
                    fixes_applied.append(f"Marked broken link [[{link}]] in {page}")

            elif fix_type in ("missing_cl_id", "orphan_subpopulations"):
                # These are informational, mark as reviewed
                fixes_applied.append(f"Reviewed: {issue.get('detail', '')[:80]}")

        except Exception as e:
            remaining.append({**issue, "fix_error": str(e)})

    if remaining:
        return {
            "fixes_applied": fixes_applied,
            "remaining_issues": remaining,
            "iteration": state.get("iteration", 0) + 1,
            "status": "rechecking",
        }

    return {
        "fixes_applied": fixes_applied,
        "remaining_issues": [],
        "iteration": state.get("iteration", 0) + 1,
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

    workflow.add_conditional_edges("classify_issues",
        lambda s: "auto_fix" if s.get("auto_fixable") else "review_queue",
        {"auto_fix": "auto_fix", "review_queue": "review_queue"},
    )

    workflow.add_edge("auto_fix", "recheck")

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
        "max_iterations": max_iterations if auto_fix else 0,
        "status": "scanning",
    }

    result = graph.invoke(initial)
    return result

