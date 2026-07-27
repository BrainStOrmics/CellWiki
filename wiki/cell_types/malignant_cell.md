---
aliases:
- Cancer Cell
- MC38 cells
- Malignant cells
- cancer cells
- cancer_cell
- malignant cells
- tumor cells
cl_id: CL:0001064
display_name: Malignant Cell
parent_type: null
references:
- paper_id: exmaple_paper_2
  title: An SPP1-SOCS1 pathway constrains interferon responses in tumor-associated
    macrophages and shapes an immunosuppressive tumor microenvironment
standard_name: malignant_cell
evidence_tier: 4
source_count: 1
positive_markers: []
negative_markers: []
tissues:
- colorectal tumor
- tumor tissue
species:
- Homo sapiens
- Mus musculus
conflicts: []
---

# Malignant Cell

> Neoplastic cells within the tumor that exhibit enhanced interferon-stimulated gene and MHC class I expression when TAM SPP1 is deleted.

## Markers

| Marker | Type | Evidence | Source |
|--------|------|----------|--------|
| ISG | transcript | scRNA-seq | [exmaple_paper_2]() |
| Mmp13 | transcript | Expression reduced by Spp1-KO TAMs and restored by recombina | [exmaple_paper_2]() |

## Functional Characteristics

- **Tumor cells that show upregulated ISG and MHC class I signatures upon SPP1 deletion in TAMs** (interferon response, antigen presentation)
  - Source: [exmaple_paper_2]()
- **Upregulate immunogenic signatures in response to SPP1-deficient macrophage signaling** (antigen presentation)
  - Source: [exmaple_paper_2]()
- **Proliferate and form tumors in vivo models** (tumor growth)
  - Source: [exmaple_paper_2]()

## Contexts

### Homo sapiens

**Tissues:** tumor tissue

**Diseases:** colorectal cancer, breast invasive carcinoma, renal cell carcinoma

### Mus musculus

**Tissues:** tumor tissue, colorectal tumor

**Diseases:** colorectal cancer, breast invasive carcinoma, renal cell carcinoma

## References

- An SPP1-SOCS1 pathway constrains interferon responses in tumor-associated macrophages and shapes an immunosuppressive tumor microenvironment (2026) [10.1016/j.immuni.2026.04.001](https://doi.org/10.1016/j.immuni.2026.04.001)
