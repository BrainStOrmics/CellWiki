"""Contract parsing and rule-level tests for workspace page schemas."""

from __future__ import annotations

from pathlib import Path

import pytest

from cellwiki.domain.page_schema import FieldRule, PageContract, WorkspacePageSchema
from cellwiki.services.schema_contract import (
    SchemaContractError,
    field_rule_error,
    load_workspace_schema,
    matching_page_types,
)


def _contract_text() -> str:
    return '''# Schema

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
      targets: [cell_type]
```
'''


def test_load_workspace_schema_and_match_page(tmp_path: Path):
    (tmp_path / "schema.md").write_text(_contract_text(), encoding="utf-8")
    schema = load_workspace_schema(tmp_path)
    matches = matching_page_types(schema, "wiki/cell_types/cd8_t_cell.md")
    assert len(matches) == 1
    assert matches[0][0] == "cell_type"
    assert matches[0][2] == "cd8_t_cell"


def test_schema_requires_one_machine_readable_block(tmp_path: Path):
    (tmp_path / "schema.md").write_text("# Prose only\n", encoding="utf-8")
    with pytest.raises(SchemaContractError, match="cellwiki-schema"):
        load_workspace_schema(tmp_path)


def test_schema_rejects_unknown_keywords(tmp_path: Path):
    text = _contract_text().replace("      optional:\n", "      optional_typo:\n")
    (tmp_path / "schema.md").write_text(text, encoding="utf-8")
    with pytest.raises(SchemaContractError, match="invalid schema contract"):
        load_workspace_schema(tmp_path)


def test_page_contract_requires_safe_path_and_identity(tmp_path: Path):
    with pytest.raises(ValueError, match="identity field"):
        PageContract(
            path="wiki/cell_types/{id}.md",
            identity="missing",
            frontmatter={"required": {"standard_name": {"type": "string"}}},
        )
    with pytest.raises(ValueError, match="start with wiki/"):
        PageContract(
            path="notes/{id}.md",
            identity="name",
            frontmatter={"required": {"name": {"type": "string"}}},
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
        "frontmatter": {"required": {"name": {"type": "string"}}},
    }
    with pytest.raises(ValueError, match="duplicate page path"):
        WorkspacePageSchema.model_validate(
            {
                "schema_version": 1,
                "pages": {
                    "a": {"path": "wiki/a/{id}.md", **page},
                    "b": {"path": "wiki/a/{id}.md", **page},
                },
            }
        )