"""Tests for the multi-layer disposable Wiki projection."""

from __future__ import annotations

from pathlib import Path

import yaml

from cellwiki.adapters.markdown_renderer import (
    generate_cell_type_page,
    generate_disease_page,
    generate_marker_gene_page,
    generate_tissue_page,
)
from cellwiki.adapters.wiki_knowledge import MultiOmicsMerger
from cellwiki.adapters.wiki_renderer import CellWikiMarkdownRenderer
from cellwiki.domain.extraction import (
    CellTypeExtract,
    ExtractionResult,
    Marker,
    MarkerType,
    PaperReference,
)
from cellwiki.models import WikiCellType


def _paper(paper_id: str) -> PaperReference:
    return PaperReference(paper_id=paper_id, title=f"Paper {paper_id}", year=2025)


def _extraction(
    paper_id: str,
    *,
    standard_name: str = "t_cell",
    markers: list[Marker] | None = None,
    tissues: list[str] | None = None,
    diseases: list[str] | None = None,
    species: list[str] | None = None,
    parent_type: str | None = None,
) -> ExtractionResult:
    paper = _paper(paper_id)
    cell_type = CellTypeExtract(
        name=standard_name.replace("_", " "),
        standard_name=standard_name,
        parent_type=parent_type,
        markers=markers or [],
        tissues=tissues or [],
        diseases=diseases or [],
        species=species or [],
        paper_ref=paper,
    )
    return ExtractionResult(paper=paper, cell_types=[cell_type])


def _frontmatter(path: Path) -> dict:
    sections = path.read_text(encoding="utf-8").split("---", 2)
    return yaml.safe_load(sections[1])


def test_multiomics_merger_aggregates_dimensions_and_assigns_gene_tiers():
    extractions = [
        _extraction(
            "p1",
            markers=[Marker(gene_symbol="CD8A", marker_type=MarkerType.POSITIVE)],
            tissues=["Lung"],
            diseases=["NSCLC"],
        ),
        _extraction(
            "p2",
            markers=[Marker(gene_symbol="CD8A", marker_type=MarkerType.POSITIVE)],
            tissues=["Lung"],
            diseases=["NSCLC"],
        ),
        _extraction(
            "p3",
            markers=[Marker(gene_symbol="CD8A", marker_type=MarkerType.POSITIVE)],
            tissues=["Blood"],
        ),
    ]

    merger = MultiOmicsMerger()
    marker_genes = merger.merge_marker_genes(extractions)
    tissues = merger.merge_tissues(extractions)
    diseases = merger.merge_diseases(extractions)
    merger.assign_evidence_tiers()

    assert marker_genes["CD8A"]["cell_types_expressed"] == ["t_cell"]
    assert marker_genes["CD8A"]["source_count"] == 3
    assert marker_genes["CD8A"]["evidence_tier"] == 3
    assert tissues["lung"]["cell_types_found"] == {"t_cell": "present"}
    assert tissues["blood"]["source_count"] == 1
    assert diseases["nsclc"]["associated_cell_types"] == {"t_cell": "associated"}


def test_page_generators_honor_explicit_destinations(tmp_path: Path):
    marker_path = tmp_path / "marker-pages" / "CD8A.md"
    tissue_path = tmp_path / "tissue-pages" / "lung.md"
    disease_path = tmp_path / "disease-pages" / "nsclc.md"

    generate_marker_gene_page(
        "CD8A",
        {
            "gene_symbol": "CD8A",
            "cell_types_expressed": ["t_cell"],
            "source_count": 2,
            "evidence_tier": 4,
        },
        destination=marker_path,
    )
    generate_tissue_page(
        "lung",
        {
            "name": "lung",
            "display_name": "Lung",
            "cell_types_found": {"t_cell": "present"},
            "source_count": 1,
            "sources": ["p1"],
        },
        destination=tissue_path,
    )
    generate_disease_page(
        "nsclc",
        {
            "name": "nsclc",
            "display_name": "NSCLC",
            "associated_cell_types": {"t_cell": "associated"},
            "source_count": 1,
            "sources": ["p1"],
        },
        destination=disease_path,
    )

    assert marker_path.exists()
    assert tissue_path.exists()
    assert disease_path.exists()
    assert "[[t_cell]]" in marker_path.read_text(encoding="utf-8")
    assert "t_cell" in tissue_path.read_text(encoding="utf-8")
    assert "t_cell" in disease_path.read_text(encoding="utf-8")


def test_cell_type_frontmatter_contains_progressive_disclosure_metadata(tmp_path: Path):
    page_path = tmp_path / "cell_types" / "t_cell.md"
    cell_type = WikiCellType(
        standard_name="t_cell",
        display_name="T Cell",
        sources=["p1", "p2", "p3"],
        evidence_tier=3,
        markers={
            "CD8A": [{"marker_type": "positive", "paper_id": "p1"}],
            "TCF7": [{"marker_type": "negative", "paper_id": "p1"}],
        },
        negative_markers=[{"gene_symbol": "TCF7", "evidence": "not detected"}],
        contexts={"human": {"tissues": ["Lung"], "diseases": ["NSCLC"]}},
        conflicts=["TCF7: positive vs negative"],
    )

    generate_cell_type_page("t_cell", cell_type, destination=page_path)

    frontmatter = _frontmatter(page_path)
    body = page_path.read_text(encoding="utf-8")
    assert frontmatter["evidence_tier"] == 3
    assert frontmatter["source_count"] == 3
    assert frontmatter["positive_markers"] == ["CD8A"]
    assert frontmatter["negative_markers"] == ["TCF7"]
    assert frontmatter["tissues"] == ["Lung"]
    assert frontmatter["species"] == ["human"]
    assert frontmatter["conflicts"] == ["TCF7: positive vs negative"]
    assert "## Negative Markers" in body
    assert "## Conflicts" in body


