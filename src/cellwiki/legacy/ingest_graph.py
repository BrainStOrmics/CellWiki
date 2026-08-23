# =============================================================================
# 导入 LangGraph 子图 —— PDF/Markdown → 实体提取 → Wiki 页面生成
# =============================================================================
# 两步链式流程，中间包含人工审查检查点：分析 →（审查）→ 生成。
# 审查节点使用 LangGraph 的 interrupt() 暂停执行，实现人在回路中的
# 工作流，用户可以在页面写入前批准、拒绝或添加注释。
# 定义于 MASTER_PLAN.md 第 4.2 节。
# =============================================================================

"""Ingest LangGraph subgraph: PDF/markdown -> entity extraction -> wiki page generation.

Two-step chain with a human review checkpoint: Analysis -> (Review) -> Generation.
The review node uses LangGraph's interrupt() to pause execution, enabling a human-in-the-loop
workflow where users can approve, reject, or annotate before pages are written.

Defined in MASTER_PLAN.md Section 4.2.

Usage:
    from cellwiki.ingest_graph import build_ingest_graph, run_ingest
    graph = build_ingest_graph()
    result = graph.invoke({"source_path": "path/to/paper.pdf", ...})
"""

import logging
from pathlib import Path

from langgraph.graph import StateGraph, END
from langgraph.types import interrupt

from cellwiki.legacy.graphs.checkpointer import get_checkpointer
from cellwiki.legacy.graphs.states import IngestState

logger = logging.getLogger(__name__)


# === Node Functions ===

def extract_text(state: IngestState) -> dict:
    """Extract text from PDF or read Markdown file. Returns the raw text for downstream LLM analysis."""
    source_path = state.get("source_path", "")
    source_type = state.get("source_type", "paper")
    paper_text = ""

    try:
        if source_path.endswith(".pdf"):
            from cellwiki.legacy.extract import extract_pdf_to_text
            paper_text = extract_pdf_to_text(source_path)
        elif source_path.endswith((".md", ".txt")):
            with open(source_path, encoding="utf-8") as f:
                paper_text = f.read()
        else:
            paper_text = f"Unsupported file format: {source_path}"
    except Exception as e:
        # Swallow errors here: the graph continues with an error message in paper_text,
        # and detect_entities will handle it gracefully via the early-exit checks below.
        paper_text = f"Error extracting text: {e}"

    return {"paper_text": paper_text, "status": "analyzing"}


def detect_entities(state: IngestState) -> dict:
    """LLM identifies entities in the paper text.

    Reuses existing llm_extract.py logic but returns structured analysis
    instead of directly creating wiki pages.
    """
    paper_text = state.get("paper_text", "")
    # Propagate extraction failures as structured low-confidence analysis so the
    # graph can still reach the review node with a clear error signal.
    if not paper_text or paper_text.startswith("Error") or paper_text.startswith("Unsupported"):
        return {
            "analysis": {
                "entities": [],
                "relationships": [],
                "contradictions": [],
                "existing_pages_touched": [],
                "new_pages_needed": [],
                "confidence": "low",
                "uncertainties": [f"Could not extract text: {paper_text[:100]}"],
            },
            "status": "reviewing",
        }

    try:
        from cellwiki.llm_extract import extract_cell_types_from_paper

        result = extract_cell_types_from_paper(paper_text, Path(state.get("source_path", "")))

        # Flatten the structured extraction result into a dict for graph state serialization
        entities = []
        for ct in result.cell_types:
            entities.append({
                "type": "cell_type",
                "name": ct.name,
                "standard_name": ct.standard_name,
                "cl_id": ct.cl_id,
                "markers": [
                    {"gene_symbol": m.gene_symbol, "marker_type": m.marker_type.value,
                     "evidence": m.evidence}
                    for m in ct.markers
                ],
                "tissues": ct.tissues,
                "diseases": ct.diseases,
                "species": ct.species,
                "description": ct.description,
            })

        analysis = {
            "entities": entities,
            "relationships": result.raw_relationships,
            "contradictions": [],
            "existing_pages_touched": [],
            "new_pages_needed": [],
            "confidence": "medium",
            "uncertainties": [],
            "paper_info": {
                "title": result.paper.title,
                "doi": result.paper.doi,
                "year": result.paper.year,
            } if result.paper else {},
        }

    except Exception as e:
        # Same pattern as extract_text: don't crash the graph, surface the error at review time
        analysis = {
            "entities": [],
            "relationships": [],
            "contradictions": [],
            "existing_pages_touched": [],
            "new_pages_needed": [],
            "confidence": "low",
            "uncertainties": [f"LLM extraction failed: {str(e)}"],
        }

    return {"analysis": analysis, "status": "analyzing"}


