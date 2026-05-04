"""Research LangGraph subgraph.

Adaptive research loop: Generate Queries -> Search -> Synthesize -> Propose Updates
Defined in MASTER_PLAN.md Section 4.5.

Usage:
    from cellwiki.research_graph import build_research_graph, run_research
    result = run_research({"type": "missing_page", "entity": "novel_macrophage_subtype"})
"""

import json
import logging
import sys
from pathlib import Path

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from graphs.checkpointer import get_checkpointer

_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from graphs.states import ResearchState

logger = logging.getLogger(__name__)


def generate_queries(state: ResearchState) -> dict:
    """Generate web search queries based on the knowledge gap."""
    gap = state.get("gap", {})
    entity = gap.get("entity", "unknown")
    gap_type = gap.get("type", "unknown")
    context = gap.get("context", "")

    # Generate queries based on gap type
    queries = []
    if gap_type == "missing_page":
        queries = [
            f"single-cell {entity} cell type marker genes",
            f"{entity} single cell RNA-seq characterization",
            f"{entity} cell ontology classification",
        ]
    elif gap_type == "unresolved_contradiction":
        queries = [
            f"{entity} single-cell contradiction marker",
            f"{entity} cell type different states scRNA-seq",
        ]
    elif gap_type == "insufficient_sources":
        queries = [
            f"single-cell {entity} recent research 2024 2025",
            f"{entity} cell type review paper",
        ]
    else:
        queries = [
            f"single-cell {entity} research",
            f"{entity} cell biology",
        ]

    if context:
        queries.append(f"{entity} {context} single-cell")

    return {
        "search_queries": queries[:5],
        "status": "searching",
    }


def web_search(state: ResearchState) -> dict:
    """Execute web search using available tools."""
    queries = state.get("search_queries", [])
    results = []

    # Try using web_search via hermes_tools if available
    try:
        from hermes_tools import web_search as hermes_web_search
        for query in queries[:3]:  # Limit to 3 queries
            try:
                search_result = hermes_web_search(query=query, limit=3)
                for item in search_result.get("data", {}).get("web", []):
                    results.append({
                        "url": item.get("url", ""),
                        "title": item.get("title", ""),
                        "description": item.get("description", ""),
                        "relevance": 0.5,  # Default relevance
                    })
            except Exception as e:
                logger.warning(f"Search failed for '{query}': {e}")
    except ImportError:
        # Fallback: try curl-based search
        import subprocess
        for query in queries[:2]:
            try:
                encoded = query.replace(" ", "+")
                result = subprocess.run(
                    ["curl", "-s", f"https://html.duckduckgo.com/html/?q={encoded}"],
                    capture_output=True, text=True, timeout=10
                )
                results.append({
                    "url": "duckduckgo",
                    "title": f"Search results for: {query}",
                    "description": result.stdout[:500],
                    "relevance": 0.3,
                })
            except Exception:
                pass

    return {
        "search_results": results,
        "status": "synthesizing",
    }


def synthesize(state: ResearchState) -> dict:
    """LLM synthesizes findings from search results."""
    gap = state.get("gap", {})
    results = state.get("search_results", [])

    if not results:
        return {
            "synthesized_findings": "No search results found. Consider manual research.",
            "confidence": "low",
            "iteration": state.get("iteration", 0) + 1,
            "status": "synthesizing",
        }

    # Build context from search results
    context = "\n".join([
        f"- [{r['title']}]({r['url']}): {r['description']}"
        for r in results[:10]
    ])

    # Try LLM synthesis
    try:
        from cellwiki.config import settings
        from openai import OpenAI
        import os

        client = OpenAI(
            api_key=settings.openai_api_key or os.environ.get("OPENAI_API_KEY", ""),
            base_url=settings.openai_base_url or os.environ.get("OPENAI_BASE_URL", None),
        )

        prompt = f"""Research gap: {gap}

Search results:
{context}

Synthesize the findings into a brief summary.
What do we know about this topic?
What are the key sources?
Is there enough evidence to create a wiki page?
"""

        response = client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": "You are a research assistant synthesizing web search results."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
        )

        findings = response.choices[0].message.content or ""
        confidence = "medium" if len(findings) > 100 else "low"

    except Exception as e:
        findings = f"Synthesis failed: {str(e)}\n\nRaw results:\n{context}"
        confidence = "low"

    return {
        "synthesized_findings": findings,
        "confidence": confidence,
        "iteration": state.get("iteration", 0) + 1,
        "status": "synthesizing",
    }


def route_after_synthesize(state: ResearchState) -> str:
    """Decide whether to re-search or propose updates."""
    confidence = state.get("confidence", "low")
    iteration = state.get("iteration", 0)
    max_iter = state.get("max_iterations", 3)

    if confidence == "low" and iteration < max_iter:
        return "generate_better_queries"
    return "propose_updates"


def generate_better_queries(state: ResearchState) -> dict:
    """Generate refined search queries based on previous results."""
    previous_queries = state.get("search_queries", [])
    findings = state.get("synthesized_findings", "")
    gap = state.get("gap", {})
    entity = gap.get("entity", "unknown")

    # Generate more specific queries
    new_queries = [
        f"{entity} single-cell multi-omics",
        f"{entity} spatial transcriptomics",
        f"{entity} proteomics CITE-seq",
    ]

    return {
        "search_queries": previous_queries + new_queries,
        "status": "searching",
    }


def propose_updates(state: ResearchState) -> dict:
    """Generate wiki update proposals based on research findings."""
    gap = state.get("gap", {})
    findings = state.get("synthesized_findings", "")
    results = state.get("search_results", [])

    proposed = [{
        "type": gap.get("type", "research_note"),
        "entity": gap.get("entity", ""),
        "findings_summary": findings[:500],
        "sources": [r.get("url", "") for r in results[:5] if r.get("url")],
        "action": "create_page" if gap.get("type") == "missing_page" else "update_page",
    }]

    return {
        "proposed_updates": proposed,
        "status": "done",
    }


def build_research_graph():
    """Build and compile the research StateGraph."""
    workflow = StateGraph(ResearchState)

    workflow.add_node("generate_queries", generate_queries)
    workflow.add_node("web_search", web_search)
    workflow.add_node("synthesize", synthesize)
    workflow.add_node("generate_better_queries", generate_better_queries)
    workflow.add_node("propose_updates", propose_updates)

    workflow.set_entry_point("generate_queries")
    workflow.add_edge("generate_queries", "web_search")
    workflow.add_edge("web_search", "synthesize")

    workflow.add_conditional_edges("synthesize", route_after_synthesize, {
        "generate_better_queries": "generate_better_queries",
        "propose_updates": "propose_updates",
    })

    workflow.add_edge("generate_better_queries", "web_search")
    workflow.add_edge("propose_updates", END)

    return workflow.compile(checkpointer=get_checkpointer())


def run_research(gap: dict, max_iterations: int = 3):
    """Run the research pipeline."""
    graph = build_research_graph()

    initial: ResearchState = {
        "gap": gap,
        "search_queries": [],
        "search_results": [],
        "synthesized_findings": "",
        "proposed_updates": [],
        "confidence": "low",
        "iteration": 0,
        "max_iterations": max_iterations,
        "status": "planning",
    }

    return graph.invoke(initial)

