# CellWiki fixture schema

```yaml cellwiki-schema
schema_version: 1
pages:
  cell_type:
    path: wiki/cell_types/{id}.md
    identity: standard_name
    frontmatter:
      required:
        standard_name:
          type: string
          pattern: '^[a-z0-9_]+$'
        display_name:
          type: string
        references:
          type: list
      optional:
        entity_type:
          type: string
        cl_id:
          type: string
          nullable: true
        species:
          type: list
        evidence_tier:
          type: integer
          enum: [1, 2, 3, 4, 5]
        source_count:
          type: integer
    sections:
      required: []
    references:
      required: true
      require_source: false
    links:
      check: false
  marker_gene:
    path: wiki/marker_genes/{id}.md
    identity: standard_name
    frontmatter:
      required:
        standard_name:
          type: string
        display_name:
          type: string
        gene_symbol:
          type: string
        references:
          type: list
      optional:
        entity_type:
          type: string
        species:
          type: list
    sections:
      required: []
    references:
      required: true
      require_source: false
    links:
      check: false
```