def fetch_existing_pages(state: IngestState) -> dict:
    """Read existing wiki pages that match extracted entities.

    This is intentionally scoped to cell_type pages only. Relationship pages, disease pages,
    etc. are not fetched here — they would follow the same pattern if needed.
    """
    from cellwiki.config import settings

    analysis = state.get("analysis", {})
    existing_pages = {}

    for entity in analysis.get("entities", []):
        name = entity.get("standard_name", "")
        if not name:
            continue

        # Only check cell_types directory; other entity types are not fetched
        page_path = settings.wiki_cell_types_dir / f"{name}.md"
        if page_path.exists():
            existing_pages[name] = page_path.read_text(encoding="utf-8")

    return {"existing_pages": existing_pages}


def build_analysis(state: IngestState) -> dict:
    """Compare analysis with existing pages to determine what needs updating."""
    analysis = state.get("analysis", {})
    existing_pages = state.get("existing_pages", {})

    touched = []
    new_needed = []

    for entity in analysis.get("entities", []):
        name = entity.get("standard_name", "")
        if name:
            if name in existing_pages:
                touched.append(name)
            else:
                new_needed.append(name)

    analysis["existing_pages_touched"] = touched
    analysis["new_pages_needed"] = new_needed

    # Detect potential contradictions with existing data
    contradictions = []
    for entity in analysis.get("entities", []):
        name = entity.get("standard_name", "")
        if name in existing_pages:
            # Simple heuristic: check if the existing page contains the literal string "CONFLICT".
            # This is intentionally naive — a real semantic diff would require LLM comparison,
            # which is too expensive to run on every ingest. The string match catches manually
            # flagged conflicts from previous review sessions.
            existing_content = existing_pages[name]
            for marker in entity.get("markers", []):
                gene = marker.get("gene_symbol", "")
                mtype = marker.get("marker_type", "")
                if gene and "CONFLICT" in existing_content:
                    contradictions.append({
                        "entity": name,
                        "description": f"Potential marker conflict for {gene} ({mtype})",
                    })

    analysis["contradictions"] = contradictions

    return {"analysis": analysis, "status": "reviewing"}


def review_node(state: IngestState) -> dict:
    """Human review point. Uses LangGraph interrupt() to pause execution.

    The interrupt() call suspends the graph and surfaces the review payload to the caller.
    The caller resumes with the user's decision (approved + optional notes). Until then,
    execution is paused — no polling, no busy-wait.
    """
    analysis = state.get("analysis", {})

    # Use interrupt to pause and wait for human input
    review_data = interrupt({
        "type": "ingest_review",
        "source": state.get("source_path", ""),
        "paper_info": analysis.get("paper_info", {}),
        "entities_found": len(analysis.get("entities", [])),
        "pages_to_update": analysis.get("existing_pages_touched", []),
        "new_pages_needed": analysis.get("new_pages_needed", []),
        "uncertainties": analysis.get("uncertainties", []),
        "contradictions": analysis.get("contradictions", []),
        "prompt": "Approve this ingest? (y/n) or provide notes:",
    })

    # Guard against non-dict resume values (e.g., a plain string answer)
    approved = review_data.get("approved", False) if isinstance(review_data, dict) else False
    notes = review_data.get("notes", "") if isinstance(review_data, dict) else ""

    return {
        "approved": approved,
        "review_notes": notes,
        "status": "generating" if approved else "aborted",
    }


