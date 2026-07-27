---
aliases:
- CD4+ TMEM
- CD4+ memory T cell
- TMEM
- memory CD4+ T cells
cl_id: CL:0000813
display_name: CD4 Memory T Cell
parent_type: cd4_t_cell
references:
- paper_id: exmaple_paper_1
  title: Lineage tracking reveals dynamic relationships of T cells in colorectal cancer
standard_name: cd4_memory_t_cell
evidence_tier: 4
source_count: 1
positive_markers:
- CCR7
- CD25
- CD3
- CD4
- IGFLR1
negative_markers:
- PTPRC
tissues:
- colorectal tumor
- peripheral blood
species:
- Homo sapiens
conflicts: []
---

# CD4 Memory T Cell

> Memory CD4+ T cells that upregulate IGFLR1 upon activation and respond to IGFL3 with enhanced co-stimulation and cytokine production.

## Markers

| Marker | Type | Evidence | Source |
|--------|------|----------|--------|
| CCR7 | positive | FACS gating (CCR7+/-) | [exmaple_paper_1]() |
| CD25 | positive | Induced by IGFL3, Fig. 4b-e | [exmaple_paper_1]() |
| CD3 | positive | FACS sorting | [exmaple_paper_1]() |
| CD4 | positive | FACS sorting | [exmaple_paper_1]() |
| IGFLR1 | positive | Fig. 4a, Extended Data Fig. 11c-e | [exmaple_paper_1]() |
| PTPRC | negative | FACS gating (CD45RA-) | [exmaple_paper_1]() |

## Functional Characteristics

- **IGFLR1 acts as a co-stimulatory receptor enhancing CD25 and IFNγ production upon IGFL3 binding** (Co-stimulatory signaling)
  - Source: [exmaple_paper_1]()
- **Antigen-experienced state capable of rapid recall responses** (Memory T cell maintenance)
  - Source: [exmaple_paper_1]()

## Contexts

### Homo sapiens

**Tissues:** peripheral blood, colorectal tumor

**Diseases:** colorectal cancer

## Related Cell Types

- Parent: [cd4_t_cell](cd4_t_cell.md)

## References

- Lineage tracking reveals dynamic relationships of T cells in colorectal cancer (2018) [10.1038/s41586-018-0694-x](https://doi.org/10.1038/s41586-018-0694-x)
