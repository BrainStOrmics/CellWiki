# CellWiki 页面提取契约

> 本文件只定义页面提取契约。Agent 在 ingest 前读取本文件；lint 解析其中的
> `yaml cellwiki-schema` 块。块外的说明仅供人和 Agent 理解，不参与机械校验。
> 该文件是用户拥有的契约，Agent 不得静默修改。

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
      optional:
        entity_type:
          type: string
        references:
          type: list
        cl_id:
          type: string
          nullable: true
        parent_type:
          type: string
          nullable: true
        aliases:
          type: list
        evidence_tier:
          type: integer
          enum: [1, 2, 3, 4, 5]
        source_count:
          type: integer
        last_updated:
          type: string
        positive_markers:
          type: list
        negative_markers:
          type: list
        tissues:
          type: list
        species:
          type: list
        conflicts:
          type: list
    sections:
      required: []
    references:
      required: false
      require_source: false
    links:
      check: false
      targets: [cell_type, marker_gene, tissue, disease]
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
          pattern: '^[A-Za-z0-9][A-Za-z0-9_.-]*$'
        evidence_tier:
          type: integer
          enum: [1, 2, 3, 4, 5]
      optional:
        gene_name:
          type: string
        gene_id_ensembl:
          type: string
        specificity:
          type: string
        source_count:
          type: integer
        last_updated:
          type: string
        sources:
          type: list
    sections:
      required: []
    references:
      required: false
    links:
      check: false
      targets: [cell_type]
  tissue:
    path: wiki/tissues/{id}.md
    identity: name
    frontmatter:
      required:
        entity_type:
          type: string
          const: tissue
        name:
          type: string
        display_name:
          type: string
        sources:
          type: list
      optional:
        source_count:
          type: integer
        last_updated:
          type: string
    sections:
      required: []
    references:
      required: false
    links:
      check: false
      targets: [cell_type]
  disease:
    path: wiki/diseases/{id}.md
    identity: name
    frontmatter:
      required:
        entity_type:
          type: string
          const: disease
        name:
          type: string
        display_name:
          type: string
        sources:
          type: list
      optional:
        source_count:
          type: integer
        last_updated:
          type: string
    sections:
      required: []
    references:
      required: false
    links:
      check: false
      targets: [cell_type]
  method:
    path: wiki/methods/{id}.md
    identity: name
    frontmatter:
      required:
        entity_type:
          type: string
          const: method
        name:
          type: string
        display_name:
          type: string
      optional:
        description:
          type: string
        category:
          type: string
        source_count:
          type: integer
        last_updated:
          type: string
    sections:
      required: []
    references:
      required: false
    links:
      check: false
      targets: [cell_type, disease, tissue]
  trajectory:
    path: wiki/trajectories/{id}.md
    identity: name
    frontmatter:
      required:
        entity_type:
          type: string
          const: trajectory
        name:
          type: string
        display_name:
          type: string
      optional:
        description:
          type: string
        start_state:
          type: string
        end_state:
          type: string
        intermediate_states:
          type: list
        evidence_tier:
          type: integer
          enum: [1, 2, 3, 4, 5]
        source_count:
          type: integer
        last_updated:
          type: string
    sections:
      required: []
    references:
      required: false
    links:
      check: false
      targets: [cell_type]
  conflict:
    path: wiki/conflicts/{id}.md
    identity: conflict_id
    frontmatter:
      required:
        conflict_id:
          type: string
        affected_cell_types:
          type: list
        severity:
          type: string
          enum: [low, medium, high]
        sources:
          type: list
    sections:
      required: []
    references:
      required: false
    links:
      check: false
      targets: [cell_type, marker_gene]
```