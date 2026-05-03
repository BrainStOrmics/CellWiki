---
aliases:
- CD4−CD8− (double negative) T cells
- double negative T cells
cl_id: CL:0002489
display_name: Double Negative T Cell
parent_type: t_cell
references:
- paper_id: exmaple_paper_1
  title: Lineage tracking reveals dynamic relationships of T cells in colorectal cancer
standard_name: double_negative_t_cell
---

# Double Negative T Cell

> T cells lacking both CD4 and CD8 co-receptors identified in silico from single-cell transcriptomic data.

## Markers

| Marker | Type | Evidence | Source |
|--------|------|----------|--------|
| CD3D | transcript | scRNA-seq TPM > 10 | [exmaple_paper_1]() |
| CD4 | negative | scRNA-seq TPM < 3 | [exmaple_paper_1]() |
| CD8A | negative | scRNA-seq TPM < 3 | [exmaple_paper_1]() |

## Functional Characteristics

- **Atypical T cell subset with unclear functional role in CRC** (Unknown)
  - Source: [exmaple_paper_1]()

## Contexts

### Homo sapiens

**Tissues:** colorectal tumor

**Diseases:** colorectal adenocarcinoma

## Related Cell Types

- Parent: [t_cell](t_cell.md)

## References

- Lineage tracking reveals dynamic relationships of T cells in colorectal cancer (2018) [10.1038/s41586-018-0694-x](https://doi.org/10.1038/s41586-018-0694-x)
