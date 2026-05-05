"""LangGraph State definitions for CellWiki.

This module defines all State models used across LangGraph subgraphs.
States are defined in MASTER_PLAN.md Section 4.
"""

from typing import Annotated, Literal
from typing_extensions import TypedDict
from langgraph.graph import add_messages


# === Reducer Functions ===

def merge_dict(a: dict, b: dict) -> dict:
    """Merge two dicts, b overwrites a."""
    return {**a, **b}


def append_list(a: list, b: list) -> list:
    """Append lists."""
    return a + b


# === WikiState (Shared across all subgraphs) ===

class WikiState(TypedDict):
    """Global CellWiki knowledge state. All subgraphs read/write this."""

    # Entity stores
    cell_types: dict
    marker_genes: dict
    tissues: dict
    diseases: dict
    methods: dict
    trajectories: dict

    # Index and log
    index: dict
    log_entries: list
    contradictions: list

    # Graph
    graph_nodes: list
    graph_edges: list

    # Metadata
    source_registry: dict
    statistics: dict


# === IngestState ===

class IngestState(TypedDict):
    """State for a single ingest operation."""

    # Input
    source_path: str
    source_type: str  # "paper", "dataset", "note"
    paper_text: str

    # Step 1: Analysis
    analysis: dict  # IngestAnalysis result

    # Context
    existing_pages: dict  # key: page_id, value: markdown content

    # Review
    review_items: list
    approved: bool
    review_notes: str

    # Step 2: Generation
    generation_plan: dict
    updated_pages: list
    new_pages: list

    # Status
    status: str  # initialized|analyzing|reviewing|generating|linting|done|aborted
    errors: list


# === QueryState ===

class QueryState(TypedDict):
    """State for a single query operation."""

    question: str
    max_context_tokens: int

    identified_entities: list
    initial_matches: list
    expanded_matches: list
    selected_pages: list
    used_tokens: int
    budget_exceeded: bool

    answer: str
    citations: list
    confidence: str

    status: str
    needs_research: bool


# === LintState ===

class LintState(TypedDict):
    """State for a lint operation."""

    issues: list
    auto_fixable: list
    manual_review: list
    fixes_applied: list
    remaining_issues: list
    iteration: int
    max_iterations: int
    status: str


# === ResearchState ===

class ResearchState(TypedDict):
    """State for a deep research operation."""

    gap: dict
    search_queries: list
    search_results: list
    synthesized_findings: str
    proposed_updates: list
    confidence: str
    iteration: int
    max_iterations: int
    status: str


# === OrchestratorState ===

class OrchestratorState(TypedDict):
    """State for the orchestrator."""

    command: str  # "ingest", "query", "lint", "research"
    command_args: dict
    result: dict

