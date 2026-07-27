---
aliases:
- CD8_C08
- CD8_C08-SLC4A10
- MAIT
- mucosal-associated invariant T (MAIT) cells
- mucosal-associated invariant T cell
cl_id: CL:0000940
display_name: Mucosal Associated Invariant T Cell
parent_type: t_cell
references:
- paper_id: exmaple_paper_1
  title: Lineage tracking reveals dynamic relationships of T cells in colorectal cancer
standard_name: mucosal_associated_invariant_t_cell
evidence_tier: 4
source_count: 1
positive_markers:
- CD8
- SLC4A10
negative_markers: []
tissues:
- adjacent normal mucosa
- colorectal tumor
- colorectal tumour
- peripheral blood
species:
- Homo sapiens
conflicts: []
---

# Mucosal Associated Invariant T Cell

> Innate-like mucosal-associated invariant T cells identified within the T cell repertoire.

## Markers

| Marker | Type | Evidence | Source |
|--------|------|----------|--------|
| CD8 | positive | In silico classification (71/102 cells) | [exmaple_paper_1]() |
| SLC4A10 | positive | cluster-specific gene expression | [exmaple_paper_1]() |
| SLC4A10 | positive | scRNA-seq | [exmaple_paper_1]() |
| TRAJ12 | transcript | TCR assembly (TraCeR) | [exmaple_paper_1]() |
| TRAJ20 | transcript | TCR assembly (TraCeR) | [exmaple_paper_1]() |
| TRAJ33 | transcript | TCR assembly (TraCeR) | [exmaple_paper_1]() |
| TRAV1-2 | transcript | TCR assembly (TraCeR) | [exmaple_paper_1]() |

## Functional Characteristics

- **Innate-like T cell subset identified in scRNA-seq** (mucosal immunity)
  - Source: [exmaple_paper_1]()
- **Innate-like immune response to microbial metabolites** (MR1-restricted antigen recognition)
  - Source: [exmaple_paper_1]()
- **Innate-like immune response with distinct TCR repertoire** (Innate-like T cell activation)
  - Source: [exmaple_paper_1]()
- **Innate-like T cells responding to microbial metabolites** (MR1-restricted antigen recognition)
  - Source: [exmaple_paper_1]()

## Contexts

### Homo sapiens

**Tissues:** colorectal tumour, adjacent normal mucosa, peripheral blood, colorectal tumor

**Diseases:** colorectal cancer, colorectal adenocarcinoma

## Related Cell Types

- Parent: [t_cell](t_cell.md)

## References

- Lineage tracking reveals dynamic relationships of T cells in colorectal cancer (2018) [10.1038/s41586-018-0694-x](https://doi.org/10.1038/s41586-018-0694-x)
