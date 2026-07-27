# exmaple_paper_2.pdf

## Page 1

Article
An SPP1-SOCS1 pathway constrains interferon
responsesintumor-associatedmacrophagesandshapes
an immunosuppressive tumor microenvironment
Graphical abstract Authors
LiangzhanSun,XiaojingChu,
TingtingKong,...,SijinCheng,
LinnanZhu,ZeminZhang
Correspondence
zhuln@pku.edu.cn(L.Z.),
zemin@pku.edu.cn(Z.Z.)
In brief
Tumor-associatedmacrophages(TAMs)
canlimitanti-tumorimmunity.Sunetal.
findthatSPP1+TAMsareenrichedin
tumorsacrosscancertypesand
associatedwithresistancetoimmune
checkpointblockade.Mechanistically,
SPP1interactswithTRIM21tolimit
SOCS1ubiquitination,thereby
dampeningIFN-γ-STAT1-ISGsignaling
inTAMs.
Highlights
• SPP1+TAMsareenrichedintumortissuesandlinkedto
immunotherapyresistance
•
IntracellularSPP1negativelyregulatestheIFN-γ-STAT1-ISG
pathwayinTAMs
•
IntracellularSPP1decreasesSOCS1ubiquitinationby
competitivelybindingtoTRIM21
•
SPP1deletioninmacrophagespromotesinflammationand
enhancesICBresponse
Sunetal.,2026,Immunity59,1–16
May12,2026©2026TheAuthor(s).PublishedbyElsevierInc.
ll
https://doi.org/10.1016/j.immuni.2026.04.001

## Page 2

