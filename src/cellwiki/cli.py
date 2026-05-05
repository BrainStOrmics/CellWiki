#!/usr/bin/env python3
"""CellWiki CLI - Build and manage a single-cell biology knowledge base."""

import argparse
import json
import shutil
import sys
from pathlib import Path

from cellwiki.config import settings, ensure_dirs
from cellwiki.knowledge import load_all_extractions, save_extraction, rebuild_wiki
from cellwiki.extract import extract_pdf_to_text
from cellwiki.llm_extract import extract_cell_types_from_paper
from cellwiki.wiki import generate_cell_type_page, generate_index_page, _proper_title_case


# v2.0 LangGraph imports
try:
    from cellwiki.ingest_graph import run_ingest
    from cellwiki.query_graph import run_query
    from cellwiki.lint_graph import run_lint
    from cellwiki.graph_analysis import build_and_analyze, CellWikiGraph
    HAS_LANGGRAPH = True
except ImportError:
    HAS_LANGGRAPH = False


def _collect_pdfs(paths: list[Path]) -> list[Path]:
    """Collect all PDF files from a list of paths (files and directories)."""
    pdfs = []
    for p in paths:
        if p.is_dir():
            pdfs.extend(sorted(p.rglob("*.pdf")))
        elif p.is_file() and p.suffix.lower() == ".pdf":
            pdfs.append(p)
        else:
            print(f"Warning: skipping non-PDF path: {p}")
    return pdfs


def cmd_init(args):
    """Initialize a new CellWiki workspace."""
    from cellwiki.config import ensure_dirs
    ensure_dirs()
    print("CellWiki workspace initialized.")
    print(f"  Data directory:    {settings.data_dir.resolve()}")
    print(f"  Wiki directory:    {settings.wiki_dir.resolve()}")
    print(f"  References:        {settings.references_dir.resolve()}")

    from scripts.download_ontology import download_ontology
    download_ontology()
    print()

    generate_index_page()


def cmd_add(args):
    """Add reference papers and extract knowledge."""
    pdfs = _collect_pdfs(args.files)
    if not pdfs:
        print("No PDF files found in the specified paths.")
        sys.exit(1)

    print(f"Found {len(pdfs)} PDF file(s).")
    ensure_dirs()

    for pdf_path in pdfs:
        # Copy to references
        dest = settings.references_dir / pdf_path.name
        if not dest.exists():
            shutil.copy2(pdf_path, dest)
            print(f"\n{'=' * 60}")
            print(f"Copied {pdf_path.name}")
        else:
            print(f"\n{'=' * 60}")
            print(f"Already exists: {dest} (skipping copy)")

        # Extract text
        print(f"Extracting text...")
        text = extract_pdf_to_text(str(dest))

        # LLM extraction
        print(f"Extracting cell types via LLM...")
        result = extract_cell_types_from_paper(text, dest)
        print(f"  Extracted {len(result.cell_types)} cell types")

        # Save extraction
        paper_id = save_extraction(result)
        print(f"  Saved extraction: {paper_id}")

    # Rebuild wiki once after all papers
    print(f"\nBuilding wiki pages...")
    rebuild_wiki()


def cmd_build(args):
    """Rebuild the wiki from all extracted data."""
    ensure_dirs()
    rebuild_wiki()
    print("Wiki rebuilt.")


def cmd_query(args):
    """Query a cell type from the wiki with rich formatting."""
    from rich.console import Console
    from rich.markdown import Markdown

    name = args.name.lower().replace(" ", "_")
    page = settings.wiki_cell_types_dir / f"{name}.md"

    if not page.exists():
        # Try fuzzy match
        matches = [p.stem for p in settings.wiki_cell_types_dir.glob("*.md")
                   if name in p.stem.lower() or p.stem.lower().replace("_", " ") == name]
        if matches:
            print(f"Did you mean one of these?")
            for m in matches[:5]:
                print(f"  {m}")
        else:
            print(f"Cell type not found: {name}")
            print(f"Available types:")
            for p in sorted(settings.wiki_cell_types_dir.glob("*.md")):
                print(f"  {p.stem}")
        return

    console = Console(width=120)
    with open(page) as f:
        content = f.read()
    # Skip frontmatter for display
    if content.startswith("---"):
        _, _, content = content.split("---", 2)
    md = Markdown(content)
    console.print(md)


