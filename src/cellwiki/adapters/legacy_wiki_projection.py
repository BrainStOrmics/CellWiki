"""Migrate the existing cell-type Markdown snapshot into projection layers.

The current checkout has 96 legacy cell-type pages but no canonical
``data/extraction/*.json`` records. This adapter treats those pages as a
one-time migration input, preserves their bodies, and writes the same modern
dimension pages used by the normal extraction-backed projection.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import yaml

from cellwiki.adapters.markdown_renderer import (
    _conflict_descriptions,
    _context_values,
    _negative_marker_details,
    _positive_marker_symbols,
    build_manifest,
    generate_conflict_pages,
    generate_disease_page,
    generate_manifest_page,
    generate_marker_gene_page,
    generate_navigation_index_page,
    generate_overview_page,
    generate_tissue_page,
)
from cellwiki.models import WikiCellType


_MARKER_TYPES = {"positive", "negative", "transcript"}


def _read_page(path: Path) -> tuple[dict, str]:
    """Read YAML frontmatter and body from one legacy page."""
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\r?\n(.*?)\r?\n---(?P<body>\r?\n.*)?$", text, re.DOTALL)
    if not match:
        raise ValueError(f"Missing YAML frontmatter: {path}")
    frontmatter = yaml.safe_load(match.group(1)) or {}
    if not isinstance(frontmatter, dict):
        raise ValueError(f"Frontmatter must be a mapping: {path}")
    return frontmatter, match.group("body") or "\n"


def _split_context_values(line: str) -> list[str]:
    """Parse a comma-separated legacy context line."""
    value = line.split(":", 1)[1].strip().strip("* ")
    return [item.strip() for item in value.split(",") if item.strip()]


def _parse_markers(body: str) -> dict[str, list[dict]]:
    """Parse marker rows while keeping source and conflict flags."""
    markers: dict[str, list[dict]] = {}
    in_markers = False
    for line in body.splitlines():
        stripped = line.strip()
        if stripped == "## Markers":
            in_markers = True
            continue
        if in_markers and stripped.startswith("## "):
            break
        if not in_markers or not stripped.startswith("|"):
            continue
        fields = [field.strip() for field in stripped.strip("|").split("|")]
        if len(fields) < 4 or fields[1].lower() not in _MARKER_TYPES:
            continue
        gene = re.sub(r"\s*(?:⚠️\s*)?CONFLICT\s*$", "", fields[0], flags=re.IGNORECASE).strip()
        if not gene:
            continue
        paper_match = re.search(r"\[([^\]]*)\]\(\)", fields[3])
        paper_id = paper_match.group(1).strip() if paper_match else ""
        entry = {
            "marker_type": fields[1].lower(),
            "evidence": fields[2],
            "paper_id": paper_id,
        }
        if "CONFLICT" in fields[0].upper():
            entry["conflict"] = True
        markers.setdefault(gene.upper(), []).append(entry)
    return markers


def _parse_contexts(body: str) -> dict[str, dict[str, list[str]]]:
    """Parse species, tissues, and diseases from the legacy Contexts section."""
    contexts: dict[str, dict[str, list[str]]] = {}
    in_contexts = False
    species = ""
    for line in body.splitlines():
        stripped = line.strip()
        if stripped == "## Contexts":
            in_contexts = True
            continue
        if in_contexts and stripped.startswith("## "):
            break
        if not in_contexts:
            continue
        if stripped.startswith("### "):
            species = stripped[4:].strip()
            contexts.setdefault(species, {"tissues": [], "diseases": []})
            continue
        if not species:
            continue
        if stripped.startswith("**Tissues:**"):
            contexts[species]["tissues"] = _split_context_values(stripped)
        elif stripped.startswith("**Diseases:**"):
            contexts[species]["diseases"] = _split_context_values(stripped)
    return contexts


def parse_legacy_cell_type_page(path: Path) -> WikiCellType:
    """Convert one existing cell-type page into the merged page model."""
    frontmatter, body = _read_page(path)
    markers = _parse_markers(body)
    contexts = _parse_contexts(body)
    references = [
        reference
        for reference in frontmatter.get("references", []) or []
        if isinstance(reference, dict) and reference.get("paper_id")
    ]
    sources = {
        str(reference["paper_id"])
        for reference in references
        if reference.get("paper_id")
    }
    for entries in markers.values():
        sources.update(entry["paper_id"] for entry in entries if entry.get("paper_id"))

    description = ""
    for line in body.splitlines():
        if line.startswith("> "):
            description = line[2:].strip()
            break

    standard_name = str(frontmatter.get("standard_name") or path.stem)
    return WikiCellType(
        standard_name=standard_name,
        display_name=str(frontmatter.get("display_name") or standard_name),
        cl_id=frontmatter.get("cl_id"),
        aliases=set(frontmatter.get("aliases", []) or []),
        parent_type=frontmatter.get("parent_type"),
        description=description,
        markers=markers,
        contexts=contexts,
        references=references,
        sources=sorted(sources),
        negative_markers=[
            entry
            for entries in markers.values()
            for entry in entries
            if entry["marker_type"] == "negative"
        ],
        evidence_tier=3 if len(sources) >= 3 else 4 if sources else 5,
    )


def _augment_cell_type_page(path: Path, wt: WikiCellType) -> None:
    """Append progressive-disclosure metadata without replacing legacy prose."""
    frontmatter, body = _read_page(path)
    tissues, species = _context_values(wt)
    negative_markers = sorted({detail["gene_symbol"] for detail in _negative_marker_details(wt)})
    frontmatter.update(
        {
            "evidence_tier": int(wt.evidence_tier),
            "source_count": len(wt.sources),
            "positive_markers": _positive_marker_symbols(wt),
            "negative_markers": negative_markers,
            "tissues": tissues,
            "species": species,
            "conflicts": _conflict_descriptions(wt),
        }
    )
    header = yaml.safe_dump(
        frontmatter,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    ).strip()
    path.write_text(f"---\n{header}\n---{body}", encoding="utf-8")


def _dimension_key(value: str) -> str:
    """Build a stable page key from a legacy context label."""
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_") or "unknown"


def _merge_dimensions(wiki: dict[str, WikiCellType]) -> tuple[dict, dict, dict]:
    """Aggregate marker, tissue, and disease data from parsed pages."""
    marker_genes: dict[str, dict] = {}
    tissues: dict[str, dict] = {}
    diseases: dict[str, dict] = {}

    for key, wt in sorted(wiki.items()):
        for gene, entries in sorted(wt.markers.items()):
            marker = marker_genes.setdefault(
                gene,
                {
                    "gene_symbol": gene,
                    "cell_types_expressed": [],
                    "source_count": 0,
                    "sources": [],
                    "evidence_tier": 5,
                },
            )
            if key not in marker["cell_types_expressed"]:
                marker["cell_types_expressed"].append(key)
            for entry in entries:
                source = entry.get("paper_id")
                if source and source not in marker["sources"]:
                    marker["sources"].append(source)

        for info in wt.contexts.values():
            for value in info.get("tissues", []):
                dimension_key = _dimension_key(value)
                tissue = tissues.setdefault(
                    dimension_key,
                    {
                        "name": dimension_key,
                        "display_name": value,
                        "cell_types_found": {},
                        "source_count": 0,
                        "sources": [],
                    },
                )
                tissue["cell_types_found"][key] = "present"
                for source in wt.sources:
                    if source not in tissue["sources"]:
                        tissue["sources"].append(source)

            for value in info.get("diseases", []):
                dimension_key = _dimension_key(value)
                disease = diseases.setdefault(
                    dimension_key,
                    {
                        "name": dimension_key,
                        "display_name": value,
                        "associated_cell_types": {},
                        "source_count": 0,
                        "sources": [],
                    },
                )
                disease["associated_cell_types"][key] = "associated"
                for source in wt.sources:
                    if source not in disease["sources"]:
                        disease["sources"].append(source)

    for marker in marker_genes.values():
        marker["cell_types_expressed"] = sorted(marker["cell_types_expressed"])
        marker["sources"] = sorted(marker["sources"])
        marker["source_count"] = len(marker["sources"])
        marker["evidence_tier"] = 3 if marker["source_count"] >= 3 else 4 if marker["source_count"] else 5
    for dimension in [*tissues.values(), *diseases.values()]:
        dimension["sources"] = sorted(dimension["sources"])
        dimension["source_count"] = len(dimension["sources"])
    return marker_genes, tissues, diseases


def _cleanup_pages(directory: Path, valid_keys: set[str]) -> None:
    """Remove stale Markdown pages from one generated layer."""
    directory.mkdir(parents=True, exist_ok=True)
    for path in directory.glob("*.md"):
        if path.stem not in valid_keys:
            path.unlink()


def rebuild_from_legacy_pages(wiki_dir: Path) -> dict[str, int]:
    """Build progressive-disclosure pages from the existing cell-type snapshot."""
    wiki_dir = Path(wiki_dir)
    pages_dir = wiki_dir / "cell_types"
    page_paths = sorted(pages_dir.glob("*.md"))
    if not page_paths:
        raise ValueError(f"No legacy cell-type pages found in {pages_dir}")

    wiki: dict[str, WikiCellType] = {}
    for path in page_paths:
        wt = parse_legacy_cell_type_page(path)
        wiki[wt.standard_name] = wt
        _augment_cell_type_page(path, wt)

    marker_genes, tissues, diseases = _merge_dimensions(wiki)
    marker_dir = wiki_dir / "marker_genes"
    tissue_dir = wiki_dir / "tissues"
    disease_dir = wiki_dir / "diseases"
    conflict_dir = wiki_dir / "conflicts"
    _cleanup_pages(marker_dir, set(marker_genes))
    _cleanup_pages(tissue_dir, set(tissues))
    _cleanup_pages(disease_dir, set(diseases))

    for symbol, data in sorted(marker_genes.items()):
        generate_marker_gene_page(symbol, data, destination=marker_dir / f"{symbol}.md")
    for key, data in sorted(tissues.items()):
        generate_tissue_page(key, data, destination=tissue_dir / f"{key}.md")
    for key, data in sorted(diseases.items()):
        generate_disease_page(key, data, destination=disease_dir / f"{key}.md")

    conflict_ids = generate_conflict_pages(wiki, conflict_dir)
    _cleanup_pages(conflict_dir, set(conflict_ids))

    manifest = build_manifest(wiki, marker_genes, tissues, diseases, conflict_ids)
    generate_manifest_page(manifest, wiki_dir / "manifest.json")
    generate_navigation_index_page(
        wiki,
        marker_genes,
        tissues,
        diseases,
        conflict_ids,
        destination=wiki_dir / "index.md",
        knowledge_version=manifest["version"],
    )
    generate_overview_page(
        wiki,
        marker_genes,
        tissues,
        diseases,
        conflict_ids,
        destination=wiki_dir / "overview.md",
        knowledge_version=manifest["version"],
    )
    return {
        "cell_types": len(wiki),
        "marker_genes": len(marker_genes),
        "tissues": len(tissues),
        "diseases": len(diseases),
        "conflicts": len(conflict_ids),
    }


def main() -> None:
    """Run the one-time legacy projection migration from the repository root."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wiki-dir", type=Path, default=Path("wiki"))
    args = parser.parse_args()
    print(json.dumps(rebuild_from_legacy_pages(args.wiki_dir), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
