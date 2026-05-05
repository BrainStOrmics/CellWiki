"""Audit: detect issues in the current wiki for human review."""

import json
from pathlib import Path
from cellwiki.config import settings
from cellwiki.knowledge import load_all_extractions, merge_to_wiki
from cellwiki.ontology import load_cell_ontology, load_cl_id_registry, load_manual_corrections, resolve_cell_type_to_cl
from cellwiki.wiki import _proper_title_case


SEVERITY_HIGH = "HIGH"
SEVERITY_MEDIUM = "MEDIUM"
SEVERITY_LOW = "LOW"

CATEGORY_LABELS = {
    "missing_cl_id": "Missing CL ID",
    "marker_conflicts": "Marker Conflicts",
    "orphan_subpopulations": "Orphan Subpopulations",
    "orphan_parent_type": "Orphan Parent Types",
    "empty_pages": "Empty Pages",
    "single_source": "Single-Source Pages",
    "unresolved_names": "Unresolved Names",
    "extraction_mismatch": "Extraction Mismatch",
    "no_extractions": "No Extractions",
}


def run_audit() -> dict[str, list[dict]]:
    """Run all audit checks and return a dict of issues grouped by category.

    Each issue is a dict with keys: cell_type, display_name, detail, severity.
    """
    extractions = load_all_extractions()
    if not extractions:
        return {"no_extractions": [{"detail": "No extractions found. Add papers first.", "severity": SEVERITY_HIGH}]}

    wiki = merge_to_wiki(extractions)
    valid_keys = set(wiki.keys())

    # Resolve CL IDs (same as rebuild_wiki does)
    ontology = load_cell_ontology()
    registry = load_cl_id_registry()
    corrections = load_manual_corrections()
    for key, wt in wiki.items():
        if not wt.cl_id:
            wt.cl_id = resolve_cell_type_to_cl(wt.display_name or key, ontology, registry, corrections)

    all_extractions = list(settings.extraction_dir.glob("*.json"))
    extraction_ids = {f.stem for f in all_extractions}

    issues: dict[str, list[dict]] = {}

    # 1. Missing CL ID
    missing_cl = []
    for key, wt in wiki.items():
        if not wt.cl_id or wt.cl_id == "CL:0000000":
            missing_cl.append({
                "cell_type": key,
                "display_name": wt.display_name or _proper_title_case(key),
                "detail": "No CL ID matched (try: cellwiki review)",
                "severity": SEVERITY_HIGH,
            })
    issues["missing_cl_id"] = missing_cl

    # 2. Marker conflicts
    marker_conflicts = []
    for key, wt in wiki.items():
        for gene, entries in wt.markers.items():
            conflict_entries = [e for e in entries if e.get("conflict")]
            if conflict_entries:
                types_found = {e["marker_type"] for e in entries}
                marker_conflicts.append({
                    "cell_type": key,
                    "display_name": wt.display_name or _proper_title_case(key),
                    "detail": f"{gene}: conflicting types {sorted(types_found)}",
                    "severity": SEVERITY_HIGH,
                })
    issues["marker_conflicts"] = marker_conflicts

    # 3. Orphan subpopulations
    orphan_subs = []
    for key, wt in wiki.items():
        for sub in wt.subpopulations:
            sub_key = sub.lower().replace(" ", "_")
            if sub_key not in valid_keys:
                orphan_subs.append({
                    "cell_type": key,
                    "display_name": wt.display_name or _proper_title_case(key),
                    "detail": f"References subpopulation '{sub}' (page not found)",
                    "severity": SEVERITY_MEDIUM,
                })
    issues["orphan_subpopulations"] = orphan_subs

    # 4. Orphan parent_type
    orphan_parents = []
    for key, wt in wiki.items():
        if wt.parent_type and wt.parent_type not in valid_keys:
            orphan_parents.append({
                "cell_type": key,
                "display_name": wt.display_name or _proper_title_case(key),
                "detail": f"Parent type '{wt.parent_type}' page not found",
                "severity": SEVERITY_MEDIUM,
            })
    issues["orphan_parent_type"] = orphan_parents

    # 5. Empty pages
    empty_pages = []
    for key, wt in wiki.items():
        has_content = bool(wt.description) or bool(wt.markers) or bool(wt.functions)
        if not has_content:
            empty_pages.append({
                "cell_type": key,
                "display_name": wt.display_name or _proper_title_case(key),
                "detail": "No description, markers, or functions",
                "severity": SEVERITY_LOW,
            })
    issues["empty_pages"] = empty_pages

    # 6. Single-source pages
    single_source = []
    for key, wt in wiki.items():
        if len(wt.sources) == 1:
            single_source.append({
                "cell_type": key,
                "display_name": wt.display_name or _proper_title_case(key),
                "detail": f"Only from: {wt.sources[0]}",
                "severity": SEVERITY_MEDIUM,
            })
    issues["single_source"] = single_source

    # 7. Unresolved names (no CL ID and can't be matched via ontology)
    # Re-check without auto-assignment to find truly unresolvable
    unresolved = []
    for key, wt in wiki.items():
        if not wt.cl_id or wt.cl_id == "CL:0000000":
            # Double-check: try resolving via ontology with registry
            cl = resolve_cell_type_to_cl(wt.display_name or key, ontology)
            if not cl:
                unresolved.append({
                    "cell_type": key,
                    "display_name": wt.display_name or _proper_title_case(key),
                    "detail": f"Name '{wt.display_name or key}' has no ontology match",
                    "severity": SEVERITY_HIGH,
                })
    issues["unresolved_names"] = unresolved

    # 8. Extraction-reference mismatch
    mismatch = []
    all_source_ids = set()
    for wt in wiki.values():
        all_source_ids.update(wt.sources)
    orphan_refs = all_source_ids - extraction_ids
    for ref_id in sorted(orphan_refs):
        mismatch.append({
            "cell_type": "(global)",
            "display_name": "Reference mismatch",
            "detail": f"Extraction '{ref_id}' referenced but file not found",
            "severity": SEVERITY_MEDIUM,
        })
    issues["extraction_mismatch"] = mismatch

    return issues