def cmd_list(args):
    """List all cell types in the wiki."""
    from rich.table import Table
    from rich.console import Console
    import yaml

    console = Console()
    table = Table(title="CellWiki Cell Types")
    table.add_column("Cell Type", style="cyan")
    table.add_column("Display Name", style="white")
    table.add_column("CL ID", style="dim")
    table.add_column("Refs", style="green", justify="right")
    table.add_column("Sources", style="yellow", justify="right")

    for page in sorted(settings.wiki_cell_types_dir.glob("*.md")):
        with open(page) as f:
            content = f.read()
            if content.startswith("---"):
                _, frontmatter, _ = content.split("---", 2)
                meta = yaml.safe_load(frontmatter) or {}
            else:
                meta = {}

        name = meta.get("standard_name", page.stem)
        display = meta.get("display_name", "")
        cl_id = meta.get("cl_id", "")
        refs = len(meta.get("references", []))

        # Count sources from content
        if "sources:" in content.lower():
            pass  # sources not in frontmatter, skip
        table.add_row(name, display[:40] or "", str(cl_id or ""), str(refs), "")

    console.print(table)


def cmd_remove(args):
    """Remove a paper's contribution from the wiki."""
    paper_id = args.paper_id
    extraction_file = settings.extraction_dir / f"{paper_id}.json"

    if not extraction_file.exists():
        print(f"No extraction found for: {paper_id}")
        print(f"Available extractions:")
        for f in sorted(settings.extraction_dir.glob("*.json")):
            print(f"  {f.stem}")
        return

    # Remove the extraction file
    extraction_file.unlink()
    print(f"Removed extraction: {paper_id}")

    # Rebuild wiki without it
    print("Rebuilding wiki...")
    rebuild_wiki()


def cmd_diff(args):
    """Show what changed in the wiki after the most recent addition."""
    import yaml

    extractions = load_all_extractions()
    if len(extractions) < 2:
        print("Need at least 2 extractions to show a diff.")
        return

    # Get the last added paper's cell types
    last_paper = extractions[-1].paper
    last_cell_types = {ct.standard_name for ct in extractions[-1].cell_types}

    # Get previous cell types
    prev_cell_types = set()
    for ext in extractions[:-1]:
        for ct in ext.cell_types:
            prev_cell_types.add(ct.standard_name)

    new_types = last_cell_types - prev_cell_types
    shared = last_cell_types & prev_cell_types

    print(f"\nPaper: {last_paper.title} ({last_paper.paper_id})")
    print(f"  New cell types: {len(new_types)}")
    print(f"  Updated cell types: {len(shared)}")
    print(f"  Total extracted: {len(last_cell_types)}")

    if new_types:
        print(f"\nNew cell types:")
        for t in sorted(new_types):
            print(f"  + {t}")

    if shared:
        print(f"\nUpdated cell types (now have more data from this paper):")
        for t in sorted(shared):
            print(f"  ~ {t}")


def cmd_graph(args):
    """Generate visualization of cell type relationships."""
    ensure_dirs()
    from cellwiki.visualization import generate_relationship_graph
    generate_relationship_graph()
    print("Graph generated:")
    print(f"  {(settings.wiki_dir / 'relationships.json').resolve()}")
    print(f"  {(settings.wiki_dir / 'graph.dot').resolve()}")
    print(f"  {(settings.wiki_dir / 'graph.mmd').resolve()}")


