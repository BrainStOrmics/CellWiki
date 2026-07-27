---
aliases:
- CD4_C09
- IFN-γ+ CD4+ T cells
- T helper 1-like cells
- TH1-like
- TH1-like cells
- Th1-like cells
cl_id: null
display_name: Th1 Like Cell
parent_type: cd4_positive_cd8_negative_t_cell
references:
- paper_id: exmaple_paper_1
  title: Lineage tracking reveals dynamic relationships of T cells in colorectal cancer
- paper_id: exmaple_paper_2
  title: An SPP1-SOCS1 pathway constrains interferon responses in tumor-associated
    macrophages and shapes an immunosuppressive tumor microenvironment
standard_name: th1_like_cell
evidence_tier: 4
source_count: 2
positive_markers:
- BHLHE40
- CD4
- CXCL13
- CXCR3
- HAVCR2
- IFNG
negative_markers: []
tissues:
- colorectal tumor
- tumor microenvironment
species:
- Homo sapiens
- Mus musculus
conflicts: []
---

# Th1 Like Cell

> A CD4+ T cell subset producing IFN-γ that drives macrophage activation and promotes an immunostimulatory tumor microenvironment.

## Markers

| Marker | Type | Evidence | Source |
|--------|------|----------|--------|
| BHLHE40 | positive | TCGA marker gene set | [exmaple_paper_1]() |
| BHLHE40 | positive | scRNA-seq | [exmaple_paper_1]() |
| CD4 | positive | TCGA marker gene set | [exmaple_paper_1]() |
| CXCL13 | positive | TCGA marker gene set | [exmaple_paper_1]() |
| CXCL13 | positive | scRNA-seq | [exmaple_paper_1]() |
| CXCR3 | positive | TCGA marker gene set | [exmaple_paper_1]() |
| Cd4 | positive | Lineage-defining surface marker | [exmaple_paper_2]() |
| HAVCR2 | positive | TCGA marker gene set | [exmaple_paper_1]() |
| IFNG | positive | TCGA marker gene set | [exmaple_paper_1]() |
| Ifng | positive | Intracellular cytokine staining and transcript analysis | [exmaple_paper_2]() |

## Functional Characteristics

- **Interferon-gamma production and cytotoxic helper activity** (IFN-gamma signaling pathway)
  - Source: [exmaple_paper_1]()
- **Tumor-infiltrating helper cells with TH1 polarization and B cell recruitment** (CXCL13 signaling)
  - Source: [exmaple_paper_1]()
- **Secrete IFN-γ to activate macrophages and promote an immunogenic TME** (interferon signaling)
  - Source: [exmaple_paper_2]()
- **Differentiate from naive CD4+ T cells upon TAM interaction** (T cell differentiation)
  - Source: [exmaple_paper_2]()

## Contexts

### Homo sapiens

**Tissues:** colorectal tumor

**Diseases:** colorectal cancer

### Mus musculus

**Tissues:** tumor microenvironment

**Diseases:** colorectal cancer

## Related Cell Types

- Parent: [cd4_positive_cd8_negative_t_cell](cd4_positive_cd8_negative_t_cell.md)

## References

- Lineage tracking reveals dynamic relationships of T cells in colorectal cancer (2018) [10.1038/s41586-018-0694-x](https://doi.org/10.1038/s41586-018-0694-x)
- An SPP1-SOCS1 pathway constrains interferon responses in tumor-associated macrophages and shapes an immunosuppressive tumor microenvironment (2026) [10.1016/j.immuni.2026.04.001](https://doi.org/10.1016/j.immuni.2026.04.001)
