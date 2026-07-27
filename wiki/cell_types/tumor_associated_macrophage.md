---
aliases:
- SPP1+ TAMs
- Spp1-KO TAMs
- TAMs
- Tumor-associated macrophages (TAMs)
- WT TAMs
- tumor-associated macrophages
- tumor-infiltrating macrophages
cl_id: null
display_name: Tumor Associated Macrophage
parent_type: macrophage
references:
- paper_id: exmaple_paper_2
  title: An SPP1-SOCS1 pathway constrains interferon responses in tumor-associated
    macrophages and shapes an immunosuppressive tumor microenvironment
standard_name: tumor_associated_macrophage
evidence_tier: 4
source_count: 1
positive_markers:
- CD11B
- CD45
- SOCS1
- SPP1
- STAT1
- TRIM21
negative_markers: []
tissues:
- CT26 tumor
- MC38 subcutaneous tumor
- breast tumor
- colon tumor
- colorectal tumor
- hepatocellular carcinoma
- human tumor
- lung tumor
- pancreatic tumor
- peritoneal tumor
- renal cell carcinoma
- solid tumors
- subcutaneous tumor
- tumor
- tumor microenvironment
- tumor tissue
species:
- Homo sapiens
- Mus musculus
conflicts:
- 'SPP1: positive vs transcript'
- 'STAT1: positive vs transcript'
- 'TRIM21: positive vs transcript'
---

# Tumor Associated Macrophage

> Macrophages residing in the tumor microenvironment that exhibit heterogeneous phenotypes and can suppress anti-tumor immunity.

## Markers

| Marker | Type | Evidence | Source |
|--------|------|----------|--------|
| Cd11b | positive | flow cytometry sorting | [exmaple_paper_2]() |
| Cd11b | positive | flow cytometry gating | [exmaple_paper_2]() |
| Cd45 | positive | flow cytometry sorting | [exmaple_paper_2]() |
| Cd45 | positive | flow cytometry gating (DAPI-CD45+CD11B+F4/80+) | [exmaple_paper_2]() |
| Cxcl10 | transcript | Upregulated in Spp1-KO TAMs after IFN-γ treatment | [exmaple_paper_2]() |
| Cxcl9 | transcript | Upregulated in Spp1-KO TAMs after IFN-γ treatment | [exmaple_paper_2]() |
| Isg15 | transcript | Upregulated in Spp1-KO TAMs after IFN-γ treatment | [exmaple_paper_2]() |
| Nos2 | transcript | Upregulated in Spp1-KO TAMs after IFN-γ treatment | [exmaple_paper_2]() |
| SOCS1 | positive | Stabilized by intracellular SPP1-TRIM21 complex to constrain | [exmaple_paper_2]() |
| SPP1 | transcript | scRNA-seq and bulk RNA-seq | [exmaple_paper_2]() |
| SPP1 ⚠️ CONFLICT | positive | High expression in colorectal and lung cancer models; low in | [exmaple_paper_2]() |
| STAT1 | transcript | Part of the IFN-γ-STAT1-ISG pathway modulated by SPP1 | [exmaple_paper_2]() |
| Socs1 | transcript | mRNA increases in Spp1-KO TAMs upon IFN-γ stimulation | [exmaple_paper_2]() |
| Socs1 | transcript | Western blot and pathway analysis | [exmaple_paper_2]() |
| Spp1 | positive | Highly expressed in TAMs across multiple cancer types; knock | [exmaple_paper_2]() |
| Spp1 ⚠️ CONFLICT | transcript | qPCR quantification | [exmaple_paper_2]() |
| Spp1 | transcript | scRNA-seq and in vitro mRNA transfection | [exmaple_paper_2]() |
| Stat1 | positive | Elevated expression and phosphorylation in Spp1-KO TAMs | [exmaple_paper_2]() |
| Stat1 ⚠️ CONFLICT | transcript | Western blot and phosphorylation analysis | [exmaple_paper_2]() |
| Trim21 | positive | Interacts with SPP1 and SOCS1 in TAMs | [exmaple_paper_2]() |
| Trim21 ⚠️ CONFLICT | transcript | Western blot and Co-IP | [exmaple_paper_2]() |

### Marker Conflicts

The following markers have conflicting reports across papers:

- **SPP1**: conflicting marker types detected
- **Spp1**: conflicting marker types detected
- **Trim21**: conflicting marker types detected
- **Stat1**: conflicting marker types detected

## Functional Characteristics

- **Suppress antitumor immunity and reduce responses to immune checkpoint blockade** (immunosuppression)
  - Source: [exmaple_paper_2]()
- **Buffers interferon signaling by competitively binding TRIM21 to stabilize SOCS1** (IFN-γ-STAT1-ISG signaling)
  - Source: [exmaple_paper_2]()