def cmd_status(args):
    """Show current wiki status."""
    from rich.console import Console
    from rich.panel import Panel
    import yaml

    console = Console()
    extractions = list(settings.extraction_dir.glob("*.json"))
    wiki_pages = list(settings.wiki_cell_types_dir.glob("*.md"))

    # Count total references
    total_refs = 0
    cl_matched = 0
    for p in wiki_pages:
        with open(p) as f:
            content = f.read()
            if content.startswith("---"):
                _, fm, _ = content.split("---", 2)
                meta = yaml.safe_load(fm) or {}
                total_refs += len(meta.get("references", []))
                if meta.get("cl_id") and meta["cl_id"] != "CL:0000000":
                    cl_matched += 1

    lines = [
        f"**Extractions:** {len(extractions)}",
        f"**Wiki pages:** {len(wiki_pages)}",
        f"**Total references:** {total_refs}",
        f"**CL IDs matched:** {cl_matched}/{len(wiki_pages)}",
    ]

    console.print(Panel("\n".join(lines), title="CellWiki Status", border_style="green"))


def cmd_audit(args):
    """Run audit checks and display results."""
    from cellwiki.audit import run_audit, display_audit_table, generate_audit_report

    ensure_dirs()
    issues = run_audit()
    display_audit_table(issues)
    report_path = generate_audit_report(issues)
    print(f"Audit report saved to: {report_path.resolve()}")


