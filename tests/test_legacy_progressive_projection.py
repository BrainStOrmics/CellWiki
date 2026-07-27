"""Tests for rebuilding progressive projection layers from legacy Wiki pages."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from cellwiki.adapters.legacy_wiki_projection import rebuild_from_legacy_pages


def test_rebuild_from_legacy_pages_preserves_body_and_builds_layers(tmp_path: Path):
    wiki_dir = tmp_path / "wiki"
    pages_dir = wiki_dir / "cell_types"
    pages_dir.mkdir(parents=True)
    legacy_page = "\n".join(
        [
            "---",
            "standard_name: t_cell",
            "display_name: T Cell",
            "parent_type: lymphocyte",
            "aliases:",
            "  - T cells",
            "references:",
            "  - paper_id: p1",
            "    title: Paper 1",
            "---",
            "",
            "# T Cell",
            "",
            "Original curated body.",
            "",
            "## Markers",
            "",
            "| Marker | Type | Evidence | Source |",
            "|--------|------|----------|--------|",
            "| CD8A | positive | positive evidence | [p1]() |",
            "| TCF7 CONFLICT | negative | negative evidence | [p1]() |",
            "",
            "## Contexts",
            "",
            "### Homo sapiens",
            "",
            "**Tissues:** lung, blood",
            "",
            "**Diseases:** NSCLC",
            "",
        ]
    )
    (pages_dir / "t_cell.md").write_text(legacy_page, encoding="utf-8")

    result = rebuild_from_legacy_pages(wiki_dir)

    assert result == {
        "cell_types": 1,
        "marker_genes": 2,
        "tissues": 2,
        "diseases": 1,
        "conflicts": 1,
    }
    cell_page = pages_dir / "t_cell.md"
    cell_text = cell_page.read_text(encoding="utf-8")
    frontmatter = yaml.safe_load(cell_text.split("---", 2)[1])
    assert "Original curated body." in cell_text
    assert frontmatter["positive_markers"] == ["CD8A"]
    assert frontmatter["negative_markers"] == ["TCF7"]
    assert frontmatter["tissues"] == ["blood", "lung"]
    assert frontmatter["species"] == ["Homo sapiens"]
    assert "## Markers" in cell_text

    assert (wiki_dir / "marker_genes" / "CD8A.md").exists()
    assert (wiki_dir / "tissues" / "lung.md").exists()
    assert (wiki_dir / "diseases" / "nsclc.md").exists()
    assert list((wiki_dir / "conflicts").glob("*.md"))
    assert "[按组织](tissues/)" in (wiki_dir / "index.md").read_text(encoding="utf-8")

    manifest = json.loads((wiki_dir / "manifest.json").read_text(encoding="utf-8"))
    assert {page["type"] for page in manifest["pages"]} >= {
        "cell_type",
        "marker_gene",
        "tissue",
        "disease",
        "conflict",
    }
