---
aliases:
- CD4+CD8+ (double positive) T cells
- double positive T cells
cl_id: null
display_name: Double Positive T Cell
parent_type: t_cell
references:
- paper_id: exmaple_paper_1
  title: Lineage tracking reveals dynamic relationships of T cells in colorectal cancer
standard_name: double_positive_t_cell
evidence_tier: 4
source_count: 1
positive_markers:
- CD4
- CD8A
negative_markers: []
tissues:
- colorectal tumor
species:
- Homo sapiens
conflicts: []
---

# Double Positive T Cell

> T cells expressing both CD4 and CD8 co-receptors identified in silico from single-cell transcriptomic data.

## Markers

| Marker | Type | Evidence | Source |
|--------|------|----------|--------|
| CD3D | transcript | scRNA-seq TPM > 10 | [exmaple_paper_1]() |
| CD4 | positive | scRNA-seq TPM > 30 | [exmaple_paper_1]() |
| CD8A | positive | scRNA-seq TPM > 30 | [exmaple_paper_1]() |

## Functional Characteristics

- **Rare transitional or atypical T cell population** (Unknown)
  - Source: [exmaple_paper_1]()

## Contexts

### Homo sapiens

**Tissues:** colorectal tumor

**Diseases:** colorectal adenocarcinoma

## Related Cell Types

- Parent: [t_cell](t_cell.md)

## References

- Lineage tracking reveals dynamic relationships of T cells in colorectal cancer (2018) [10.1038/s41586-018-0694-x](https://doi.org/10.1038/s41586-018-0694-x)
