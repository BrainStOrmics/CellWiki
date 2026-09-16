"""Template-driven schema lint and L0 gate tests."""

from __future__ import annotations

from pathlib import Path
from shutil import copyfile

from cellwiki.services.quality import inspect_projection

ROOT = Path(__file__).resolve().parents[1]


def _write_schema(root: Path) -> None:
    copyfile(ROOT / "schema.md", root / "schema.md")


def _write_support_pages(root: Path, source_id: str = "source_cd8") -> None:
    for rel in ("raw", "wiki/marker_genes", "wiki/tissues", "wiki/diseases"):
        (root / rel).mkdir(parents=True, exist_ok=True)
    (root / "raw" / source_id).mkdir(parents=True, exist_ok=True)
    (root / "wiki/marker_genes/CD8A.md").write_text(
        "---\n"
        "entity_type: marker_gene\n"
        "gene_symbol: CD8A\n"
        "evidence_tier: 2\n"
        f"sources: [{source_id}]\n"
        "---\n"
        "# CD8A\n\n"
        "## Expression\n\n"
        "| Cell Type | Detection | Level | Evidence | Source |\n"
        "| --- | --- | --- | --- | --- |\n"
        f"| [[cd8_t_cell]] | positive | high | Tier 2 | [{source_id}](#references) |\n\n"
        "## References\n\n"
        f"- {source_id}\n",
        encoding="utf-8",
    )
    (root / "wiki/tissues/blood.md").write_text(
        "---\n"
        "entity_type: tissue\n"
        "name: blood\n"
        "display_name: Blood\n"
        "evidence_tier: 2\n"
        f"sources: [{source_id}]\n"
        "---\n"
        "# Blood\n\n"
        "## Cell Types\n\n"
        "| Cell Type | Status | Evidence | Source |\n"
        "| --- | --- | --- | --- |\n"
        f"| [[cd8_t_cell]] | confirmed | Tier 2 | [{source_id}](#references) |\n\n"
        "## References\n\n"
        f"- {source_id}\n",
        encoding="utf-8",
    )
    (root / "wiki/diseases/cancer.md").write_text(
        "---\n"
        "entity_type: disease\n"
        "name: cancer\n"
        "display_name: Cancer\n"
        "evidence_tier: 2\n"
        f"sources: [{source_id}]\n"
        "---\n"
        "# Cancer\n\n"
        "## Associated Cell Types\n\n"
        "| Cell Type | Evidence | Source |\n"
        "| --- | --- | --- |\n"
        f"| [[cd8_t_cell]] | Tier 2 | [{source_id}](#references) |\n\n"
        "## References\n\n"
        f"- {source_id}\n",
        encoding="utf-8",
    )


def _valid_cell_page(
    *,
    evidence: str = "Tier 2",
    source: str = "[source_cd8](#references)",
    marker: str = "[[CD8A]]",
    marker_type: str = "positive",
    frontmatter_tier: int = 2,
    include_markers: bool = True,
    extra_paragraph: str = "",
) -> str:
    markers = ""
    if include_markers:
        markers = (
            "## Markers\n\n"
            "| Marker | Type | Evidence | Source |\n"
            "| --- | --- | --- | --- |\n"
            f"| {marker} | {marker_type} | {evidence} | {source} |\n\n"
        )
    return (
        "---\n"
        "standard_name: cd8_t_cell\n"
        "display_name: CD8 T Cell\n"
        "aliases: []\n"
        "cl_id: null\n"
        "parent_type: null\n"
        "references:\n"
        "  - paper_id: source_cd8\n"
        "    title: Source paper\n"
        f"evidence_tier: {frontmatter_tier}\n"
        "source_count: 1\n"
        "positive_markers: [CD8A]\n"
        "negative_markers: []\n"
        "tissues: [blood]\n"
        "species: [Homo sapiens]\n"
        "conflicts: []\n"
        "---\n"
        "# CD8 T Cell\n\n"
        "> Cytotoxic T cells.\n\n"
        f"{extra_paragraph}"
        f"{markers}"
        "## Contexts\n\n"
        "### Homo sapiens\n\n"
        "**Tissues:** [[blood]]\n\n"
        "**Diseases:** [[cancer]]\n\n"
        f"**Evidence:** {evidence}\n\n"
        f"**Source:** {source}\n\n"
        "## References\n\n"
        "- Source paper (2024) [10.1/test](https://doi.org/10.1/test)\n"
    )