def display_audit_table(issues: dict[str, list[dict]]):
    """Display audit results as a Rich table in the terminal."""
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel

    console = Console()

    total_issues = sum(len(v) for v in issues.values())
    if total_issues == 0:
        console.print(Panel("No issues detected! Wiki looks clean.", border_style="green"))
        return

    high = sum(1 for v in issues.values() for i in v if i["severity"] == SEVERITY_HIGH)
    medium = sum(1 for v in issues.values() for i in v if i["severity"] == SEVERITY_MEDIUM)
    low = sum(1 for v in issues.values() for i in v if i["severity"] == SEVERITY_LOW)

    summary_lines = [
        f"Total issues: {total_issues}",
        f"[red]HIGH:[/red] {high}",
        f"[yellow]MEDIUM:[/yellow] {medium}",
        f"[green]LOW:[/green] {low}",
    ]
    console.print(Panel("\n".join(summary_lines), title="Audit Summary", border_style="yellow"))
    console.print()

    for category, label in CATEGORY_LABELS.items():
        items = issues.get(category, [])
        if not items:
            continue

        table = Table(title=f"{label} ({len(items)} issues)")
        table.add_column("Cell Type", style="cyan", width=35)
        table.add_column("Display Name", style="white", width=30)
        table.add_column("Detail", style="dim", width=55)
        table.add_column("Severity", width=8, justify="center")

        for item in items:
            sev = item["severity"]
            sev_style = {"HIGH": "red", "MEDIUM": "yellow", "LOW": "green"}[sev]
            table.add_row(
                item["cell_type"],
                item["display_name"][:30],
                item["detail"],
                f"[{sev_style}]{sev}[/{sev_style}]",
            )
        console.print(table)
        console.print()


def generate_audit_report(issues: dict[str, list[dict]]) -> Path:
    """Write a Markdown audit report to wiki/audit_report.md."""
    report_path = settings.wiki_dir / "audit_report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)

    severity_emoji = {
        SEVERITY_HIGH: "🔴",
        SEVERITY_MEDIUM: "🟡",
        SEVERITY_LOW: "🟢",
    }

    lines = [
        "# CellWiki Audit Report",
        "",
        f"**Total issues:** {sum(len(v) for v in issues.values())}",
        "",
    ]

    total = sum(len(v) for v in issues.values())
    high = sum(1 for v in issues.values() for i in v if i["severity"] == SEVERITY_HIGH)
    medium = sum(1 for v in issues.values() for i in v if i["severity"] == SEVERITY_MEDIUM)
    low = sum(1 for v in issues.values() for i in v if i["severity"] == SEVERITY_LOW)
    lines.append(f"- 🔴 HIGH: {high}")
    lines.append(f"- 🟡 MEDIUM: {medium}")
    lines.append(f"- 🟢 LOW: {low}")
    lines.append("")
    lines.append("---")
    lines.append("")

    for category, label in CATEGORY_LABELS.items():
        items = issues.get(category, [])
        if not items:
            continue

        lines.append(f"## {label}")
        lines.append("")
        lines.append("| Cell Type | Display Name | Detail | Severity |")
        lines.append("|-----------|-------------|--------|----------|")
        for item in items:
            sev = severity_emoji.get(item["severity"], "")
            lines.append(
                f"| `{item['cell_type']}` | {item['display_name']} | {item['detail']} | {sev} {item['severity']} |"
            )
        lines.append("")

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return report_path
