# =============================================================================
# 审计模块 —— 检测编译后 Wiki 的质量问题、本体论缺口和结构不一致
# =============================================================================
# 对合并后的 Wiki 数据运行一系列检查，暴露出需要人工审查的问题。
# 每个检查针对特定的失败模式（缺失本体论 ID、矛盾标记物证据、# 断链交叉引用等）。结果可以渲染为 Rich 终端表格或写入 Markdown 报告。
# =============================================================================

"""Audit: detect quality issues, ontology gaps, and structural inconsistencies in the compiled wiki.

Runs a battery of checks against the merged wiki data to surface problems that need
human review before the wiki is considered publication-ready. Each check targets a
specific failure mode (missing ontology IDs, contradictory marker evidence, broken
cross-references, etc.). Results can be rendered as a Rich terminal table or written
to a Markdown report."""

from pathlib import Path
from cellwiki.config import settings
from cellwiki.knowledge import load_all_extractions, merge_to_wiki
from cellwiki.legacy.ontology import load_cell_ontology, load_cl_id_registry, load_manual_corrections, resolve_cell_type_to_cl
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
        return {"no_extractions": [{"cell_type": "(system)", "display_name": "No extractions", "detail": "No extractions found. Add papers first.", "severity": SEVERITY_HIGH}]}

    wiki = merge_to_wiki(extractions)
    # Cache valid keys for O(1) cross-reference lookups (orphan checks below)
    valid_keys = set(wiki.keys())

    # Re-resolve CL IDs during audit so checks reflect the latest ontology, not
    # whatever was cached at merge time. Mutates wiki entries in-place.
    ontology = load_cell_ontology()
    registry = load_cl_id_registry()
    corrections = load_manual_corrections()
    for key, wt in wiki.items():
        if not wt.cl_id:
            wt.cl_id = resolve_cell_type_to_cl(wt.display_name or key, ontology, registry, corrections)

    # Source-side reference set: filenames (without .json) of all extraction files on disk
    all_extractions = list(settings.extraction_dir.glob("*.json"))
    extraction_ids = {f.stem for f in all_extractions}

    issues: dict[str, list[dict]] = {}

    # 1. Missing CL ID
    missing_cl = []
    for key, wt in wiki.items():
        if not wt.cl_id or wt.cl_id == "CL:0000000":
            # CL:0000000 is the "unassigned" sentinel in the Cell Ontology; treat it as missing
            missing_cl.append({
                "cell_type": key,
                "display_name": wt.display_name or _proper_title_case(key),
                "detail": "No CL ID matched (try: cellwiki review)",
                "severity": SEVERITY_HIGH,
            })
    issues["missing_cl_id"] = missing_cl

    # 2. Marker conflicts — a marker is flagged when at least one extraction marks it
    # as "conflict", indicating contradictory evidence (e.g., positive in one paper, negative in another)
    marker_conflicts = []
    for key, wt in wiki.items():
        for gene, entries in wt.markers.items():
            conflict_entries = [e for e in entries if e.get("conflict")]
            if conflict_entries:
                # Collect all distinct marker types across all sources to show the full contradiction
                types_found = {e["marker_type"] for e in entries}
                marker_conflicts.append({
                    "cell_type": key,
                    "display_name": wt.display_name or _proper_title_case(key),
                    "detail": f"{gene}: conflicting types {sorted(types_found)}",
                    "severity": SEVERITY_HIGH,
                })
    issues["marker_conflicts"] = marker_conflicts

    # 3. Orphan subpopulations — subpopulation text references that don't match any wiki page key
    orphan_subs = []
    for key, wt in wiki.items():
        for sub in wt.subpopulations:
            # Normalize to match wiki page ID convention (lowercase, underscore-separated)
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

    # 5. Empty pages — pages with no substantive content beyond a title and a CL ID
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

    # 6. Single-source pages — flagged as medium severity because claims lack corroboration
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

    # 7. Unresolved names — re-run resolution *without* registry/corrections to
    # distinguish names that genuinely can't be mapped from those auto-assigned above
    unresolved = []
    for key, wt in wiki.items():
        if not wt.cl_id or wt.cl_id == "CL:0000000":
            # Omit registry/corrections here; only the base ontology should count as "resolved"
            cl = resolve_cell_type_to_cl(wt.display_name or key, ontology)
            if not cl:
                unresolved.append({
                    "cell_type": key,
                    "display_name": wt.display_name or _proper_title_case(key),
                    "detail": f"Name '{wt.display_name or key}' has no ontology match",
                    "severity": SEVERITY_HIGH,
                })
    issues["unresolved_names"] = unresolved

    # 8. Extraction-reference mismatch — sources cited in the wiki whose extraction files no longer exist on disk
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
            # Map severity to Rich-style color for terminal display
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
