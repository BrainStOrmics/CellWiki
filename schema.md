# CellWiki 页面提取契约

> 本文件只定义页面提取契约。Agent 在 ingest 前读取本文件；lint 解析其中的
> `yaml cellwiki-schema` 块和 `markdown cellwiki-template` 模板块。
> 块外的普通说明不参与机械校验。该文件是用户拥有的契约，Agent 不得静默修改。

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
        aliases:
          type: list
        cl_id:
          type: string
          nullable: true
        parent_type:
          type: string
          nullable: true
        references:
          type: list
        evidence_tier:
          type: integer
          enum: [1, 2, 3, 4, 5]
        source_count:
          type: integer
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
      optional: {}

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
          pattern: '^[A-Za-z0-9][A-Za-z0-9_.-]*$'
        evidence_tier:
          type: integer
          enum: [1, 2, 3, 4, 5]
        sources:
          type: list
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

  tissue:
    path: wiki/tissues/{id}.md
    identity: name
    source_field: sources
    frontmatter:
      required:
        entity_type:
          type: string
          const: tissue
        name:
          type: string
        display_name:
          type: string
        evidence_tier:
          type: integer
          enum: [1, 2, 3, 4, 5]
        sources:
          type: list
      optional:
        source_count:
          type: integer
        last_updated:
          type: string

  disease:
    path: wiki/diseases/{id}.md
    identity: name
    source_field: sources
    frontmatter:
      required:
        entity_type:
          type: string
          const: disease
        name:
          type: string
        display_name:
          type: string
        evidence_tier:
          type: integer
          enum: [1, 2, 3, 4, 5]
        sources:
          type: list
      optional:
        source_count:
          type: integer
        last_updated:
          type: string

  method:
    path: wiki/methods/{id}.md
    identity: name
    source_field: sources
    frontmatter:
      required:
        entity_type:
          type: string
          const: method
        name:
          type: string
        display_name:
          type: string
        evidence_tier:
          type: integer
          enum: [1, 2, 3, 4, 5]
        sources:
          type: list
      optional:
        description:
          type: string
        category:
          type: string
        source_count:
          type: integer
        last_updated:
          type: string

  trajectory:
    path: wiki/trajectories/{id}.md
    identity: name
    source_field: sources
    frontmatter:
      required:
        entity_type:
          type: string
          const: trajectory
        name:
          type: string
        display_name:
          type: string
        start_state:
          type: string
        end_state:
          type: string
        evidence_tier:
          type: integer
          enum: [1, 2, 3, 4, 5]
        sources:
          type: list
      optional:
        description:
          type: string
        intermediate_states:
          type: list
        source_count:
          type: integer
        last_updated:
          type: string
```

```markdown cellwiki-template cell_type
<!-- cellwiki
title_field: display_name
required_any: []
-->
# {{ display_name }}

> {{ summary }}

<!-- cellwiki
required: true
block: table
min: 1
columns: [Marker, Type, Evidence, Source]
column_rules:
  Marker:
    wikilink: marker_gene
  Type:
    enum: [positive, negative, transcript]
citation: per-item
source: raw
-->
## Markers

