"""Wiki page generation with YAML frontmatter and structured Markdown."""

import re
import yaml
from pathlib import Path
from cellwiki.config import settings
from cellwiki.models import WikiCellType


def _proper_title_case(s: str) -> str:
    """Convert a snake_case or poorly cased name to proper title case.

    Handles common biology terms: CD8+ -> CD8+, T cell -> T cell, etc.
    """
    # Replace underscores with spaces
    s = s.replace("_", " ")
    # Title case
    s = s.title()
    # Fix common biology terms
    fixes = {
        "Cd4": "CD4",
        "Cd8": "CD8",
        "T Cell": "T Cell",
        "T Cells": "T Cells",
        "B Cell": "B Cell",
        "B Cells": "B Cells",
        "Nk Cell": "NK Cell",
        "Nk Cells": "NK Cells",
        "T H": "Th",
        "T Reg": "T Reg",
        "Treg": "Treg",
        "T Em": "T EM",
        "T Cm": "T CM",
        "T Rm": "T RM",
        "T Emra": "T EMRA",
        "Mait": "MAIT",
        "Ifng": "IFNG",
        "Ifnγ": "IFN-γ",
        "Spp1": "SPP1",
        "Cxcl": "CXCL",
        "Ccr": "CCR",
        "Cd6": "CD6",
        "Cd160": "CD160",
        "Gzmk": "GZMK",
        "Gzmb": "GZMB",
        "Lef1": "LEF1",
        "Gpr183": "GPR183",
        "Cx3Cr1": "CX3CR1",
        "Layn": "LAYN",
        "Il": "IL",
        "Foxp3": "FOXP3",
        "Ctla4": "CTLA4",
        "Cxcr": "CXCR",
        "Slc4A10": "SLC4A10",
        "Anxa1": "ANXA1",
        "Gnly": "GNLY",
        "Tcf7": "TCF7",
        "Il23R": "IL23R",
        "Il10": "IL10",
        "Tmem": "Tmem",
        "Tex": "TEX",
    }
    for old, new in fixes.items():
        s = re.sub(rf"\b{re.escape(old)}\b", new, s)
    return s


def generate_cell_type_page(key: str, wt: WikiCellType):
    """Generate a single cell type wiki page."""
    dest = settings.wiki_cell_types_dir / f"{key}.md"

    # Build frontmatter
    frontmatter = {
        "standard_name": wt.standard_name,
        "display_name": wt.display_name,
        "cl_id": wt.cl_id,
        "parent_type": wt.parent_type,
        "aliases": sorted(wt.aliases),
        "references": [{"paper_id": r["paper_id"], "title": r["title"]} for r in wt.references],
    }

    # Build body
    lines = []

    display = wt.display_name or _proper_title_case(key)
    lines.append(f"# {display}")
    lines.append("")

    if wt.description:
        lines.append(f"> {wt.description}")
        lines.append("")

    # Markers table - grouped by species/context
    if wt.markers:
        lines.append("## Markers")
        lines.append("")
        lines.append("| Marker | Type | Evidence | Source |")
        lines.append("|--------|------|----------|--------|")
        for gene, entries in sorted(wt.markers.items()):
            for entry in entries:
                mtype = entry["marker_type"]
                evidence = entry.get("evidence", "")[:60]
                paper_id = entry.get("paper_id", "")
                conflict_marker = " ⚠️ CONFLICT" if entry.get("conflict") else ""
                lines.append(f"| {gene}{conflict_marker} | {mtype} | {evidence} | [{paper_id}]() |")
        lines.append("")

        # Conflicts section
        conflict_markers = [e for entries in wt.markers.values() for e in entries if e.get("conflict")]
        if conflict_markers:
            lines.append("### Marker Conflicts")
            lines.append("")
            lines.append("The following markers have conflicting reports across papers:")
            lines.append("")
            for entry in conflict_markers:
                gene = next(g for g, es in wt.markers.items() if entry in es)
                lines.append(f"- **{gene}**: conflicting marker types detected")
            lines.append("")

    # Functional characteristics
    if wt.functions:
        lines.append("## Functional Characteristics")
        lines.append("")
        for desc, entries in wt.functions.items():
            pathways = [e.get("pathway") for e in entries if e.get("pathway")]
            pathway_str = f" ({', '.join(pathways)})" if pathways else ""
            lines.append(f"- **{desc}**{pathway_str}")
            for entry in entries:
                paper_id = entry.get("paper_id", "")
                if paper_id:
                    lines.append(f"  - Source: [{paper_id}]()")
        lines.append("")

    # Contexts by species
    if wt.contexts:
        lines.append("## Contexts")
        lines.append("")
        for species, info in sorted(wt.contexts.items()):
            lines.append(f"### {species}")
            lines.append("")
            if info["tissues"]:
                lines.append("**Tissues:** " + ", ".join(info["tissues"]))
                lines.append("")
            if info["diseases"]:
                lines.append("**Diseases:** " + ", ".join(info["diseases"]))
                lines.append("")

    # Subpopulations
    if wt.subpopulations:
        lines.append("## Subpopulations")
        lines.append("")
        for sub in sorted(wt.subpopulations):
            sub_link = sub.lower().replace(" ", "_")
            lines.append(f"- [{sub}]({sub_link}.md)")
        lines.append("")

    # Related cell types
    related = _find_related(wt)
    if related:
        lines.append("## Related Cell Types")
        lines.append("")
        if wt.parent_type:
            lines.append(f"- Parent: [{wt.parent_type}]({wt.parent_type}.md)")
        for rel in sorted(related):
            if rel != wt.parent_type and rel != key:
                lines.append(f"- [{rel}]({rel}.md)")
        lines.append("")

    # References
    if wt.references:
        lines.append("## References")
        lines.append("")
        for ref in wt.references:
            doi_link = f" [{ref['doi']}](https://doi.org/{ref['doi']})" if ref.get("doi") else ""
            lines.append(f"- {ref.get('title', ref['paper_id'])} ({ref.get('year', 'n.d.')}){doi_link}")
        lines.append("")

    # Write file
    fm_str = yaml.dump(frontmatter, default_flow_style=False, allow_unicode=True).strip()
    content = f"---\n{fm_str}\n---\n\n" + "\n".join(lines)

    with open(dest, "w", encoding="utf-8") as f:
        f.write(content)