def generate_pages(state: IngestState) -> dict:
    """Generate/update wiki pages based on analysis."""
    from cellwiki.knowledge import load_all_extractions, merge_to_wiki

    analysis = state.get("analysis", {})
    updated_pages = []
    new_pages = []

    try:
        # Load existing extractions and merge
        extractions = load_all_extractions()
        wiki = merge_to_wiki(extractions)

        # Generate cell type pages
        from cellwiki.wiki import generate_cell_type_page

        for key, wt in wiki.items():
            generate_cell_type_page(key, wt)
            if key in analysis.get("existing_pages_touched", []):
                updated_pages.append(key)
            if key in analysis.get("new_pages_needed", []):
                new_pages.append(key)

        # Generate index
        from cellwiki.wiki import generate_index_page
        generate_index_page(wiki)

    except Exception as e:
        # Note: on failure, we return errors but don't update status, so downstream
        # nodes (update_index_log, detect_conflicts) still run. This is intentional —
        # partial failures should still produce log entries and conflict records.
        return {
            "errors": state.get("errors", []) + [f"Page generation failed: {str(e)}"],
            "updated_pages": updated_pages,
            "new_pages": new_pages,
        }

    return {
        "updated_pages": updated_pages,
        "new_pages": new_pages,
        "status": "linting",
    }


def update_index_log(state: IngestState) -> dict:
    """Update index.md, log.md, and statistics.md."""
    from cellwiki.config import settings
    from cellwiki.knowledge import load_all_extractions, merge_to_wiki
    from cellwiki.wiki import generate_index_page
    import datetime

    try:
        wiki = merge_to_wiki(load_all_extractions())
        generate_index_page(wiki)

        # Append to log.md
        log_path = settings.wiki_dir / "log.md"
        if log_path.exists():
            content = log_path.read_text(encoding="utf-8")
        else:
            content = "# CellWiki Operation Log\n\n"

        log_entry = (
            f"## [{datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}] ingest | "
            f"{state.get('source_path', 'unknown')} | "
            f"updated: {state.get('updated_pages', [])}, new: {state.get('new_pages', [])}\n"
        )

        # Insert before the last section if it exists
        # String replacement on markdown is fragile but avoids a markdown parser dependency.
        if "## 日志条目" in content:
            content = content.replace("## 日志条目\n_(暂无记录)_", f"## 日志条目\n{log_entry}")
        elif "_(暂无记录)_" in content:
            content = content.replace("_(暂无记录)_", log_entry)
        else:
            content += log_entry

        log_path.write_text(content, encoding="utf-8")

        # Update statistics.md
        stats_path = settings.wiki_dir / "statistics.md"
        if stats_path.exists():
            stats_content = stats_path.read_text(encoding="utf-8")
            # Count cell type pages
            ct_dir = settings.wiki_cell_types_dir
            ct_count = len(list(ct_dir.glob("*.md"))) if ct_dir.exists() else 0
            stats_content = stats_content.replace("| cell_type | 0 |", f"| cell_type | {ct_count} |")
            stats_content = stats_content.replace("| **总计** | 0 |", f"| **总计** | {ct_count} |")
            stats_path.write_text(stats_content, encoding="utf-8")

    except Exception as e:
        return {"errors": state.get("errors", []) + [f"Index/log update failed: {str(e)}"]}

    return {"status": "detecting_conflicts"}