| Marker | Type | Evidence | Source |
| --- | --- | --- | --- |
| {{ marker }} | {{ marker_type }} | {{ evidence_tier }} | [{{ paper_id }}](#references) |

<!-- cellwiki
required: false
block: bullets
min: 1
citation: per-item
source: raw
evidence_items: true
-->
## Functional Characteristics

- **{{ function }}** ({{ pathway }})
  - Evidence: Tier 2
  - Source: [{{ paper_id }}](#references)

<!-- cellwiki
required: false
block: mixed
children: allowed
citation: optional
source: none
line_rules:
  - label: "**Tissues:**"
    wikilink: tissue
    separator: ","
  - label: "**Diseases:**"
    wikilink: disease
    separator: ","
  - label: "**Evidence:**"
    evidence_line: true
  - label: "**Source:**"
    source_line: true
-->
## Contexts

### {{ species }}

**Tissues:** [[{{ tissue_id }}]]

**Diseases:** [[{{ disease_id }}]]

**Evidence:** Tier 2

**Source:** [{{ paper_id }}](#references)

<!-- cellwiki
required: false
block: bullets
item_rules:
  - wikilink: cell_type
-->
## Subpopulations

- [[{{ cell_type_id }}]]

<!-- cellwiki
required: false
block: bullets
item_rules:
  - wikilink: cell_type
    allow_prefixes: ["Parent:"]
-->
## Related Cell Types

- Parent: [[{{ parent_type }}]]
- [[{{ related_cell_type_id }}]]

<!-- cellwiki
required: true
block: bullets
min: 1
-->
## References

- {{ title }} ({{ year }}) [{{ doi }}](https://doi.org/{{ doi }})
```

```markdown cellwiki-template marker_gene
<!-- cellwiki
title_field: gene_symbol
required_any: [Expression, Negative Evidence, Co-expression]
-->
# {{ gene_symbol }}

> {{ summary }}

<!-- cellwiki
required: false
block: table
min: 1
columns: [Cell Type, Detection, Level, Evidence, Source]
column_rules:
  Cell Type:
    wikilink: cell_type
  Detection:
    enum: [positive, negative, unknown]
  Level:
    enum: [high, medium, low, unknown]
citation: per-item
source: raw
-->
## Expression

| Cell Type | Detection | Level | Evidence | Source |
| --- | --- | --- | --- | --- |
| [[{{ cell_type_id }}]] | positive | high | Tier 2 | [{{ paper_id }}](#references) |

<!-- cellwiki
required: false
block: table
min: 1
columns: [Cell Type, Evidence, Source]
column_rules:
  Cell Type:
    wikilink: cell_type
citation: per-item
source: raw
-->
## Negative Evidence

| Cell Type | Evidence | Source |
| --- | --- | --- |
| [[{{ cell_type_id }}]] | Tier 2 | [{{ paper_id }}](#references) |

<!-- cellwiki
required: false
block: table
min: 1
columns: [Gene, Cell Type, Direction, Correlation, Evidence, Source]
column_rules:
  Gene:
    wikilink: marker_gene
  Cell Type:
    wikilink: cell_type
  Direction:
    enum: [positive, negative, none, unknown]
  Correlation:
    number:
      min: -1
      max: 1
    allow_unknown: true
citation: per-item
source: raw
-->
## Co-expression

| Gene | Cell Type | Direction | Correlation | Evidence | Source |
| --- | --- | --- | --- | --- | --- |
| [[{{ gene_symbol }}]] | [[{{ cell_type_id }}]] | positive | 0.75 | Tier 2 | [{{ paper_id }}](#references) |

<!-- cellwiki
required: false
block: bullets
item_rules:
  - wikilink: cell_type
-->
## Related Cell Types

- [[{{ cell_type_id }}]]

<!-- cellwiki
required: true
block: bullets
min: 1
-->
## References

- {{ title }} ({{ year }}) [{{ doi }}](https://doi.org/{{ doi }})
```

```markdown cellwiki-template tissue
<!-- cellwiki
title_field: display_name
required_any: [Cell Types, Diseases, Markers]
-->
# {{ display_name }}

> {{ summary }}

<!-- cellwiki
required: false
block: table
min: 1
columns: [Cell Type, Status, Evidence, Source]
column_rules:
  Cell Type:
    wikilink: cell_type
  Status:
    enum: [confirmed, predicted, conflicting, unknown]
citation: per-item
source: raw
-->
## Cell Types

| Cell Type | Status | Evidence | Source |
| --- | --- | --- | --- |
| [[{{ cell_type_id }}]] | confirmed | Tier 2 | [{{ paper_id }}](#references) |

<!-- cellwiki
required: false
block: table
min: 1
columns: [Disease, Evidence, Source]
column_rules:
  Disease:
    wikilink: disease
citation: per-item
source: raw
-->
## Diseases

| Disease | Evidence | Source |
| --- | --- | --- |
| [[{{ disease_id }}]] | Tier 2 | [{{ paper_id }}](#references) |

<!-- cellwiki
required: false
block: table
min: 1
columns: [Marker, Type, Evidence, Source]
column_rules:
  Marker:
    wikilink: marker_gene
  Type:
    enum: [positive, negative, transcript]
citation: per-item
source: raw
-->
## Markers

| Marker | Type | Evidence | Source |
| --- | --- | --- | --- |
| [[{{ gene_symbol }}]] | positive | Tier 2 | [{{ paper_id }}](#references) |

<!-- cellwiki
required: true
block: bullets
min: 1
-->
## References

- {{ title }} ({{ year }}) [{{ doi }}](https://doi.org/{{ doi }})
```

```markdown cellwiki-template disease
<!-- cellwiki
title_field: display_name
required_any: [Associated Cell Types, Tissues, Markers]
-->
# {{ display_name }}

> {{ summary }}

<!-- cellwiki
required: false
block: table
min: 1
columns: [Cell Type, Evidence, Source]
column_rules:
  Cell Type:
    wikilink: cell_type
citation: per-item
source: raw
-->
## Associated Cell Types

| Cell Type | Evidence | Source |
| --- | --- | --- |
| [[{{ cell_type_id }}]] | Tier 2 | [{{ paper_id }}](#references) |

<!-- cellwiki
required: false
block: table
min: 1
columns: [Tissue, Evidence, Source]
column_rules:
  Tissue:
    wikilink: tissue
citation: per-item
source: raw
-->
## Tissues

| Tissue | Evidence | Source |
| --- | --- | --- |
| [[{{ tissue_id }}]] | Tier 2 | [{{ paper_id }}](#references) |

<!-- cellwiki
required: false
block: table
min: 1
columns: [Marker, Type, Evidence, Source]
column_rules:
  Marker:
    wikilink: marker_gene
  Type:
    enum: [positive, negative, transcript]
citation: per-item
source: raw
-->
## Markers

| Marker | Type | Evidence | Source |
| --- | --- | --- | --- |
| [[{{ gene_symbol }}]] | positive | Tier 2 | [{{ paper_id }}](#references) |

<!-- cellwiki
required: true
block: bullets
min: 1
-->
## References

- {{ title }} ({{ year }}) [{{ doi }}](https://doi.org/{{ doi }})
```

```markdown cellwiki-template method
<!-- cellwiki
title_field: display_name
required_any: [Inputs, Outputs, Workflow, Assumptions]
-->
# {{ display_name }}

> {{ summary }}

<!-- cellwiki
required: false
block: table
min: 1
columns: [Input, Type, Description, Evidence, Source]
column_rules:
  Type:
    enum: [fastq, bam, matrix, h5ad, metadata, annotation, table, image, model, embedding, other]
citation: per-item
source: raw
-->
## Inputs

| Input | Type | Description | Evidence | Source |
| --- | --- | --- | --- | --- |
| {{ input }} | fastq | {{ description }} | Tier 2 | [{{ paper_id }}](#references) |

<!-- cellwiki
required: false
block: table
min: 1
columns: [Output, Type, Description, Evidence, Source]
column_rules:
  Type:
    enum: [fastq, bam, matrix, h5ad, metadata, annotation, table, image, model, embedding, other]
citation: per-item
source: raw
-->
## Outputs

| Output | Type | Description | Evidence | Source |
| --- | --- | --- | --- | --- |
| {{ output }} | matrix | {{ description }} | Tier 2 | [{{ paper_id }}](#references) |

<!-- cellwiki
required: false
block: bullets
min: 1
citation: per-item
source: raw
evidence_items: true
-->
## Workflow

1. {{ step }}
   - Evidence: Tier 2
   - Source: [{{ paper_id }}](#references)

<!-- cellwiki
required: false
block: bullets
min: 1
citation: per-item
source: raw
evidence_items: true
-->
## Assumptions

- {{ assumption }}
  - Evidence: Tier 2
  - Source: [{{ paper_id }}](#references)

<!-- cellwiki
required: false
block: bullets
item_rules:
  - wikilink: method
-->
## Related Methods

- [[{{ method_id }}]]

<!-- cellwiki
required: true
block: bullets
min: 1
-->
## References

- {{ title }} ({{ year }}) [{{ doi }}](https://doi.org/{{ doi }})
```

```markdown cellwiki-template trajectory
<!-- cellwiki
title_field: display_name
required_any: [States, Transitions]
-->
# {{ display_name }}

> {{ summary }}

<!-- cellwiki
required: false
block: table
min: 1
columns: [Order, State, Role, Description, Evidence, Source]
column_rules:
  State:
    wikilink: cell_type
  Role:
    enum: [start, intermediate, end]
citation: per-item
source: raw
-->
## States

| Order | State | Role | Description | Evidence | Source |
| --- | --- | --- | --- | --- | --- |
| 1 | [[{{ start_state }}]] | start | {{ description }} | Tier 2 | [{{ paper_id }}](#references) |

<!-- cellwiki
required: false
block: table
min: 1
columns: [From, To, Evidence, Source]
column_rules:
  From:
    wikilink: cell_type
  To:
    wikilink: cell_type
citation: per-item
source: raw
-->
## Transitions

| From | To | Evidence | Source |
| --- | --- | --- | --- |
| [[{{ from_state }}]] | [[{{ to_state }}]] | Tier 2 | [{{ paper_id }}](#references) |

<!-- cellwiki
required: false
block: bullets
item_rules:
  - wikilink: cell_type
-->
## Related Cell Types

- [[{{ cell_type_id }}]]

<!-- cellwiki
required: true
block: bullets
min: 1
-->
## References

- {{ title }} ({{ year }}) [{{ doi }}](https://doi.org/{{ doi }})
```
