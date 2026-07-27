"""Compatibility Adapter for the original merge and Markdown renderer.

This is the only product-side Module allowed to call the legacy projection
implementation while it is replaced incrementally.
"""

from __future__ import annotations

from pathlib import Path

from cellwiki.adapters.markdown_renderer import (
    build_manifest,
    generate_cell_type_page,
    generate_conflict_pages,
    generate_disease_page,
    generate_index_page,
    generate_manifest_page,
    generate_marker_gene_page,
    generate_navigation_index_page,
    generate_overview_page,
    generate_tissue_page,
)
from cellwiki.adapters.wiki_knowledge import MultiOmicsMerger, merge_to_wiki
from cellwiki.domain.extraction import ExtractionResult


def _cleanup_pages(directory: Path, valid_keys: set[str]) -> None:
    """Remove stale generated Markdown pages from one projection layer."""
    directory.mkdir(parents=True, exist_ok=True)
    for existing in directory.glob("*.md"):
        if existing.stem not in valid_keys:
            existing.unlink()


def _assign_cell_type_evidence_tiers(wiki: dict) -> None:
    """Derive cell-type evidence tiers from distinct source papers."""
    for wiki_type in wiki.values():
        source_count = len(wiki_type.sources)
        if source_count >= 3:
            wiki_type.evidence_tier = 3
        elif source_count >= 1:
            wiki_type.evidence_tier = 4
        else:
            wiki_type.evidence_tier = 5


class CellWikiMarkdownRenderer:
    """Render the canonical CellWiki Markdown projection."""

    def render(
        self,
        extractions: list[ExtractionResult],
        *,
        wiki_dir: Path,
        curation_dir: Path,
    ) -> list[str]:
        wiki_dir.mkdir(parents=True, exist_ok=True)
        wiki = merge_to_wiki(extractions)
        _assign_cell_type_evidence_tiers(wiki)

        pages_dir = wiki_dir / "cell_types"
        valid_keys = set(wiki)
        _cleanup_pages(pages_dir, valid_keys)

        for key, wiki_type in sorted(wiki.items()):
            curation = curation_dir / f"{key}.md"
            curated_content = curation.read_text(encoding="utf-8") if curation.exists() else ""
            generate_cell_type_page(
                key,
                wiki_type,
                destination=pages_dir / f"{key}.md",
                curated_content=curated_content,
            )

        merger = MultiOmicsMerger()
        marker_genes = merger.merge_marker_genes(extractions)
        tissues = merger.merge_tissues(extractions)
        diseases = merger.merge_diseases(extractions)
        merger.assign_evidence_tiers()

        marker_dir = wiki_dir / "marker_genes"
        tissue_dir = wiki_dir / "tissues"
        disease_dir = wiki_dir / "diseases"
        conflict_dir = wiki_dir / "conflicts"
        _cleanup_pages(marker_dir, set(marker_genes))
        _cleanup_pages(tissue_dir, set(tissues))
        _cleanup_pages(disease_dir, set(diseases))

        for symbol, marker_gene in sorted(marker_genes.items()):
            generate_marker_gene_page(
                symbol,
                marker_gene,
                destination=marker_dir / f"{symbol}.md",
            )
        for key, tissue_data in sorted(tissues.items()):
            generate_tissue_page(key, tissue_data, destination=tissue_dir / f"{key}.md")
        for key, disease_data in sorted(diseases.items()):
            generate_disease_page(key, disease_data, destination=disease_dir / f"{key}.md")

        conflict_ids = generate_conflict_pages(wiki, conflict_dir)
        _cleanup_pages(conflict_dir, set(conflict_ids))

        manifest = build_manifest(wiki, marker_genes, tissues, diseases, conflict_ids)
        generate_manifest_page(manifest, destination=wiki_dir / "manifest.json")
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

        # README.md remains the compatibility index consumed by the existing
        # CentralWriter and legacy lint paths.
        generate_index_page(wiki, destination=wiki_dir / "README.md")
        return sorted(
            [*valid_keys]
            + [f"marker_gene:{key}" for key in marker_genes]
            + [f"tissue:{key}" for key in tissues]
            + [f"disease:{key}" for key in diseases]
            + [f"conflict:{key}" for key in conflict_ids]
        )
