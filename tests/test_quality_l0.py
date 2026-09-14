"""Schema-driven lint and L0 gate tests."""

from __future__ import annotations

from pathlib import Path

from cellwiki.services.quality import inspect_projection


def _write_schema(root: Path) -> None:
    (root / "schema.md").write_text(
        '''# Schema

```yaml cellwiki-schema
schema_version: 1
pages:
  cell_type:
    path: wiki/cell_types/{id}.md
    identity: standard_name
    frontmatter:
      required:
        entity_type:
          type: string
          const: cell_type
        standard_name:
          type: string
          pattern: '^[a-z0-9_]+$'
        display_name:
          type: string
        references:
          type: list
      optional:
        cl_id:
          type: string
          nullable: true
    sections:
      required: [Evidence]
    references:
      required: true
      require_source: true
    links:
      check: true
      targets: [cell_type, marker_gene]
  marker_gene:
    path: wiki/marker_genes/{id}.md
    identity: gene_symbol
    frontmatter:
      required:
        entity_type:
          type: string
          const: marker_gene
        gene_symbol:
          type: string
    sections:
      required: []
    references:
      required: false
    links:
      check: false
```
''',
        encoding="utf-8",
    )


def _write_cell_page(root: Path, *, include_display_name: bool = True, link: str = "") -> Path:
    path = root / "wiki" / "cell_types" / "cd8_t_cell.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    display = 'display_name: "CD8 T Cell"\n' if include_display_name else ""
    body = "# CD8 T Cell\n\n## Evidence\n\nCD3D.\n"
    if link:
        body += f"\n[Related]({link})\n"
    path.write_text(
        "---\n"
        "entity_type: cell_type\n"
        "standard_name: cd8_t_cell\n"
        f"{display}"
        "references:\n"
        "  - source_id: paper_one\n"
        "---\n\n"
        f"{body}",
        encoding="utf-8",
    )
    return path


def test_valid_changed_page_passes(tmp_path: Path):
    _write_schema(tmp_path)
    (tmp_path / "raw" / "paper_one").mkdir(parents=True)
    marker = tmp_path / "wiki" / "marker_genes" / "CD8A.md"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        "---\nentity_type: marker_gene\ngene_symbol: CD8A\n---\n\n# CD8A\n",
        encoding="utf-8",
    )
    _write_cell_page(tmp_path, link="../marker_genes/CD8A.md")
    report = inspect_projection(
        tmp_path, changed_paths=["wiki/cell_types/cd8_t_cell.md"]
    )
    assert report["status"] == "passed", report["issues"]
    assert report["schema"]["status"] == "valid"


def test_changed_missing_field_is_l0_but_unchanged_is_l1(tmp_path: Path):
    _write_schema(tmp_path)
    (tmp_path / "raw" / "paper_one").mkdir(parents=True)
    _write_cell_page(tmp_path, include_display_name=False)

    strict = inspect_projection(tmp_path, changed_paths=["wiki/cell_types/cd8_t_cell.md"])
    assert strict["status"] == "failed"
    assert any(issue["type"] == "missing_required_field" for issue in strict["issues"])

    historical = inspect_projection(tmp_path, changed_paths=["README.md"])
    assert historical["status"] == "passed_with_warnings"
    assert any(issue["type"] == "missing_required_field" for issue in historical["issues"])
    assert all(issue["severity"] == "warning" for issue in historical["issues"])


def test_required_section_and_source_are_enforced(tmp_path: Path):
    _write_schema(tmp_path)
    path = _write_cell_page(tmp_path)
    path.write_text(
        "---\n"
        "entity_type: cell_type\n"
        "standard_name: cd8_t_cell\n"
        'display_name: "CD8 T Cell"\n'
        "references:\n"
        "  - source_id: missing_source\n"
        "---\n\n# CD8 T Cell\n",
        encoding="utf-8",
    )
    report = inspect_projection(tmp_path, changed_paths=["wiki/cell_types/cd8_t_cell.md"])
    types = {issue["type"] for issue in report["issues"]}
    assert "missing_required_section" in types
    assert "missing_reference_source" in types
    assert report["status"] == "failed"


def test_broken_link_and_wrong_target_type_are_errors(tmp_path: Path):
    _write_schema(tmp_path)
    (tmp_path / "raw" / "paper_one").mkdir(parents=True)
    _write_cell_page(tmp_path, link="../marker_genes/MISSING.md")
    report = inspect_projection(tmp_path, changed_paths=["wiki/cell_types/cd8_t_cell.md"])
    assert any(issue["type"] == "broken_local_link" for issue in report["issues"])
    assert report["status"] == "failed"


def test_duplicate_page_id_is_error(tmp_path: Path):
    _write_schema(tmp_path)
    (tmp_path / "raw" / "paper_one").mkdir(parents=True)
    _write_cell_page(tmp_path)
    duplicate = tmp_path / "wiki" / "other" / "cd8_t_cell.md"
    duplicate.parent.mkdir(parents=True, exist_ok=True)
    duplicate.write_text("# Duplicate\n", encoding="utf-8")
    report = inspect_projection(tmp_path, changed_paths=["wiki/other/cd8_t_cell.md"])
    assert any(issue["type"] == "duplicate_page_id" for issue in report["issues"])
    assert report["status"] == "failed"


def test_missing_schema_blocks_changed_wiki_page(tmp_path: Path):
    _write_cell_page(tmp_path)
    report = inspect_projection(tmp_path, changed_paths=["wiki/cell_types/cd8_t_cell.md"])
    assert any(issue["type"] == "missing_schema" for issue in report["issues"])
    assert report["status"] == "failed"

def test_invalid_schema_change_is_l0_even_without_wiki_page_change(tmp_path: Path):
    _write_schema(tmp_path)
    report = inspect_projection(tmp_path, changed_paths=["schema.md"])
    assert report["status"] == "passed"
    (tmp_path / "schema.md").write_text("# missing contract\n", encoding="utf-8")
    invalid = inspect_projection(tmp_path, changed_paths=["schema.md"])
    assert invalid["status"] == "failed"
    assert any(issue["type"] == "invalid_schema" for issue in invalid["issues"])