def _write_cell_page(root: Path, **kwargs) -> Path:
    path = root / "wiki/cell_types/cd8_t_cell.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_valid_cell_page(**kwargs), encoding="utf-8")
    return path


def test_valid_changed_page_passes(tmp_path: Path):
    _write_schema(tmp_path)
    _write_support_pages(tmp_path)
    _write_cell_page(tmp_path)
    report = inspect_projection(
        tmp_path, changed_paths=["wiki/cell_types/cd8_t_cell.md"]
    )
    assert report["status"] == "passed", report["issues"]


def test_legacy_pages_are_ignored_until_changed(tmp_path: Path):
    _write_schema(tmp_path)
    path = tmp_path / "wiki/cell_types/legacy.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\nstandard_name: legacy\ndisplay_name: Legacy\n---\n# Legacy\n",
        encoding="utf-8",
    )
    assert inspect_projection(tmp_path)["status"] == "passed"
    report = inspect_projection(tmp_path, changed_paths=["wiki/cell_types/legacy.md"])
    assert report["status"] == "failed"
    assert any(issue["type"] == "missing_required_field" for issue in report["issues"])


def test_missing_markers_is_l0(tmp_path: Path):
    _write_schema(tmp_path)
    _write_support_pages(tmp_path)
    _write_cell_page(tmp_path, include_markers=False)
    report = inspect_projection(
        tmp_path, changed_paths=["wiki/cell_types/cd8_t_cell.md"]
    )
    types = {issue["type"] for issue in report["issues"]}
    assert "missing_required_section" in types


def test_controlled_vocabulary_and_columns_are_enforced(tmp_path: Path):
    _write_schema(tmp_path)
    _write_support_pages(tmp_path)
    _write_cell_page(tmp_path, marker_type="bogus")
    report = inspect_projection(
        tmp_path, changed_paths=["wiki/cell_types/cd8_t_cell.md"]
    )
    assert any(issue["type"] == "invalid_controlled_value" for issue in report["issues"])


def test_source_binding_and_raw_directory_are_enforced(tmp_path: Path):
    _write_schema(tmp_path)
    _write_support_pages(tmp_path)
    _write_cell_page(tmp_path, source="[missing](#references)")
    report = inspect_projection(
        tmp_path, changed_paths=["wiki/cell_types/cd8_t_cell.md"]
    )
    types = {issue["type"] for issue in report["issues"]}
    assert "undeclared_source" in types
    assert "missing_reference_source" in types


def test_tier5_allows_inference_without_raw(tmp_path: Path):
    _write_schema(tmp_path)
    _write_support_pages(tmp_path)
    _write_cell_page(
        tmp_path,
        evidence="Tier 5",
        source="inference",
        frontmatter_tier=5,
    )
    report = inspect_projection(
        tmp_path, changed_paths=["wiki/cell_types/cd8_t_cell.md"]
    )
    assert report["status"] == "passed", report["issues"]


def test_page_evidence_tier_is_the_weakest_claim(tmp_path: Path):
    _write_schema(tmp_path)
    _write_support_pages(tmp_path)
    _write_cell_page(tmp_path, evidence="Tier 3", frontmatter_tier=2)
    report = inspect_projection(
        tmp_path, changed_paths=["wiki/cell_types/cd8_t_cell.md"]
    )
    assert any(
        issue["type"] == "page_evidence_tier_mismatch" for issue in report["issues"]
    )


def test_structured_wikilinks_are_l0_and_prose_mentions_are_l1(tmp_path: Path):
    _write_schema(tmp_path)
    _write_support_pages(tmp_path)
    _write_cell_page(
        tmp_path,
        marker="CD8A",
        extra_paragraph="CD8A is discussed here without a wikilink.\n\n",
    )
    report = inspect_projection(
        tmp_path, changed_paths=["wiki/cell_types/cd8_t_cell.md"]
    )
    types = {issue["type"] for issue in report["issues"]}
    assert "missing_wikilink" in types
    assert any(
        issue["type"] == "missing_wikilink" and issue["severity"] == "warning"
        for issue in report["issues"]
    )


