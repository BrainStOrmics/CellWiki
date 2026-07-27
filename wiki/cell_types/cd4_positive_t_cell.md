---
aliases:
- CD4 T cells
- CD4+ T cells
- CD8−CD4+ T cells
- TH cells
- helper T cell
- memory CD4+ T cells
cl_id: null
display_name: CD4 Positive T Cell
parent_type: t_cell
references:
- paper_id: exmaple_paper_1
  title: Lineage tracking reveals dynamic relationships of T cells in colorectal cancer
- paper_id: exmaple_paper_2
  title: An SPP1-SOCS1 pathway constrains interferon responses in tumor-associated
    macrophages and shapes an immunosuppressive tumor microenvironment
standard_name: cd4_positive_t_cell
evidence_tier: 4
source_count: 2
positive_markers:
- CD4
- KI67
negative_markers:
- CD8
tissues:
- colorectal tumor
- lymphoid tissue
- peripheral blood
- tumor microenvironment
- tumor tissue
species:
- Homo sapiens
- Mus musculus
conflicts:
- 'CD4: positive vs transcript'
---

# CD4 Positive T Cell

> CD4-positive T helper cells isolated from PBMCs and tumor tissues, used for activation and cytokine production assays.

## Markers

| Marker | Type | Evidence | Source |
|--------|------|----------|--------|
| CD4 | transcript | scRNA-seq TPM > 30 | [exmaple_paper_1]() |
| CD4 ⚠️ CONFLICT | positive | FACS gating (7AAD−CD3+CD4+CD25−/int) | [exmaple_paper_1]() |
| CD4 | positive | flow cytometry and scRNA-seq | [exmaple_paper_2]() |
| CD8 | negative | FACS and scRNA-seq classification | [exmaple_paper_1]() |
| Cd4 | positive | Standard surface marker used for identification | [exmaple_paper_2]() |
| IFNG | transcript | scRNA-seq | [exmaple_paper_2]() |
| Ki67 | positive | Used to assess proliferation in co-culture assays | [exmaple_paper_2]() |

### Marker Conflicts

The following markers have conflicting reports across papers:

- **CD4**: conflicting marker types detected

## Functional Characteristics

- **Helper functions and cytokine production (e.g., IFNγ)** (T cell activation and cytokine signaling)
  - Source: [exmaple_paper_1]()
- **Helper T cells that increase in frequency and IFN-γ production upon SPP1 deletion in TAMs** (T cell activation, interferon-gamma response)
  - Source: [exmaple_paper_2]()
- **Differentiate into Th1-like or regulatory subsets depending on TAM-derived signals** (T cell differentiation)
  - Source: [exmaple_paper_2]()
- **Secrete IFN-γ to activate macrophages and enhance anti-tumor immunity** (cytokine signaling)
  - Source: [exmaple_paper_2]()

## Contexts

### Homo sapiens

**Tissues:** colorectal tumor, peripheral blood, tumor tissue, tumor microenvironment, lymphoid tissue

**Diseases:** colorectal adenocarcinoma, colorectal cancer

### Mus musculus

**Tissues:** tumor tissue, tumor microenvironment, lymphoid tissue

**Diseases:** colorectal cancer

## Subpopulations

- [regulatory_t_cell](regulatory_t_cell.md)
- [th1_like_cd4_t_cell](th1_like_cd4_t_cell.md)

## Related Cell Types

- Parent: [t_cell](t_cell.md)
- [regulatory_t_cell](regulatory_t_cell.md)
- [th1_like_cd4_t_cell](th1_like_cd4_t_cell.md)

## References

- Lineage tracking reveals dynamic relationships of T cells in colorectal cancer (2018) [10.1038/s41586-018-0694-x](https://doi.org/10.1038/s41586-018-0694-x)
- An SPP1-SOCS1 pathway constrains interferon responses in tumor-associated macrophages and shapes an immunosuppressive tumor microenvironment (2026) [10.1016/j.immuni.2026.04.001](https://doi.org/10.1016/j.immuni.2026.04.001)
