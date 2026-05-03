---
aliases:
- CD4 Naive T Cell
- CD4+ naive T cell
- CD4_C01
- CD4_C01-CCR7
- CD8_C01
- CD8_C01-CCR7
- Naive T Cell
- TN
- T_N
- cd4_naive_t_cell
- naive (T_N) T cells
- naive CD4+ T cells
- naive CD8+ T cells
- naive T cell
- naive T cells
- naive_t_cell
cl_id: CL:0000898
display_name: CD8 Naive T Cell
parent_type: cd8_t_cell
references:
- paper_id: exmaple_paper_1
  title: Lineage tracking reveals dynamic relationships of T cells in colorectal cancer
- paper_id: exmaple_paper_2
  title: An SPP1-SOCS1 pathway constrains interferon responses in tumor-associated
    macrophages and shapes an immunosuppressive tumor microenvironment
standard_name: cd8_naive_t_cell
---

# CD8 Naive T Cell

> Unactivated T lymphocytes isolated from mouse spleen for in vitro differentiation and proliferation assays.

## Markers

| Marker | Type | Evidence | Source |
|--------|------|----------|--------|
| CCR7 | positive | Cluster naming convention and standard naive T cell biology | [exmaple_paper_1]() |
| CCR7 | positive | scRNA-seq | [exmaple_paper_1]() |
| CCR7 | positive | Cluster designation | [exmaple_paper_1]() |
| CCR7 | positive | FACS gating (CCR7+) | [exmaple_paper_1]() |
| CD3 | positive | FACS sorting | [exmaple_paper_1]() |
| CD4 | positive | FACS sorting | [exmaple_paper_1]() |
| CD45RA | positive | FACS | [exmaple_paper_1]() |
| Cd3 | positive | isolation kit and flow cytometry | [exmaple_paper_2]() |
| Cd4 | positive | subset isolation | [exmaple_paper_2]() |
| Cd8a | positive | subset isolation | [exmaple_paper_2]() |
| LEF1 | positive | scRNA-seq | [exmaple_paper_1]() |
| PTPRC | positive | FACS gating (CD45RA+) | [exmaple_paper_1]() |

## Functional Characteristics

- **Baseline circulating T cell state with low tissue infiltration** (lymphocyte trafficking)
  - Source: [exmaple_paper_1]()
- **Antigen-naive state with low proliferation and migration potential** (Wnt signaling)
  - Source: [exmaple_paper_1]()
- **Circulating naive CD4+ T cell pool** (lymphocyte homeostasis)
  - Source: [exmaple_paper_1]()
- **Antigen-inexperienced helper cells with lymphoid homing potential** (Chemokine signaling)
  - Source: [exmaple_paper_1]()
- **Antigen-inexperienced state ready for primary activation** (Naive T cell homeostasis)
  - Source: [exmaple_paper_1]()
- **Precursor state for clonal expansion and tissue migration** (T cell development)
  - Source: [exmaple_paper_1]()
- **Serve as precursors for in vitro polarization into effector or regulatory subsets** (T cell receptor signaling)
  - Source: [exmaple_paper_2]()

## Contexts

### Homo sapiens

**Tissues:** peripheral blood, colorectal tumor, adjacent normal mucosa, lymphoid tissue

**Diseases:** colorectal cancer

### Mus musculus

**Tissues:** spleen

## Subpopulations

- [naive_cd4_t_cell](naive_cd4_t_cell.md)
- [naive_cd8_t_cell](naive_cd8_t_cell.md)

## Related Cell Types

- Parent: [cd8_t_cell](cd8_t_cell.md)
- [naive_cd4_t_cell](naive_cd4_t_cell.md)
- [naive_cd8_t_cell](naive_cd8_t_cell.md)

## References

- Lineage tracking reveals dynamic relationships of T cells in colorectal cancer (2018) [10.1038/s41586-018-0694-x](https://doi.org/10.1038/s41586-018-0694-x)
- An SPP1-SOCS1 pathway constrains interferon responses in tumor-associated macrophages and shapes an immunosuppressive tumor microenvironment (2026) [10.1016/j.immuni.2026.04.001](https://doi.org/10.1016/j.immuni.2026.04.001)
