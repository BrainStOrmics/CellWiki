---
aliases:
- CD4 T Cell
- CD4+ T cells
- CD8 T Cell
- CD8+ T cells
- Primary human T cell
- T cell
- T cells
- T helper cells
- T lymphocytes
- TC
- TH
- cd4_t_cell
- cd8_t_cell
- cytotoxic T cells
- lymphocyte
cl_id: CL:0000084
display_name: T Cell
parent_type: lymphocyte
references:
- paper_id: exmaple_paper_1
  title: Lineage tracking reveals dynamic relationships of T cells in colorectal cancer
- paper_id: exmaple_paper_2
  title: An SPP1-SOCS1 pathway constrains interferon responses in tumor-associated
    macrophages and shapes an immunosuppressive tumor microenvironment
standard_name: t_cell
evidence_tier: 4
source_count: 2
positive_markers:
- CD3
- CD4
- CD8A
- PD-1
negative_markers: []
tissues:
- adjacent normal mucosa
- adjacent normal tissue
- colorectal tumor
- peripheral blood
- tumor microenvironment
species:
- Homo sapiens
- Mus musculus
conflicts: []
---

# T Cell

> Adaptive immune lymphocytes responsible for direct tumor cell killing, whose efficacy is suppressed by TAMs and restored by SPP1 targeting.

## Markers

| Marker | Type | Evidence | Source |
|--------|------|----------|--------|
| CD3 | positive | FACS sorting, IHC | [exmaple_paper_1]() |
| CD3D | transcript | scRNA-seq TPM > 10 | [exmaple_paper_1]() |
| CD3E | transcript | scRNA-seq TPM > 10 | [exmaple_paper_1]() |
| CD3G | transcript | scRNA-seq TPM > 10 | [exmaple_paper_1]() |
| CD4 | positive | FACS sorting, IHC | [exmaple_paper_1]() |
| CD8A | positive | FACS sorting, IHC | [exmaple_paper_1]() |
| PD-1 | positive | Targeted indirectly via anti-PD-L1 therapy to restore T cell | [exmaple_paper_2]() |

## Functional Characteristics

- **Adaptive immune response and tumor infiltration** (T cell receptor signaling)
  - Source: [exmaple_paper_1]()
- **Execute anti-tumor immune responses that are enhanced by TAM modulation** (Cytotoxic T cell response)
  - Source: [exmaple_paper_2]()
- **Cytotoxic effector function and clonal expansion in tumor microenvironment** (T cell receptor signaling)
  - Source: [exmaple_paper_1]()
- **Immune regulation, helper function, and cytokine secretion** (T cell receptor signaling)
  - Source: [exmaple_paper_1]()

## Contexts

### Homo sapiens

**Tissues:** colorectal tumor, adjacent normal tissue, peripheral blood, tumor microenvironment, adjacent normal mucosa

**Diseases:** colorectal adenocarcinoma, colorectal cancer, solid tumors

### Mus musculus

**Tissues:** tumor microenvironment, peripheral blood

**Diseases:** colorectal cancer, solid tumors

## Subpopulations

- [cd4_central_memory_t_cell](cd4_central_memory_t_cell.md)
- [cd4_effector_memory_t_cell](cd4_effector_memory_t_cell.md)
- [cd4_naive_t_cell](cd4_naive_t_cell.md)
- [cd4_positive_t_cell](cd4_positive_t_cell.md)
- [cd4_temra_t_cell](cd4_temra_t_cell.md)
- [cd4_tissue_resident_memory_t_cell](cd4_tissue_resident_memory_t_cell.md)
- [cd8_central_memory_t_cell](cd8_central_memory_t_cell.md)
- [cd8_effector_memory_t_cell](cd8_effector_memory_t_cell.md)
- [cd8_exhausted_t_cell](cd8_exhausted_t_cell.md)
- [cd8_intraepithelial_lymphocyte](cd8_intraepithelial_lymphocyte.md)
- [cd8_naive_t_cell](cd8_naive_t_cell.md)
- [cd8_positive_t_cell](cd8_positive_t_cell.md)
- [cd8_temra_t_cell](cd8_temra_t_cell.md)
- [cd8_tissue_resident_memory_t_cell](cd8_tissue_resident_memory_t_cell.md)
- [double_negative_t_cell](double_negative_t_cell.md)
- [double_positive_t_cell](double_positive_t_cell.md)
- [follicular_helper_t_cell](follicular_helper_t_cell.md)
- [invariant_natural_killer_t_cell](invariant_natural_killer_t_cell.md)
- [mucosal_associated_invariant_t_cell](mucosal_associated_invariant_t_cell.md)
- [regulatory_t_cell](regulatory_t_cell.md)
- [th17_cell](th17_cell.md)
- [th1_like_cell](th1_like_cell.md)

## Related Cell Types

- Parent: [lymphocyte](lymphocyte.md)
- [cd4_central_memory_t_cell](cd4_central_memory_t_cell.md)
- [cd4_effector_memory_t_cell](cd4_effector_memory_t_cell.md)
- [cd4_naive_t_cell](cd4_naive_t_cell.md)
- [cd4_positive_t_cell](cd4_positive_t_cell.md)
- [cd4_temra_t_cell](cd4_temra_t_cell.md)
- [cd4_tissue_resident_memory_t_cell](cd4_tissue_resident_memory_t_cell.md)
- [cd8_central_memory_t_cell](cd8_central_memory_t_cell.md)
- [cd8_effector_memory_t_cell](cd8_effector_memory_t_cell.md)
- [cd8_exhausted_t_cell](cd8_exhausted_t_cell.md)
- [cd8_intraepithelial_lymphocyte](cd8_intraepithelial_lymphocyte.md)
- [cd8_naive_t_cell](cd8_naive_t_cell.md)
- [cd8_positive_t_cell](cd8_positive_t_cell.md)
- [cd8_temra_t_cell](cd8_temra_t_cell.md)
- [cd8_tissue_resident_memory_t_cell](cd8_tissue_resident_memory_t_cell.md)
- [double_negative_t_cell](double_negative_t_cell.md)
- [double_positive_t_cell](double_positive_t_cell.md)
- [follicular_helper_t_cell](follicular_helper_t_cell.md)
- [invariant_natural_killer_t_cell](invariant_natural_killer_t_cell.md)
- [mucosal_associated_invariant_t_cell](mucosal_associated_invariant_t_cell.md)
- [regulatory_t_cell](regulatory_t_cell.md)
- [th17_cell](th17_cell.md)
- [th1_like_cell](th1_like_cell.md)

## References

- Lineage tracking reveals dynamic relationships of T cells in colorectal cancer (2018) [10.1038/s41586-018-0694-x](https://doi.org/10.1038/s41586-018-0694-x)
- An SPP1-SOCS1 pathway constrains interferon responses in tumor-associated macrophages and shapes an immunosuppressive tumor microenvironment (2026) [10.1016/j.immuni.2026.04.001](https://doi.org/10.1016/j.immuni.2026.04.001)