def _find_related(wt: WikiCellType) -> list[str]:
    """Find related cell types based on parent_type, subpopulations, and shared markers."""
    related = set()
    if wt.parent_type:
        related.add(wt.parent_type)
    for sub in wt.subpopulations:
        related.add(sub.lower().replace(" ", "_"))
    return list(related)


def generate_index_page(wiki: dict[str, WikiCellType] | None = None):
    """Generate the wiki README.md index page."""
    dest = settings.wiki_dir / "README.md"

    lines = [
        "# CellWiki - Single Cell Type Knowledge Base",
        "",
        "A knowledge base of cell types and subpopulations built from scientific literature.",
        "",
        "## Cell Types",
        "",
    ]

    if wiki:
        # Group by parent type for hierarchy
        roots = []
        children = {}
        for key, wt in sorted(wiki.items()):
            if wt.parent_type and wt.parent_type in wiki:
                children.setdefault(wt.parent_type, []).append((key, wt))
            else:
                roots.append((key, wt))

        for key, wt in roots:
            cl_tag = f" ({wt.cl_id})" if wt.cl_id else ""
            lines.append(f"- [{wt.display_name or _proper_title_case(key)}]({key}.md){cl_tag}")
            if key in children:
                for child_key, child_wt in children[key]:
                    cl_tag = f" ({child_wt.cl_id})" if child_wt.cl_id else ""
                    lines.append(f"  - [{child_wt.display_name or _proper_title_case(child_key)}]({child_key}.md){cl_tag}")

        # Remaining items
        remaining = [k for k in wiki if k not in roots and k not in children]
        for k in remaining:
            wt = wiki[k]
            cl_tag = f" ({wt.cl_id})" if wt.cl_id else ""
            lines.append(f"- [{wt.display_name or _proper_title_case(k)}]({k}.md){cl_tag}")
    else:
        lines.append("No cell types yet. Add reference papers with `cellwiki add <paper.pdf>`.")

    lines.append("")
    lines.append("## Relationship Graph")
    lines.append("")
    lines.append("- [relationships.json](relationships.json) - Machine-readable relationship data")
    lines.append("- [graph.dot](graph.dot) - Graphviz DOT format")
    lines.append("- [graph.mmd](graph.mmd) - Mermaid diagram format")
    lines.append("")

    with open(dest, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def generate_marker_gene_page(symbol: str, mg: dict):
    """Generate a marker gene wiki page."""
    import json
    from cellwiki.config import settings

    dest = settings.wiki_marker_genes_dir / f"{symbol}.md"

    frontmatter = {
        "entity_type": "marker_gene",
        "gene_symbol": mg.get("gene_symbol", symbol),
        "gene_name": mg.get("gene_name", ""),
        "specificity": mg.get("specificity", ""),
        "evidence_tier": mg.get("evidence_tier", 5),
        "source_count": mg.get("source_count", 0),
        "last_updated": mg.get("last_updated", ""),
    }

    lines = []
    lines.append(f"# {symbol}")
    lines.append("")

    if mg.get("description"):
        lines.append(f"> {mg['description']}")
        lines.append("")

    if mg.get("cell_types_expressed"):
        lines.append("## Expression")
        lines.append("")
        lines.append("| Cell Type | Level | Evidence |")
        lines.append("|-----------|-------|----------|")
        for ct in mg["cell_types_expressed"]:
            lines.append(f"| [[{ct}]] | | |")
        lines.append("")

    if mg.get("negative_evidence"):
        lines.append("## Negative Evidence")
        lines.append("")
        lines.append("| Cell Type | Evidence | Sources |")
        lines.append("|-----------|----------|---------|")
        for ne in mg["negative_evidence"]:
            lines.append(f"| {ne.get('cell_type', '')} | {ne.get('evidence', '')} | {', '.join(ne.get('sources', []))} |")
        lines.append("")

    if mg.get("co_expression"):
        lines.append("## Co-expression")
        lines.append("")
        lines.append("| Gene | Cell Type | Correlation |")
        lines.append("|------|-----------|-------------|")
        for ce in mg["co_expression"]:
            lines.append(f"| {ce.get('gene', '')} | {ce.get('cell_type', '')} | {ce.get('correlation', '')} |")
        lines.append("")

    lines.append("## Related Pages")
    lines.append("")
    for ct in mg.get("cell_types_expressed", [])[:5]:
        lines.append(f"- [[{ct}]]")
    lines.append("")

    if mg.get("sources"):
        lines.append("## Sources")
        lines.append("")
        for s in mg["sources"]:
            lines.append(f"- {s}")
        lines.append("")

    header = "---\n"
    for k, v in frontmatter.items():
        header += f"{k}: {json.dumps(v) if isinstance(v, (list, dict)) else v}\n"
    header += "---\n\n"

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(header + "\n".join(lines), encoding="utf-8")

