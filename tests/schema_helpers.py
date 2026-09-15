"""Shared v2 schema fixtures for tests that are not about contract details."""

from __future__ import annotations


def minimal_schema_contract() -> str:
    return '''# Test schema

```yaml cellwiki-schema
schema_version: 2
pages:
  cell_type:
    path: wiki/cell_types/{id}.md
    identity: standard_name
    source_field: references
    source_id_field: paper_id
    frontmatter:
      required:
        standard_name:
          type: string
          pattern: '^[a-z0-9_]+$'
        display_name:
          type: string
        evidence_tier:
          type: integer
          enum: [1, 2, 3, 4, 5]
        references:
          type: list
      optional: {}
```

```markdown cellwiki-template cell_type
<!-- cellwiki
title_field: display_name
required_any: []
-->
# {{ display_name }}

<!-- cellwiki
required: true
block: table
min: 1
columns: [Marker, Type, Evidence, Source]
citation: per-item
source: raw
-->
## Markers

| Marker | Type | Evidence | Source |
| --- | --- | --- | --- |
| {{ marker }} | positive | Tier 5 | inference |

<!-- cellwiki
required: true
block: bullets
min: 1
-->
## References

- {{ source }}
```
'''


def valid_cell_type_page(
    *,
    standard_name: str = "alpha_cell",
    display_name: str = "Alpha Cell",
    body_suffix: str = "",
) -> str:
    return (
        "---\n"
        f"standard_name: {standard_name}\n"
        f"display_name: {display_name}\n"
        "evidence_tier: 5\n"
        "references: []\n"
        "---\n\n"
        f"# {display_name}\n\n"
        "## Markers\n\n"
        "| Marker | Type | Evidence | Source |\n"
        "| --- | --- | --- | --- |\n"
        "| CD8A | positive | Tier 5 | inference |\n\n"
        "## References\n\n"
        "- inference\n"
        f"{body_suffix}"
    )


def invalid_cell_type_page() -> str:
    return (
        "---\n"
        "standard_name: alpha_cell\n"
        "references: []\n"
        "---\n\n"
        "# Alpha Cell\n\n"
        "Invalid body.\n"
    )