def test_duplicate_page_id_is_error(tmp_path: Path):
    _write_schema(tmp_path)
    _write_support_pages(tmp_path)
    _write_cell_page(tmp_path)
    duplicate = tmp_path / "wiki/other/cd8_t_cell.md"
    duplicate.parent.mkdir(parents=True, exist_ok=True)
    duplicate.write_text("# Duplicate\n", encoding="utf-8")
    report = inspect_projection(tmp_path, changed_paths=["wiki/other/cd8_t_cell.md"])
    assert any(issue["type"] == "duplicate_page_id" for issue in report["issues"])


def test_invalid_schema_change_is_l0(tmp_path: Path):
    _write_schema(tmp_path)
    (tmp_path / "schema.md").write_text("# missing contract\n", encoding="utf-8")
    report = inspect_projection(tmp_path, changed_paths=["schema.md"])
    assert report["status"] == "failed"
    assert any(issue["type"] == "invalid_schema" for issue in report["issues"])


def _write_related_cell(root: Path) -> None:
    path = root / "wiki/cell_types/alpha_cell.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        "standard_name: alpha_cell\n"
        "display_name: Alpha Cell\n"
        "---\n\n"
        "# Alpha Cell\n",
        encoding="utf-8",
    )


def _template_shaped_cell_page(
    *,
    function_evidence: str | None = "  - Evidence: Tier 2",
    function_source: str | None = "  - Source: [source_cd8](#references)",
    related_item: str = "- [[alpha_cell]]",
    table_gaps: bool = False,
) -> str:
    function_lines = [
        line for line in (function_evidence, function_source) if line is not None
    ]
    if table_gaps:
        markers = (
            "| Marker | Type | Evidence | Source |\n"
            "\n"
            "| --- | --- | --- | --- |\n"
            "\n"
            "| [[CD8A]] | positive | Tier 2 | [source_cd8](#references) |\n"
        )
    else:
        markers = (
            "| Marker | Type | Evidence | Source |\n"
            "| --- | --- | --- | --- |\n"
            "| [[CD8A]] | positive | Tier 2 | [source_cd8](#references) |\n"
        )
    return (
        "---\n"
        "standard_name: cd8_t_cell\n"
        "display_name: CD8 T Cell\n"
        "aliases: []\n"
        "cl_id: null\n"
        "parent_type: null\n"
        "references:\n"
        "  - paper_id: source_cd8\n"
        "evidence_tier: 2\n"
        "source_count: 1\n"
        "positive_markers: [CD8A]\n"
        "negative_markers: []\n"
        "tissues: [blood]\n"
        "species: [Homo sapiens]\n"
        "conflicts: []\n"
        "---\n\n"
        "# CD8 T Cell\n\n"
        "> Cytotoxic T cells.\n\n"
        "## Markers\n\n"
        f"{markers}\n"
        "## Functional Characteristics\n\n"
        "- **Kills infected cells**\n"
        + "".join(f"{line}\n" for line in function_lines)
        + "\n"
        "## Subpopulations\n\n"
        "- [[alpha_cell]]\n\n"
        "## Related Cell Types\n\n"
        f"{related_item}\n\n"
        "## References\n\n"
        "- Source paper (2024) [10.1/test](https://doi.org/10.1/test)\n"
    )


def test_template_shaped_page_passes(tmp_path: Path):
    _write_schema(tmp_path)
    _write_support_pages(tmp_path)
    _write_related_cell(tmp_path)
    page = tmp_path / "wiki/cell_types/cd8_t_cell.md"
    page.write_text(_template_shaped_cell_page(), encoding="utf-8")
    report = inspect_projection(tmp_path, changed_paths=["wiki/cell_types/cd8_t_cell.md"])
    assert report["status"] == "passed", report["issues"]


def test_function_item_without_evidence_is_l0(tmp_path: Path):
    _write_schema(tmp_path)
    _write_support_pages(tmp_path)
    _write_related_cell(tmp_path)
    page = tmp_path / "wiki/cell_types/cd8_t_cell.md"
    page.write_text(_template_shaped_cell_page(function_evidence=None), encoding="utf-8")
    report = inspect_projection(tmp_path, changed_paths=["wiki/cell_types/cd8_t_cell.md"])
    assert any(issue["type"] == "missing_item_evidence" for issue in report["issues"])


