---
aliases:
- myeloid cells
cl_id: CL:0000763
display_name: Myeloid Cell
parent_type: null
references:
- paper_id: exmaple_paper_2
  title: An SPP1-SOCS1 pathway constrains interferon responses in tumor-associated
    macrophages and shapes an immunosuppressive tumor microenvironment
standard_name: myeloid_cell
evidence_tier: 4
source_count: 1
positive_markers:
- CD11B
- CD45
- PTPRC
negative_markers: []
tissues:
- tumor
- tumor microenvironment
species:
- Homo sapiens
- Mus musculus
conflicts: []
---

# Myeloid Cell

> A broad lineage of innate immune cells including macrophages and monocytes that populate the tumor microenvironment.

## Markers

| Marker | Type | Evidence | Source |
|--------|------|----------|--------|
| Cd11b | positive | flow cytometry gating | [exmaple_paper_2]() |
| Cd45 | positive | flow cytometry gating (DAPI-CD45+CD11B+) | [exmaple_paper_2]() |
| Ptprc | positive | CD45+ population used to define immune/myeloid compartment | [exmaple_paper_2]() |

## Functional Characteristics

- **Encompass macrophages and monocytes; proportions shift in Spp1-KO tumors** (hematopoiesis and immune regulation)
  - Source: [exmaple_paper_2]()
- **Broad immune compartment encompassing macrophages, DCs, and granulocytes** (innate immune signaling)
  - Source: [exmaple_paper_2]()

## Contexts

### Homo sapiens

**Tissues:** tumor microenvironment, tumor

**Diseases:** colorectal cancer, cancer

### Mus musculus

**Tissues:** tumor microenvironment, tumor

**Diseases:** colorectal cancer, cancer

## Subpopulations

- [monocyte](monocyte.md)
- [tumor_associated_macrophage](tumor_associated_macrophage.md)

## Related Cell Types

- [monocyte](monocyte.md)
- [tumor_associated_macrophage](tumor_associated_macrophage.md)

## References

- An SPP1-SOCS1 pathway constrains interferon responses in tumor-associated macrophages and shapes an immunosuppressive tumor microenvironment (2026) [10.1016/j.immuni.2026.04.001](https://doi.org/10.1016/j.immuni.2026.04.001)