def test_projection_generates_layers_index_and_overview_without_manifest(tmp_path: Path):
    wiki_dir = tmp_path / "wiki"
    curation_dir = wiki_dir / "curation" / "cell_types"
    wiki_dir.mkdir(parents=True)
    (wiki_dir / "manifest.json").write_text("obsolete", encoding="utf-8")
    extractions = [
        _extraction(
            "p1",
            markers=[
                Marker(gene_symbol="CD8A", marker_type=MarkerType.POSITIVE),
                Marker(gene_symbol="TCF7", marker_type=MarkerType.POSITIVE),
            ],
            tissues=["Lung"],
            diseases=["NSCLC"],
            species=["human"],
            parent_type="lymphocyte",
        ),
        _extraction(
            "p2",
            markers=[
                Marker(gene_symbol="CD8A", marker_type=MarkerType.POSITIVE),
                Marker(gene_symbol="TCF7", marker_type=MarkerType.NEGATIVE),
            ],
            tissues=["Lung"],
            diseases=["NSCLC"],
            species=["human"],
            parent_type="lymphocyte",
        ),
        _extraction(
            "p3",
            markers=[Marker(gene_symbol="CD8A", marker_type=MarkerType.POSITIVE)],
            tissues=["Blood"],
            species=["mouse"],
            parent_type="lymphocyte",
        ),
    ]

    result = CellWikiMarkdownRenderer().render(
        extractions,
        wiki_dir=wiki_dir,
        curation_dir=curation_dir,
    )

    assert "t_cell" in result
    assert "marker_gene:CD8A" in result
    assert "tissue:lung" in result
    assert "disease:nsclc" in result
    assert (wiki_dir / "marker_genes" / "CD8A.md").exists()
    assert (wiki_dir / "tissues" / "lung.md").exists()
    assert (wiki_dir / "diseases" / "nsclc.md").exists()
    assert "[按组织](tissues/)" in (wiki_dir / "index.md").read_text(encoding="utf-8")
    assert "[按疾病](diseases/)" in (wiki_dir / "index.md").read_text(encoding="utf-8")
    assert "Evidence Tier" in (wiki_dir / "overview.md").read_text(encoding="utf-8")
    assert (wiki_dir / "README.md").exists()
    assert not (wiki_dir / "manifest.json").exists()

    conflict_pages = list((wiki_dir / "conflicts").glob("*.md"))
    assert len(conflict_pages) == 1
    assert "TCF7: positive vs negative" in conflict_pages[0].read_text(encoding="utf-8")


def test_projection_removes_stale_layer_pages_and_is_idempotent(tmp_path: Path):
    wiki_dir = tmp_path / "wiki"
    curation_dir = wiki_dir / "curation" / "cell_types"
    stale_dirs = ["cell_types", "marker_genes", "tissues", "diseases", "conflicts"]
    for directory in stale_dirs:
        target = wiki_dir / directory
        target.mkdir(parents=True, exist_ok=True)
        (target / "stale.md").write_text("stale", encoding="utf-8")

    renderer = CellWikiMarkdownRenderer()
    renderer.render(
        [
            _extraction(
                "p1",
                markers=[Marker(gene_symbol="CD8A", marker_type=MarkerType.POSITIVE)],
                tissues=["Lung"],
                diseases=["NSCLC"],
            )
        ],
        wiki_dir=wiki_dir,
        curation_dir=curation_dir,
    )
    first_snapshot = {
        path.relative_to(wiki_dir).as_posix(): path.read_bytes()
        for path in wiki_dir.rglob("*")
        if path.is_file()
    }

    renderer.render(
        [_extraction("p2", standard_name="b_cell")],
        wiki_dir=wiki_dir,
        curation_dir=curation_dir,
    )
    assert not (wiki_dir / "cell_types" / "stale.md").exists()
    assert not (wiki_dir / "marker_genes" / "CD8A.md").exists()
    assert not (wiki_dir / "tissues" / "lung.md").exists()
    assert not (wiki_dir / "diseases" / "nsclc.md").exists()

    renderer.render(
        [_extraction("p2", standard_name="b_cell")],
        wiki_dir=wiki_dir,
        curation_dir=curation_dir,
    )
    second_snapshot = {
        path.relative_to(wiki_dir).as_posix(): path.read_bytes()
        for path in wiki_dir.rglob("*")
        if path.is_file()
    }
    assert second_snapshot == {
        path.relative_to(wiki_dir).as_posix(): path.read_bytes()
        for path in wiki_dir.rglob("*")
        if path.is_file()
    }
    assert first_snapshot != second_snapshot
