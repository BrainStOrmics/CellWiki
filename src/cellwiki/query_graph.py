"""Query LangGraph subgraph.

Multi-phase retrieval: Entity Match -> Graph Expansion -> Context Assembly -> Synthesis
Defined in MASTER_PLAN.md Section 4.3.

Usage:
    from cellwiki.query_graph import build_query_graph, run_query
    result = run_query("What are Treg markers?")
"""

import json
import logging
import re
from pathlib import Path

from langgraph.graph import StateGraph, END

from graphs.checkpointer import get_checkpointer
from graphs.states import QueryState

logger = logging.getLogger(__name__)


def parse_question(state: QueryState) -> dict:
    """Identify entity types in the query (genes, cell types, tissues, etc.)."""
    question = state.get("question", "")
    identified_entities = []

    # Rule-based: UPPERCASE words might be gene symbols
    genes = re.findall(r'\b[A-Z]{2,}\b', question)
    for gene in genes:
        identified_entities.append({
            "type": "marker_gene",
            "id": gene,
            "confidence": 0.7,
            "source": "pattern_match",
        })

    # Rule-based: common cell type keywords
    cell_keywords = {
        "treg": "regulatory_t_cell",
        "t regulatory": "regulatory_t_cell",
        "regulatory t": "regulatory_t_cell",
        "cd4": "cd4_positive_t_cell",
        "cd8": "cd8_positive_t_cell",
        "t cell": "t_cell",
        "macrophage": "macrophage",
        "b cell": "b_cell",
        "nk cell": "natural_killer_cell",
        "dendritic": "dendritic_cell",
        "monocyte": "monocyte",
        "neutrophil": "neutrophil",
        "exhausted": "cd8_exhausted_t_cell",
        "tumor": "tumor_cell",
    }

    question_lower = question.lower()
    for keyword, ct_id in cell_keywords.items():
        if keyword in question_lower:
            identified_entities.append({
                "type": "cell_type",
                "id": ct_id,
                "confidence": 0.6,
                "source": "keyword_match",
            })

    # Deduplicate
    seen = set()
    unique_entities = []
    for e in identified_entities:
        key = (e["type"], e["id"])
        if key not in seen:
            seen.add(key)
            unique_entities.append(e)

    return {
        "identified_entities": unique_entities,
        "status": "searching",
    }


def entity_search(state: QueryState) -> dict:
    """Search wiki pages based on identified entities."""
    from cellwiki.config import settings

    entities = state.get("identified_entities", [])
    matches = []

    for entity in entities:
        if entity["type"] == "cell_type":
            # Exact match
            page = settings.wiki_cell_types_dir / f"{entity['id']}.md"
            if page.exists():
                matches.append({"type": "cell_type", "id": entity["id"], "score": 1.0})
            else:
                # Fuzzy match: search all cell type files
                if settings.wiki_cell_types_dir.exists():
                    for f in settings.wiki_cell_types_dir.glob("*.md"):
                        if entity["id"].replace("_", "") in f.stem.replace("_", "").lower():
                            matches.append({"type": "cell_type", "id": f.stem, "score": 0.7})

        elif entity["type"] == "marker_gene":
            # Check if marker_genes directory exists and has the gene
            mg_dir = settings.wiki_marker_genes_dir
            if mg_dir and mg_dir.exists():
                page = mg_dir / f"{entity['id']}.md"
                if page.exists():
                    matches.append({"type": "marker_gene", "id": entity["id"], "score": 1.0})

    # Deduplicate
    seen = set()
    unique_matches = []
    for m in matches:
        if m["id"] not in seen:
            seen.add(m["id"])
            unique_matches.append(m["id"])

    needs_research = len(unique_matches) == 0

    return {
        "initial_matches": unique_matches,
        "needs_research": needs_research,
        "status": "expanding" if unique_matches else "searching",
    }


def route_after_search(state: QueryState) -> str:
    if state.get("needs_research", False):
        return "research"
    return "graph_expansion"


def graph_expansion(state: QueryState) -> dict:
    """Expand from matched pages along relationships."""
    initial = state.get("initial_matches", [])
    expanded = list(initial)

    # Read relationships.json if available
    from cellwiki.config import settings
    rel_path = settings.wiki_dir / "relationships.json"
    if rel_path.exists():
        try:
            with open(rel_path) as f:
                rel_data = json.load(f)

            for page_id in initial:
                # Find edges connected to this page
                for edge in rel_data.get("edges", []):
                    if edge.get("source") == page_id:
                        target = edge.get("target", "")
                        if target and target not in expanded:
                            expanded.append(target)
                    if edge.get("target") == page_id:
                        source = edge.get("source", "")
                        if source and source not in expanded:
                            expanded.append(source)
        except Exception:
            pass

    # Also expand cell types to their parent/child types
    from cellwiki.config import settings
    if settings.wiki_cell_types_dir.exists():
        for page_id in initial:
            page = settings.wiki_cell_types_dir / f"{page_id}.md"
            if page.exists():
                content = page.read_text(encoding="utf-8")
                # Extract wikilinks
                links = re.findall(r'\[\[(.+?)\]\]', content)
                for link in links:
                    if link not in expanded:
                        expanded.append(link)

    # Limit expansion
    expanded = expanded[:20]

    return {
        "expanded_matches": expanded,
        "status": "assembling",
    }


