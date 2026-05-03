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
    print(f"  {Path('wiki/relationships.json').resolve()}")
    print(f"  {Path('wiki/graph.dot').resolve()}")
    print(f"  {Path('wiki/graph.mmd').resolve()}")


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
    corrections_path = settings.cell_ontology_dir / "manual_corrections.json"
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

    args = parser.parse_args()
    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