def detect_conflicts(state: IngestState) -> dict:
    """Detect and record contradictions."""
    from cellwiki.config import settings
    import datetime

    analysis = state.get("analysis", {})
    contradictions = state.get("contradictions", [])

    # Add any contradictions found during analysis
    for c in analysis.get("contradictions", []):
        contradictions.append({
            "id": f"contradiction_{len(contradictions) + 1}",
            "entity": c.get("entity", ""),
            "description": c.get("description", ""),
            "sources": [state.get("source_path", "")],
            "status": "unresolved",
            "detected_at": datetime.datetime.now().isoformat(),
        })

    # Write to contradictions.md
    try:
        contr_path = settings.wiki_dir / "contradictions.md"
        if contr_path.exists():
            content = contr_path.read_text(encoding="utf-8")
        else:
            content = "# CellWiki Contradictions Log\n\n## 活跃矛盾\n_(暂无活跃矛盾)_\n"

        if contradictions:
            # Add new contradictions before the existing section
            for c in contradictions:
                entry = (
                    f"\n### {c.get('id', 'unknown')}: {c.get('entity', '')}\n"
                    f"- **矛盾点**: {c.get('description', '')}\n"
                    f"- **涉及页面**: [[{c.get('entity', '')}]]\n"
                    f"- **来源**: [{c.get('sources', ['unknown'])[0]}]\n"
                    f"- **状态**: unresolved\n"
                    f"- **创建时间**: {c.get('detected_at', '')[:10]}\n"
                )
                if "_(暂无活跃矛盾)_" in content:
                    content = content.replace("_(暂无活跃矛盾)_", entry)
                else:
                    content += entry

            contr_path.write_text(content, encoding="utf-8")
    except Exception as e:
        return {"errors": state.get("errors", []) + [f"Conflict detection failed: {str(e)}"]}

    return {"contradictions": contradictions, "status": "done"}


# === Graph Builder ===

def build_ingest_graph():
    """Build and compile the ingest StateGraph.

    Flow: extract_text -> detect_entities -> fetch_existing_pages -> build_analysis ->
          review (interrupt) -> generate_pages -> update_index_log -> detect_conflicts -> END.

    The review node is configured as an interrupt point, so the graph pauses before it
    and resumes when the user provides input.
    """

    workflow = StateGraph(IngestState)

    # Add nodes
    workflow.add_node("extract_text", extract_text)
    workflow.add_node("detect_entities", detect_entities)
    workflow.add_node("fetch_existing_pages", fetch_existing_pages)
    workflow.add_node("build_analysis", build_analysis)
    workflow.add_node("review", review_node)
    workflow.add_node("generate_pages", generate_pages)
    workflow.add_node("update_index_log", update_index_log)
    workflow.add_node("detect_conflicts", detect_conflicts)

    # Add edges
    workflow.set_entry_point("extract_text")
    workflow.add_edge("extract_text", "detect_entities")
    workflow.add_edge("detect_entities", "fetch_existing_pages")
    workflow.add_edge("fetch_existing_pages", "build_analysis")
    workflow.add_edge("build_analysis", "review")

    # Conditional routing after review
    def route_after_review(state: IngestState) -> str:
        return "generate_pages" if state.get("approved", False) else END

    workflow.add_conditional_edges("review", route_after_review, {
        "generate_pages": "generate_pages",
        END: END,
    })

    workflow.add_edge("generate_pages", "update_index_log")
    workflow.add_edge("update_index_log", "detect_conflicts")
    workflow.add_edge("detect_conflicts", END)

    return workflow.compile(
        interrupt_before=["review"],
        checkpointer=get_checkpointer(),
    )


def run_ingest(source_path: str, source_type: str = "paper", no_review: bool = False):
    """Run the ingest pipeline for a single source.

    Args:
        source_path: Path to the PDF or Markdown file
        source_type: Type of source ("paper", "dataset", "note")
        no_review: If True, skip human review (batch mode)

    Returns:
        Final state dict
    """
    graph = build_ingest_graph()

    initial_state: IngestState = {
        "source_path": source_path,
        "source_type": source_type,
        "paper_text": "",
        "analysis": {},
        "existing_pages": {},
        "review_items": [],
        "approved": no_review,
        "review_notes": "",
        "generation_plan": {},
        "updated_pages": [],
        "new_pages": [],
        "status": "initialized",
        "errors": [],
    }

    if no_review:
        # Skip review entirely
        result = graph.invoke(initial_state)
        return result

    # Run to the interrupt point
    result = graph.invoke(initial_state)

    # Check if review was approved
    if result.get("status") == "aborted":
        print("\n⚠ Ingest aborted by user.")
        return result

    # Continue from checkpoint
    config = {"configurable": {"thread_id": "default"}}
    final_result = graph.invoke(None, config=config)

    return final_result