def budget_select(state: QueryState) -> dict:
    """Select pages within token budget."""
    from cellwiki.config import settings

    expanded = state.get("expanded_matches", [])
    max_tokens = state.get("max_context_tokens", 8000)

    selected = []
    used = 0

    for page_id in expanded:
        # Try cell_types first, then other directories
        content = None
        for subdir in ["cell_types", "marker_genes", "tissues", "diseases", "methods", "trajectories"]:
            page = settings.wiki_dir / subdir / f"{page_id}.md"
            if page.exists():
                content = page.read_text(encoding="utf-8")
                break

        if content is None:
            continue

        # Rough token estimate: ~4 chars per token
        tokens = len(content) // 4

        if used + tokens > max_tokens and selected:
            return {
                "selected_pages": selected,
                "used_tokens": used,
                "budget_exceeded": True,
                "status": "synthesizing",
            }

        selected.append({"id": page_id, "content": content})
        used += tokens

    return {
        "selected_pages": selected,
        "used_tokens": used,
        "budget_exceeded": False,
        "status": "synthesizing",
    }


def llm_synthesize(state: QueryState) -> dict:
    """LLM synthesizes answer from selected pages."""
    question = state.get("question", "")
    selected = state.get("selected_pages", [])

    if not selected:
        return {
            "answer": f"No relevant wiki pages found for: {question}",
            "citations": [],
            "confidence": "low",
        }

    # Build context
    context_parts = []
    citations = []
    for i, page in enumerate(selected):
        page_id = page["id"]
        content = page["content"]
        # Truncate very long pages
        if len(content) > 3000:
            content = content[:3000] + "\n...[truncated]..."
        context_parts.append(f"[{i+1}] {page_id}:\n{content}")
        citations.append({"index": i+1, "page_id": page_id})

    full_context = "\n\n".join(context_parts)

    # Read purpose.md for context
    project_root = Path(__file__).parent.parent
    purpose_path = project_root / "purpose.md"
    purpose = ""
    if purpose_path.exists():
        purpose = purpose_path.read_text(encoding="utf-8")[:2000]

    prompt = f"""You are a single-cell biology expert answering questions based on the CellWiki knowledge base.

Question: {question}

Relevant wiki pages:
{full_context}

Answer the question comprehensively using ONLY the provided wiki pages. Cite sources using [1], [2], etc.
Do NOT use outside knowledge or make up facts not present in the wiki.
If the wiki pages don't contain enough information, state that explicitly rather than guessing.
If you need more data, suggest what research would help.
"""

    try:
        from cellwiki.config import settings
        from openai import OpenAI

        client = OpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url or None,
        )

        response = client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": "You are a CellWiki query assistant. Answer ONLY based on the provided wiki pages. If information is not in the pages, say so explicitly."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
        )

        answer = response.choices[0].message.content or ""

    except Exception as e:
        answer = f"LLM synthesis failed: {str(e)}\n\nAvailable pages: {', '.join(p['id'] for p in selected)}"

    return {
        "answer": answer,
        "citations": citations,
        "confidence": "medium" if answer else "low",
    }


def build_query_graph():
    """Build and compile the query StateGraph."""
    workflow = StateGraph(QueryState)

    workflow.add_node("parse_question", parse_question)
    workflow.add_node("entity_search", entity_search)
    workflow.add_node("graph_expansion", graph_expansion)
    workflow.add_node("budget_select", budget_select)
    workflow.add_node("llm_synthesize", llm_synthesize)

    workflow.set_entry_point("parse_question")
    workflow.add_edge("parse_question", "entity_search")

    workflow.add_conditional_edges("entity_search", route_after_search, {
        "research": "graph_expansion",  # Falls through to synthesis with no context; TODO: integrate research subgraph
        "graph_expansion": "graph_expansion",
    })

    workflow.add_edge("graph_expansion", "budget_select")
    workflow.add_edge("budget_select", "llm_synthesize")
    workflow.add_edge("llm_synthesize", END)

    return workflow.compile(checkpointer=get_checkpointer())


def run_query(question: str, max_tokens: int = 8000):
    """Run the query pipeline."""
    graph = build_query_graph()

    initial: QueryState = {
        "question": question,
        "max_context_tokens": max_tokens,
        "identified_entities": [],
        "initial_matches": [],
        "expanded_matches": [],
        "selected_pages": [],
        "used_tokens": 0,
        "budget_exceeded": False,
        "answer": "",
        "citations": [],
        "confidence": "medium",
        "status": "parsing",
        "needs_research": False,
    }

    result = graph.invoke(initial)
    return result