def cmd_review(args):
    """Interactive review of audit issues."""
    from rich.console import Console
    from rich.prompt import Prompt, Confirm
    from rich.panel import Panel
    from rich.table import Table
    from cellwiki.audit import run_audit, SEVERITY_HIGH, SEVERITY_MEDIUM, SEVERITY_LOW
    from cellwiki.ontology import load_cell_ontology, load_cl_id_registry, load_manual_corrections
    import json

    console = Console()
    ensure_dirs()
    issues = run_audit()
    total = sum(len(v) for v in issues.values())

    if total == 0:
        console.print(Panel("No issues to review!", border_style="green"))
        return

    ontology = load_cell_ontology()
    registry = load_cl_id_registry()
    corrections = load_manual_corrections()

    console.print(Panel(f"Found {total} issues to review", border_style="yellow"))
    console.print()

    # Review missing CL IDs
    missing_cl = issues.get("missing_cl_id", [])
    if missing_cl:
        console.print(Panel("Missing CL IDs — suggest ontology mappings", border_style="red"))
        for item in missing_cl:
            key = item["cell_type"]
            display = item["display_name"]
            console.print(f"\n  [cyan]{display}[/cyan] ({key})")

            # Try ontology search for candidates
            lookup = display.lower()
            candidates = []
            for term_name, cl_id in ontology.get("synonym_map", {}).items():
                if any(w in term_name for w in lookup.replace("+", "").replace("cell", "").split()):
                    candidates.append((cl_id, term_name))
                    if len(candidates) >= 5:
                        break

            if candidates:
                console.print("  Suggested CL IDs:")
                for i, (cl_id, name) in enumerate(candidates):
                    console.print(f"    {i + 1}. {cl_id} — {name}")
                choice = Prompt.ask("  Select CL ID (number or type manually, or skip)")
                if choice.isdigit() and 1 <= int(choice) <= len(candidates):
                    corrections.setdefault(key, {})["cl_id_override"] = candidates[int(choice) - 1][0]
                    console.print(f"  [green]Saved CL: {candidates[int(choice) - 1][0]}[/green]")
                elif choice.strip():
                    corrections.setdefault(key, {})["cl_id_override"] = choice.strip()
                    console.print(f"  [green]Saved CL: {choice.strip()}[/green]")
            else:
                cl_id = Prompt.ask("  No ontology match. Enter CL ID (or skip)")
                if cl_id.strip():
                    corrections.setdefault(key, {})["cl_id_override"] = cl_id.strip()
                    console.print(f"  [green]Saved CL: {cl_id.strip()}[/green]")

        console.print()

    # Review marker conflicts
    conflicts = issues.get("marker_conflicts", [])
    if conflicts:
        console.print(Panel("Marker Conflicts — choose resolution", border_style="red"))
        for item in conflicts:
            key = item["cell_type"]
            detail = item["detail"]
            console.print(f"\n  [cyan]{item['display_name']}[/cyan] — {detail}")

            table = Table(show_header=True)
            table.add_column("Gene")
            table.add_column("Type")
            table.add_column("Evidence")
            table.add_column("Source")
            table.add_column("Conflict")

            # Find the conflicting marker details
            exts = [e for e in issues.get("marker_conflicts", []) if e["cell_type"] == key]
            gene = detail.split(":")[0].strip()

            # Load from wiki data to show details
            from cellwiki.knowledge import merge_to_wiki, load_all_extractions
            wiki = merge_to_wiki(load_all_extractions())
            if key in wiki and gene in wiki[key].markers:
                for entry in wiki[key].markers[gene]:
                    conflict_str = "[red]CONFLICT[/red]" if entry.get("conflict") else ""
                    table.add_row(
                        gene,
                        entry["marker_type"],
                        entry.get("evidence", "")[:40],
                        entry.get("paper_id", ""),
                        conflict_str,
                    )
                console.print(table)

            if Confirm.ask("  Resolve this conflict (mark one as preferred)?", default=False):
                preferred = Prompt.ask("  Preferred marker type (positive/negative/transcript)")
                corrections.setdefault(key, {}).setdefault("marker_overrides", {})[gene] = preferred
                console.print(f"  [green]Saved override: {gene} = {preferred}[/green]")

        console.print()

    # Save corrections
    if corrections:
        data = {"description": "Manual corrections for CL IDs and markers.", "entries": {}}
        # Load existing
        if corrections_path.exists():
            with open(corrections_path) as f:
                existing = json.load(f)
            data["entries"] = existing.get("entries", {})
        data["entries"].update(corrections)
        with open(corrections_path, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        console.print(Panel(f"Saved {len(corrections)} correction(s) to {corrections_path.name}", border_style="green"))

        # Ask if user wants to rebuild
        if Confirm.ask("Rebuild wiki with corrections?", default=True):
            from cellwiki.knowledge import rebuild_wiki
            rebuild_wiki()
    else:
        console.print("No corrections made.")




def cmd_ingest(args):
    """Ingest a paper using the LangGraph two-step chain."""
    from cellwiki.ingest_graph import run_ingest
    pdfs = _collect_pdfs(args.files)
    if not pdfs:
        print("No PDF files found.")
        sys.exit(1)
    ensure_dirs()
    for pdf_path in pdfs:
        dest = settings.references_dir / pdf_path.name
        if not dest.exists():
            shutil.copy2(pdf_path, dest)
            print(f"Copied {pdf_path.name}")
        no_review = getattr(args, "no_review", False)
        result = run_ingest(source_path=str(dest), source_type="paper", no_review=no_review)
        print(f"Ingest complete: status={result.get('status', 'unknown')}")
        if result.get("errors"):
            print(f"  Errors: {result['errors']}")


def cmd_query_v2(args):
    """Query the wiki using the LangGraph retrieval pipeline."""
    from cellwiki.query_graph import run_query
    question = " ".join(args.question)
    result = run_query(question=question, max_tokens=getattr(args, "max_tokens", 8000))
    print(result.get("answer", "No answer found."))
    if result.get("citations"):
        print("\nSources:")
        for c in result["citations"]:
            print(f"  [{c['index']}] {c['page_id']}")


def cmd_lint_v2(args):
    """Run lint checks with auto-fix using LangGraph."""
    from cellwiki.lint_graph import run_lint
    result = run_lint(auto_fix=not getattr(args, "no_fix", False), max_iterations=getattr(args, "max_iterations", 3))
    summary = result.get("summary", {})
    print(f"  Total issues: {summary.get('total_issues', 0)}")
    print(f"  Fixes applied: {summary.get('fixes_applied', 0)}")
    print(f"  Remaining for review: {summary.get('remaining_for_review', 0)}")


def cmd_memory(args):
    """Manage LangGraph checkpoint memory."""
    from graphs.checkpointer import list_threads, get_thread_history, delete_thread, cleanup_old_threads, get_db_stats, get_db_path
    action = args.action
    if action == "list":
        threads = list_threads(limit=getattr(args, "limit", 50))
        if not threads:
            print("No checkpoint threads found.")
            return
        print(f"Checkpoint Threads (DB: {get_db_path()})")
        print(f"{'Thread ID':<40} {'Count':>8}")
        print("-" * 50)
        for t in threads:
            if "error" in t:
                print(f"  Error: {t['error']}")
                continue
            print(f"{str(t['thread_id'])[:38]:<40} {t['checkpoint_count']:>8}")
    elif action == "history":
        history = get_thread_history(args.thread_id)
        if not history:
            print(f"No history for thread: {args.thread_id}")
            return
        print(f"State History: {args.thread_id}")
        for i, e in enumerate(history):
            print(f"  [{i+1:3}] {str(e.get('created_at',''))[:19]} | {e.get('node','unknown')}")
    elif action == "delete":
        print("Deleted" if delete_thread(args.thread_id) else "Failed to delete", f"thread: {args.thread_id}")
    elif action == "cleanup":
        print(f"Cleaned up {cleanup_old_threads(getattr(args, 'days', 30))} old checkpoints")
    elif action == "stats":
        stats = get_db_stats()
        for k, v in stats.items():
            if isinstance(v, list):
                print(f"  {k}:")
                for item in v:
                    print(f"    {item}")
            else:
                print(f"  {k}: {v}")


def cmd_debug(args):
    """Debug CellWiki LangGraph execution."""
    action = args.action
    if action == "graph":
        from graphs.debug import visualize_graph
        cmd = args.command
        build_fns = {"ingest": "cellwiki.ingest_graph:build_ingest_graph", "query": "cellwiki.query_graph:build_query_graph",
                     "lint": "cellwiki.lint_graph:build_lint_graph", "research": "cellwiki.research_graph:build_research_graph",
                     "orchestrator": "cellwiki.orchestrator:build_orchestrator"}
        if cmd in build_fns:
            mod_name, func_name = build_fns[cmd].split(":")
            import importlib
            mod = importlib.import_module(mod_name)
            graph = getattr(mod, func_name)()
            print(visualize_graph(graph, output_format=getattr(args, "format", "text") or "text"))
        else:
            print(f"Unknown command: {cmd}")
    elif action == "trace":
        from graphs.debug import trace_execution
        cmd = args.command
        if cmd == "query":
            from cellwiki.query_graph import build_query_graph
            graph = build_query_graph()
            q = " ".join(getattr(args, "question", []) or ["What are Treg markers?"])
            initial = {"question": q, "max_context_tokens": 8000, "identified_entities": [], "initial_matches": [], "expanded_matches": [], "selected_pages": [], "used_tokens": 0, "budget_exceeded": False, "answer": "", "citations": [], "confidence": "medium", "status": "parsing", "needs_research": False}
        elif cmd == "lint":
            from cellwiki.lint_graph import build_lint_graph
            graph = build_lint_graph()
            initial = {"issues": [], "auto_fixable": [], "manual_review": [], "fixes_applied": [], "remaining_issues": [], "iteration": 0, "max_iterations": 3, "status": "scanning"}
        else:
            print(f"Trace not supported for: {cmd}"); return
        trace_execution(graph, initial, thread_id="debug_trace")
    elif action == "memory":
        from graphs.debug import get_memory_usage
        mem = get_memory_usage()
        print("Memory Usage")
        for k, v in mem.items():
            print(f"  {k}: {v}")
    elif action == "history":
        from graphs.debug import visualize_state_history
        print(visualize_state_history(args.thread_id))


def main():
    parser = argparse.ArgumentParser(
        prog="cellwiki",
        description="CellWiki - Single-cell biology knowledge base",
    )
    sub = parser.add_subparsers(dest="command")

    p_init = sub.add_parser("init", help="Initialize a new CellWiki workspace")
    p_init.set_defaults(func=cmd_init)

    p_add = sub.add_parser("add", help="Add reference PDFs or directories and extract knowledge")
    p_add.add_argument("files", nargs="+", type=Path, help="PDF files or directories containing PDFs")
    p_add.set_defaults(func=cmd_add)

    p_build = sub.add_parser("build", help="Rebuild the wiki from all extracted data")
    p_build.set_defaults(func=cmd_build)

    p_query = sub.add_parser("query", help="Query a cell type from the wiki")
    p_query.add_argument("name", help="Cell type name to look up")
    p_query.set_defaults(func=cmd_query)

    p_list = sub.add_parser("list", help="List all cell types in the wiki")
    p_list.set_defaults(func=cmd_list)

    p_remove = sub.add_parser("remove", help="Remove a paper's contribution from the wiki")
    p_remove.add_argument("paper_id", help="Paper ID (filename stem)")
    p_remove.set_defaults(func=cmd_remove)

    p_diff = sub.add_parser("diff", help="Show what the last added paper changed")
    p_diff.set_defaults(func=cmd_diff)

    p_graph = sub.add_parser("graph", help="Generate cell type relationship visualization")
    p_graph.set_defaults(func=cmd_graph)

    p_status = sub.add_parser("status", help="Show current wiki status")
    p_status.set_defaults(func=cmd_status)

    p_audit = sub.add_parser("audit", help="Run audit checks and generate report")
    p_audit.set_defaults(func=cmd_audit)

    p_review = sub.add_parser("review", help="Interactive review of audit issues")
    p_review.set_defaults(func=cmd_review)


    # v2.0 commands
    p_ingest = sub.add_parser("ingest", help="Ingest papers using LangGraph two-step chain")
    p_ingest.add_argument("files", nargs="+", type=Path, help="PDF files to ingest")
    p_ingest.add_argument("--no-review", action="store_true", help="Skip human review (batch mode)")
    p_ingest.set_defaults(func=cmd_ingest)

    p_query_v2 = sub.add_parser("query-v2", help="Query wiki using LangGraph pipeline")
    p_query_v2.add_argument("question", nargs="+", help="Question to ask")
    p_query_v2.add_argument("--max-tokens", type=int, default=8000, help="Max context tokens")
    p_query_v2.set_defaults(func=cmd_query_v2)

    p_lint_v2 = sub.add_parser("lint-v2", help="Run lint checks with auto-fix")
    p_lint_v2.add_argument("--no-fix", action="store_true", help="Don't auto-fix, just report")
    p_lint_v2.add_argument("--max-iterations", type=int, default=3, help="Max auto-fix iterations")
    p_lint_v2.set_defaults(func=cmd_lint_v2)

    p_memory = sub.add_parser("memory", help="Manage LangGraph checkpoint memory")
    p_memory.add_argument("action", choices=["list", "history", "delete", "cleanup", "stats"], help="Action")
    p_memory.add_argument("--thread-id", type=str, help="Thread ID for history/delete")
    p_memory.add_argument("--limit", type=int, default=50, help="Max threads to list")
    p_memory.add_argument("--days", type=int, default=30, help="Days for cleanup")
    p_memory.set_defaults(func=cmd_memory)

    p_debug = sub.add_parser("debug", help="Debug LangGraph execution")
    p_debug.add_argument("action", choices=["graph", "trace", "memory", "history"], help="Action")
    p_debug.add_argument("--command", type=str, choices=["ingest", "query", "lint", "research", "orchestrator"], help="Command to debug")
    p_debug.add_argument("--format", type=str, choices=["text", "mermaid"], help="Output format")
    p_debug.add_argument("--thread-id", type=str, help="Thread ID for history view")
    p_debug.add_argument("question", nargs="*", help="Query question for trace")
    p_debug.set_defaults(func=cmd_debug)

    args = parser.parse_args()
    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
