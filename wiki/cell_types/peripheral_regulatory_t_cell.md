---
aliases:
- CD4_C10
- CD4_C10-FOXP3 / P.Treg
- P.Treg
cl_id: null
display_name: Peripheral Regulatory T Cell
parent_type: regulatory_t_cell
references:
- paper_id: exmaple_paper_1
  title: Lineage tracking reveals dynamic relationships of T cells in colorectal cancer
standard_name: peripheral_regulatory_t_cell
evidence_tier: 4
source_count: 1
positive_markers:
- FOXP3
- IL10
negative_markers: []
tissues:
- peripheral blood
species:
- Homo sapiens
conflicts: []
---

# Peripheral Regulatory T Cell

> Peripheral regulatory T cell cluster found in blood.

## Markers

| Marker | Type | Evidence | Source |
|--------|------|----------|--------|
| FOXP3 | positive | scRNA-seq, IHC | [exmaple_paper_1]() |
| IL10 | positive | scRNA-seq | [exmaple_paper_1]() |

## Functional Characteristics

- **Peripheral regulatory cells maintaining immune tolerance** (TGF-beta/IL-10 signaling)
  - Source: [exmaple_paper_1]()

## Contexts

### Homo sapiens

**Tissues:** peripheral blood

**Diseases:** colorectal cancer

## Related Cell Types

- Parent: [regulatory_t_cell](regulatory_t_cell.md)

## References

- Lineage tracking reveals dynamic relationships of T cells in colorectal cancer (2018) [10.1038/s41586-018-0694-x](https://doi.org/10.1038/s41586-018-0694-x)
