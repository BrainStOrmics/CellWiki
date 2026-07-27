---
aliases:
- CD4+CD25+FOXP3+ T cells
- CD4+CD25hi T cells
- CD4_C10-FOXP3
- CD4_C11-IL10
- CD4_C12-CTLA4
- RORγ+ Treg cells
- T regulatory (T_reg) cells
- T regulatory cell (Treg)
- Treg
- Tregs
- iTreg
- induced Treg
- natural Treg
- regulatory T cell
- regulatory T cells
cl_id: CL:0000815
display_name: Regulatory T Cell
parent_type: cd4_t_cell
references:
- paper_id: exmaple_paper_1
  title: Lineage tracking reveals dynamic relationships of T cells in colorectal cancer
- paper_id: exmaple_paper_2
  title: An SPP1-SOCS1 pathway constrains interferon responses in tumor-associated
    macrophages and shapes an immunosuppressive tumor microenvironment
standard_name: regulatory_t_cell
evidence_tier: 4
source_count: 2
positive_markers:
- CD25
- CD3
- CD4
- CTLA4
- FOXP3
- IL10
- IL2RA
- RORC
- SATB1
- TIGIT
- TNFRSF9
negative_markers: []
tissues:
- adjacent normal mucosa
- colorectal tumor
- colorectal tumour
- in vitro culture
- normal mucosa
- peripheral blood
- spleen (in vitro derived)
- tumor
- tumor microenvironment
- tumor tissue
species:
- Homo sapiens
- Mus musculus
conflicts:
- 'IL10: positive vs transcript'
---

# Regulatory T Cell

> A subset of CD4+ T cells that suppress immune responses and are reduced in frequency following SPP1 ablation in TAMs.

## Markers

| Marker | Type | Evidence | Source |
|--------|------|----------|--------|
| CD25 | positive | FACS sorting strategy | [exmaple_paper_1]() |
| CD25 | positive | FACS gating (CD25hi) | [exmaple_paper_1]() |
| CD3 | positive | Multi-colour IHC | [exmaple_paper_1]() |
| CD4 | positive | FACS gating (7AAD−CD3+CD4+CD25hi) | [exmaple_paper_1]() |
| CD4 | positive | Multi-colour IHC | [exmaple_paper_1]() |
| CTLA4 | positive | Cluster designation | [exmaple_paper_1]() |
| Cd25 | positive | Surface marker used for FACS identification | [exmaple_paper_2]() |
| Cd25 | positive | polarization protocol with IL-2 | [exmaple_paper_2]() |
| Cd25 | positive | flow cytometry gating | [exmaple_paper_2]() |
| Cd4 | positive | flow cytometry gating (NIR-CD4+CD25+FOXP3+) | [exmaple_paper_2]() |
| FOXP3 | positive | Cluster designation | [exmaple_paper_1]() |
| FOXP3 | positive | Cluster naming and IHC | [exmaple_paper_1]() |
| FOXP3 | positive | Multiplex IHC validation | [exmaple_paper_1]() |
| FOXP3 | positive | Multi-colour IHC | [exmaple_paper_1]() |
| FOXP3 | positive | canonical markers | [exmaple_paper_2]() |
| Foxp3 | positive | Transcription factor defining regulatory lineage | [exmaple_paper_2]() |
| Foxp3 | positive | polarization protocol with TGF-β | [exmaple_paper_2]() |
| Foxp3 | positive | intracellular staining | [exmaple_paper_2]() |
| IL10 | positive | Cluster designation | [exmaple_paper_1]() |
| IL10 ⚠️ CONFLICT | transcript | Cluster naming | [exmaple_paper_1]() |
| IL2RA | positive | FACS sorting (CD25) | [exmaple_paper_1]() |
| RORC | positive | Multiplex IHC validation (RORγ protein) | [exmaple_paper_1]() |
| SATB1 | positive | Fig. 2e, Supplementary Table 8 | [exmaple_paper_1]() |
| TIGIT | positive | Fig. 2e | [exmaple_paper_1]() |
| TNFRSF9 | positive | Fig. 2e | [exmaple_paper_1]() |

### Marker Conflicts

The following markers have conflicting reports across papers:

- **IL10**: conflicting marker types detected

## Functional Characteristics

- **Immune suppression with clonal exclusivity and developmental links to Th17** (immune tolerance)
  - Source: [exmaple_paper_1]()
- **Maintains immune homeostasis and suppresses effector responses** (Immune tolerance)
  - Source: [exmaple_paper_1]()
- **Shares TCR clonotypes with blood and normal mucosa T cells** (T cell migration)
  - Source: [exmaple_paper_1]()
- **Immune suppression and tolerance maintenance** (Immunosuppressive cytokine signaling)
  - Source: [exmaple_paper_1]()
- **Immune suppression and maintenance of peripheral tolerance** (TGF-beta and IL-2 signaling)
  - Source: [exmaple_paper_1]()
- **Immunosuppressive T cells whose frequency decreases when SPP1 is deleted in TAMs** (immune tolerance)
  - Source: [exmaple_paper_2]()
- **Suppress effector T cell responses and maintain immune tolerance** (immune suppression, TGF-beta signaling)
  - Source: [exmaple_paper_2]()
  - Source: [exmaple_paper_2]()
- **Differentiation is not increased by Spp1-KO TAMs** (T cell differentiation)
  - Source: [exmaple_paper_2]()
- **Suppress anti-tumor immunity; can be converted from conventional CD4+ T cells via PD-1 signaling** (PD-1 signaling pathway)
  - Source: [exmaple_paper_2]()
- **Mediate immune suppression and tolerance** (immune regulation)
  - Source: [exmaple_paper_2]()

## Contexts

### Homo sapiens

**Tissues:** peripheral blood, adjacent normal mucosa, colorectal tumour, colorectal tumor, normal mucosa, tumor tissue, tumor microenvironment, in vitro culture, tumor, spleen (in vitro derived)

**Diseases:** colorectal cancer, colorectal adenocarcinoma, cancer

### Mus musculus

**Tissues:** tumor tissue, tumor microenvironment, in vitro culture, tumor, spleen (in vitro derived)

**Diseases:** colorectal cancer, cancer

## Subpopulations

- [CD4_C10-FOXP3](cd4_c10-foxp3.md)
- [CD4_C11-IL10](cd4_c11-il10.md)
- [CD4_C12-CTLA4](cd4_c12-ctla4.md)

## Related Cell Types

- Parent: [cd4_t_cell](cd4_t_cell.md)
- [cd4_c10-foxp3](cd4_c10-foxp3.md)
- [cd4_c11-il10](cd4_c11-il10.md)
- [cd4_c12-ctla4](cd4_c12-ctla4.md)

## References

- Lineage tracking reveals dynamic relationships of T cells in colorectal cancer (2018) [10.1038/s41586-018-0694-x](https://doi.org/10.1038/s41586-018-0694-x)
- An SPP1-SOCS1 pathway constrains interferon responses in tumor-associated macrophages and shapes an immunosuppressive tumor microenvironment (2026) [10.1016/j.immuni.2026.04.001](https://doi.org/10.1016/j.immuni.2026.04.001)