def test_related_cell_item_without_wikilink_is_l0(tmp_path: Path):
    _write_schema(tmp_path)
    _write_support_pages(tmp_path)
    _write_related_cell(tmp_path)
    page = tmp_path / "wiki/cell_types/cd8_t_cell.md"
    page.write_text(
        _template_shaped_cell_page(related_item="- alpha cell"), encoding="utf-8"
    )
    report = inspect_projection(tmp_path, changed_paths=["wiki/cell_types/cd8_t_cell.md"])
    assert any(issue["type"] == "missing_wikilink" for issue in report["issues"])


def test_markers_table_tolerates_blank_lines(tmp_path: Path):
    _write_schema(tmp_path)
    _write_support_pages(tmp_path)
    _write_related_cell(tmp_path)
    page = tmp_path / "wiki/cell_types/cd8_t_cell.md"
    page.write_text(_template_shaped_cell_page(table_gaps=True), encoding="utf-8")
    report = inspect_projection(tmp_path, changed_paths=["wiki/cell_types/cd8_t_cell.md"])
    assert report["status"] == "passed", report["issues"]


def test_duplicate_frontmatter_key_is_l0(tmp_path: Path):
    _write_schema(tmp_path)
    _write_support_pages(tmp_path)
    _write_related_cell(tmp_path)
    page = tmp_path / "wiki/cell_types/cd8_t_cell.md"
    text = _template_shaped_cell_page().replace(
        "source_count: 1\n", "source_count: 1\nsource_count: 1\n"
    )
    page.write_text(text, encoding="utf-8")
    report = inspect_projection(tmp_path, changed_paths=["wiki/cell_types/cd8_t_cell.md"])
    assert any(
        issue["type"] == "invalid_frontmatter"
        and "duplicate mapping keys" in issue["detail"]
        for issue in report["issues"]
    )


def test_references_item_must_be_paper_id_mapping(tmp_path: Path):
    _write_schema(tmp_path)
    _write_support_pages(tmp_path)
    _write_related_cell(tmp_path)
    page = tmp_path / "wiki/cell_types/cd8_t_cell.md"
    text = _template_shaped_cell_page().replace(
        "references:\n  - paper_id: source_cd8\n", "references:\n  - source_cd8\n"
    )
    page.write_text(text, encoding="utf-8")
    report = inspect_projection(tmp_path, changed_paths=["wiki/cell_types/cd8_t_cell.md"])
    assert any(
        issue["type"] == "invalid_field_value" and "list of mappings" in issue["detail"]
        for issue in report["issues"]
    )


def test_l1_skips_summary_but_flags_prose_mentions(tmp_path: Path):
    _write_schema(tmp_path)
    _write_support_pages(tmp_path)
    _write_related_cell(tmp_path)
    page = tmp_path / "wiki/cell_types/cd8_t_cell.md"
    text = _valid_cell_page(extra_paragraph="Alpha cell migration is tissue dependent.\n\n")
    text = text.replace("> Cytotoxic T cells.", "> Alpha cell, a cytotoxic lineage.")
    page.write_text(text, encoding="utf-8")
    report = inspect_projection(tmp_path, changed_paths=["wiki/cell_types/cd8_t_cell.md"])
    warnings = [
        issue
        for issue in report["issues"]
        if issue["type"] == "missing_wikilink" and issue["severity"] == "warning"
    ]
    assert any(issue["locator"].endswith(":5") for issue in warnings)
    assert not any(issue["locator"].endswith(":3") for issue in warnings)


def test_term_matching_is_word_bounded():
    from cellwiki.services import quality as quality_module

    assert quality_module._term_pattern("tex").search("this context") is None
    assert quality_module._term_pattern("tan").search("resistance") is None
    assert quality_module._term_pattern("tex").search("tex cells") is not None


def test_tool_directive_comment_is_l0(tmp_path: Path):
    _write_schema(tmp_path)
    _write_support_pages(tmp_path)
    _write_related_cell(tmp_path)
    page = tmp_path / "wiki/cell_types/cd8_t_cell.md"
    text = _template_shaped_cell_page().replace(
        "## Markers\n",
        "<!-- cellwiki\nrequired: true\nblock: table\n-->\n\n## Markers\n",
        1,
    )
    page.write_text(text, encoding="utf-8")
    report = inspect_projection(tmp_path, changed_paths=["wiki/cell_types/cd8_t_cell.md"])
    assert any(
        issue["type"] == "tool_directive_residue" and issue["level"] == "L0"
        for issue in report["issues"]
    )
