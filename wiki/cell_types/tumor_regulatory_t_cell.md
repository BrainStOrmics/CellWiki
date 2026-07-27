---
aliases:
- CD4_C12
- CD4_C12-CTLA4 / T.Treg
- T.Treg
cl_id: null
display_name: Tumor Regulatory T Cell
parent_type: regulatory_t_cell
references:
- paper_id: exmaple_paper_1
  title: Lineage tracking reveals dynamic relationships of T cells in colorectal cancer
standard_name: tumor_regulatory_t_cell
evidence_tier: 4
source_count: 1
positive_markers:
- CTLA4
- FOXP3
negative_markers: []
tissues:
- colorectal tumor
species:
- Homo sapiens
conflicts: []
---

# Tumor Regulatory T Cell

> Tumor-enriched regulatory T cell cluster expressing high CTLA4.

## Markers

| Marker | Type | Evidence | Source |
|--------|------|----------|--------|
| CTLA4 | positive | scRNA-seq | [exmaple_paper_1]() |
| FOXP3 | positive | scRNA-seq, IHC | [exmaple_paper_1]() |

## Functional Characteristics

- **Tumor-infiltrating regulatory cells suppressing anti-tumor immunity** (Immune checkpoint signaling)
  - Source: [exmaple_paper_1]()

## Contexts

### Homo sapiens

**Tissues:** colorectal tumor

**Diseases:** colorectal cancer

## Related Cell Types

- Parent: [regulatory_t_cell](regulatory_t_cell.md)

## References

- Lineage tracking reveals dynamic relationships of T cells in colorectal cancer (2018) [10.1038/s41586-018-0694-x](https://doi.org/10.1038/s41586-018-0694-x)
