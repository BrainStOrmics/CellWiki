---
aliases:
- CD8+ stem-like T cell
- TCS
- TCS cells
cl_id: null
display_name: CD8 Stem Like T Cell
parent_type: cd8_t_cell
references:
- paper_id: exmaple_paper_1
  title: Lineage tracking reveals dynamic relationships of T cells in colorectal cancer
standard_name: cd8_stem_like_t_cell
evidence_tier: 4
source_count: 1
positive_markers:
- CD3
- CD8A
- IGFLR1
negative_markers:
- HAVCR2
tissues:
- colorectal tumor
species:
- Homo sapiens
conflicts: []
---

# CD8 Stem Like T Cell

> A CD8+ T cell subset characterized by high IGFLR1 expression and distinct from terminally exhausted cells, likely representing a progenitor or stem-like population.

## Markers

| Marker | Type | Evidence | Source |
|--------|------|----------|--------|
| CD3 | positive | FACS sorting | [exmaple_paper_1]() |
| CD8A | positive | FACS sorting | [exmaple_paper_1]() |
| HAVCR2 | negative | Lower expression compared to TEX cells | [exmaple_paper_1]() |
| IGFLR1 | positive | FACS histogram and MFI quantification | [exmaple_paper_1]() |

## Functional Characteristics

- **Progenitor/stem-like state responsive to IGFL3 ligand stimulation** (IGFLR1 signaling)
  - Source: [exmaple_paper_1]()

## Contexts

### Homo sapiens

**Tissues:** colorectal tumor

**Diseases:** colorectal cancer

## Related Cell Types

- Parent: [cd8_t_cell](cd8_t_cell.md)

## References

- Lineage tracking reveals dynamic relationships of T cells in colorectal cancer (2018) [10.1038/s41586-018-0694-x](https://doi.org/10.1038/s41586-018-0694-x)