Please cite this article in press as: Sun et al., An SPP1-SOCS1 pathway constrains interferon responses in tumor-associated macrophages and
shapes an immunosuppressive tumor microenvironment, Immunity (2026), https://doi.org/10.1016/j.immuni.2026.04.001
ll
OPEN ACCESS
Article
An SPP1-SOCS1 pathway constrains interferon
responses in tumor-associated macrophages and
shapes an immunosuppressive tumor microenvironment
Liangzhan Sun,1,2,3,8Xiaojing Chu,4,5,8Tingting Kong,1Xirui Chen,1Jianing Ru,1Qianqian Gao,1,3Wei Zhou,3
Xiliang Wang,6Sijin Cheng,1,4Linnan Zhu,7,*and Zemin Zhang1,7,9,*
1Institute for Data-Driven Tumor Immunology, Chongqing Medical University, Chongqing 400016, China
2Peking University Shenzhen Graduate School, Peking University, Shenzhen 518055, China
3Institute of Cancer Research, Shenzhen Bay Laboratory, Shenzhen 518000, China
4Changping Laboratory, Beijing 102206, China
5Key Laboratory of Cell Proliferation and Regulation Biology, Ministry of Education, Department of Biology, College of Life Sciences, Beijing
Normal University, Beijing 100875, China
6Analytical Biosciences Limited, Beijing 100083, China
7Biomedical Pioneering Innovation Center (BIOPIC), Academy for Advanced Interdisciplinary Studies, and School of Life Sciences, Peking
University, Beijing 100871, China
8These authors contributed equally
9Lead contact
*Correspondence: zhuln@pku.edu.cn(L.Z.), zemin@pku.edu.cn(Z.Z.)
https://doi.org/10.1016/j.immuni.2026.04.001
SUMMARY
Tumor-associated macrophages (TAMs) can suppress antitumor immunity and reduce responses to immune
checkpoint blockade (ICB). Here, we asked how TAM programs contribute to ICB non-response. Integration
of public single-cell RNA sequencing (scRNA-seq) datasets across 12 cancer types identified SPP1+ TAMs as
a tumor-enriched macrophage subset with immunosuppressive features. TAMs from ICB non-responders
across multiple tumor types exhibited higher SPP1 expression. In murine models, macrophage Spp1 deletion
suppressed tumor growth and prolonged survival and was associated with a remodeled tumor microenviron-
ment featuring reduced T regulatory cell (Treg) frequencies, increased interferon (IFN)-γ+ CD4+ and GZMB+
CD8+ T cells, and augmented interferon-stimulated gene (ISG) expression across immune and malignant
compartments. Mechanistically, intracellular SPP1 interacted with TRIM21 to limit SOCS1 ubiquitination, sta-
bilizing SOCS1-mediated negative feedback and dampening IFN-γ-STAT1-ISG signaling in TAMs. Consis-
tently, SPP1 targeting enhanced the efficacy of anti-PD-L1 therapy in vivo. Thus, remodeling the TME via tar-
geting the TAM SPP1-IFN-γ axis presents a therapeutic avenue for enhancing responses to ICB.
INTRODUCTION Highlighting the transcriptomic heterogeneities within TAMs,
our previous single-cell studies in multiple cancer types have re-
T cell-targeting strategies, such as immune checkpoint ported distinct TAM subsets with different functional potentials
blockade (ICB) therapies against CTLA4 and PD-1/PD-L1, as involving phagocytosis, lymphocyte recruitment, angiogenesis,
well as T cell receptor (TCR) or chimeric antigen receptor and immunotherapy resistance.6–9 However, these studies
(CAR) T cell therapies, have revolutionized the immunotherapy have not identified the key molecules and mechanisms driving
landscape.1–3 However, only 15%–35% of patients with solid the functions of TAMs in the tumor microenvironment and ICB
tumors benefit from these therapies, with the majority either therapy. In this study, leveraging public single-cell RNA
failing to respond or rapidly developing resistance after an sequencing (scRNA-seq) data from multiple cancer types, we re-
initial, transient response.1–3 Tumor-associated macrophages vealed the enrichment and pro-tumor effects of SPP1+ TAMs in
(TAMs) can eliminate cancer cells directly through phagocy- tumors from a larger cohort and prioritized SPP1 as a defining
tosis and the secretion of cytotoxic cytokines, while also marker of this subset and further validated across multiple can-
strengthening adaptive immunity by presenting antigens.4,5 cers that elevated SPP1 expression in TAMs is associated with
Additionally, their capacity to infiltrate dense tumor stroma resistance to ICB therapy. The full SPP1 transcript encodes a
and superior tolerance to hypoxic and acidic intra-tumor envi- secreted form of the SPP1 protein, while alternative translation
ronments position TAMs as up-and-coming candidates for initiation can produce an intracellular form by excluding the
anti-tumor immunotherapy.4–6 signal sequence.10 Both secreted and intracellular SPP1
Immunity 59, 1–16, May 12, 2026 © 2026 The Author(s). Published by Elsevier Inc. 1
This is an open access article under the CC BY license (http://creativecommons.org/licenses/by/4.0/).

## Page 3

Please cite this article in press as: Sun et al., An SPP1-SOCS1 pathway constrains interferon responses in tumor-associated macrophages and
shapes an immunosuppressive tumor microenvironment, Immunity (2026), https://doi.org/10.1016/j.immuni.2026.04.001
ll
OPEN ACCESS Article
A C
B
D E
F G
Figure 1. Integrative single-cell analysis reveals that SPP1 in TAMs is associated with pro-tumor effects
(A) Uniform manifold approximation and projection (UMAP) plot showing identified subsets of all monocytes and macrophages. n = 182158 cells.
(B) Dot plot showing the expression level of the top ten marker genes of each monocyte and macrophage subset. Dot size indicates the fraction of expressing
cells, and dot color indicates the normalized expression level.
(C) Heatmap showing tissue preference of each monocyte and macrophage subset indicated by Ro/e.
(D) Scatterplot showing the expression difference of all marker genes of the Macro-SPP1 subset in contrast to other subsets. The x axis indicates the average log
2
fold change, and the y axis indicates expression specificity calculated by subtracting the expressing percent out of the subset from the expressing percent in the
subset.
(E) Scatterplot and violin plot showing SPP1 expression in TAMs of different treatment responses at different time points of ICB therapy from colorectal cancer
(CRC) patients. Pre, pre-treatment; Post, post-treatment; SD, stable disease; PR, partial response; CR, complete response. Unpaired two-sided Wilcoxon’s test.
n = 565, 509, 242, 361, 739, and 1197 cells from left to right.
(legend continued on next page)
2 Immunity 59, 1–16, May 12, 2026

## Page 4

Please cite this article in press as: Sun et al., An SPP1-SOCS1 pathway constrains interferon responses in tumor-associated macrophages and
shapes an immunosuppressive tumor microenvironment, Immunity (2026), https://doi.org/10.1016/j.immuni.2026.04.001
ll
Article OPEN ACCESS
participate in macrophage polarization and immune responses, (Figure 1C). Notably, among these tumor-enriched cell subsets,
but their effects can vary and sometimes contradict based on SPP1+ TAMs stood out, consistent with previous studies sug-
expression context.11–15 SPP1+ TAMs have been identified in gesting their pro-tumor roles in CRC.6–9 Our integrative
various tumor types, and our previous studies have found that scRNA-seq data further confirmed that this subpopulation ex-
these TAMs are associated with poor survival, liver metastasis, hibited pro-tumor characteristics by upregulating pathways
and immunotherapy resistance in colorectal cancer (CRC) pa- related to angiogenesis, response to hypoxia, cell-matrix adhe-
tients.6–9 However, the specific functions of SPP1 in TAMs and sion, and transforming growth factor β (TGF-β) production, as
the underlying mechanisms remain unclear. Moreover, although well as negative regulation of adaptive immune response
a few preclinical studies have reported that SPP1-targeting anti- (Figure S1B). Furthermore, using our recently published CRC
bodies exhibit therapeutic potential, no benefit has been atlas,7 we found that SPP1+ TAM abundance was positively
observed in clinical trials.16,17 Therefore, whether SPP1 can correlated with T regulatory cell (Treg) abundance and the co-
serve as an effective therapeutic target for cancer remains to inhibitory score of CD8+ T cells (Figures S1C and S1D). These re-
be further investigated. sults reinforced the immune-suppressive potential of macro-
In this study, we utilized multiple cancer models to demonstrate phages marked with high expression of SPP1.
that SPP1 knockout in TAMs significantly inhibited tumor growth To uncover key regulators of the SPP1+ TAMs phenotype, we
and prolonged survival. Following SPP1 knockout in TAMs, in- analyzed differentially expressed genes and found that SPP1 ex-
flammatory signaling within the tumor was enhanced, with hibited the most significant upregulation and specificity
increased immune cell infiltration, particularly of tumor-suppres- (Figure 1D). Additionally, by comparing the expression levels of
sive interferon (IFN)-γ+ CD4+ T cells and GZMB+ CD8+ T cells, indi- SPP1 in tumor-infiltrating macrophages before and after ICB
cating a transition to a more immune-responsive environment. therapy in publicly available datasets, we observed higher
Mechanistically, we found that SPP1 is markedly overexpressed SPP1 expression in TAMs from patients with poor response
in TAMs, and intracellular SPP1 attenuates IFN-γ-STAT1-inter- across multiple cancer types (Figures 1E–1G and S1E).7,31–34
feron-stimulated gene (ISG) signaling by limiting SOCS1 ubiquiti- Consistent with these findings, pan-cancer bulk RNA
nation through competitive binding to TRIM21, thereby acting as a sequencing (RNA-seq) data revealed significantly elevated
molecular shock absorber of interferon signaling. Importantly, SPP1 expression in tumors compared with adjacent normal tis-
SPP1 ablation in TAMs significantly improved the efficacy of sues across 16 cancer types, including colon adenocarcinoma
anti-PD-L1 immunotherapy. Together, these findings suggest (COAD) and rectal adenocarcinoma (READ) (Figure S1F). Collec-
that SPP1 is a promising target to reverse the immunosuppressive tively, these results prompted us to investigate further the func-
roles of TAMs for cancer immunotherapy. tional roles of SPP1 in TAMs and its impact on the tumor micro-
environment, aiming to better understand its roles in tumor
RESULTS progression and immunotherapy resistance.
SPP1 in the pro-tumor role of TAMs Knockout SPP1 in TAMs delays tumor growth
To comprehensively characterize the gene expression land- To investigate the role of SPP1 in cancer, we generated myeloid-
scape of tumor-infiltrating monocytes and macrophages, we specific SPP1 knockout (Spp1-KO) mice and established a sub-
collected single-cell transcriptomic data of 135 donors from 15 cutaneous tumor model using the MC38 CRC and LLC1 lung
publicly available datasets covering 12 cancer types cancer cell line. Myeloid Spp1 deletion significantly inhibited tu-
(Table S1).6,9,13,14,18–28 Following batch correction and quality mor growth (Figures 2A, S2A, and S2B). Given reports of SPP1+
control, 182,158 single cells from tumors, adjacent normal tis- neutrophils with potential pro-tumor activity,35,36 we sought to
sues, and peripheral blood mononuclear cells (PBMCs) were determine whether the phenotype reflects SPP1 loss in TAMs
kept for clustering (Figures 1A and S1A). Based on the distinct or in neutrophils. However, in this setting, SPP1 expression in
gene expression patterns, we subsequently classified mono- neutrophils is exceedingly low, and SPP1+ neutrophils are virtu-
cytes and macrophages into eight subsets, including two mono- ally undetectable (Figures S2C and S2D). Additionally, we per-
cyte subsets (Mono-CD16 and Mono-CD14) and six formed in vivo macrophage depletion and repeated subcutane-
macrophage subsets characterized by the differential expres- ous implantation (Figure S2E). The antitumor effect was
sion of CXCL10, SPP1, C1QC, MACRO, LYVE1, and MKI67 abolished, demonstrating that it depends on TAMs rather than
(Figures 1A, 1B, and S1A; Table S2). To assess the tissue distri- neutrophils (Figure S2F).
bution of these monocyte and macrophage subsets, we used the Consistent with the observation in the subcutaneous tumor
ratio of observed to expected cell numbers (Ro/e)29,30 and re- model, tumor progression was also significantly delayed in a
vealed that CXCL10+ TAMs, SPP1+ TAMs, C1QC+ TAMs, and peritoneal tumor model established by injecting luciferase-
a subset of proliferating MKI67+ TAMs were enriched in tumor labeled MC38 cells into the peritoneal cavity, resulting in
tissues compared with adjacent normal tissues and PBMCs reduced tumor burden and markedly prolonged survival in
(F) Violin plots showing SPP1 expression in TAMs in different treatment responses at different time points of ICB therapy from breast invasive carcinoma (BRCA)
patients. Pre, pre-treatment; Post, post-treatment; SD, stable disease; PR, partial response. Unpaired two-sided Wilcoxon’s test. n = 3373, 443, 843, and 85 cells
from left to right.
(G) Violin plots showing SPP1 expression in TAMs of different treatment responses of ICB therapy from renal cell carcinoma (RCC) patients. PD, progressive
disease; PR, partial response; NR, non-responder; R, responder. Unpaired two-sided Wilcoxon’s test. n = 107, 754, 7872, and 4195 cells from left to right.
See also Figure S1.
Immunity 59, 1–16, May 12, 2026 3

## Page 5

Please cite this article in press as: Sun et al., An SPP1-SOCS1 pathway constrains interferon responses in tumor-associated macrophages and
shapes an immunosuppressive tumor microenvironment, Immunity (2026), https://doi.org/10.1016/j.immuni.2026.04.001
ll
OPEN ACCESS Article
A B C
D E
F G
H I J
Figure 2. SPP1 knockout in TAMs delays tumor progression in a lymphocyte-dependent manner
(A) Tumor growth curves after 2×106 MC38 cells subcutaneously transplanted into WT/Spp1-KO mice (n=6 per group).
(B) Bioluminescence analysis of the abdominal tumor burden of the indicated mice 14 days after intraperitoneal injection of 2×106 MC38-luciferase cells. The
representative picture (right) and the statistical result (left) are shown (n = 10 per group).
(C) Survival analysis of the indicated mice after intraperitoneal injection of 2×106 MC38-luciferase cells. Survival analysis was performed using the log-rank
(Mantel-Cox) test (n = 20 per group).
(D–F) Strategy for generating orthotopic CRC model (D). The representative picture (right) and the statistical result of tumor number (left) (E) and survival analysis of
indicated groups (F). Survival analysis was performed using the log-rank (Mantel-Cox) test (tumor number: n = 10 per group; survival analysis: n = 20 per group).
(G) Representative fluorescence-activated cell sorting (FACS) analysis of tumor and TAMs cells mixed 1:1 and co-cultured for 4 days. Representative picture
(right) and the statistical result (left) (n = 3 per group).
(H) The schematic diagram for generating the NOD-SCID Mix and C57BL/6J Mix model.
(I and J) Tumor growth curves after 2×106 MC38 mixed with 2×106 WT/Spp1-KO BMDM cells and transplanted into immunocompetent C57BL/6J (I) or NOD-
SCID (J) mice (NOD-SCID Mix model: n=5 per group; C57BL/6J Mix model: n=7 per group).
Data are shown as mean ± SEM; ns: non-significant. *p < 0.05, **p < 0.01, ***p < 0.001, ****p < 0.0001, unpaired Student’s t test, two-tailed (A, B, E, G, I, and J).
See also Figure S2.
Spp1-KO mice compared with wild-type (WT) controls described previously37 (Figure 2D). After SPP1 knockout, the
(Figures 2B and 2C). We next evaluated this in a colorectal ortho- number of large tumors (>5 mm) significantly decreased
topic model that better recapitulates human disease: we gener- (Figure 2E), although the total number of colorectal tumors re-
ated bone-marrow chimeric (BMC) mice by transplanting WT or mained unchanged (Figure S2G), and survival was significantly
Spp1-KO marrow into APC/DSS-induced CRC recipients, as extended (Figures 2F and S2H). Together, these results
4 Immunity 59, 1–16, May 12, 2026

## Page 6

Please cite this article in press as: Sun et al., An SPP1-SOCS1 pathway constrains interferon responses in tumor-associated macrophages and
shapes an immunosuppressive tumor microenvironment, Immunity (2026), https://doi.org/10.1016/j.immuni.2026.04.001
ll
Article OPEN ACCESS
Figure 3. Knocking out SPP1 in TAMs reshapes the tumor microenvironment
(A) FACS analysis of the frequency of immune cell infiltration in the indicated tumor. Representative picture (left) and statistical result (right) (n=5 per group).
(B) FACS analysis of absolute immune cell number per gram of tumor (n = 5 per group).
(C) FACS analysis of the frequency of CD4+ T cells, CD8+ T cells, NK cells, B cells, TAMs, and myeloid cells as a percentage of total immune cells (n=5 per group).
(D–F) mIF of murine tumors. Representative images (D), relative abundance of CD45+ immune cells (E), and fractional composition of major immune lineages
within the CD45+ compartment (F) in WT versus Spp1-KO (n=5 per group).
(G and H) scRNA-seq analysis of the CD45+ immune cells in indicated tumors (n=3 per group). UMAP plot of CD45+ immune cell clusters from merged con-
ditions, n = 17659 cells (G). Stacked columns show the major lineages’ proportions in indicated tumors (H).
(I) Stacked columns show the cluster proportions of lymphoid cells in indicated tumors.
(J) Boxplot showing the proportion of regulatory T cells (Tregs) in the indicated tumors (n=3). Unpaired two-sided t test.
(legend continued on next page)
Immunity 59, 1–16, May 12, 2026 5

## Page 7

Please cite this article in press as: Sun et al., An SPP1-SOCS1 pathway constrains interferon responses in tumor-associated macrophages and
shapes an immunosuppressive tumor microenvironment, Immunity (2026), https://doi.org/10.1016/j.immuni.2026.04.001
ll
OPEN ACCESS Article
indicated that SPP1 knockout in TAMs inhibited tumor progres- Spp1-KO group (Figure 3J). In CD8+ T cells, we observed
sion and prolonged survival in multiple cancer models. increased expression of GZMB after SPP1 knockout in TAMs
To examine whether SPP1 in TAMs could directly affect can- (Figure 3K). Additionally, IFN-γ expression was markedly
cer cells, we first cultured CT26 and MC38 CRC cells with elevated in Th1-like cells within the Spp1-KO group (Figure 3L).
TAM-conditioned media. As shown by the cancer cell clone for- Cell-cell interaction analysis indicated that TAMs exhibited
mation assay, SPP1 deficiency did not significantly affect cancer increased interactions with both CD4+ and CD8+ T cells after
cell proliferation (Figure S2I). Next, by co-culturing bone- SPP1 knockout (Figure S3C). Flow cytometry analysis confirmed
marrow-derived macrophages (BMDMs) with MC38 cells, we these results, showing a reduction in Tregs and an increase in
found cancer cell proliferation was not altered when SPP1 was both IFN-γ+ CD4+ T cells and GZMB+ CD8+ T cells within the tu-
knocked out (Figures 2G and S2J), indicating that SPP1 in mors of the Spp1-KO group (Figure 3M).
TAMs did not influence cancer cell growth directly. In the CD45− cell population, we identified malignant cells,
To further investigate the necessity of lymphocytes in the anti- endothelial cells (ECs), and cancer-associated fibroblasts
tumor effect of Spp1-KO in TAMs, we co-implanted WT or Spp1- (CAFs) based on the distinctive expression of known marker
KO BMDMs with MC38 cells into either immunocompetent genes (Figures S3D and S3E). Significant upregulation of type I
C57BL/6J mice (C57BL/6J Mix model) or immunodeficient and II interferon responses was observed after SPP1 knockout
non-obese diabetic (NOD)-severe combined immunodeficiency in TAMs (Figure 3N). Specifically, the ISG and major histocom-
(SCID) mice (NOD-SCID Mix model), which lacked T, B, and patibility complex class I (MHC class I) signatures, both associ-
functional natural killer (NK) cells (Figure 2H). In contrast to the ated with the ICB response,39,40were markedly upregulated in
significant tumor growth inhibition observed in the C57BL/6J malignant cells in the Spp1-KO group (Figure S3F). These data
Mix model, this effect was completely abrogated in the NOD- showed that SPP1 knockout in TAMs enhanced immune cell
SCID Mix model (Figures 2I, 2J, S2K, and S2L). These results infiltration, boosted type I and II interferon responses, and upre-
indicated that tumor growth inhibition caused by SPP1 knockout gulated ISG and MHC class I signatures, indicating an increased
in TAMs requires the synergistic action of lymphocytes, while the immune activation state, which may improve the tumor’s
absence of SPP1 in TAMs alone does not directly affect tumor responsiveness to immunotherapy.
growth.
SPP1 regulates ISG expression in TAMs
SPP1 knockout in TAMs enhances immune activity Next, we aimed to investigate the effects of SPP1 knockout in
To dissect the potential cellular and molecular mechanisms un- TAMs and how these changes influence the tumor microenviron-
derlying the anti-tumor effects of SPP1 knockout in TAMs, we ment. Our scRNA-seq analysis identified four major myeloid cell
examined the immune cell infiltration by flow cytometry and compartments: macrophages, monocytes, neutrophils, and
multicolor immunofluorescence (mIF) staining. SPP1 deletion dendritic cells (DCs) (Figure 4A). Within the macrophage
led to a marked increase in immune cell infiltration (Figures 3A– compartment, we resolved five subsets: C1qc+, Cxcl9+,
3F). Further analysis revealed a higher proportion of CD4+ and Spp1+, Isg15+, and Lyve1+ (Figure 4A). Although SPP1 deletion
CD8+ T cells, along with a reduced proportion of myeloid cells, did not notably change the overall proportion of TAMs, including
especially TAMs in the Spp1-KO group (Figures 3C and 3F). the Spp1+ TAMs subset, within the myeloid compartment, gene
To pinpoint cell populations involved, we performed scRNA- expression analysis revealed a marked increase in ISGs, such as
seq to analyze CD45+ and CD45− cell populations within the tu- Cxcl9, Cxcl10, Isg15, Nos2, Stat1, and Irf1 (Figures 4B, 4C, and
mor microenvironment. Within the CD45+ compartment, we S4A–S4C), which are associated with T cell recruitment and tu-
resolved 10 major lineages comprising 27 subpopulations based mor cell killing. Pathway enrichment analysis showed that
on canonical markers (Figures 3G and S3A). Because of tech- SPP1 deletion in TAMs led to an enrichment of inflammatory
nical constraints, scRNA-seq may underrepresent MDSCs and response, interferon-gamma, and interferon-alpha response
neutrophils,38 but for other immune subsets, it is concordant pathways (Figures 4D and S4D). Additionally, alignment with
with flow cytometry and mIF results, notably showing higher public macrophage polarization and signature data indicated a
CD4+/CD8+ T cell proportions and lower TAM proportions in shift toward M1-like and tumor-suppressive signatures
the Spp1-KO group (Figures 3C, 3F, and 3H). Pathway enrich- after SPP1 deletion (Figures 4E, 4F, and S4E).9,41Interestingly,
ment analysis of CD45+ cells revealed activation of type I and II unlike the in vivo TAMs analyzed through scRNA-seq, our bulk
interferon responses following SPP1 knockout (Figure S3B), RNA-seq analysis of TAMs obtained from in vitro co-culture
suggesting an enhanced immune response. Additionally, (Figures S4F and S4G) revealed that SPP1 deletion had no signif-
through the analysis of lymphoid cells obtained from scRNA- icant impact on interferon (IFN) responses or ISG expression
seq, we identified 1 B, 9 T, and 3 NK cell subsets (Figures 3G (Figures S4H and S4I). The expression of ISGs, such as Cxcl9,
and 3I). Notably, the proportion of Tregs was reduced in the Cxcl10, Isg15, and Nos2, did not show significant changes either
(K and L) Violin plots showing the expression level of GZMB in CD8+ T cells, n = 517 (WT) and 617 (Spp1-KO) cells (K), and IFN-γ in Th1-like cells, n = 59 (WT) and
142 (Spp1-KO) cells (L), unpaired two-sided Wilcoxon’s test.
(M) FACS analysis of the frequency of Tregs, IFN-γ+ CD4+ T cells and GZMB+CD8+ T cells in the indicated tumor (n=5 per group).
(N) Lollipop plot showing the enriched Hallmark pathways in the upregulated genes in CD45- cells in the Spp1-KO group compared with the WT group. Over-
representation analysis (BH adjustment).
Data are shown as mean ± SEM, **p < 0.01, ***p < 0.001, ****p < 0.0001 by unpaired Student’s t test, two-tailed (A–C, E, F, J, and M).
See also Figure S3.
6 Immunity 59, 1–16, May 12, 2026

## Page 8

Please cite this article in press as: Sun et al., An SPP1-SOCS1 pathway constrains interferon responses in tumor-associated macrophages and
shapes an immunosuppressive tumor microenvironment, Immunity (2026), https://doi.org/10.1016/j.immuni.2026.04.001
ll
Article OPEN ACCESS
A B
C
D E F
G H I
J K L M
N O P
Figure 4. The role of SPP1 in TAMs
(A) Global representation of myeloid cells in the single-cell analysis, including UMAP plots denoting cell types (left) and genotypes of the tumors of origins (right)
(n = 14699 cells).
(legend continued on next page)
Immunity 59, 1–16, May 12, 2026 7

## Page 9

Please cite this article in press as: Sun et al., An SPP1-SOCS1 pathway constrains interferon responses in tumor-associated macrophages and
shapes an immunosuppressive tumor microenvironment, Immunity (2026), https://doi.org/10.1016/j.immuni.2026.04.001
ll
OPEN ACCESS Article
(Figures S4J and S4K). Since in vivo scRNA-seq analysis indi- SPP1 might influence the process of interferon reception or the
cated that SPP1 deletion in TAMs enhanced their response to downstream intracellular signal transmission. First, we evaluated
both type I and type II interferons (Figure 4D), it was noteworthy the expression of IFN receptors in TAMs and observed no differ-
that in vitro-cultured TAMs lacked the stimulation from endoge- ences, suggesting that SPP1 does not influence interferon
nous IFN present in vivo. Thus, we treated in vitro-induced TAMs reception by regulating the expression of these receptors
with type I or type II interferons to assess the impact of SPP1 (Figure 5B). Considering that SPP1 could be secreted extracellu-
knockout on their interferon response. After interferon activation, larly and is a key component of the extracellular matrix, we
Spp1-KO TAMs displayed increased expression of Cxcl9, tested whether extracellular matrix SPP1 could affect interferon
Cxcl10, Isg15, and Nos2 (Figures 4G–4I), while ISG expression binding to its receptors. Supplementing Spp1-KO TAMs with re-
remained unchanged in the absence of interferon treatment combinant SPP1 protein to mimic its secreted form failed to
(Figures S4J and S4K). These findings suggested that SPP1 rescue the elevated ISG expression and STAT1 activation
knockout in TAMs enhanced ISG expression and drove a transi- (Figures 5A and 5C). Recombinant Spp1 protein was biologically
tion toward an anti-tumor phenotype upon interferon activation. active, as analysis of bulk RNA-seq data from our in vitro co-cul-
To define how SPP1 loss in TAMs reshapes the tumor micro- ture model demonstrated that Spp1 knockout in TAMs reduced
environment, we functionally profiled T cell trafficking and fate in Mmp13 expression in cancer cells, while the addition of recom-
co-cultures with WT or Spp1-KO TAMs. In Transwell assays, binant Spp1 restored Mmp13 levels (Figures S5E and S5F).
SPP1-deficient TAMs recruited more CD4+ and CD8+ T cells un- Collectively, these results suggest that SPP1 does not affect
der IFN-γ stimulation (Figures 4J and 4K), whereas T cell prolifer- the interferon signal reception.
ation (Ki67+ CD4+/CD8+) was not significantly altered (Figures 4L Next, we hypothesized that SPP1 might regulate ISG expres-
and 4M). Regarding effector differentiation/function, Spp1-KO sion by participating in the intracellular signaling downstream of
TAMs promoted Th1-like differentiation of naive CD4+ T cells IFN-γ. To test this, we synthesized intracellular (iSpp1) and
(IFN-γ+) without increasing Treg (CD25+FOXP3+) generation secretory Spp1 (sSpp1) mRNA via in vitro transcription and deliv-
(Figures 4N and 4O), and GZMB+ CD8+ T cells were unchanged ered them into Spp1-KO TAMs. We found that intracellular Spp1,
(Figure 4P). Consistent with these in vitro readouts, our scRNA- but not the secretory Spp1, restored ISG levels resulting from
seq data showed greater lymphocyte infiltration and higher fre- Spp1 deletion (Figures 5D and S5G). To investigate how intracel-
quencies of Th1-like cells in Spp1-KO tumors. Collectively, these lular Spp1 influences IFN-γ signal transduction, we supple-
data indicate that SPP1 deletion in TAMs primarily enhances mented Spp1-KO TAMs with intracellular Spp1-3XFlag mRNA,
lymphocyte recruitment and biases CD4+ T cells toward a Th1- then activated such TAMs with IFN-γ, and conducted immuno-
like state upon IFN-γ stimulation, providing a mechanistic link precipitation. Mass spectrometry analysis of the precipitated
between SPP1 loss in TAMs and a more immunostimula- proteins revealed a strong interaction between the Spp1 protein
tory TME. and the E3 ubiquitin ligase Trim21 (Figures 5E and S5H).
Pathway enrichment analysis of the precipitated proteins also
Intracellular SPP1 modulates SOCS1 abundance showed that these proteins were related to the ubiquitination
Subsequently, we sought to investigate how SPP1 influenced process (Figures S5I and S5J). Interestingly, TRIM21 has been
the expression of ISG under interferon stimulation in TAMs. reported to interact with the Janus kinase (JAK)-STAT negative
The IFN-STAT1-ISG pathway is a well-established mechanism regulator suppressor of cytokine signaling 3 (SOCS3) and pro-
by which interferons regulate ISG expression. Western blot anal- mote its degradation through the ubiquitin-proteasome sys-
ysis demonstrated that Stat1 expression and activation were tem.42SOCS1, structurally similar to SOCS3 and a crucial nega-
elevated in Spp1-KO TAMs upon interferon stimulation tive regulator of the IFN-γ-STAT1-ISGs pathway, exhibited
(Figure 5A). Since IFN-γ predominated over other interferons in elevated expression in Spp1-KO TAMs (Figure S5K). To examine
our tumor model, we used only IFN-γ for subsequent in vitro ex- whether Trim21 also interacted with Socs1, we performed immu-
periments (Figures S5A–S5D). We observed that ISG expression noprecipitation experiments under IFN-γ stimulation and discov-
was elevated in the Spp1-KO TAMs following treatment with the ered that Trim21 indeed interacted with Socs1 (Figure 5F). These
same dose of IFN (Figures 4G–4I). Therefore, we speculated that findings demonstrated that Spp1, Socs1, and Socs3 were all
(B) Volcano plot showing differentially expressed genes (DEGs) in comparing WT and Spp1-KO TAMs in scRNA-seq analysis.
(C) Violin plots showing the expression level of the indicated genes in WT/Spp1-KO TAMs (n = 8140 (WT) and 4978 (Spp1-KO) cells). Unpaired two-sided
Wilcoxon’s test. Bonferroni correction.
(D) Barplot showing the Gene Ontology (GO) pathways differentially activated in TAMs from different groups, and the x axis indicates the t-statistic from the
unpaired two-sided t test.
(E) Stacked bar plots showing the predicted cell states of TAMs of WT/Spp1-KO groups.
(F) Heat map showing the gene signature scores of the WT/Spp1-KO TAMs.
(G–I) qPCR tests measuring the expression levels of indicated ISG treated with IFN-α (G), IFN-β (H), and IFN-γ (I).
(J and K) Percent of migrated CD4+ (J) and CD8+ (K) T cells in response to WT vs. Spp1-KO TAMs under Ctrl or +IFN-γ conditions (n = 3 per group).
(L and M) FACS analysis of the frequency of Ki67+ CD4+ (L) and Ki67+ CD8+ (M) T cells after co-culture with control or IFN-γ-activated WT and Spp1-KO TAMs (n =
3 per group).
(N–P) FACS analysis of the frequency of IFN-γ+ CD4+ T cells (N), Tregs (O), and GZMB+ CD8+ T cells (P) after naive CD4+ T cell/naive CD8+ T cell co-culture with
control or IFN-γ-activated WT and Spp1-KO TAMs (n = 3 per group).
Data are shown as mean ± SEM, **p < 0.01, ***p < 0.001 by unpaired Student’s t test, two-tailed (G–P).
See also Figure S4.
8 Immunity 59, 1–16, May 12, 2026

## Page 10

Please cite this article in press as: Sun et al., An SPP1-SOCS1 pathway constrains interferon responses in tumor-associated macrophages and
shapes an immunosuppressive tumor microenvironment, Immunity (2026), https://doi.org/10.1016/j.immuni.2026.04.001
ll
Article OPEN ACCESS
Figure 5. The mechanism of SPP1 regulating IFN-γ-STAT1-ISG signaling in TAMs
(A) Western blot analysis of WT/Spp1-KO TAMs cultured with complete growth media (10% FBS) alone and Spp1-KO TAMs with 100 ng/ml recombinant
Spp1(rSpp1) protein after being treated with PBS (Ctrl), IFN-α (25 ng/μl), IFN-β (25 ng/μl), and IFN-γ (25 ng/μl) for 48 h. The expression of Stat1, p-Stat1(S727), and
p-Stat1(Y701) under the indicated treatment was standardized against the corresponding WT group. Using β-actin as a loading control. Immunoblots are
representative of two independent experiments.
(legend continued on next page)
Immunity 59, 1–16, May 12, 2026 9

## Page 11

Please cite this article in press as: Sun et al., An SPP1-SOCS1 pathway constrains interferon responses in tumor-associated macrophages and
shapes an immunosuppressive tumor microenvironment, Immunity (2026), https://doi.org/10.1016/j.immuni.2026.04.001
ll
OPEN ACCESS Article
substrates for Trim21. Therefore, we speculated that SPP1 might suppressive role of SPP1+ TAMs, we treated TAMs with common
influence the protein abundance of SOCS1 by binding to TRIM21 immunosuppressive factors to identify specific triggers of SPP1
competitively. In WT TAMs, both SOCS1 mRNA and protein expression. In addition to hypoxia, which is well known to induce
expression were upregulated following IFN-γ treatment SPP1 expression, we found that both interleukin (IL)-10 and
(Figures 5G and 5H). By contrast, although SOCS1 mRNA levels TGF-β significantly stimulated SPP1 expression in TAMs
increased in Spp1-KO TAMs, protein abundance remained un- (Figure S6D). Analysis of TCGA data further supported this
changed under IFN-γ stimulation, resulting in enhanced down- finding, showing a significant positive correlation between
stream Stat1 activation (Figures 5G and 5H). To further verify SPP1 expression and the levels of IL-10 and TGF-β
that the differences in Socs1 protein abundance between IFN- (Figures S6E and S6F). To better understand the underlying
γ-treated WT and Spp1-KO TAMs were attributable to Trim21, mechanisms, we treated IL-10-stimulated TAMs with Stattic,
we silenced Trim21 and observed an increase in SOCS1 protein an inhibitor of an IL-10 downstream factor STAT3, and found
levels, thereby eliminating the differences between WT and that Stattic effectively suppressed IL-10-induced SPP1 overex-
Spp1-KO TAMs (Figures 5G and S5L). The downstream Stat1 pression (Figure S6G). Similarly, we treated TGF-β-activated
activation and ISG expression also showed no further differ- TAMs with SIS3, an inhibitor of the activation of SMAD3 (a
ences (Figures 5G and 5I). To determine whether Trim21 TGF-β downstream effector), and observed that SIS3 reduced
regulated Stat1 through its ubiquitination function, we treated TGF-β-induced SPP1 expression (Figure S6H).
IFN-γ-activated TAMs with the autophagy-lysosome inhibitor We next tested in vivo whether inhibiting IL-10 and TGF-β
Bafilomycin A1 and the ubiquitin-proteasome inhibitor Bortezo- signaling reduces SPP1 in TAMs and slows tumor progression.
mib. We found Bafilomycin A1 had no impact on the Stat1 alter- Consistent with a recent report,43 pharmacologic inhibition of
ations caused by Spp1 deletion, whereas Bortezomib treatment adenosine A2A receptors (Ciforadenant) suppressed tumor
abolished the differences in Stat1 (Figure 5J). growth and TAMs-SPP1. By contrast, anti-IL-10R and Galuniser-
In summary, these findings suggest that SPP1 competes with tib (TGF-β pathway inhibitor) did not significantly affect tumor
SOCS1 for TRIM21 binding. Following SPP1 knockout, TRIM21- growth in this setting (Figures S6I and S6J). Galunisertib lowers
mediated binding and ubiquitination of SOCS1 increased, lead- TAMs-SPP1 yet fails to control tumors, likely because TGF-β re-
ing to reduced SOCS1 protein abundance and a consequent ceptors are broadly expressed across the TME (Figures S6K and
loss of negative regulation of the IFN-γ-STAT1-ISG pathway. In S7A), which diminishes net benefit. For IL-10, although it induces
this context, SPP1 functions as a molecular shock absorber by SPP1 in macrophages in vitro, anti-IL-10R neither controlled tu-
buffering interferon signaling: it preserves SOCS1 stability and mors nor lowered TAMs-SPP1 in vivo (Figures S6J and S6K),
thereby maintains the feedback inhibition of IFN-γ-driven inflam- consistent with low IL-10 expression in this model and indicating
matory responses. Loss of SPP1 removes this buffering effect, that TAMs-SPP1 is largely IL-10-independent here (Figures S7B
resulting in amplified interferon signaling. and S7C). Analysis of human CRC scRNA-seq showed IL10/
IL10R and TGFB/TGFBR expression patterns similar to those
IL-10 and TGF-β contribute to SPP1 expression observed in our mouse datasets (Figures S7D and S7E). Thus,
Our scRNA-seq analysis revealed that Spp1 was among the while TGF-β and IL-10 can induce SPP1 in macrophages
most highly expressed genes in TAMs across multiple cancer in vitro, TGF-β blockade lacks cellular selectivity, and IL-10
types (Figure S6A). Additionally, our bulk RNA-seq data, comple- blockade is context-dependent. Neither alone is an ideal strat-
mented by qPCR validation of in vitro-induced TAMs, confirmed egy to lower TAMs-SPP1 for tumor control.
that Spp1 expression levels exceed those of housekeeping
genes Gapdh and Actb (Figures S6B and S6C). These observa- Targeting SPP1 augments ICB efficacy
tions prompted us to investigate the upstream signals that As aforementioned, patients with elevated SPP1 in TAMs
strongly induce SPP1 expression in TAMs. Given the immuno- showed poor ICB response, while SPP1 ablation in TAMs
(B) qPCR tests measuring the expression levels of type I and type II interferon receptors in WT and Spp1-KO TAMs (n = 3 per group).
(C) qPCR tests measured indicated ISG expression levels in Spp1-KO TAMs cultured with complete growth media (10% FBS) alone and with recombinant Spp1
(rSpp1) at different concentrations after 24-h IFN-γ (25 ng/μl) treatment (n = 3 per group).
(D) qPCR tests measured indicated ISG expression levels in WT TAMs and Spp1-KO TAMs saved with mRNA transfection reagent only (Ctrl), sSpp1 isoform
mRNA, or iSpp1 isoform mRNA after 48-h IFN-γ (25 ng/μl) treatment (n = 3 per group).
(E) Proteins precipitated with anti-flag nanobody from extracts of Spp1-KO TAMs transiently transfected with 3XFlag-tagged iSpp1 and analyzed with mass
spectrometry. The top 15 proteins based on unique peptides and the sum of posterior error probability (PEP) scores are shown.
(F) Proteins precipitated from extracts of Spp1-KO TAMs transiently transfected with 3XFlag-tagged iSpp1 and immunoblotted for endogenous Socs1, Socs3,
and Trim21. Immunoblots are representative of two independent experiments.
(G) Western blot analysis of the expression of Trim21, Socs1, Stat1, p-Stat1(S727), and p-Stat1(Y701) in WT and Spp1-KO TAMs after indicated treatment. The
expression of the indicated protein was standardized against WT TAMs treated with IFN-γ (25 ng/μl). Using β-actin as a housekeeping protein. Immunoblots are
representative of two independent experiments.
(H) qPCR tests measuring the expression levels of Socs1 and Socs3 in WT and Spp1-KO TAMs after indicated treatment (n = 3 per group).
(I) qPCR tests measured ISG expression levels in WT and Spp1-KO TAMs following Trim21 knockdown and subsequent treatment with IFN-γ (n = 3 per group).
(J) Western blot analysis of the expression of Stat1, p-Stat1(S727), and p-Stat1(Y701) in WT and Spp1-KO TAMs treated with PBS (Ctrl), autophagosome-
lysosome inhibitor bafilomycin A1(BafA1) (20 nM), and ubiquitin-proteasome inhibitor Bortezomib (2.5 nM) after being activated by IFN-γ (25 ng/μl). Immunoblots
are representative of two independent experiments.
Data are shown as mean ± SEM, **p < 0.01, ***p < 0.001, ****p < 0.0001 by unpaired Student’s t test, two-tailed (B, H, and I), or one-way ANOVA (C and D).
See also Figures S5–S7.
10 Immunity 59, 1–16, May 12, 2026

## Page 12

Please cite this article in press as: Sun et al., An SPP1-SOCS1 pathway constrains interferon responses in tumor-associated macrophages and
shapes an immunosuppressive tumor microenvironment, Immunity (2026), https://doi.org/10.1016/j.immuni.2026.04.001
ll
Article OPEN ACCESS
increased immune cell infiltration and enhanced ISG and MHC vealed that SPP1+ TAMs were linked with poor prognosis in pa-
class I signatures in malignant cells (Figures 1E–1G and 3A– tients of multiple cancer types, such as CRC.6,8,9With an unsu-
3J). Consistently, analysis of pre- and post-ICB single-cell data pervised ranking, we prioritized SPP1 as the leading marker of
across several tumor types revealed that higher ISG signatures this subset, prompting the in-depth functional investigation of
were associated with improved ICB responses31–34 this gene in both tumor progression and immunotherapy. We
(Figures S8A–S8D). These results indicated that SPP1 knockout demonstrated the potential of SPP1 as a target of TAMs-based
in TAMs might improve the response rates and overall efficacy of immunotherapy by revealing that SPP1 ablation led to a favor-
ICB therapy. We next assessed the antitumor effects of Spp1- able survival and improvement of anti-PD-L1 immunotherapy
KO TAMs plus anti-PD-L1 therapy in subcutaneous tumor in multiple mouse CRC models. Further, we uncovered the
models. Our experiments further demonstrated that SPP1 cellular and molecular mechanism by which SPP1 deficiency in
knockout in TAMs improved the effectiveness of PD-L1 therapy, TAMs drives these anti-tumor effects.
resulting in a substantial tumor reduction, with complete regres- TAMs facilitate tumor immune evasion by inhibiting T cell infil-
sion observed in four out of seven cases (Figures 6A and 6B). tration and/or impairing their cytotoxic functions.44–46 In this
Furthermore, we observed that cancer cells mixed with Spp1- study, we observed that knocking out SPP1 in TAMs led to
KO TAMs grew slower than those mixed with WT TAMs in our increased infiltration of immune cells, primarily lymphoid cells,
C57BL/6J Mix model (Figure 2I). Flow cytometry analysis re- including tumor-suppressive IFN-γ+ CD4+ T cells and GZMB+
vealed increased immune cell infiltration in the Spp1-KO group CD8+ T cells, together with elevated expression of ISGs, such
(Figure S9A). Concurrently, scRNA-seq analysis indicated a as Cxcl9, Cxcl10, Nos2, and Isg15 in TAMs. TAMs-derived
reduction in myeloid cell proportions, particularly macrophages CXCL9, CXCL10, and iNOS are known to play key roles in re-
and monocytes, accompanied by an increase in CD4+ T, CD8+ cruiting T cells, with CXCL9+ TAMs, CXCL10+ TAMs, and
T, and NK cells (Figures S9B–S9D). Additionally, ISG expression NOS2+ TAMs linked to T cell infiltration across various can-
and immune activation pathways were upregulated in the Spp1- cers.47–51 Additionally, secreted ISG15 has been shown to pro-
KO group, suggesting that Spp1-KO TAMs can effectively mote IFN-γ expression in both T cells and NK cells.52 In line
induce a more immunogenic microenvironment compared with with these findings, our data demonstrated that Spp1-KO
WT TAMs (Figures S9E and S9F). Thus, we hypothesized that us- TAMs, upon activation by IFN-γ, further enhanced IFN-γ expres-
ing Spp1-KO macrophages for cell therapy might enhance ICB sion in CD4+ T cells. This suggests a potential positive feedback
therapy. To validate our hypothesis, we injected cancer cells mechanism linking Spp1-KO TAMs and IFN-γ+ CD4+ T cells in
into the peritoneal cavity of mice, treating them with either WT immune regulation. In this loop, IFN-γ+ CD4+ T cells secrete
or Spp1-KO BMDMs (Figure 6C). Spp1-KO BMDM treatment in- IFN-γ, activating Spp1-KO TAMs to increase their CXCL9,
hibited tumor progression and improved survival (Figures 6D and CXCL10, NOS2, and ISG15 expression. These cytokines, in
6E). Additionally, combining Spp1-KO BMDMs with anti-PD-L1 turn, further enhance CD4+ T cell recruitment and differentiation
therapy showed markedly greater efficacy than WT BMDMs of IFN-γ+ CD4+ T cells, thereby fostering a more immunogenic
(Figures 6D and 6E). Encouragingly, IFN-γ further amplified effi- tumor environment.
cacy: after two rounds of combined IFN-γ, Spp1-KO BMDMs, Mechanistically, we demonstrated that intracellular SPP1
and anti-PD-L1, complete tumor regression was achieved in participated in the negative feedback regulation of the IFN-
70% (7/10) of mice (Figures 6D, 6E, and S9G). These findings γ-STAT1-ISG pathway in TAMs. While the IFN-γ-STAT1-ISG
suggested that SPP1 ablation in macrophages enhances the ef- pathway is vital for immune defense, its hyperactivation can cause
ficacy of ICB, positioning SPP1 as a promising target for cell- pathological consequences, making negative feedback crucial for
based immunotherapy. maintaining immune balance.53 SOCS1 serves as an important
While macrophage transfer studies demonstrate that SPP1 negative feedback regulator of the IFN-γ-STAT1-ISG pathway
ablation augments ICB, their clinical deployment remains by inhibiting this signaling through targeting the upstream activa-
limited. To strengthen translational relevance and directly vali- tors of STAT1, JAKs, either by preventing their activation or pro-
date SPP1 as a therapeutic target, we developed a gene-therapy moting their degradation.54,55Additionally, SOCS1 may indirectly
strategy using lipid nanoparticle (LNP)-formulated small inter- regulate STAT1 expression by inhibiting its activation and
fering RNA (siRNA). We first designed a panel of anti-SPP1 reducing IRF1’s transcriptional output, as IRF1 binds to the
siRNAs and identified a top performer based on robust Spp1 STAT1 promoter and drives its transcription.56–58 This aligns
knockdown in BMDMs in vitro (Figure S9H). We then introduced with our findings that SPP1 knockout not only altered the activa-
2′-O-Me and 2′-F modifications with terminal phosphorothioate tion of STAT1 but also resulted in significant changes in the
linkages to enhance stability, formulated the optimized siRNA expression of IRF1 and STAT1. Tripartite motif (TRIM) family pro-
in LNPs, and delivered it intratumorally, which inhibited tumor teins have been shown to regulate SOCS proteins with their E3-
growth both as monotherapy and in combination with anti-PD- ubiquitin ligase activity. TRIM21 has been shown to interact with
L1 (Figures 6F, 6G, S9I, and S9J). Together, these data support SOCS3 in thymic stromal cells.42In this study, we demonstrated
SPP1 in TAMs as a tractable target to potentiate ICB. that intracellular SPP1 participates in the negative feedback regu-
lation of the IFN-γ-STAT1-ISG pathway by competitively binding
DISCUSSION to TRIM21 with SOCS1. Notably, the efficiency of this regulatory
mechanism may be influenced by the abundance of SPP1. Given
In this study, we showed the pro-tumor effects of SPP1+ TAMs that this function relies on SPP1 outcompeting SOCS1 for TRIM21
by integrating large-scale single-cell transcriptomic data from binding, its exceptionally high expression in TAMs across various
multiple cancer types. Additionally, our previous studies re- cancer types—including breast cancer, melanoma, pancreatic
Immunity 59, 1–16, May 12, 2026 11

## Page 13

Please cite this article in press as: Sun et al., An SPP1-SOCS1 pathway constrains interferon responses in tumor-associated macrophages and
shapes an immunosuppressive tumor microenvironment, Immunity (2026), https://doi.org/10.1016/j.immuni.2026.04.001
ll
OPEN ACCESS Article
A B
C
D E
G
F
Figure 6. SPP1 knockout in TAMs enhances the efficacy of ICB therapy
(A and B) Tumor growth in mice injected subcutaneously with the MC38 cell line treated with IgG or anti-PD-L1 antibodies (A). Data are shown as a growth curve
for each individual tumor (B) (n = 6 per group).
(C) Schematic diagram of the combined treatment plan.
(D and E) Bioluminescence analysis of the abdominal tumor burden (D) and survival analysis (E) of the indicated mice 14 days after intraperitoneal injection of
2×106 MC38-luciferase cells and indicated treatment. Survival analysis was performed using the log-rank (Mantel-Cox) test (tumor burden n = 5 per group;
survival n = 10 per group).
(F) Schematic of siRNA sequences and modifications.
(G) Tumor growth curves after 1×106 MC38 cells subcutaneously transplanted into WT C57BL/6J under the indicated treatments (n = 5).
Data are shown as mean ± SEM; *p < 0.05, ***p < 0.001, ****p < 0.0001 by one-way ANOVA (A, D, and G).
See also Figures S8and S9.
adenocarcinoma, and colon cancer—may be essential for We demonstrated that SPP1 knockout in BMDMs syner-
enabling SPP1 to act as a ‘‘molecular shock absorber’’ that gizes with anti-PD-L1 therapy, highlighting macrophage mod-
buffers excessive interferon signaling. This buffering capacity ulation as a promising strategy to enhance T cell-based ther-
may be limited in contexts where SPP1 expression is low, such apies. Notably, in 70% of mice, complete tumor regression
as in TAMs from myeloma or lymphatic cancers. Whether this was observed following combined treatment with IFN-γ,
mechanism operates in such settings remains to be determined. Spp1-KO BMDMs, and anti-PD-L1 therapy, emphasizing the
12 Immunity 59, 1–16, May 12, 2026

## Page 14

Please cite this article in press as: Sun et al., An SPP1-SOCS1 pathway constrains interferon responses in tumor-associated macrophages and
shapes an immunosuppressive tumor microenvironment, Immunity (2026), https://doi.org/10.1016/j.immuni.2026.04.001
ll
Article OPEN ACCESS
therapeutic potential of targeting SPP1 in enhancing immune RESOURCE AVAILABILITY
responses. This finding aligns with previous reports suggest-
ing that modulating TAMs is a viable strategy to overcome im- Lead contact
Requests for information and reagents should be directed to and will be ful-
mune resistance and enhance T cell-mediated anti-tumor ef-
filled by the lead contact, Zemin Zhang (zemin@pku.edu.cn).
fects.5 Despite the promising results, exploring effective
strategies for targeting SPP1 necessitates further investiga-
Materials availability
tion. Although a few preclinical studies have suggested that All unique reagents and data generated in this study are available from the lead
anti-SPP1 antibodies may have therapeutic potential, clinical contact.
trials have shown no significant benefit.16,17,59,60 Our findings
offer a potential explanation for this discrepancy: intracellular Data and code availability
SPP1, which cannot be targeted by extracellular antibodies, Newly generated bulk RNA-seq and scRNA-seq data were deposited at Fig-
share: https://doi.org/10.6084/m9.figshare.27628173. This paper does not
plays a pivotal role in regulating the IFN-γ-STAT1-ISG
report original code. Additional information required to reanalyze the data re-
pathway. Thus, antibody-based strategies may fail to recapit-
ported in this paper is available from the lead contactupon request.
ulate the full effects of SPP1 deletion in TAMs, particularly the
intracellular functions that contribute to immune regulation ACKNOWLEDGMENTS
and therapy resistance. To this end, we implemented an
LNP-siRNA strategy that directly targets intracellular SPP1. We thank the Institutional Animal Care and Use Committee of Shenzhen Bay
When delivered intratumorally in LNPs, the siRNA inhibited tu- Laboratory for assistance with animal experiments. We thank M. Chen, H.
Ning, Y. Gao, and Y. Miao for discussions. This project was supported by fund-
mor growth as monotherapy and enhanced anti-PD-L1 effi-
ing from the Noncommunicable Chronic Diseases-National Science and Tech-
cacy, thereby operationalizing SPP1 targeting in a drug-like,
nology Major Project (grant nos. 2025ZD0552500 and 2025ZD0552501), the
clinically oriented modality that captures the intracellular func- Chongqing Key Talent Project (grant no. X9-1358), the Chongqing Medical
tions missed by antibody blockade. Moreover, chemical mod- University Start-up Research Funding (grant no. J0325001), the Major Pro-
ifications enhance siRNA stability, and LNPs are efficiently gram of Shenzhen Bay Laboratory (grant no. S201101004), and the Open Pro-
taken up by macrophages, enabling sustained, macrophage- gram (grant no. SZBL2020090501005).
enriched SPP1 silencing and offering a promising avenue for
future therapeutic development.61 AUTHOR CONTRIBUTIONS
In conclusion, our findings position SPP1 as a promising
L.S., X. Chu, L.Z., and Z.Z. contributed to conceptualization, writing of the orig-
immunotherapy target, with the potential to convert immuno- inal draft, and project administration. S.C., L.Z., and Z.Z. contributed to the re-
suppressive TAMs into pro-inflammatory players that view and editing of the paper. L.S., X. Chu, and X.W. contributed to software
facilitate anti-tumor immune responses. The results provide and/or code and formal data analysis. Q.G. and W.Z. performed R analysis
insights into the mechanisms underlying TAMs-mediated im- and scRNA-seq. T.K., X. Chen, and J.R. were responsible for animal and in vi-
tro experiments. Z.Z. was responsible for supervision and funding acquisition.
mune suppression and pave the way for novel combination
therapies that could enhance ICB efficacy in solid tumors.
DECLARATION OF INTERESTS
Further research should focus on optimizing SPP1-targeted in-
terventions and exploring their synergistic effects with existing Z.Z. is a founder of Analytical Bioscience Limited and also serves on the advi-
immunotherapies in clinical settings. sory board of Cell. X.W. is an employee of Analytical Biosciences Limited.
STAR★METHODS
Limitations of the study
Our therapeutic validation of SPP1 targeting relied on an LNP- Detailed methods are provided in the online version of this paper and include
formulated siRNA approach tested in immunocompetent the following:
C57BL/6J mice with syngeneic tumor models. While these ex-
• KEY RESOURCES TABLE
periments establish in vivo feasibility and efficacy in a physio- • METHOD DETAILS
logic immune setting, it remains to be determined whether com-
○ Animals
parable delivery, on-target silencing, and antitumor benefit are ○ Tumor models
achieved in models that better approximate human tumor-im- ○ In vivo treatments
mune interactions, including humanized mice and patient- ○ Cell culture
derived xenograft (PDX) systems. ○ In vitro T Cells polarization
Mechanistically, the intracellular SPP1-TRIM21-SOCS1 ○ T-cell recruitment
○ Flow Cytometry, staining, and gating strategies
framework was defined in tumor contexts in which TAMs ex-
○ Immunofluorescence staining
press SPP1 at high levels, such as colorectal and lung cancer ○ Gene expression quantification by real-time PCR
models. In other malignancies, including multiple myeloma and ○ In vitro coculture and bulk RNA-seq
some lymphoid cancers, TAM SPP1 expression is often less ○ Western blots
prominent. Whether intracellular SPP1 similarly engages ○ Ectopic gene expression in macrophages using in vitro tran-
scribed mRNA
TRIM21 to modulate SOCS1 stability and constrain interferon re-
○ Co-IP assay
sponses in these settings, and more broadly, what the boundary
○ LC–MS/MS analysis
conditions are for this regulatory axis, remains an important di- ○ Foci formation
rection for future investigation. ○ siRNA-mediated silencing
Immunity 59, 1–16, May 12, 2026 13

## Page 15

Please cite this article in press as: Sun et al., An SPP1-SOCS1 pathway constrains interferon responses in tumor-associated macrophages and
shapes an immunosuppressive tumor microenvironment, Immunity (2026), https://doi.org/10.1016/j.immuni.2026.04.001
ll
OPEN ACCESS Article
○ Human scRNAseq data collection and quality control Natl. Acad. Sci. USA 105, 7235–7239. https://doi.org/10.1073/pnas.
○ TCGA data collection 0802301105.
○ Clustering and cell subset identification in human scRNAseq data 11.Ashkar, S., Weber, G.F., Panoutsakopoulou, V., Sanchirico, M.E.,
○ Tissue preference evaluation of monocyte and macrophage subsets Jansson, M., Zawaideh, S., Rittling, S.R., Denhardt, D.T., Glimcher,
○ Mouse single-cell transcriptome sequencing M.J., and Cantor, H. (2000). Eta-1 (osteopontin): an early component of
○ Mouse models scRNAseq data preprocessing and quality control type-1 (cell-mediated) immunity. Science 287, 860–864. https://doi.org/
○ Clustering and cell subset identification in mouse models’ scRNA- 10.1126/science.287.5454.860.
seq data
12.Inoue, M., Arikawa, T., Chen, Y.H., Moriwaki, Y., Price, M., Brown, M.,
○ Differential expression analysis in mouse models of scRNA-seq data
Perfect, J.R., and Shinohara, M.L. (2014). T cells down-regulate macro-
○ Bulk RNA-seq data analysis
phage TNF production by IRAK1-mediated IL-10 expression and control
○ Gene ontology (GO) and Hallmark term enrichment analysis
innate hyperinflammation. Proc. Natl. Acad. Sci. USA 111, 5295–5300.
○ Gene set variation analysis (GSVA) and scoring of signature genes
https://doi.org/10.1073/pnas.1321427111.
○ Macrophage type inference
○ Cell-cell interaction inference 13.Khosravi, M.J., Morton, R.C., and Diamandis, E.P. (1988). Sensitive, rapid
○ Other visualization procedure for time-resolved immunofluorometry of lutropin. Clin. Chem.
• STATISTICAL ANALYSIS 34, 1640–1644. https://doi.org/10.1093/clinchem/34.8.1640.
14.Kim, N., Kim, H.K., Lee, K., Hong, Y., Cho, J.H., Choi, J.W., Lee, J.I., Suh,
Y.L., Ku, B.M., Eum, H.H., et al. (2020). Single-cell RNA sequencing dem-
SUPPLEMENTAL INFORMATION
onstrates the molecular and cellular reprogramming of metastatic lung
adenocarcinoma. Nat. Commun. 11, 2285. https://doi.org/10.1038/
Supplemental information can be found online at https://doi.org/10.1016/j.
s41467-020-16164-1.
immuni.2026.04.001.
15.Zhao, K., Zhang, M., Zhang, L., Wang, P., Song, G., Liu, B., Wu, H., Yin, Z.,
Received: May 7, 2025 and Gao, C. (2016). Intracellular osteopontin stabilizes TRAF3 to positively
Revised: January 17, 2026 regulate innate antiviral response. Sci. Rep. 6, 23771. https://doi.org/10.
Accepted: March 31, 2026 1038/srep23771.
16.Boumans, M.J., Houbiers, J.G., Verschueren, P., Ishikura, H.,
Westhovens, R., Brouwer, E., Rojkovich, B., Kelly, S., Den Adel, M.,
Isaacs, J., et al. (2012). Safety, tolerability, pharmacokinetics, pharmaco-
REFERENCES
dynamics and efficacy of the monoclonal antibody ASK8007 blocking os-
teopontin in patients with rheumatoid arthritis: a randomised, placebo
1. Ribas, A., and Wolchok, J.D. (2018). Cancer immunotherapy using check-
controlled, proof-of-concept study. Ann. Rheum. Dis. 71, 180–185.
point blockade. Science 359, 1350–1355. https://doi.org/10.1126/sci-
https://doi.org/10.1136/annrheumdis-2011-200298.
ence.aar4060.
17.Moorman, H.R., Poschel, D., Klement, J.D., Lu, C., Redd, P.S., and Liu, K.
2. Uslu, U., Castelli, S., and June, C.H. (2024). CAR T cell combination ther-
(2020). Osteopontin: A Key Regulator of Tumor Progression and
apies to treat cancer. Cancer Cell 42, 1319–1325. https://doi.org/10.1016/
Immunomodulation. Cancers (Basel) 12, 3379. https://doi.org/10.3390/
j.ccell.2024.07.002.
cancers12113379.
3. Shafer, P., Kelly, L.M., and Hoyos, V. (2022). Cancer Therapy With TCR-
18.Azizi, E., Carr, A.J., Plitas, G., Cornish, A.E., Konopacki, C., Prabhakaran,
Engineered T Cells: Current Strategies, Challenges, and Prospects.
S., Nainys, J., Wu, K., Kiseliovas, V., Setty, M., et al. (2018). Single-Cell
Front. Immunol. 13, 835762. https://doi.org/10.3389/fimmu.2022.835762.
Map of Diverse Immune Phenotypes in the Breast Tumor
4. Pittet, M.J., Michielin, O., and Migliorini, D. (2022). Clinical relevance of Microenvironment. Cell 174, 1293–1308.e36. https://doi.org/10.1016/j.
tumour-associated macrophages. Nat. Rev. Clin. Oncol. 19, 402–421. cell.2018.05.060.
https://doi.org/10.1038/s41571-022-00620-6.
19.Lambrechts, D., Wauters, E., Boeckx, B., Aibar, S., Nittner, D., Burton, O.,
5. Mantovani, A., Marchesi, F., Malesci, A., Laghi, L., and Allavena, P. (2017). Bassez, A., Decaluwe´, H., Pircher, A., Van den Eynde, K., et al. (2018).
Tumour-associated macrophages as treatment targets in oncology. Nat. Phenotype molding of stromal cells in the lung tumor microenvironment.
Rev. Clin. Oncol. 14, 399–416. https://doi.org/10.1038/nrclinonc. Nat. Med. 24, 1277–1289. https://doi.org/10.1038/s41591-018-0096-5.
2016.217.
20.Zilionis, R., Engblom, C., Pfirschke, C., Savova, V., Zemmour, D.,
6. Cheng, S., Li, Z., Gao, R., Xing, B., Gao, Y., Yang, Y., Qin, S., Zhang, L., Saatcioglu, H.D., Krishnan, I., Maroni, G., Meyerovitz, C.V., Kerwin,
Ouyang, H., Du, P., et al. (2021). A pan-cancer single-cell transcriptional C.M., et al. (2019). Single-Cell Transcriptomics of Human and Mouse
atlas of tumor infiltrating myeloid cells. Cell 184, 792–809.e23. https:// Lung Cancers Reveals Conserved Myeloid Populations across
doi.org/10.1016/j.cell.2021.01.010. Individuals and Species. Immunity 50, 1317–1334.e10. https://doi.org/
7. Chen, Y., Wang, D., Li, Y., Qi, L., Si, W., Bo, Y., Chen, X., Ye, Z., Fan, H., 10.1016/j.immuni.2019.03.009.
Liu, B., et al. (2024). Spatiotemporal single-cell analysis decodes cellular 21.Zhang, Q., He, Y., Luo, N., Patel, S.J., Han, Y., Gao, R., Modak, M.,
dynamics underlying different responses to immunotherapy in colorectal Carotta, S., Haslinger, C., Kind, D., et al. (2019). Landscape and
cancer. Cancer Cell 42, 1268–1285.e7. https://doi.org/10.1016/j.ccell. Dynamics of Single Immune Cells in Hepatocellular Carcinoma. Cell 179,
2024.06.009. 829–845.e20. https://doi.org/10.1016/j.cell.2019.10.003.
8. Liu, Y., Zhang, Q., Xing, B., Luo, N., Gao, R., Yu, K., Hu, X., Bu, Z., Peng, J., 22.Cillo, A.R., Ku¨rten, C.H.L., Tabib, T., Qi, Z., Onkar, S., Wang, T., Liu, A.,
Ren, X., et al. (2022). Immune phenotypic linkage between colorectal can- Duvvuri, U., Kim, S., Soose, R.J., et al. (2020). Immune Landscape of
cer and liver metastasis. Cancer Cell 40, 424–437.e5. https://doi.org/10. Viral- and Carcinogen-Driven Head and Neck Cancer. Immunity 52,
1016/j.ccell.2022.02.013. 183–199.e9. https://doi.org/10.1016/j.immuni.2019.11.014.
9. Zhang, L., Li, Z., Skrzypczynska, K.M., Fang, Q., Zhang, W., O’Brien, S.A., 23.Slyper, M., Porter, C.B.M., Ashenberg, O., Waldman, J., Drokhlyansky, E.,
He, Y., Wang, L., Zhang, Q., Kim, A., et al. (2020). Single-Cell Analyses Wakiro, I., Smillie, C., Smith-Rosario, G., Wu, J., Dionne, D., et al. (2020). A
Inform Mechanisms of Myeloid-Targeted Therapies in Colon Cancer. single-cell and single-nucleus RNA-Seq toolbox for fresh and frozen hu-
Cell 181, 442–459.e29. https://doi.org/10.1016/j.cell.2020.03.048. man tumors. Nat. Med. 26, 792–802. https://doi.org/10.1038/s41591-
10. Shinohara, M.L., Kim, H.J., Kim, J.H., Garcia, V.A., and Cantor, H. (2008). 020-0844-1.
Alternative translation of osteopontin generates intracellular and secreted 24.Lee, H.O., Hong, Y., Etlioglu, H.E., Cho, Y.B., Pomella, V., Van den
isoforms that mediate distinct biological activities in dendritic cells. Proc. Bosch, B., Vanhecke, J., Verbandt, S., Hong, H., Min, J.W., et al.
14 Immunity 59, 1–16, May 12, 2026

## Page 16

Please cite this article in press as: Sun et al., An SPP1-SOCS1 pathway constrains interferon responses in tumor-associated macrophages and
shapes an immunosuppressive tumor microenvironment, Immunity (2026), https://doi.org/10.1016/j.immuni.2026.04.001
ll
Article OPEN ACCESS
(2020). Lineage-dependent gene expression programs influence the im- 38.Chen, J., Cheung, F., Shi, R., Zhou, H., and Lu, W.; CHI Consortium (2018).
mune landscape of colorectal cancer. Nat. Genet. 52, 594–603. https:// PBMC fixation and processing for Chromium single-cell RNA sequencing.
doi.org/10.1038/s41588-020-0636-z. J. Transl. Med. 16, 198. https://doi.org/10.1186/s12967-018-1578-4.
25.Qian, J., Olbrecht, S., Boeckx, B., Vos, H., Laoui, D., Etlioglu, E., Wauters, 39.Gao, J., Shi, L.Z., Zhao, H., Chen, J., Xiong, L., He, Q., Chen, T., Roszik, J.,
E., Pomella, V., Verbandt, S., Busschaert, P., et al. (2020). A pan-cancer Bernatchez, C., Woodman, S.E., et al. (2016). Loss of IFN-γ Pathway
blueprint of the heterogeneous tumor microenvironment revealed by sin- Genes in Tumor Cells as a Mechanism of Resistance to Anti-CTLA-4
gle-cell profiling. Cell Res. 30, 745–762. https://doi.org/10.1038/s41422- Therapy. Cell 167, 397–404.e9. https://doi.org/10.1016/j.cell.2016.
020-0355-0. 08.069.
26.Zheng, Y., Chen, Z., Han, Y., Han, L., Zou, X., Zhou, B., Hu, R., Hao, J., Bai, 40.Gu, S.S., Zhang, W., Wang, X., Jiang, P., Traugh, N., Li, Z., Meyer, C.,
S., Xiao, H., et al. (2020). Immune suppressive landscape in the human Stewig, B., Xie, Y., Bu, X., et al. (2021). Therapeutically Increasing
esophageal squamous cell carcinoma microenvironment. Nat. Commun. MHC-I Expression Potentiates Immune Checkpoint Blockade. Cancer
11, 6268. https://doi.org/10.1038/s41467-020-20019-0. Discov. 11, 1524–1541. https://doi.org/10.1158/2159-8290.Cd-20-0812.
27.Leader, A.M., Grout, J.A., Maier, B.B., Nabet, B.Y., Park, M.D., 41.Liu, S.X., Gustafson, H.H., Jackson, D.L., Pun, S.H., and Trapnell, C.
Tabachnikova, A., Chang, C., Walker, L., Lansky, A., Le Berichel, J., (2020). Trajectory analysis quantifies transcriptional plasticity during
et al. (2021). Single-cell analysis of human non-small cell lung cancer le- macrophage polarization. Sci. Rep. 10, 12273. https://doi.org/10.1038/
sions refines tumor classification and patient stratification. Cancer Cell s41598-020-68766-w.
39, 1594–1609.e12. https://doi.org/10.1016/j.ccell.2021.10.009. 42.Gao, Y., Liu, R., He, C., Basile, J., Vesterlund, M., Wahren-Herlenius, M.,
28.Kim, J., Park, C., Kim, K.H., Kim, E.H., Kim, H., Woo, J.K., Seong, J.K., Espinoza, A., Hokka-Zakrisson, C., Zadjali, F., Yoshimura, A., et al.
Nam, K.T., Lee, Y.C., and Cho, S.Y. (2022). Single-cell analysis of gastric (2021). SOCS3 Expression by Thymic Stromal Cells Is Required for
pre-cancerous and cancer lesions reveals cell lineage diversity and intra- Normal T Cell Development. Front. Immunol. 12, 642173. https://doi.org/
tumoral heterogeneity. NPJ Precis. Oncol. 6, 9. https://doi.org/10.1038/ 10.3389/fimmu.2021.642173.
s41698-022-00251-1. 43.Lyu, A., Fan, Z., Clark, M., Lea, A., Luong, D., Setayesh, A., Starzinski, A.,
Wolters, R., Arias-Badia, M., Allaire, K., et al. (2025). Evolution of myeloid-
29.Guo, X., Zhang, Y., Zheng, L., Zheng, C., Song, J., Zhang, Q., Kang, B.,
mediated immunotherapy resistance in prostate cancer. Nature 637,
Liu, Z., Jin, L., Xing, R., et al. (2018). Global characterization of T cells in
1207–1217. https://doi.org/10.1038/s41586-024-08290-3.
non-small-cell lung cancer by single-cell sequencing. Nat. Med. 24,
978–985. https://doi.org/10.1038/s41591-018-0045-3. 44.Kersten, K., Hu, K.H., Combes, A.J., Samad, B., Harwin, T., Ray, A., Rao,
A.A., Cai, E., Marchuk, K., Artichoker, J., et al. (2022). Spatiotemporal co-
30.Zhang, L., Yu, X., Zheng, L., Zhang, Y., Li, Y., Fang, Q., Gao, R., Kang, B.,
dependency between macrophages and exhausted CD8+ T cells in can-
Zhang, Q., Huang, J.Y., et al. (2018). Lineage tracking reveals dynamic re-
cer. Cancer Cell 40, 624–638.e9. https://doi.org/10.1016/j.ccell.2022.
lationships of T cells in colorectal cancer. Nature 564, 268–272. https://
05.004.
doi.org/10.1038/s41586-018-0694-x.
45.Peranzoni, E., Lemoine, J., Vimeux, L., Feuillet, V., Barrin, S., Kantari-
31.Bi, K., He, M.X., Bakouny, Z., Kanodia, A., Napolitano, S., Wu, J., Grimaldi,
Mimoun, C., Bercovici, N., Gue´rin, M., Biton, J., Ouakrim, H., et al.
G., Braun, D.A., Cuoco, M.S., Mayorga, A., et al. (2021). Tumor and im-
(2018). Macrophages impede CD8 T cells from reaching tumor cells and
mune reprogramming during immunotherapy in advanced renal cell carci-
limit the efficacy of anti-PD-1 treatment. Proc. Natl. Acad. Sci. USA 115,
noma. Cancer Cell 39, 649–661.e5. https://doi.org/10.1016/j.ccell.2021.
E4041–E4050. https://doi.org/10.1073/pnas.1720948115.
02.015.
46.Kos, K., Salvagno, C., Wellenstein, M.D., Aslam, M.A., Meijer, D.A., Hau,
32.Krishna, C., DiNatale, R.G., Kuo, F., Srivastava, R.M., Vuong, L., Chowell,
C.S., Vrijland, K., Kaldenbach, D., Raeven, E.A.M., Schmittnaegel, M.,
D., Gupta, S., Vanderbilt, C., Purohit, T.A., Liu, M., et al. (2021). Single-cell
et al. (2022). Tumor-associated macrophages promote intratumoral con-
sequencing links multiregional immune landscapes and tissue-resident
version of conventional CD4(+) T cells into regulatory T cells via PD-1 sig-
T cells in ccRCC to tumor topology and therapy efficacy. Cancer Cell
nalling. Oncoimmunology 11, 2063225. https://doi.org/10.1080/
39, 662–677.e6. https://doi.org/10.1016/j.ccell.2021.03.007.
2162402x.2022.2063225.
33.Shiao, S.L., Gouin, K.H., 3rd, Ing, N., Ho, A., Basho, R., Shah, A., Mebane, 47.Klug, F., Prakash, H., Huber, P.E., Seibel, T., Bender, N., Halama, N.,
R.H., Zitser, D., Martinez, A., Mevises, N.Y., et al. (2024). Single-cell and Pfirschke, C., Voss, R.H., Timke, C., Umansky, L., et al. (2013). Low-
spatial profiling identify three response trajectories to pembrolizumab dose irradiation programs macrophage differentiation to an iNOS⁺/M1
and radiation therapy in triple negative breast cancer. Cancer Cell 42, phenotype that orchestrates effective T cell immunotherapy. Cancer Cell
70–84.e8. https://doi.org/10.1016/j.ccell.2023.12.012. 24, 589–602. https://doi.org/10.1016/j.ccr.2013.09.014.
34.Zhang, Y., Chen, H., Mo, H., Hu, X., Gao, R., Zhao, Y., Liu, B., Niu, L., Sun, 48.Bill, R., Wirapati, P., Messemaker, M., Roh, W., Zitti, B., Duval, F., Kiss, M.,
X., Yu, X., et al. (2021). Single-cell analyses reveal key immune cell subsets Park, J.C., Saal, T.M., Hoelzl, J., et al. (2023). CXCL9:SPP1 macrophage
associated with response to PD-L1 blockade in triple-negative breast can- polarity identifies a network of cellular programs that control human can-
cer. Cancer Cell 39, 1578–1593.e8. https://doi.org/10.1016/j.ccell.2021. cers. Science 381, 515–524. https://doi.org/10.1126/science.ade2292.
09.010.
49.Reschke, R., and Gajewski, T.F. (2022). CXCL9 and CXCL10 bring the heat
35.Chen, J., Sun, H.W., Yang, Y.Y., Chen, H.T., Yu, X.J., Wu, W.C., Xu, Y.T., to tumors. Sci. Immunol. 7, eabq6509. https://doi.org/10.1126/sciimmu-
Jin, L.L., Wu, X.J., Xu, J., et al. (2021). Reprogramming immunosuppres- nol.abq6509.
sive myeloid cells by activated T cells promotes the response to anti-
50.House, I.G., Savas, P., Lai, J., Chen, A.X.Y., Oliver, A.J., Teo, Z.L., Todd,
PD-1 therapy in colorectal cancer. Signal Transduct. Target. Ther. 6, 4.
K.L., Henderson, M.A., Giuffrida, L., Petley, E.V., et al. (2020).
https://doi.org/10.1038/s41392-020-00377-3.
Macrophage-Derived CXCL9 and CXCL10 Are Required for Antitumor
36.Wu, Y., Ma, J., Yang, X., Nan, F., Zhang, T., Ji, S., Rao, D., Feng, H., Gao, Immune Responses Following Immune Checkpoint Blockade. Clin.
K., Gu, X., et al. (2024). Neutrophil profiling illuminates anti-tumor antigen- Cancer Res. 26, 487–504. https://doi.org/10.1158/1078-0432.Ccr-
presenting potency. Cell 187, 1422–1439.e24. https://doi.org/10.1016/j. 19-1868.
cell.2024.02.005.
51.Liang, Y.K., Deng, Z.K., Chen, M.T., Qiu, S.Q., Xiao, Y.S., Qi, Y.Z., Xie, Q.,
37.Li, Q., Chen, Y., Zhang, D., Grossman, J., Li, L., Khurana, N., Jiang, H., Wang, Z.H., Jia, S.C., Zeng, D., et al. (2021). CXCL9 Is a Potential
Grierson, P.M., Herndon, J., DeNardo, D.G., et al. (2019). IRAK4 mediates Biomarker of Immune Infiltration Associated with Favorable Prognosis in
colitis-induced tumorigenesis and chemoresistance in colorectal cancer. ER-Negative Breast Cancer. Front. Oncol. 11, 710286. https://doi.org/
JCI Insight 4, e130867. https://doi.org/10.1172/jci.insight.130867. 10.3389/fonc.2021.710286.
Immunity 59, 1–16, May 12, 2026 15

## Page 17

Please cite this article in press as: Sun et al., An SPP1-SOCS1 pathway constrains interferon responses in tumor-associated macrophages and
shapes an immunosuppressive tumor microenvironment, Immunity (2026), https://doi.org/10.1016/j.immuni.2026.04.001
ll
OPEN ACCESS Article
52. Recht, M., Borden, E.C., and Knight, E., Jr. (1991). A human 15-kDa IFN- nisms. Nat. Cancer 5, 1409–1426. https://doi.org/10.1038/s43018-024-
induced protein induces the secretion of IFN-gamma. J. Immunol. 147, 00807-z.
2617–2623. https://doi.org/10.4049/jimmunol.147.8.2617. 63.Hao, Y., Hao, S., Andersen-Nissen, E., Mauck, W.M., 3rd, Zheng, S.,
53. Philips, R.L., Wang, Y., Cheon, H., Kanno, Y., Gadina, M., Sartorelli, V., Butler, A., Lee, M.J., Wilk, A.J., Darby, C., Zager, M., et al. (2021).
Horvath, C.M., Darnell, J.E., Jr., Stark, G.R., and O’Shea, J.J. (2022). Integrated analysis of multimodal single-cell data. Cell 184, 3573–
The JAK-STAT pathway at 30: Much learned, much more to do. Cell 3587.e29. https://doi.org/10.1016/j.cell.2021.04.048.
185, 3857–3876. https://doi.org/10.1016/j.cell.2022.09.023. 64.Korsunsky, I., Millard, N., Fan, J., Slowikowski, K., Zhang, F., Wei, K.,
54. Giordanetto, F., and Kroemer, R.T. (2003). A three-dimensional model of Baglaenko, Y., Brenner, M., Loh, P.R., and Raychaudhuri, S. (2019).
Suppressor Of Cytokine Signalling 1 (SOCS-1). Protein Eng. 16, Fast, sensitive and accurate integration of single-cell data with
115–124. https://doi.org/10.1093/proeng/gzg015. Harmony. Nat. Methods 16, 1289–1296. https://doi.org/10.1038/s41592-
55. Liau, N.P.D., Laktyushin, A., Lucet, I.S., Murphy, J.M., Yao, S., Whitlock, 019-0619-0.
E., Callaghan, K., Nicola, N.A., Kershaw, N.J., and Babon, J.J. (2018). 65.Chen, S., Zhou, Y., Chen, Y., and Gu, J. (2018). fastp: an ultra-fast all-in-
The molecular basis of JAK/STAT inhibition by SOCS1. Nat. Commun. one FASTQ preprocessor. Bioinformatics 34, i884–i890. https://doi.org/
9, 1558. https://doi.org/10.1038/s41467-018-04013-1. 10.1093/bioinformatics/bty560.
56. Kamitani, S., Ohbayashi, N., Ikeda, O., Togi, S., Muromoto, R., Sekine, Y., 66.Pertea, M., Pertea, G.M., Antonescu, C.M., Chang, T.C., Mendell, J.T., and
Ohta, K., Ishiyama, H., and Matsuda, T. (2008). KAP1 regulates type I inter- Salzberg, S.L. (2015). StringTie enables improved reconstruction of a tran-
feron/STAT1-mediated IRF-1 gene expression. Biochem. Biophys. Res. scriptome from RNA-seq reads. Nat. Biotechnol. 33, 290–295. https://doi.
Commun. 370, 366–370. https://doi.org/10.1016/j.bbrc.2008.03.104. org/10.1038/nbt.3122.
57. Meraz, M.A., White, J.M., Sheehan, K.C., Bach, E.A., Rodig, S.J., Dighe, 67.Li, B., and Dewey, C.N. (2011). RSEM: accurate transcript quantification
A.S., Kaplan, D.H., Riley, J.K., Greenlund, A.C., Campbell, D., et al. from RNA-Seq data with or without a reference genome. BMC
(1996). Targeted disruption of the Stat1 gene in mice reveals unexpected Bioinform. 12, 323. https://doi.org/10.1186/1471-2105-12-323.
physiologic specificity in the JAK-STAT signaling pathway. Cell 84, 68.Love, M.I., Huber, W., and Anders, S. (2014). Moderated estimation of fold
431–442. https://doi.org/10.1016/s0092-8674(00)81288-x. change and dispersion for RNA-seq data with DESeq2. Genome Biol. 15,
58. Wang, A., Kang, X., Wang, J., and Zhang, S. (2023). IFIH1/IRF1/STAT1 550. https://doi.org/10.1186/s13059-014-0550-8.
promotes sepsis associated inflammatory lung injury via activating macro- 69.Liu, H., Golji, J., Brodeur, L.K., Chung, F.S., Chen, J.T., deBeaumont, R.S.,
phage M1 polarization. Int. Immunopharmacol. 114, 109478. https://doi. Bullock, C.P., Jones, M.D., Kerr, G., Li, L., et al. (2019). Tumor-derived IFN
org/10.1016/j.intimp.2022.109478. triggers chronic pathway agonism and sensitivity to ADAR loss. Nat. Med.
59. Klement, J.D., Poschel, D.B., Lu, C., Merting, A.D., Yang, D., Redd, P.S., 25, 95–102. https://doi.org/10.1038/s41591-018-0302-5.
and Liu, K. (2021). Osteopontin Blockade Immunotherapy Increases 70.Caronni, N., La Terza, F., Vittoria, F.M., Barbiera, G., Mezzanzanica, L.,
Cytotoxic T Lymphocyte Lytic Activity and Suppresses Colon Tumor Cuzzola, V., Barresi, S., Pellegatta, M., Canevazzi, P., Dunsmore, G.,
Progression. Cancers (Basel) 13, 1006. https://doi.org/10.3390/ et al. (2023). IL-1β+ macrophages fuel pathogenic inflammation in pancre-
cancers13051006. atic cancer. Nature 623, 415–422. https://doi.org/10.1038/s41586-023-
60. Liu, Y., Xun, Z., Ma, K., Liang, S., Li, X., Zhou, S., Sun, L., Liu, Y., Du, Y., 06685-2.
Guo, X., et al. (2023). Identification of a tumour immune barrier in the 71.Aran, D., Looney, A.P., Liu, L., Wu, E., Fong, V., Hsu, A., Chak, S.,
HCC microenvironment that determines the efficacy of immunotherapy. Naikawadi, R.P., Wolters, P.J., Abate, A.R., et al. (2019). Reference-based
J. Hepatol. 78, 770–782. https://doi.org/10.1016/j.jhep.2023.01.011. analysis of lung single-cell sequencing reveals a transitional profibrotic
61. Hu, B., Zhong, L., Weng, Y., Peng, L., Huang, Y., Zhao, Y., and Liang, X.J. macrophage. Nat. Immunol. 20, 163–172. https://doi.org/10.1038/
(2020). Therapeutic siRNA: state of the art. Signal Transduct. Target. Ther. s41590-018-0276-y.
5, 101. https://doi.org/10.1038/s41392-020-0207-x. 72.Jin, S., Guerrero-Juarez, C.F., Zhang, L., Chang, I., Ramos, R., Kuan, C.H.,
62. Chu, X., Li, X., Zhang, Y., Dang, G., Miao, Y., Xu, W., Wang, J., Zhang, Z., Myung, P., Plikus, M.V., and Nie, Q. (2021). Inference and analysis of cell-
and Cheng, S. (2024). Integrative single-cell analysis of human colorectal cell communication using CellChat. Nat. Commun. 12, 1088. https://doi.
cancer reveals patient stratification with distinct immune evasion mecha- org/10.1038/s41467-021-21246-9.
16 Immunity 59, 1–16, May 12, 2026

## Page 18

Please cite this article in press as: Sun et al., An SPP1-SOCS1 pathway constrains interferon responses in tumor-associated macrophages and
shapes an immunosuppressive tumor microenvironment, Immunity (2026), https://doi.org/10.1016/j.immuni.2026.04.001
ll
Article OPEN ACCESS
STAR★METHODS
KEY RESOURCES TABLE
REAGENT or RESOURCE SOURCE IDENTIFIER
Antibodies
Rat APC anti-mouse CD45 Antibody Biolegend Cat# 103112; RRID: AB_312977
FITC Rat anti-mouse CD45 BD Bioscience Cat# 553079; RRID: AB_394609
BV510 Rat Anti-CD11B BD Bioscience Cat# 562950; RRID: AB_2737913
BUV496 Rat Anti-Mouse MHC class II BD Bioscience Cat#750281; RRID: AB_2874472
PerCP-Cy™5.5 Hamster Anti-Mouse CD11c BD Bioscience Cat#560584; RRID: AB_1727422
Brilliant Violet 605™ anti-mouse CD8a BioLegend Cat#100744; RRID: AB_2562609
Antibody
PerCP-Cy™5.5 Rat Anti-Mouse CD4 BD Bioscience Cat#550954; RRID: AB_393977
Alexa Fluor® 488 anti-mouse CD3 Antibody Biolegend Cat#100210; RRID: AB_389301
APC anti-mouse IFN-γ Antibody Biolegend Cat#505810; RRID: AB_315404
FITC anti-human/mouse Granzyme B Biolegend Cat#372206; RRID: AB_2687030
Recombinant Antibody
Alexa Fluor® 700 anti-mouse F4/80 Biolegend Cat#123130; RRID: AB_2293450
Alexa Fluor® 700 anti-mouse FOXP3 Biolegend Cat#126422; RRID: AB_2750493
Antibody
BV605 Rat Anti-Mouse CD25 BD Bioscience Cat#563061; RRID: AB_2737982
PE/Cyanine7 anti-mouse NK-1.1 Antibody Biolegend Cat# 108714; RRID: AB_389364
PE anti-mouse CD19 Antibody Biolegend Cat#115508; RRID: AB_313643
Purified Rat Anti-Mouse CD16/CD32 BD Bioscience Cat#553142; RRID: AB_394657
(Mouse BD Fc Block™)
Anti-β-Actin (13E5) Rabbit mAb CST Cat#4970T; RRID: AB_2223172
Stat1 (D1K9Y) Rabbit mAb CST Cat#14994; RRID: AB_2737027
Phospho-Stat1 (Tyr701) (58D6) Rabbit mAb CST Cat#9167; RRID: AB_561284
Phospho-Stat1 (Ser727) Antibody CST Cat#9177; RRID: AB_2197983
Anti-FLAG® M2 CST Cat# 70569; RRID: AB_2799786
SOCS1 (E3Q4M) Rabbit mAb CST Cat#55313; RRID: AB_3731289
Anti-SOCS3 antibody [EPR24090-74] Abcam Cat#ab280884; RRID: AB_3065200
Anti-TRIM21/SS-A antibody [EPR20290] Abcam Cat#ab207728; RRID: AB_2927717
CD4 (D7D2Z) Antibody CST Cat#25229; RRID: AB_2798898
CD45 (D3F8Q) Antibody CST Cat#70257; RRID: AB_2799780
CD11b (E4K8C) Antibody CST Cat#93169; RRID: AB_3731290
Ly-6G (E6Z1T) Antibody CST Cat#87048; RRID: AB_2909808
NK1.1 (E6Y9G) Antibody CST Cat#39197; RRID: AB_2943222
CD19 (D4V4B) Antibody CST Cat#90176; RRID: AB_2800152
CD8α (D4W2Z) Antibody CST Cat#98941; RRID: AB_2756376
SPP1 Antibody Abcam Cat#ab216406; RRID: AB_3731292
CD3 Monoclonal Antibody (17A2) Thermo Fisher Cat#16-0032-82; RRID: AB_468851
CD28 Monoclonal Antibody (37.51) Thermo Fisher Cat#16-0281-82; RRID: AB_468921
Anti-mouse PD-L1 (B7-H1)-In Vivo Selleck Cat#A2115; RRID: AB_3675704
IgG2b isotype control-In Vivo Selleck Cat#A2116; RRID: AB_3662740
Anti-Mouse IL-10R Antibody (1B1.3A) MCE Cat#HY-P990228; RRID: AB_3731293
Rat IgG1 kappa, Isotype Control MCE Cat#HY-P99979; RRID: AB_3731294
Chemicals, peptides, and recombinant proteins
DAPI Solution BD Bioscience Cat#564907
Red Cell Lysis Buffer TIANGEN Cat#RT122-02
(Continued on next page)
Immunity 59, 1–16.e1–e9, May 12, 2026 e1

## Page 19

Please cite this article in press as: Sun et al., An SPP1-SOCS1 pathway constrains interferon responses in tumor-associated macrophages and
shapes an immunosuppressive tumor microenvironment, Immunity (2026), https://doi.org/10.1016/j.immuni.2026.04.001
ll
OPEN ACCESS Article
Continued
REAGENT or RESOURCE SOURCE IDENTIFIER
Protein Transport Inhibitor BD Bioscience Cat#555029
BD Horizon™ Brilliant Stain Buffer BD Bioscience Cat#566349
Recombinant Mouse Osteopontin/OPN R&D Cat#441-OP-050
Protein
Recombinant Osteopontin/OPN, Mouse MCE Cat#HY-P78358
(HEK293, His)
Recombinant IFN-alpha 14, Mouse MCE Cat#HY-P76401
Recombinant IFN-beta, Mouse MCE Cat#HY-P73130
Recombinant IFN-gamma, Mouse MCE Cat#HY-P70667
Azoxymethane (AOM) MP Biomedicals Cat#2180139.1
Dextran Sodium Sulfate (DSS) MP Biomedical Cat#216011080
SIS3 SELLECK Cat#S7959
Stattic MCE Cat#HY-13818
Galunisertib MCE Cat#HY-13226
Ciforadenant MCE Cat#HY-101978
Corn Oil MCE Cat#HY-Y1888
DMSO SIGMA Cat#D8418
Recombinant Murine IL-2 PEPROTECH Cat#212-12
Recombinant Murine IL-4 PEPROTECH Cat#214-14
Recombinant Murine IL-10 PEPROTECH Cat#210-10
Recombinant Murine IL-12 p70 PEPROTECH Cat#210-12
Recombinant IL-13, Mouse MCE Cat#HY-P70460
Recombinant TGF beta 1/TGFB1, Mouse MCE Cat#HY-P7117
Bafilomycin A1 MCE Cat#HY-100558
Bortezomib MCE Cat#HY-10227
Recombinant Murine MCSF PEPROTECH Cat#315-02
D-Luciferin, Potassium Salt Goldbio Cat#LUCK-2G
Critical commercial assays
Zombie NIR™ Fixable Viability Kit Biolegend Cat#423106
Tumor Dissociation Kit, mouse MILTENYI Cat#130-096-730
EasySep™ Mouse CD4+ T Cell Isolation Kit STEMCELL Cat#19852
EasySep™ Mouse CD8+ T Cell Isolation Kit STEMCELL Cat#19853
RNeasy Mini Kit QIAGEN Cat# 74104
FOXP3/Transcription Factor Staining Thermo Fisher Cat# 00-5532-00
Buffer Set
RNA isolater Total RNA Extraction Reagent Vazyme Cat# R401-01-AA
PrimeScript RT Reagent Kit Takara Cat# RR047A
TB Green Premix Ex Taq kit Takara Cat# RR420A
Anti-Flag Nanobody IP kit (Magarose) AlpaLifeBio Cat# KTSM1361
mMESSAGE mMACHINE™ T7 Thermo Fisher Cat#AM1344
Transcription Kit
Lipofectamine™ MessengerMAX™ Thermo Fisher Cat#LMRNA001
Transfection Reagent
HiPerFect Transfection Reagent QIAGEN Cat#301704
QIAquick Gel Extraction Kit QIAGEN Cat#28704
Anti-Flag Nanobody IP kit (Magarose) AlpaLifeBio Cat#KTSM1361
PANO 7-plex IHC kit Panovue Cat#10217100100
Deposited data
Processed Bulk RNA-seq data This paper https://doi.org/10.6084/m9.figshare.
27628173
(Continued on next page)
e2 Immunity 59, 1–16.e1–e9, May 12, 2026

## Page 20

Please cite this article in press as: Sun et al., An SPP1-SOCS1 pathway constrains interferon responses in tumor-associated macrophages and
shapes an immunosuppressive tumor microenvironment, Immunity (2026), https://doi.org/10.1016/j.immuni.2026.04.001
ll
Article OPEN ACCESS
Continued
REAGENT or RESOURCE SOURCE IDENTIFIER
Processed single-cell RNA-seq data This paper https://doi.org/10.6084/m9.figshare.
27628173
Monocyte and macrophage Single-cell Cheng et al.6Zhang et al.9Khosravi et al.13 GSE114727, E-MTAB-6149, E-MTAB-
transcriptomic data Kim et al.14Azizi et al.18Lambrechts et al.19 6653, GSE127465, EGAS00001003449,
Zilionis et al.20Zhang et al.21Cillo et al.22 GSE139324, GSE123904, GSE146771,
Slyper et al.23Lee et al.24Qian et al.25Zheng GSE131907, GSE140819, GSE132465,
et al.26Leader et al.27Kim et al.28 GSE132257, GSE144735, E-MTAB-8107,
E-MTAB-6149, E-MTAB-6653,
GSE145370, GSE154763, GSE154826,
GSE150290
ICB treatment-related single-cell Chen et al.7Bi et al.31Krishna et al.32Shiao https://singlecell.broadinstitute.org/single_
transcriptomic data et al.33Zhang et al.34 cell/study/ SCP1288/tumor-and-immune-
reprogramming-during-immunotherapy-in-
advanced-renal-cell- carcinoma#study-
summary,
SRA: PRJNA705464, SRZ: SRZ190804,
GSE169246, GSE246613, GSE236581
CRC single-cell atlas Chu et al.62 https://doi.org/10.6084/m9.figshare.
25323397
Experimental models: Cell lines
MC38 Kerafast Cat# ENH204
Luciferase-labeled MC38 This Paper N/A
CT26 ATCC Cat#CRL-2638
Experimental models: Organisms/strains
Wild-type C57BL/6J Shanghai Model Organisms Cat#SM-001
NOD-SCID (NOD.Cg-Prkdcscid/NifdcSmoc) Shanghai Model Organisms Cat#SM-019
C57BL/6Smoc-Apctm2(flox)Smoc Shanghai Model Organisms Cat#NM-CKO-200013
C57BL/6Smoc-Spp1em1(flox)Smoc Shanghai Model Organisms Cat#NM-CKO-210205
Lyz2-Cre mice (B6.129P2-Lyz2tm1(cre)Ifo/J) Jackson Laboratory Ca# 004781;
Vil1-MerCreMer mice Cyagen Cat#C001433
Oligonucleotides
siRNA targeting Trim21: This study N/A
CAGAAUACCAAGAAGAGUACC
List of primers Table S3 N/A
Recombinant DNA
pCDNA3.1(+)-intracellular Spp1-3xFlag IGEbio N/A
pCDNA3.1(+)-extracellular Spp1-3xFlag IGEbio N/A
pCDNA3.1(+)-Trim21-3xFlag IGEbio N/A
Software and algorithms
FlowJo 10.3 BD Biosciences https://www.flowjo.com
FIJI (ImageJ) ImageJ https://fiji.sc/
Imaris v.9.3.1 Oxford Instruments plc https://imaris.oxinst.com/
GraphPad Prism Version 9 GraphPad Prism www.graphpad.com
TCGAbiolinks (v2.22.4) Bioconductor https://bioconductor.org/packages/
release/bioc/html/TCGAbiolinks.html
Seurat (v5.0.1) Hao et al.63 https://satijalab.org/seurat/index.html
Harmony (v1.1.0) Github https://github.com/immunogenomics/
harmony
CellRanger v6.12 10×Genomics https://www.10xgenomics.com/
fastp (v0.18.0) Github https://github.com/OpenGene/fastp
HISAT2 (v2.4) Github http://daehwankimlab.github.io/hisat2/
(Continued on next page)
Immunity 59, 1–16.e1–e9, May 12, 2026 e3

## Page 21

Please cite this article in press as: Sun et al., An SPP1-SOCS1 pathway constrains interferon responses in tumor-associated macrophages and
shapes an immunosuppressive tumor microenvironment, Immunity (2026), https://doi.org/10.1016/j.immuni.2026.04.001
ll
OPEN ACCESS Article
Continued
REAGENT or RESOURCE SOURCE IDENTIFIER
StringTie (v1.3.1) Github https://github.com/gpertea/stringtie
RSEM (v1) Github https://github.com/deweylab/RSEM
DESeq2 (v1.42.0) Bioconductor https://bioconductor.org/packages/
release/bioc/html/DESeq2.html
clusterProfiler (v4.10.0) Bioconductor https://www.bioconductor.org/packages/
release/bioc/html/clusterProfiler.html
GSVA (v1.50.0) Bioconductor https://www.bioconductor.org/packages/
release/bioc/html/GSVA.html
SingleR (v2.4.1) Github https://github.com/dviraran/SingleR
CellChat (v1.6.1) Github https://github.com/sqjin/CellChat
ggplot2 (v3.4.2) CRAN https://cran.microsoft.com/web/packages/
ggplot2/
pheatmap (v1.0.12) CRAN https://cran.r-project.org/web/packages/
pheatmap/
VennDiagram (v1.7.3) CRAN https://cran.r-project.org/web/packages/
VennDiagram/index.html
Other
N/A N/A N/A
METHOD DETAILS
Animals
All animal experiments in this study were reviewed and approved by the Institutional Animal Care and Use Committee of Shenzhen
Bay Laboratory (AEZZM20201). Wild-type C57BL/6J mice, NOD-SCID mice (NOD.Cg-Prkdcscid/NifdcSmoc), Apc-flox mice (C57BL/
6Smoc-Apctm2(flox)Smoc), and Spp1-flox mice (C57BL/6Smoc-Spp1em1(flox)Smoc) were purchased from the Shanghai Model Organ-
isms Center, Inc (Shanghai, China). Vil1-Cre (Vil1-MerCreMer) mice were obtained from Cyagen Biosciences (Guangzhou, China).
Lyz2-Cre mice (B6.129P2-Lyz2tm1(cre)Ifo/J) were purchased from Jackson Lab. Mice were bred under SPF conditions, maintained
on a 12-hour light/dark cycle at 21–22◦C with 30–70% humidity. Mice within experiments were age and sex matched and all mice
were genotyped before the experiment.
Tumor models
To generate macrophage-specific Spp1 knockout mice, we crossed Spp1-flox mice with Lyz2-Cre mice. Spp1wt/wt Lyz2-Cre+/- mice
were designated as WT and Spp1flox/flox Lyz2-Cre+/- mice were designated as Spp1-KO. To establish a subcutaneous tumor model,
we resuspend MC38/LLC1 cells in a mixture of PBS and Matrigel (Corning, 354234) (1:1) at a concentration of 1x107 cells/ml. WT and
Spp1-KO male mice at 6 weeks of age were used and injected with 200 μL MC38 (or 100 μL LLC1) cell suspension subcutaneously
into the flank region.
For the macrophage depletion experiment, mice received clodronate liposomes by i.p. injection (200 μL/mouse) 1 day before tumor
inoculation, then every 3 days thereafter. On day 0, 1 ×106 MC38 cells in 100 μL mixture of PBS and Matrigel were injected subcu-
taneously into the right flank to establish tumors. Tumors were measured with a caliper 5 days after injection and then every three
days thereafter.
For the C57BL/6J Mix tumor model, we mixed MC38 cells and WT or Spp1-KO BMDMs (1:1) and resuspended cells in a mixture of
PBS and Matrigel (1:1) at a concentration of 2x107 cells/ml. Male C57BL/6J mice at 6 weeks of age were used and injected with
200 μL cell suspension subcutaneously into the flank region. The NOD-SCID Mix tumor model was constructed using the same
method as the C57BL/6J Mix tumor model mentioned above. Tumors were measured with a caliper 5 days after injection and
then every three days thereafter. Mice were sacrificed when the biggest tumor reached 1.5 cm in diameter.
To establish a peritoneal tumor model, we resuspend the luciferase-labeled MC38 cells in cold PBS at a concentration of 1x107
cells/ml and injected with 200 μL cell suspension intraperitoneally (IP) by inserting the needle into the lower right quadrant of the
abdomen. The tumor burden was assessed by in vivo bioluminescence at 14 days after injection. As for survival assays, tumor-
bearing mice were monitored every two days for signs of disease progression or death. Humane endpoints are defined by a veter-
inarian and euthanized by CO asphyxiation.
2
The bone marrow chimeric APC/DSS spontaneous colorectal cancer model was conducted as previously described.37Briefly, we
crossed Apc-flox mice with Vil1-Cre mice to generate Apcflox/wtVil1-Cre+/- mice. At 6 weeks old, Apcflox/wtVil1-Cre+/- mice were given
a split dose (∼4 hours apart) of lethal irradiation totaling 10.5 Gy prior to transplantation via retro-orbital injection of 2 ×106 unfrac-
tionated whole bone marrow cells harvested from 8-week-old WT or Spp1-KO mice. At 8 weeks old, bone marrow chimeric
e4 Immunity 59, 1–16.e1–e9, May 12, 2026

## Page 22

Please cite this article in press as: Sun et al., An SPP1-SOCS1 pathway constrains interferon responses in tumor-associated macrophages and
shapes an immunosuppressive tumor microenvironment, Immunity (2026), https://doi.org/10.1016/j.immuni.2026.04.001
ll
Article OPEN ACCESS
Apcflox/wtVil1-Cre+/- mice were treated with 2% dextran sodium sulfate (DSS, MP Biomedical, 216011080) in drinking water for
1 week then replaced with regular drinking water for two weeks. And repeated DSS treatment three times to enhance colon tumor
formation. Mice were euthanized 2 weeks later, and the number and size of tumors in the colon were recorded. For survival assays,
tumor-bearing mice were monitored every two days for signs of disease progression or mortality. Humane endpoints were deter-
mined by a veterinarian, and euthanasia was performed using CO asphyxiation.
2
In vivo treatments
For in vivo validation of IL-10/TGF-β blockade, Wild-type C57BL/6J mice were implanted subcutaneously with 1×106 MC38 cells.
Once tumors were measurable, mice were randomized (n = 5/group) to the indicated treatments: Ciforadenant (10 mg/kg, oral
gavage), Galunisertib (75 mg/kg, oral gavage), or vehicle (10% DMSO / 90% corn oil, oral gavage). For IL-10 blockade, anti–IL-
10R (CD210) or isotype IgG control (100 μg/mouse) was administered by peritumoral injection. Tumor dimensions were recorded
every 3 days. At endpoint, tumors were dissociated, TAMs (CD45⁺CD11b⁺F4/80⁺) were sorted by flow cytometry, and Spp1
mRNA was quantified by qPCR.
In the subcutaneous tumor model, para-tumor injections of control IgG (100 μg/mouse, Selleck, A2116) or anti-PD-L1 antibody
(100 μg/mouse, Selleck, A2115) every 3 days, starting at day 8 after tumor injection. In the peritoneal tumor model, tumor-bearing
mice were treated intraperitoneally (i.p.) with WT or Spp1-KO BMDMs starting on day 4 after cancer cell injection. One day later,
mice were treated with IgG, anti-PD-L1 antibody (100 μg/mouse), or a combination of either IgG or anti-PD-L1 antibody with IFN
γ (200 ng/mouse, MCE, HY-P70667). This treatment regimen was repeated starting on day 9. The tumor burden was assessed by
in vivo bioluminescence at 14 days by intraperitoneal injection of D-Luciferin potassium (150 mg/kg, Goldbio, LUCK-2G).
The subcutaneous implantation and group allocation for the in vivo LNP–siRNA study followed the same protocol as the antibody-
treatment experiments. The siRNA (si-SPP1 or si-Ctrl) was formulated into MC3-based LNPs (DLin-MC3-DMA: Chol: DSPC: DMG-
PEG2000 ≈ 50 : 38.5 : 10: 1.5 mol%; mean diameter ∼70–90 nm; PDI < 0.2) and administered by intratumoral injection at 23 μg per
dose, every 2 days. For combination groups, anti–PD-L1 (or IgG control) was co-administered by intratumoral injection at 100 μg per
mouse, once every 3 days, alongside the LNP–siRNA regimen.
Cell culture
MC38 was purchased from Kerafast (Boston, MA; ENH204). CT26 was obtained from ATCC (Manassas, VA; CRL-2638). The above
cell lines were grown in DMEM (Gibco), supplemented with 10% fetal bovine serum (Gibco) and a 1% penicillin/streptomycin mixture
(Gibco), and maintained at 37 ◦C in a humidified atmosphere containing 5% CO .
2
We euthanized the mouse and extracted the femur and tibia to derive bone marrow-derived macrophages (BMDMs) from mice.
The bone marrow was flushed out using a syringe filled with cold PBS and filtered through a 40 μm strainer. The cells were then centri-
fuged and resuspended in RPMI-1640 medium supplemented with 10% FBS, 1% penicillin-streptomycin (PS), and 25 ng/mL M-CSF.
The cells were incubated for 6 days, with media replaced every 3 days to promote differentiation into macrophages. On day 7, the
adherent macrophages were gently harvested by scraping and co-cultured with tumor cells for 48 hours to induce their differentiation
into TAMs. Before the subsequent experiments, the phenotype of TAMs was confirmed through flow cytometry. For hypoxic cell cul-
ture, TAMs were exposed to 1% O₂ for 24 hours prior to harvesting.
In vitro T Cells polarization
For non-IFN γ activated assays, sorting the in vitro-induced WT and Spp1-KO TAMs and seeding them into a 96-well plate at 2000
cells per well for 48 hours of culture. For IFN γ activated assays, seeding them into a 96-well plate at 2000 cells per well and treating
vitro-induced WT and Spp1-KO TAMs with 25 ng/mL IFN γ for 48 hours. Refresh the medium before the co-culture experiment. Naive
CD4+ and CD8+ T cells were isolated from the 6 weeks old wild-type C57BL/6J mouse spleen using a naive T cell isolation kit,
following the manufacturer’s protocol (BioLegend, 480039, 480043). For GZMB+CD8+T cells, resuspend na¨ıve CD8+T cells in
RPMI-1640 medium containing 10% FBS, 1% PS, soluble antibody against CD3 (3 μg/ml, Thermo Fisher, 16-0032-82), soluble anti-
body against CD28 (3 μg/ml, Thermo Fisher, 16-0281-82), IL-2 (20 U/ml, PEPROTECH, 212-12), and IL-12 (20 ng/ml, PEPROTECH,
210-12) at a concentration of 2x105 cells/ml. For Treg cells, resuspend na¨ıve CD4+T cells in RPMI-1640 medium containing 10% FBS,
1% PS, soluble antibody against CD3 (3 μg/ml), soluble antibody against CD28 (3 μg/ml), IL-2 (20 U/mL), and recombinant TGFβ (5 ng/
ml, MCE, HY-P7117) at a concentration of 2x105 cells/ml. For IFNγ+CD4+T cells, resuspend na¨ıve CD4+T cells in RPMI-1640 medium
containing 10% FBS, 1% PS, soluble antibody against CD3 (3 μg/ml), soluble antibody against CD28 (3 μg/ml), IL-2 (20 U/mL), and IL-
12 (20 ng/mL) at a concentration of 2x105 cells/ml. For T cell proliferation, resuspend naı¨ve CD4+T/CD8+T cells in RPMI-1640 medium
containing 10% FBS, 1% PS, soluble antibody against CD3 (1.5 μg/ml), soluble antibody against CD28 (1.5 μg/ml), IL-2 (10 U/mL), at
a concentration of 2x105 cells/ml. Transfer 100 μL of the above cell suspension into a 96-well plate coated with IFN γ activated or non-
activated TAMs and culture for 2.5 days. Assessing T cell polarization using flow cytometry.
T-cell recruitment
WT or Spp1-KO TAMs were seeded in the lower chamber and allowed to condition the medium for 48 h. Purified CD4⁺ or CD8⁺ T cells
were then added to the upper insert. After 5 h, T cells that migrated to the lower chamber were collected and enumerated, and migra-
tion was expressed as the percentage of migrated T cells per condition.
Immunity 59, 1–16.e1–e9, May 12, 2026 e5

## Page 23

Please cite this article in press as: Sun et al., An SPP1-SOCS1 pathway constrains interferon responses in tumor-associated macrophages and
shapes an immunosuppressive tumor microenvironment, Immunity (2026), https://doi.org/10.1016/j.immuni.2026.04.001
ll
OPEN ACCESS Article
Flow Cytometry, staining, and gating strategies
Tumors were minced and digested using the Tumor Dissociation Kit (Miltenyi, 30-096-730) according to the manufacturer’s instruc-
tions. The resulting single-cell suspensions were filtered through 70-μm strainers, washed with cold PBS, and incubated with Fc
blocking antibody (CD16/32, BD Biosciences, 553142) for 10 minutes at 4◦C. Cells were then stained with a cocktail of fluoro-
chrome-conjugated antibodies for 30 minutes at 4◦C. For cell surface staining, DAPI was used to exclude dead cells. For intracellular
staining, dead cells were labeled using the Zombie NIR Fixable Viability Kit (BioLegend, 423105) prior to fixation and staining. The
Foxp3/Transcription Factor Staining Buffer Set (Thermo Fisher, 00-5532-00) was used for subsequent staining procedures. To detect
intracellular IFN γ and GZMB, cell suspensions were incubated in a 96-well plate with Brefeldin A (BioLegend) for 3 hours at 37◦C
before continuing with staining as described. Cells were analyzed on the CytoFLEX LX (Beckman), and sorting was performed using
the FACSAria II (BD Biosciences).
The following gating strategies were applied for the analysis of mouse tumor samples: Total immune cells: DAPI-CD45+; CD4+T
cells: DAPI-CD45+CD3+CD4+; CD8+T cells: DAPI-CD45+CD3+CD8+; NK cells: DAPI-CD45+CD3-NK1.1+; B cells:
DAPI-CD45+CD19+; TAMs: DAPI-CD45+CD11B+F4/80+; DCs: DAPI-CD45+CD11C+MHCII+; Myeloid cells: DAPI-CD45+CD11B+;
NIR-CD45+CD3+CD4+IFNγ+ was used to detect IFN γ in CD4+ T cells, while NIR-CD45+CD3+CD4+CD25+FOXP3+ was used to identify
Tregs, and DAPI-CD45+CD3+CD8+GZMB+ was used to detect GZMB in CD8+ T cells. For the in vitro TAMs and T cell co-culture
model, the following gating strategies were applied: NIR-CD4+CD25+FOXP3+ for Tregs, NIR-CD4+IFNγ+ for IFN γ expression in
CD4+ T cells, and NIR-CD8+GZMB+ for GZMB expression in CD8+ T cells. A complete list of antibodies and reagents used in this
study is provided in the KEY RESOURCES TABLE.
Immunofluorescence staining
Tumor specimens were fixed in 4% paraformaldehyde (PFA) at 4◦C overnight with agitation, then transferred to 70% ethanol for pres-
ervation and subsequently embedded in paraffin. Sections were blocked for 1 hour in 5% BSA and stained using a multiplex immu-
nofluorescence PANO 7-plex IHC kit (Panovue, 10217100100) according to the manufacturer’s instructions. CD45 (D3F8Q) (1:200,
CST, 70257), CD11b (E4K8C) (1:50, CST, 93169), Ly-6G (E6Z1T) (1:100, CST, 87048), NK1.1 (E6Y9G) (1:50, CST, 39197), CD19
(D4V4B) (1:1600, CST, 90176), CD8α (D4W2Z) (1:200, CST, 98941), CD4 (D7D2Z) (1:50, CST, 25229), SPP1 (1:100, Abcam,
ab216406). DAPI staining was performed at room temperature for 10 minutes. The sections were then mounted using ProLong Dia-
mond anti-fade mounting media (Thermo Fisher, P36961). Data acquisition was performed using the VS200 slide scanner, and image
analysis was carried out with Imaris v.9.3.1 and ImageJ software.
Gene expression quantification by real-time PCR
Total RNA was extracted using RNA isolater Total RNA Extraction Reagent (Vazyme, R401-01-AA), followed by cDNA synthesis
through reverse transcription with the PrimeScript RT Reagent Kit and gDNA Eraser (Takara, RR047A). Quantitative PCR (qPCR)
was conducted using the TB Green Premix Ex Taq kit (Takara, RR420A), with Ct values detected by the CFX384 Touch™ Real-
Time PCR Detection System (BioRad). Relative mRNA expression levels were normalized to the internal reference gene 18S. The
primer sequences are listed in Table S3.
In vitro coculture and bulk RNA-seq
In vitro-induced BMDMs were scraped and co-cultured with MC38 tumor cells at a 1:1 ratio for two days. Following co-culture, cells
were harvested and stained with anti-CD45 antibody and DAPI. Tumor cells (DAPI-CD45-) and TAMs (DAPI-CD45+) were subse-
quently sorted, with 2x106 cells from each population collected for RNA sequencing. Total RNA was isolated using Total RNA Extrac-
tion Reagent (Vazyme, R401-01-AA), and full-length cDNA was synthesized using the SMART-Seq HT Kit (Takara; 634436). Libraries
were constructed using the Nextera XT DNA Library Preparation Kit (Illumina, San Diego, CA, USA), and sequencing was conducted
on the Illumina NovaSeq 6000 platform in 100-base single-end mode.
Western blots
WT/Spp1-KO TAMs were treated with 25 ng/ml IFNs for 48 hours and 2x106 cells were lysed in RIPA Lysis and Extraction Buffer
(Thermo Scientific, 89901) supplemented with protease and phosphatase inhibitors, and protein concentrations were quantified us-
ing the Pierce BCA Protein Assay Kit.
To determine whether TRIM21 regulated STAT1 through its ubiquitination function, we treated IFN γ-activated TAMs with 20 nM
autophagy-lysosome inhibitor Bafilomycin A1 or 2.5 nM ubiquitin-proteasome inhibitor Bortezomib for 48 hours. The protein samples
were resolved by SDS-PAGE and transferred onto polyvinylidene fluoride (PVDF) membranes (Roche). Membranes were blocked in
5% BSA and incubated overnight at 4◦C with primary antibodies. The following primary antibodies were used: Anti-β-actin (CST,
4970T, 1:1000), Anti-Stat1 (CST, 14994s, 1:1000), Anti-p-Stat1(S727) (CST, 9177s, 1:1000), Anti-p-Stat1(Y701) (CST, 9167s,
1:1000), anti-Socs1 (CST, 55313S, 1:1000), anti-Socs3 (Abcam, ab280884, 1:1000), anti-Trim21 (Abcam, ab207728, 1:1000) and
anti-Flag (CST,55313S, 1:1000). After TBST washing, membranes were incubated with HRP-conjugated secondary antibodies
(CST, 7074S, 1:5000), and signals were visualized using Clarity Western ECL Substrate (Bio-Rad). Western blot data were analyzed
using ImageJ software. All raw western blot images are provided in Figure S10.
e6 Immunity 59, 1–16.e1–e9, May 12, 2026

## Page 24

Please cite this article in press as: Sun et al., An SPP1-SOCS1 pathway constrains interferon responses in tumor-associated macrophages and
shapes an immunosuppressive tumor microenvironment, Immunity (2026), https://doi.org/10.1016/j.immuni.2026.04.001
ll
Article OPEN ACCESS
Ectopic gene expression in macrophages using in vitro transcribed mRNA
pCDNA3.1(+)-intracellular Spp1-3xFlag, pCDNA3.1(+)-extracellular Spp1-3xFlag and pCDNA3.1(+)-Trim21-3xFlag plasmids were
generated as PCR templates (IGEbio). We designed forward and reverse primers specific to the flag-tagged intracellular Spp1, secreted
Spp1 and Trim21 mRNA, appending the T7 RNA polymerase promoter sequence (T7) [5′-AGTAATACGACTCACTATAGGG-3′] up-
stream of the forward primer. The T7 DNA templates were amplified following the instructions of SMART-Seq HT Kit (Takara;
634436), and the PCR products were purified using the QIAquick Gel Extraction Kit (QIAGEN; 28704) according to the manufacturer’s
instructions. The mRNA fragments were then transcribed in vitro using the mMESSAGE mMACHINE™ T7 Transcription Kit according to
the manufacturer’s protocol (Thermo Scientific, AM1344). The in vitro transcribed mRNA fragments were purified and quality-checked.
Next, transfect 1 μg intracellular Spp1-3xFlag, secreted Spp1-3xFlag or Trim21-3xFlag mRNA into 2x106 Spp1-KO or WT TAMs using
the Lipofectamine™ MessengerMAX™ Transfection Reagent (Thermo Scientific, LMRNA003).
Co-IP assay
Spp1-KO TAMs were transfected with intracellular Spp1-3XFlag mRNA, and 24 hours post-transfection, the cells were treated with
25 ng/mL of IFN γ to activate the TAMs for an additional 48 hours. Following activation, 1x108 TAMs were washed with cold PBS and
lysed using lysis buffer. To avoid interference from the light and heavy chains, co-immunoprecipitation was carried out using Anti-
Flag Nanobody IP kit (Magarose) (AlpaLifeBio, KTSM1361), following the manufacturer’s instructions. The precipitated proteins
were subsequently utilized for Western blot or mass spectrometry analysis.
LC–MS/MS analysis
Proteins immunoprecipitated using Anti-Flag and negative control beads were digested with trypsin for 16 hours at 37◦C with agita-
tion at 600 rpm in darkness. After desalting, the resulting peptides were lyophilized and analyzed by ultra-high-performance liquid
chromatography (Acquity, Waters) coupled to a Q Exactive Plus Hybrid Quadrupole-Orbitrap Mass Spectrometer (Thermo Fisher).
Data analysis was performed using Proteome Discoverer software.
Foci formation
Seeded 1.5 ×10⁶ WT or Spp1-KO TAMs into 6-well plates and cultured them for two days. After incubation, collected the supernatant
and diluted it 1:1 with fresh DMEM medium containing 10% FBS and 1% PS to prepare the TAMs-conditioned medium. Next, seeded
500 MC38 or CT26 cells per well into 6-well plates and added 2 mL of TAMs-conditioned medium to each well. Replaced the WT or
Spp1-KO TAMs-conditioned medium every two days. On day eight, fixed and stained the cells with crystal violet, then quantified the
colony numbers.
siRNA-mediated silencing
TAMs were transfected with 25 nM siRNA for 24 hours using HiPerFect Transfection Reagent (QIAGEN, 301704), following the man-
ufacturer’s instructions. The cells were then stimulated with 25 ng/mL IFNs for 48 hours prior to PCR or Western blot analysis.
Human scRNAseq data collection and quality control
Monocyte and macrophage Single-cell transcriptomic data of 12 cancer types from 15 studies,6,9,13,14,18–28 covering PBMC, adja-
cent normal tissues and tumors, were collected and quality controlled by removing cells expressing less than 800 genes. ICB treat-
ment-related single-cell transcriptomic data were acquired from public studies.7,31–34 Processed expression matrices of TAMs were
extracted for analyses. The CRC single-cell atlas was obtained from our previously published data.62
TCGA data collection
Gene expression matrix in TPM format of each cancer type was acquired from TCGA database (https://portal.gdc.cancer.gov/) using
the R package TCGAbiolinks (v2.22.4) in December 2022.
Clustering and cell subset identification in human scRNAseq data
For constructing the monocyte and macrophage single-cell atlas, an R package Seurat (v5.0.1)63was applied first for normalization
and highly variable gene identification. The top 2000 variable genes excluding mitochondrial genes were next scaled for principal
compartment analysis (PCA). We corrected the top 30 principal components (PCs) by different datasets using Harmony (v1.1.0)64
and the corrected PCs were used for cell clustering by constructing a K nearest neighbor (KNN) graph with default settings and res-
olution = 0.4 and for visualization with a Uniform Manifold Approximation and Projection (UMAP) approach. Marker genes for each
cell subset were identified using Wilcoxon rank-sum tests on the genes expressed in >25% of the cells. P values of multiple tests were
corrected using the Benjamini-Hochberg approach and genes with adjusted p value less than 0.05 and log2 fold change larger than
0.5 were considered to be upregulated genes.
Tissue preference evaluation of monocyte and macrophage subsets
To detect the tissue preference of each monocyte and macrophage subset, a ratio of observed/expected (Ro/e) cell numbers was
calculated. The expected cell numbers were obtained from the chi-square test, as previously described.29,30
Immunity 59, 1–16.e1–e9, May 12, 2026 e7

## Page 25

Please cite this article in press as: Sun et al., An SPP1-SOCS1 pathway constrains interferon responses in tumor-associated macrophages and
shapes an immunosuppressive tumor microenvironment, Immunity (2026), https://doi.org/10.1016/j.immuni.2026.04.001
ll
OPEN ACCESS Article
Mouse single-cell transcriptome sequencing
To examine changes in the tumor microenvironment following SPP1 knockout in TAMs, DAPI-CD45+ and DAPI-CD45- cells were
sorted from MC38 subcutaneous tumors. After staining with Trypan blue, cells were counted, and 10,000 live cells were loaded
onto a Chromium Chip A (10X Genomics, PN 230027). GEM generation, cDNA synthesis, amplification, and library preparation
were conducted using the Chromium Single Cell 5’ Reagent Kit (10X Genomics, PN 1000006), following the manufacturer’s protocol.
Indexed libraries were pooled in equimolar ratios and sequenced on a NextSeq 500 in a 26 bp/91 bp paired-end run with the NextSeq
500/550 High Output Kit v2.5 (150 cycles, Illumina).
Mouse models scRNAseq data preprocessing and quality control
CellRanger v6.12 (10x Genomics) was applied to process raw sequencing data with default settings and reads from single cells were
aligned to the mm10 reference genome. Next, Seurat was applied to analyze the gene expression matrix. To acquire an accurate cell
type annotation, for conditional Spp1-KO data, CD45+ cells with less than 800 detected genes and with more than 20% mitochondrial
counts were excluded and for the mix model data, CD45+ cells with less than 500 detected genes and with more than 10% mitochon-
drial counts were excluded. The potential doublets, which co-expressed different well-known cell type marker genes, were also
filtered out, leaving 17659 cells for conditional Spp1-KO data and 12298 cells for the mix model. CD45- cells of the conditional
Spp1-KO data expressing less than 2000 genes and more than 20% mitochondrial counts were excluded, ending up with 15275 cells
in the downstream analysis.
Clustering and cell subset identification in mouse models’ scRNAseq data
By applying Seurat, we clustered and annotated cell subsets following the procedure below. First, we normalized the count matrix
and identified the top 2000 variable genes, the expression levels of which were next scaled and used for PCA. The first 20 PCs were
used to construct KNN graph with default settings and resolutions ranging from 0.5 to 1 were selected for cell clustering. For visu-
alization, UMAP was implemented on the first 20 PCs. Finally, cell types were identified based on the expression pattern of canonical
markers and over-presentative genes in each cell cluster. We first went through the procedure to identify major cell types in CD45+
cells and CD45- cells respectively. Then we followed the procedure again to identify cell subsets within myeloid cells and lympho-
cytes of CD45+ cells respectively. Marker genes for each cell subset were identified using Wilcoxon rank-sum tests on the genes
expressed in >25% of the cells. P values of multiple tests were corrected using the Benjamini-Hochberg approach and genes
with adjusted p value less than 0.05 and log2 fold change larger than 0.5 were considered to be upregulated genes.
Differential expression analysis in mouse models of scRNA-seq data
To identify differentially expressed genes between different treatment groups, we applied Wilcoxon’s tests using the function ‘‘Find-
Markers’’ from Seurat on genes expressed in >25% of the cells from any group, and P values of multiple tests were corrected using
the Benjamini-Hochberg approach. Genes with adjusted p value less than 0.05 and log2 fold change larger than 0.5 were considered
to be differentially expressed genes.
Bulk RNA-seq data analysis
Sequencing reads were first filtered by fastp (v0.18.0)65to remove reads containing adapters, containing more than 10% unknown
nucleotides, or containing more than 50% of low-quality (Q-value≤20) bases. Next, HISAT2 (v2.4) was applied for alignment to the
mouse reference genome (Ensembl_release107). The mapped reads were assembled and quantified using StringTie (v1.3.1)66and
RSEM (v1)67respectively. To perform differential expression analysis, an R package DESeq2 (v1.42.0)68was applied, and the genes
with FDR less than 0.05 and absolute fold change≥2 were considered differentially expressed.
Gene ontology (GO) and Hallmark term enrichment analysis
To identify over-represented GO biological processes and Hallmark terms, an R package clusterProfiler v4.10.0 was applied and p
values adjusted with the Benjamini-Hochberg approach less than 0.05 were considered statistically significant.
Gene set variation analysis (GSVA) and scoring of signature genes
To estimate the variation of GO or Hallmark terms enrichment in scRNAseq data, an R package GSVA (v1.50.0) was applied with the
method ‘‘ssgsva’’. The scores of different groups of cells for each term were next compared using two-sided unpaired t-tests with p
values corrected using the Benjamini-Hochberg approach, and FDR values less than 0.05 were considered statistically significant. To
evaluate the signature of interesting cell subsets and biological pathways, the signature gene lists were acquired from previous
studies9,69,70and an ‘‘AddModuleScore’’ function from Seurat was implemented on the expression values of each cell.
Macrophage type inference
To estimate the similarity of TAMs to M1 macrophages and M2 macrophages, we downloaded the single-cell transcriptomic data of
in vitro induced M1, M2 and unpolarized macrophages at 24h after treatments from a public study.41The top 50 marker genes with
the largest log2 fold changes were first identified using the ‘‘Find All Markers’’ function from Seurat. Then an R package SingleR
(v2.4.1)71was applied taking this data as the reference to annotate each TAMs to either M1, M2, or unpolarized macrophage with
only max prediction scores > 0.3 were kept for downstream analysis.
e8 Immunity 59, 1–16.e1–e9, May 12, 2026

## Page 26

Please cite this article in press as: Sun et al., An SPP1-SOCS1 pathway constrains interferon responses in tumor-associated macrophages and
shapes an immunosuppressive tumor microenvironment, Immunity (2026), https://doi.org/10.1016/j.immuni.2026.04.001
ll
Article OPEN ACCESS
Cell-cell interaction inference
We used Cell Chat (v1.6.1)72to identify cell-cell interactions between cell types with more than 50 cells for each group with default
settings.
Other visualization
The R package ggplot2 (v3.4.2) and Seurat were applied for most visualizations. The package pheatmap (v1.0.12) was used to
generate most heatmaps and the package Venn Diagram was used to generate the Venn diagram (v1.7.3).
STATISTICAL ANALYSIS
For statistical analysis, Student’s t-test (two-tailed) was used for experiments with only two groups. For experiments with more than
two groups, one-way ANOVA with multiple comparisons was performed. Survival analysis was conducted using the Kaplan–Meier
method and the log-rank test. Data are expressed as mean ± SEM, with statistical significance defined as *p < 0.05, **p < 0.01,
***p < 0.001, and ****p < 0.0001.
Immunity 59, 1–16.e1–e9, May 12, 2026 e9