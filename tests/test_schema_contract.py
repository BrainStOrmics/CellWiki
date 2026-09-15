"""Contract parsing and rule-level tests for workspace page schemas."""

from __future__ import annotations

from pathlib import Path
from shutil import copyfile

import pytest

from cellwiki.domain.page_schema import FieldRule, PageContract, WorkspacePageSchema
from cellwiki.services.schema_contract import (
    SchemaContractError,
    field_rule_error,
    load_workspace_schema,
    matching_page_types,
    workspace_schema_hash,
)

ROOT = Path(__file__).resolve().parents[1]


def _write_root_schema(tmp_path: Path) -> None:
    copyfile(ROOT / "schema.md", tmp_path / "schema.md")


def test_root_v2_schema_loads_and_matches_pages(tmp_path: Path):
    _write_root_schema(tmp_path)
    schema = load_workspace_schema(tmp_path)
    assert schema.schema_version == 2
    assert set(schema.pages) == {
        "cell_type",
        "marker_gene",
        "tissue",
        "disease",
        "method",
        "trajectory",
    }
    matches = matching_page_types(schema, "wiki/cell_types/cd8_t_cell.md")
    assert matches[0][0] == "cell_type"
    assert matches[0][2] == "cd8_t_cell"
    assert schema.pages["cell_type"].template is not None
    assert schema.pages["cell_type"].template.title_field == "display_name"


def test_schema_rejects_v1_with_migration_message(tmp_path: Path):
    (tmp_path / "schema.md").write_text(
        "# Schema\n\n```yaml cellwiki-schema\nschema_version: 1\npages: {}\n```\n",
        encoding="utf-8",
    )
    with pytest.raises(SchemaContractError, match="schema_version 1 is no longer supported"):
        load_workspace_schema(tmp_path)


def test_schema_hash_uses_parsed_contract_and_templates(tmp_path: Path):
    _write_root_schema(tmp_path)
    schema_path = tmp_path / "schema.md"
    baseline = workspace_schema_hash(tmp_path)

    schema_path.write_text(
        schema_path.read_text(encoding="utf-8") + "\n<!-- formatting only -->\n",
        encoding="utf-8",
    )
    assert workspace_schema_hash(tmp_path) == baseline

    text = schema_path.read_text(encoding="utf-8")
    schema_path.write_text(text.replace("## Markers", "## Markers Renamed", 1), encoding="utf-8")
    assert workspace_schema_hash(tmp_path) != baseline


def test_schema_requires_one_machine_readable_block(tmp_path: Path):
    (tmp_path / "schema.md").write_text("# Prose only\n", encoding="utf-8")
    with pytest.raises(SchemaContractError, match="cellwiki-schema"):
        load_workspace_schema(tmp_path)


def test_schema_rejects_unknown_keywords(tmp_path: Path):
    _write_root_schema(tmp_path)
    schema_path = tmp_path / "schema.md"
    text = schema_path.read_text(encoding="utf-8")
    text = text.replace("      optional: {}\n", "      optional_typo: {}\n", 1)
    schema_path.write_text(text, encoding="utf-8")
    with pytest.raises(SchemaContractError, match="invalid page contract"):
        load_workspace_schema(tmp_path)


def test_page_contract_requires_safe_path_identity_and_source(tmp_path: Path):
    with pytest.raises(ValueError, match="identity field"):
        PageContract(
            path="wiki/cell_types/{id}.md",
            identity="missing",
            source_field="references",
            frontmatter={
                "required": {
                    "standard_name": {"type": "string"},
                    "references": {"type": "list"},
                }
            },
        )
    with pytest.raises(ValueError, match="start with wiki/"):
        PageContract(
            path="notes/{id}.md",
            identity="standard_name",
            source_field="references",
            frontmatter={
                "required": {
                    "standard_name": {"type": "string"},
                    "references": {"type": "list"},
                }
            },
        )
    with pytest.raises(ValueError, match="source_field"):
        PageContract(
            path="wiki/cell_types/{id}.md",
            identity="standard_name",
            source_field="references",
            frontmatter={"required": {"standard_name": {"type": "string"}}},
        )


def test_field_rule_validation():
    rule = FieldRule(type="string", pattern="^[a-z0-9_]+$")
    assert field_rule_error(rule, "cd8_t_cell") is None
    assert "pattern" in (field_rule_error(rule, "CD8 T cell") or "")
    assert field_rule_error(FieldRule(type="integer"), True) == "must be integer"
    assert field_rule_error(FieldRule(type="list"), {}) == "must be list"


def test_workspace_schema_rejects_duplicate_path_templates():
    page = {
        "identity": "name",
        "source_field": "sources",
        "frontmatter": {
            "required": {
                "name": {"type": "string"},
                "sources": {"type": "list"},
            }
        },
    }
    with pytest.raises(ValueError, match="duplicate page path"):
        WorkspacePageSchema.model_validate(
            {
                "schema_version": 2,
                "pages": {
                    "a": {"path": "wiki/a/{id}.md", **page},
                    "b": {"path": "wiki/a/{id}.md", **page},
                },
            }
        )
