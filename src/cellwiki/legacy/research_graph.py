# =============================================================================
# 研究 LangGraph 子图 —— 受控的外部研究发现的兼容性子图
# =============================================================================
# 旧版图谱直接抓取任意网页 HTML 并发出直接 Wiki 更新字典。
# 此适配器保留公共的 `run_research` 接口，同时将每个网络结果路由到
# `ResearchService`，使其成为注册的 SourceRecord 和 ResearchCandidate。
# 它没有写入或提交能力。
# =============================================================================

"""Compatibility LangGraph for governed external research discovery.

The legacy graph scraped arbitrary web HTML and emitted direct Wiki update dicts.
This adapter keeps the public ``run_research`` seam while routing every network
result through ``ResearchService`` so it becomes a registered SourceRecord and a
ResearchCandidate. It has no writer or commit capability.
"""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from cellwiki.config import settings
from cellwiki.services.research import ResearchService
from cellwiki.legacy.graphs.checkpointer import get_checkpointer
from cellwiki.legacy.graphs.states import ResearchState


def generate_queries(state: ResearchState) -> dict:
    """Create a small deterministic query set from the declared knowledge gap."""

    gap = state.get("gap", {})
    entity = " ".join(str(gap.get("entity", "")).split()) or "single-cell biology"
    gap_type = str(gap.get("type", "research_gap"))
    context = " ".join(str(gap.get("context", "")).split())
    queries = [
        f"{entity} single-cell characterization",
        f"{entity} marker genes transcriptomics",
    ]
    if gap_type == "unresolved_contradiction":
        queries.append(f"{entity} conflicting markers cell state")
    elif gap_type == "insufficient_sources":
        queries.append(f"{entity} review single-cell")
    else:
        queries.append(f"{entity} cell ontology")
    if context:
        queries.append(f"{entity} {context}")
    return {"search_queries": queries[:5], "status": "registering_candidates"}


def register_candidates(state: ResearchState) -> dict:
    """Register provider metadata as SourceRecords before exposing it downstream."""

    service = ResearchService(settings.project_root)
    candidates: list[dict] = []
    query_limit = max(1, min(state.get("max_iterations", 3), 5))
    for query in state.get("search_queries", [])[:query_limit]:
        registered = service.search_and_register(query, project_id="cellwiki", limit=3)
        candidates.extend(item.model_dump(mode="json") for item in registered)
    return {
        "search_results": candidates,
        "iteration": query_limit,
        "status": "candidate_review",
    }


def summarize_candidates(state: ResearchState) -> dict:
    """Emit only ingest-ready candidate instructions, never direct page mutations."""

    candidates = state.get("search_results", [])
    warnings = sorted({warning for item in candidates for warning in item.get("warnings", [])})
    if not candidates:
        summary = "No external metadata candidates were registered."
        confidence = "low"
    else:
        summary = (
            f"Registered {len(candidates)} external metadata candidates. "
            f"Warnings: {', '.join(warnings) if warnings else 'none'}. "
            "Each source must pass ingest, ChangeSet review, and explicit approval."
        )
        confidence = "medium"
    proposals = [
        {
            "type": "research_candidate",
            "candidate_id": item["candidate_id"],
            "source_id": item["source_id"],
            "action": "ingest_registered_source",
            "requires_changeset": True,
            "requires_human_approval": True,
        }
        for item in candidates
    ]
    return {
        "synthesized_findings": summary,
        "proposed_updates": proposals,
        "confidence": confidence,
        "status": "done",
    }


def build_research_graph():
    """Compile the compatibility graph with a candidate-only terminal state."""

    workflow = StateGraph(ResearchState)
    workflow.add_node("generate_queries", generate_queries)
    workflow.add_node("register_candidates", register_candidates)
    workflow.add_node("summarize_candidates", summarize_candidates)
    workflow.set_entry_point("generate_queries")
    workflow.add_edge("generate_queries", "register_candidates")
    workflow.add_edge("register_candidates", "summarize_candidates")
    workflow.add_edge("summarize_candidates", END)
    return workflow.compile(checkpointer=get_checkpointer())


def run_research(gap: dict, max_iterations: int = 3):
    """Run governed discovery; returned proposals can only enter the ingest workflow."""

    initial: ResearchState = {
        "gap": gap,
        "search_queries": [],
        "search_results": [],
        "synthesized_findings": "",
        "proposed_updates": [],
        "confidence": "low",
        "iteration": 0,
        "max_iterations": max(1, min(max_iterations, 5)),
        "status": "planning",
    }
    return build_research_graph().invoke(initial)
