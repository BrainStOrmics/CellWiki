# CellWiki fixture schema

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
      optional:
        cl_id:
          type: string
          nullable: true
        species:
          type: list
        source_count:
          type: integer
  marker_gene:
    path: wiki/marker_genes/{id}.md
    identity: gene_symbol
    source_field: sources
    frontmatter:
      required:
        entity_type:
          type: string
          const: marker_gene
        gene_symbol:
          type: string
        evidence_tier:
          type: integer
          enum: [1, 2, 3, 4, 5]
        sources:
          type: list
      optional:
        gene_name:
          type: string
  note:
    path: wiki/notes/{id}.md
    identity: name
    source_field: sources
    frontmatter:
      required:
        name:
          type: string
        sources:
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
required: false
block: paragraphs
-->
## Definition

<!-- cellwiki
required: true
block: table
min: 1
columns: [Marker, Type, Evidence, Source]
-->
## Markers

| Marker | Type | Evidence | Source |
| --- | --- | --- | --- |
| {{ marker }} | positive | Tier 5 | inference |

<!-- cellwiki
required: false
block: paragraphs
-->
## Notes

<!-- cellwiki
required: true
block: bullets
min: 1
-->
## References

- {{ source }}
```

```markdown cellwiki-template marker_gene
<!-- cellwiki
title_field: gene_symbol
required_any: []
-->
# {{ gene_symbol }}

<!-- cellwiki
required: true
block: table
min: 1
columns: [Cell Type, Detection, Level, Evidence, Source]
-->
## Expression

| Cell Type | Detection | Level | Evidence | Source |
| --- | --- | --- | --- | --- |
| {{ cell_type }} | positive | high | Tier 5 | inference |

<!-- cellwiki
required: false
block: paragraphs
-->
## Notes

<!-- cellwiki
required: true
block: bullets
min: 1
-->
## References

- {{ source }}
```

```markdown cellwiki-template note
<!-- cellwiki
title_field: name
required_any: []
-->
# {{ name }}

<!-- cellwiki
required: false
block: paragraphs
-->
## Notes
```
