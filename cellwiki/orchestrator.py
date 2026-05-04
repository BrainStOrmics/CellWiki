"""Orchestrator: composes all CellWiki LangGraph subgraphs.

Routes commands (ingest/query/lint/research) to the appropriate subgraph.
Defined in MASTER_PLAN.md Section 4.6.

Usage:
    from cellwiki.orchestrator import build_orchestrator, run_command
    result = run_command("ingest", {"source_path": "paper.pdf"})
    result = run_command("query", {"question": "What are Treg markers?"})
    result = run_command("lint", {"auto_fix": True})
"""

import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


def build_orchestrator():
    """Build and compile the orchestrator StateGraph."""
    from langgraph.graph import StateGraph, END
    from langgraph.checkpoint.memory import MemorySaver
    from graphs.checkpointer import get_checkpointer
    from graphs.states import OrchestratorState

    workflow = StateGraph(OrchestratorState)

    def route_command(state: OrchestratorState) -> str:
        return state.get("command", "unknown")

    def run_ingest_node(state: OrchestratorState) -> dict:
        from cellwiki.ingest_graph import run_ingest
        args = state.get("command_args", {})
        result = run_ingest(
            source_path=args.get("source_path", ""),
            source_type=args.get("source_type", "paper"),
            no_review=args.get("no_review", False),
        )
        return {"result": result}

    def run_query_node(state: OrchestratorState) -> dict:
        from cellwiki.query_graph import run_query
        args = state.get("command_args", {})
        result = run_query(
            question=args.get("question", ""),
            max_tokens=args.get("max_tokens", 8000),
        )
        return {"result": result}

    def run_lint_node(state: OrchestratorState) -> dict:
        from cellwiki.lint_graph import run_lint
        args = state.get("command_args", {})
        result = run_lint(
            auto_fix=args.get("auto_fix", True),
            max_iterations=args.get("max_iterations", 3),
        )
        return {"result": result}

    def run_research_node(state: OrchestratorState) -> dict:
        from cellwiki.research_graph import run_research
        args = state.get("command_args", {})
        result = run_research(
            gap=args.get("gap", {}),
            max_iterations=args.get("max_iterations", 3),
        )
        return {"result": result}

    # Add nodes (each node is a subgraph call)
    workflow.add_node("ingest", run_ingest_node)
    workflow.add_node("query", run_query_node)
    workflow.add_node("lint", run_lint_node)
    workflow.add_node("research", run_research_node)

    workflow.set_entry_point("route_command")
    workflow.add_conditional_edges("route_command", route_command, {
        "ingest": "ingest",
        "query": "query",
        "lint": "lint",
        "research": "research",
    })

    workflow.add_edge("ingest", END)
    workflow.add_edge("query", END)
    workflow.add_edge("lint", END)
    workflow.add_edge("research", END)

    return workflow.compile(checkpointer=get_checkpointer())


def run_command(command: str, args: dict = None):
    """Run a CellWiki command through the orchestrator."""
    graph = build_orchestrator()

    initial_state = {
        "command": command,
        "command_args": args or {},
        "result": {},
    }

    return graph.invoke(initial_state)

