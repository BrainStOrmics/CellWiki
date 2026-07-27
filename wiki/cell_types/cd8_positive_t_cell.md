---
aliases:
- CD8 T cells
- CD8+ T cells
- CD8+CD4− T cells
- cytotoxic T (TC) cells
- cytotoxic T cell
- cytotoxic T cells
cl_id: null
display_name: CD8 Positive T Cell
parent_type: t_cell
references:
- paper_id: exmaple_paper_1
  title: Lineage tracking reveals dynamic relationships of T cells in colorectal cancer
- paper_id: exmaple_paper_2
  title: An SPP1-SOCS1 pathway constrains interferon responses in tumor-associated
    macrophages and shapes an immunosuppressive tumor microenvironment
standard_name: cd8_positive_t_cell
evidence_tier: 4
source_count: 2
positive_markers:
- CD8
- CD8A
- GZMB
- KI67
negative_markers:
- CD4
tissues:
- colorectal tumor
- peripheral blood
- tumor microenvironment
- tumor tissue
species:
- Homo sapiens
- Mus musculus
conflicts:
- 'CD8A: positive vs transcript'
---

# CD8 Positive T Cell

> CD8-positive T lymphocytes sorted for scRNA-seq and in vitro chronic stimulation assays to study exhaustion and cytotoxicity.

## Markers

| Marker | Type | Evidence | Source |
|--------|------|----------|--------|
| CD4 | negative | FACS and scRNA-seq classification | [exmaple_paper_1]() |
| CD8 | positive | FACS gating (7AAD−CD3+CD8+) | [exmaple_paper_1]() |
| CD8A | transcript | scRNA-seq TPM > 30 | [exmaple_paper_1]() |
| CD8A ⚠️ CONFLICT | positive | flow cytometry and scRNA-seq | [exmaple_paper_2]() |
| CD8B | transcript | scRNA-seq TPM > 30 | [exmaple_paper_1]() |
| Cd8a | positive | Standard surface marker for cytotoxic T cells | [exmaple_paper_2]() |
| GZMB | transcript | scRNA-seq | [exmaple_paper_2]() |
| Gzmb | positive | Expressed in cytotoxic subset; frequency unchanged in Spp1-K | [exmaple_paper_2]() |
| Ki67 | positive | Proliferation marker assessed by FACS | [exmaple_paper_2]() |

### Marker Conflicts

The following markers have conflicting reports across papers:

- **CD8A**: conflicting marker types detected

## Functional Characteristics

- **Direct tumor cell killing and cytotoxicity** (Cytotoxic granule exocytosis)
  - Source: [exmaple_paper_1]()
- **Cytotoxic T cells that increase in frequency and granzyme B expression upon SPP1 deletion in TAMs** (cytotoxicity, T cell activation)
  - Source: [exmaple_paper_2]()
- **Mediate direct cytotoxic killing of tumor cells** (cell-mediated cytotoxicity)
  - Source: [exmaple_paper_2]()
- **Recruited to tumors via TAM-derived chemokines** (chemotaxis)
  - Source: [exmaple_paper_2]()

## Contexts

### Homo sapiens

**Tissues:** colorectal tumor, peripheral blood, tumor tissue, tumor microenvironment

**Diseases:** colorectal adenocarcinoma, colorectal cancer

### Mus musculus

**Tissues:** tumor tissue, tumor microenvironment

**Diseases:** colorectal cancer

## Subpopulations

- [chronically_stimulated_cd8_t_cell](chronically_stimulated_cd8_t_cell.md)
- [mucosal_associated_invariant_t_cell](mucosal_associated_invariant_t_cell.md)
- [proliferative_exhausted_cd8_t_cell](proliferative_exhausted_cd8_t_cell.md)

## Related Cell Types

- Parent: [t_cell](t_cell.md)
- [chronically_stimulated_cd8_t_cell](chronically_stimulated_cd8_t_cell.md)
- [mucosal_associated_invariant_t_cell](mucosal_associated_invariant_t_cell.md)
- [proliferative_exhausted_cd8_t_cell](proliferative_exhausted_cd8_t_cell.md)

## References

- Lineage tracking reveals dynamic relationships of T cells in colorectal cancer (2018) [10.1038/s41586-018-0694-x](https://doi.org/10.1038/s41586-018-0694-x)
- An SPP1-SOCS1 pathway constrains interferon responses in tumor-associated macrophages and shapes an immunosuppressive tumor microenvironment (2026) [10.1016/j.immuni.2026.04.001](https://doi.org/10.1016/j.immuni.2026.04.001)
