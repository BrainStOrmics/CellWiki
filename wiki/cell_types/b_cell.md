---
aliases:
- B cell subsets
- B cells
cl_id: CL:0000236
display_name: B Cell
parent_type: lymphoid_cell
references:
- paper_id: exmaple_paper_2
  title: An SPP1-SOCS1 pathway constrains interferon responses in tumor-associated
    macrophages and shapes an immunosuppressive tumor microenvironment
standard_name: b_cell
evidence_tier: 4
source_count: 1
positive_markers:
- CD19
- CD45
negative_markers: []
tissues:
- tumor
- tumor microenvironment
- tumor tissue
species:
- Homo sapiens
- Mus musculus
conflicts: []
---

# B Cell

> B lymphocytes identified within the tumor immune infiltrate.

## Markers

| Marker | Type | Evidence | Source |
|--------|------|----------|--------|
| Cd19 | positive | flow cytometry and immunofluorescence | [exmaple_paper_2]() |
| Cd45 | positive | flow cytometry gating (DAPI-CD45+CD19+) | [exmaple_paper_2]() |

## Functional Characteristics

- **Humoral immune cells present in the tumor microenvironment** (antibody production)
  - Source: [exmaple_paper_2]()
- **Identified as part of the lymphoid compartment in tumor scRNA-seq** (adaptive immunity)
  - Source: [exmaple_paper_2]()
- **Participate in humoral immunity and antigen presentation within the tumor** (B cell receptor signaling)
  - Source: [exmaple_paper_2]()

## Contexts

### Homo sapiens

**Tissues:** tumor tissue, tumor microenvironment, tumor

**Diseases:** colorectal cancer, cancer

### Mus musculus

**Tissues:** tumor tissue, tumor microenvironment, tumor

**Diseases:** colorectal cancer, cancer

## Related Cell Types

- Parent: [lymphoid_cell](lymphoid_cell.md)

## References

- An SPP1-SOCS1 pathway constrains interferon responses in tumor-associated macrophages and shapes an immunosuppressive tumor microenvironment (2026) [10.1016/j.immuni.2026.04.001](https://doi.org/10.1016/j.immuni.2026.04.001)