- **Suppresses T cell infiltration and cytotoxic functions to maintain immunosuppressive TME** (immune evasion)
  - Source: [exmaple_paper_2]()
- **Secretes chemokines to recruit and activate lymphocytes** (chemokine signaling)
  - Source: [exmaple_paper_2]()
- **Buffer excessive interferon signaling to prevent hyperinflammation** (IFN-γ-STAT1-ISG)
  - Source: [exmaple_paper_2]()
- **Shape an immunosuppressive tumor microenvironment and mediate immune checkpoint therapy resistance** (Immune suppression)
  - Source: [exmaple_paper_2]()
- **Constrain interferon responses via SPP1-SOCS1 pathway to shape an immunosuppressive tumor microenvironment** (SPP1-SOCS1 signaling)
  - Source: [exmaple_paper_2]()
- **Constrain interferon signaling via the SPP1-SOCS1 axis** (SPP1-SOCS1 pathway)
  - Source: [exmaple_paper_2]()
- **Shape an immunosuppressive tumor microenvironment** (immunosuppression, SPP1-SOCS1-STAT1 axis)
  - Source: [exmaple_paper_2]()
  - Source: [exmaple_paper_2]()
- **Modulate T cell polarization and recruitment** (T cell regulation)
  - Source: [exmaple_paper_2]()
- **Constrain interferon responses in the tumor microenvironment** (SPP1-SOCS1 pathway)
  - Source: [exmaple_paper_2]()
- **Regulate STAT1 stability via ubiquitination** (TRIM21-mediated ubiquitin-proteasome pathway)
  - Source: [exmaple_paper_2]()

## Contexts

### Homo sapiens

**Tissues:** tumor tissue, colorectal tumor, breast tumor, renal cell carcinoma, lung tumor, tumor microenvironment, solid tumors, hepatocellular carcinoma, pancreatic tumor, subcutaneous tumor, peritoneal tumor, colon tumor, tumor, MC38 subcutaneous tumor, CT26 tumor, human tumor

**Diseases:** colorectal cancer, breast invasive carcinoma, renal cell carcinoma, lung cancer, cancer, lung adenocarcinoma, multiple myeloma, lymphoid cancers, hepatocellular carcinoma, pancreatic cancer, non-small cell lung cancer, colon carcinoma, lung carcinoma

### Mus musculus

**Tissues:** tumor tissue, colorectal tumor, breast tumor, renal cell carcinoma, lung tumor, tumor microenvironment, solid tumors, hepatocellular carcinoma, pancreatic tumor, subcutaneous tumor, peritoneal tumor, colon tumor, tumor, MC38 subcutaneous tumor, CT26 tumor, human tumor

**Diseases:** colorectal cancer, breast invasive carcinoma, renal cell carcinoma, lung cancer, cancer, lung adenocarcinoma, multiple myeloma, lymphoid cancers, hepatocellular carcinoma, pancreatic cancer, non-small cell lung cancer, colon carcinoma, lung carcinoma

## Subpopulations

- [c1qc_positive_tumor_associated_macrophage](c1qc_positive_tumor_associated_macrophage.md)
- [cxcl10_positive_tumor_associated_macrophage](cxcl10_positive_tumor_associated_macrophage.md)
- [lyve1_positive_tumor_associated_macrophage](lyve1_positive_tumor_associated_macrophage.md)
- [macrophage_signature_tumor_associated_macrophage](macrophage_signature_tumor_associated_macrophage.md)
- [proliferating_tumor_associated_macrophage](proliferating_tumor_associated_macrophage.md)
- [spp1_positive_tumor_associated_macrophage](spp1_positive_tumor_associated_macrophage.md)

## Related Cell Types

- Parent: [macrophage](macrophage.md)
- [c1qc_positive_tumor_associated_macrophage](c1qc_positive_tumor_associated_macrophage.md)
- [cxcl10_positive_tumor_associated_macrophage](cxcl10_positive_tumor_associated_macrophage.md)
- [lyve1_positive_tumor_associated_macrophage](lyve1_positive_tumor_associated_macrophage.md)
- [macrophage_signature_tumor_associated_macrophage](macrophage_signature_tumor_associated_macrophage.md)
- [proliferating_tumor_associated_macrophage](proliferating_tumor_associated_macrophage.md)
- [spp1_positive_tumor_associated_macrophage](spp1_positive_tumor_associated_macrophage.md)

## References

- An SPP1-SOCS1 pathway constrains interferon responses in tumor-associated macrophages and shapes an immunosuppressive tumor microenvironment (2026) [10.1016/j.immuni.2026.04.001](https://doi.org/10.1016/j.immuni.2026.04.001)
