---
aliases:
- CD4_C02
- CD4_C02-ANXA1 / P.TCM
- CD4_C04
- N.TCM
- P.TCM
cl_id: null
display_name: CD4 Central Memory T Cell
parent_type: cd4_t_cell
references:
- paper_id: exmaple_paper_1
  title: Lineage tracking reveals dynamic relationships of T cells in colorectal cancer
standard_name: cd4_central_memory_t_cell
evidence_tier: 4
source_count: 1
positive_markers:
- ANXA1
- TCF7
negative_markers: []
tissues:
- adjacent normal mucosa
- peripheral blood
species:
- Homo sapiens
conflicts: []
---

# CD4 Central Memory T Cell

> Peripheral central memory CD4+ T cell cluster enriched in blood.

## Markers

| Marker | Type | Evidence | Source |
|--------|------|----------|--------|
| ANXA1 | positive | scRNA-seq | [exmaple_paper_1]() |
| TCF7 | positive | scRNA-seq | [exmaple_paper_1]() |

## Functional Characteristics

- **Peripheral central memory phenotype with proliferative potential** (Memory T cell maintenance)
  - Source: [exmaple_paper_1]()
- **Normal tissue central memory cells with stem-like properties** (Wnt/beta-catenin signaling)
  - Source: [exmaple_paper_1]()

## Contexts

### Homo sapiens

**Tissues:** peripheral blood, adjacent normal mucosa

**Diseases:** colorectal cancer

## Related Cell Types

- Parent: [cd4_t_cell](cd4_t_cell.md)

## References

- Lineage tracking reveals dynamic relationships of T cells in colorectal cancer (2018) [10.1038/s41586-018-0694-x](https://doi.org/10.1038/s41586-018-0694-x)
