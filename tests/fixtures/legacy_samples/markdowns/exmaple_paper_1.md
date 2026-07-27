# exmaple_paper_1.pdf

## Page 1

Letter
https://doi.org/10.1038/s41586-018-0694-x
Lineage tracking reveals dynamic relationships of
T cells in colorectal cancer
Lei Zhang1,6, Xin Yu2,6, Liangtao Zheng1,6, Yuanyuan Zhang3,6, Yansen Li4, Qiao Fang1, ranran Gao3, Boxi Kang3, Qiming Zhang3,
Julie Y. Huang2, Hiroyasu Konno2, Xinyi Guo3, Yingjiang Ye4, Songyuan Gao5, Shan Wang4, Xueda Hu3, Xianwen ren3,
Zhanlong Shen4*, Wenjun Ouyang2* & Zemin Zhang1,3*
T cells are key elements of cancer immunotherapy1 but certain differentiation, respectively, which are essential for anti-tumour immu-
fundamental properties, such as the development and migration nity by T cells (Extended Data Fig. 1b, Methods).
of T cells within tumours, remain unknown. The enormous T cell We obtained transcriptome data for 11,138 single T cells from
receptor (TCR) repertoire, which is required for the recognition of 12 patients with CRC, including 4 MSI and 8 MSS patients (Extended
foreign and self-antigens2, could serve as lineage tags to track these Data Figs. 1a, 2a, Supplementary Table 1). Genomic alterations
T cells in tumours3. Here we obtained transcriptomes of 11,138 single of these tumours were consistent with the characteristics of CRC
T cells from 12 patients with colorectal cancer, and developed single from The Cancer Genome Atlas (TCGA)12 (Extended Data Fig. 2b,
T cell analysis by RNA sequencing and TCR tracking (STARTRAC) Supplementary Table 2). CD8+ T cells, CD4+CD25−/int T cells and
H
indices to quantitatively analyse the dynamic relationships among CD4+CD25hi T cells were assessed by multi-colour immunohisto-
reg
20 identified T cell subsets with distinct functions and clonalities. chemistry (IHC) (Extended Data Fig. 1c) and collected by fluores-
Although both CD8+ effector and ‘exhausted’ T cells exhibited cence-activated cell sorting (FACS) before deep single-cell RNA-seq
high clonal expansion, they were independently connected with analyses (Extended Data Fig. 1a, d, Methods). Overall, we obtained an
tumour-resident CD8+ effector memory cells, implicating a TCR- average of 1.25 million uniquely mapped read pairs (Extended Data
based fate decision. Of the CD4+ T cells, most tumour-infiltrating Fig. 3a, b, Supplementary Table 3). After a series of quality control
T regulatory (T ) cells showed clonal exclusivity, whereas certain filtering, 10,805 cells remained—of which 91.4% had at least one pair
reg
T cell clones were developmentally linked to several T helper (T ) of full-length productive α and β chains (Extended Data Fig. 3c, d,
reg H
cell clones. Notably, we identified two IFNG+ T 1-like cell clusters Supplementary Table 4). There were 7,274 clonotypes, each of which
H
in tumours that were associated with distinct IFNγ-regulating had unique productive α–β chain pairs and out of which 870 were
transcription factors —the GZMK+ effector memory T cells, which represented by two or more cells that resulted in 3,474 clonal T cells.
were associated with EOMES and RUNX3, and CXCL13+BHLHE40+ A total of 8 CD8+ and 12 CD4+ T cell clusters were identified,
T 1-like cell clusters, which were associated with BHLHE40. each exhibiting a distinct distribution of clonotypes and clonal T cells
H
Only CXCL13+BHLHE40+ T 1-like cells were preferentially (Fig. 1a, Extended Data Fig. 3e). The stability of clusters was supported
H
enriched in patients with microsatellite-instable tumours, and this by different clustering methods, down-sampling analysis (Extended
might explain their favourable responses to immune-checkpoint Data Fig. 3f, g) and distinct signature genes (Extended Data Fig. 4a–c,
blockade. Furthermore, IGFLR1 was highly expressed in both Supplementary Table 5). In addition to typical CD8+ and CD4+ T
CXCL13+BHLHE40+ T 1-like cells and CD8+ exhausted T cells and cell clusters including naive (T ), central memory (T ) and effector
H N CM
possessed co-stimulatory functions. Our integrated STARTRAC memory (T ) T cells, recently activated effector memory or effector
EM
analyses provide a powerful approach to dissect the T cell properties T cells (T /T , designated T hereafter), mucosal-associated
EMRA EFF EMRA
in colorectal cancer comprehensively, and could provide insights invariant T (MAIT) cells, blood-T cells, tumour-T cells, and
reg reg
into the dynamic relationships of T cells in other cancers. dysfunctional or ‘exhausted’ CD8+ T (T ) cells, we also identified
EX
Tumour-infiltrating lymphocytes are highly heterogeneous with two IFNG+ T 1-like cell clusters, with the CD4_C07-GZMK cluster
H
respect to their cell-type compositions, gene expression profiles and expressing several markers of T cells (designated as CD4+ T
EM EM
functional properties, which might contribute to diverse responses to cells) and the CD4_C09-CXCL13 cluster showing higher expres-
cancer immunotherapies1. Recent clinical trials have demonstrated that sion of CXCL13 and BHLHE40 (designated as CXCL13+BHLHE40+
patients with colorectal cancer (CRC) who display microsatellite insta- T 1-like cells; Extended Data Fig. 5a). In contrast to the hepatocel-
H
bility (MSI) but not microsatellite-stable (MSS) phenotypes respond to lular carcinoma (HCC) and non-small-cell lung carcinoma (NSCLC)
the immune-checkpoint blockade of PD-14, but the underlying mecha- datasets9,10, we found additional T cell subsets, including T 17 (CD4_
H
nisms are not fully understood5–7. Several single-cell RNA sequencing C08-IL23R), follicular T helper cells (CD4_C06-CXCR5), follicular
(RNA-seq) studies have revealed diverse subsets and functions of T cells T regulatory cells (CD4_C11-IL10), and two additional subsets of CD8+
in various cancer types8–10. Here we developed an integrated approach, T cells (CD8_C05-CD6 and CD8_C06-CD160). The latter two highly
STARTRAC, to track further the dynamic relationships among T cell expressed CD69 and ITGAE, known markers of tissue-resident memory
subsets identified inside colorectal carcinoma, adjacent normal mucosa T (T ) cells13 (Extended Data Fig. 5b). Whereas CD8_C05-CD6
RM
and peripheral blood, based on both single-cell transcriptome and TCR probably represented lamina propria T cells13, CD8_C06-CD160
RM
α- and β-chain sequences as lineage-specific markers2,11 (Extended was characterized as intraepithelial lymphocytes (IELs) based on the
Data Fig. 1a, b). STARTRAC incorporated several unique indices, highly expressed natural killer cell markers14.
including STARTRAC distribution (dist), expansion (expa), migration Our STARTRAC-dist index revealed distinct patterns of tissue distri-
(migr) and transition (tran), to quantitatively describe tissue distri- bution of different T cells (Fig. 1b, Extended Data Fig. 5c, d). Within the
bution, clonal expansion, migration and developmental transition or CD8+ subtypes, T , T and T cells were predominantly enriched
N CM EMRA
1Beijing Advanced Innovation Centre for Genomics, Peking-Tsinghua Centre for Life Sciences, Peking University, Beijing, China. 2Department of Inflammation and Oncology, Discovery Research,
Amgen, South San Francisco, CA, USA. 3BIOPIC and School of Life Sciences, Peking University, Beijing, China. 4Department of Gastroenterological Surgery, Peking University People’s Hospital,
Beijing, China. 5Department of Pathology, Peking University People’s Hospital, Beijing, China. 6These authors contributed equally: Lei Zhang, Xin Yu, Liangtao Zheng, Yuanyuan Zhang.
*e-mail: shenlong1977@163.com; wouyang@amgen.com; zemin@pku.edu.cn
268 | NAtUre | VOL 564 | 13 DeCeMBer 2018
© 2018 Springer Nature Limited. All rights reserved.

## Page 2

Letter reSeArCH
T cell clusters
40 20
0 –20 –40
in blood (Fig. 1b). T cells were specifically enriched in tumours, The STARTRAC-migr analysis of CD8+ clusters revealed that T
EX EMRA
whereas two subsets of T cells were predominantly found in nor- cells were associated with the highest mobility, followed by T cells,
RM EM
mal mucosa. Likewise, among CD4+ subtypes, naive and effector-like and both clusters had higher mobility than T cells (Fig. 1e, Extended
EX
cells were enriched in blood. Follicular T helper cells were enriched in Data Fig. 7a). Furthermore, pairwise STARTRAC-migr analyses
normal mucosa, whereas two IFNG+ T 1-cell-like subsets and T 17 revealed a high degree of TCR sharing of T cells among blood,
H H EMRA
cells were enriched in tumours. Three FOXP3+ T cell clusters, CD4_ normal mucosa and tumours, whereas T exhibited tumour exclusivity
reg EX
C10-FOXP3, CD4_C11-IL10 and CD4_C12-CTLA4, were enriched in (Fig. 1f). Accordingly, these clusters expressed different sets of genes
blood, normal mucosa and tumours, respectively. related to migration18, including chemokine receptors, integrin and
Focusing on CD8+ T cells, the STARTRAC-expa index revealed other trafficking-related molecules such as S1P receptors (Extended
the CD8+ T and T cells as the clusters with the highest degree Data Fig. 7b). For example, T cells highly expressed S1PR1, S1PR5
EX EMRA EMRA
of clonal expansion, followed by IELs (Fig. 1c). T cells in CRC and ITGB7, which supports their capability to circulate in the periphery
EX
contained the highest percentage of proliferative cells (Fig. 1d), and and home to normal mucosa and tumours.
enriched with MKI67hi cells and proliferation-related pathways, Although T cells also expressed many effector molecules such
EMRA
as confirmed by IHC (Extended Data Fig. 6a–c), although these as PRF1, GZMB and GZMH, they did not express T cell markers
EX
high-proliferative cells resembled the low-proliferative cells with such as PDCD1 and HAVCR2 (also known as TIM3) (Extended Data
respect to the expression of key genes, including TBX21, EOMES and Fig. 6g). Notably, STARTRAC-tran analysis indicated that both T
EMRA
PDCD115 (Extended Data Fig. 6d, e). Consistently, although 79.26% and T cell clusters were highly associated with T cells (Fig. 1g,
EX EM
of high-proliferative cells were clonal, most of their clonotypes (40 out Extended Data Fig. 8a). T cells were only linked to T cells, but
EX EM
of 46) were shared with low-proliferative cells (Extended Data Fig. 6f); both T and T cells were associated with T cells (Extended
EMRA EM CM
this suggests that proliferative status was not a distinguishing feature, Data Fig. 8b). Furthermore, T cells were also moderately connected
EM
as was observed between progenitor and terminally differentiated to normal-enriched T cells. Accordingly, Monocle trajectory anal-
RM
exhausted states from chronic infections15. Furthermore, although ex ysis of these CD8+ cell clusters also corroborated a developmental
vivo reactivation experiments have demonstrated that these CD8+ T trajectory from T cells to either T or T cells (Extended Data
EX EM EMRA EX
cells produce less effector cytokines16, our analyses revealed that these Fig. 8c).
cells expressed higher levels of effector molecules—such as IFNG, The transition from T to T cells may predominantly occur in
EM EX
GZMB, GZMH and PRF1—than other CD8+ subsets (Extended Data tumours based on their tissue distribution patterns (Fig. 1b). Although
Fig. 6g); this indicates that T cells may not have completely lost their only 19.35% (24 out of 124) of T cell-expanded clonotypes had
EX EMRA
anti-tumour effector potential in vivo. Several transcription factors clonal cells located inside tumours, 44.35% (55 out of 124) were linked
were preferentially expressed in the CD8+ T cell subset. Although to tumour-infiltrating T cells, whereas only 5.65% (7 out of 124) were
EX EM
PRDM1 and BATF were the only previously known factors17, RBPJ, associated with blood T cells (Extended Data Fig. 8d, Supplementary
EM
TOX and BHLHE40 were functionally uncharacterized in T cells Table 6); this supports the developmental connection between T
EX EMRA
(Extended Data Fig. 6g). cells and tumour T cells. Notably, tumour T cell clones linked to
EM EM
2 miD ENS-t
a Clonal T cells b Blo S o T d A N RT o R rm A a C l - T d u is m t our Ro/e0 Max.
CD8_C07 CD4_C07 CD4_C09 CD4_C08 C C D C C D 4_ D D 4 C C _ 4 4 C D C 1 _ _ D 4 C C 2 1 4 _ 1 0 0 C _ 6 5 C 1 0 0 4 + + + + + – + – + + + / + – + + + + + + + + + + + + + / + / / + – – – + + + + + + + + + + + / + + + / – – + + C C C C C C C C D D D D D D D D 8 8 8 8 8 8 8 8 _ _ _ _ _ _ _ _ C C C C C C C C 0 0 0 0 0 0 0 0 3 2 8 1 6 7 4 5 - - - - - - - - C G S L C L G C E A L X D D P Z Y F C 3 M R 1 6 1 N C 4 6 1 K ( A T 0 ( R 8 ( T T R 1 ( 3 1 ( N T M E I 0 E ) E ( X ( ) T T M ) L (M C E ) ) M M A ) R I A T / ) TEFF)
t C C – - D D S 4 8 8 N 0 _ _ C C E C 0 0 6 D 4 D 8_C im 0 C 5 D 1 8 – _ C C 2 D 0 0 8 8_C03 C 0 D4_C03 CD8_C02 20 C C D C D 8 D _ 4 4 C _ _ C 0 C 1 0 0 2 1 –40 –20 0 20 + + + + + + – – + + – – + + + + / / / / – – – – + + + + + + + + + + + + + + + + + / / + + + / / – – – – + + + + + + + + + + + + + + + + / + + / / / + + + – – – – + + + + + C C C C C C C C C C C C D D D D D D D D D D D D 4 4 4 4 4 4 4 4 4 4 4 4 _ _ _ _ _ _ _ _ _ _ _ _ C C C C C C C C C C C C 0 1 0 0 1 0 0 1 0 0 0 0 1 2 3 9 1 2 8 0 6 5 4 7 - - - - - - - - - - - - C C G C I A I F C C T G L L O C N C T X X X N Z 1 2 L F C X C C X 0 3 M R L A 7 Y R P A L R R 7 ( K T 4 3 1 1 ( 5 6 ( ( ( N F T T 3 ( T ( ( R T ( ( ( T E P . P H N T T ) T ( E . M . . 1 T ) T F R T M T C R 7 H H M r r C M / e e A ) 1 ) T g ) M g ) / - ) H ) T ) l 1 i E k F - e F li ) k c e e l c ls e ) lls)
c d e
0.4
0.3
0.2
0.1
0.0
apxe-CARTRATS
1.00 0.6
0.75 0.4
0.50
0.2 0.25
0.0 0.00
TN TCM TEMRATEM TRM IEL TEX
rgim-CARTRATS
h TEM TEX
TCRsharing TEM and TEMRA TEM and TEX
TEM, TEMRA and TEX Cells ≥8 7 6 5 4 3 2 1 0
f g
......
TEMRA
P1212_C000029:48 P0825_C000095:24 Clonotypes
nart-CARTRATSp
Blood Tumour
CD8_C04-GZMK TEM
*** * P ** = P 2 = . 1 5 2 .3 × 9 1 × 0 1 –4 0 –5 *** P = 5.98 × 10–5 *** P = 2.1 × 10–7 *** P = 1.39 × 10–4 0.10 *** P = 1.96 × 10–4
*** P = 3.81 × 10–5 *** P = 3.81 × 10–5
0.05
0.00 0.00 0.05 0.10 0.15
Frequency of proliferative cells
apxe-CARTRATS
TEMRA TEX 0.6
IEL 0.4
TRM
TEM 0.2
T T N CM 0.0
rgim-CARTRATSp
Blood–tumour Blood–normalNormal–tumour
*** ** NS P = 1.25 × 10–4 P = 0.0029 * P = 0.0228 NS NS
TN TCM TEMRATEM TRM IEL TEX TEMRA TEM TEX TCM TEMRATRM IEL TEX
Fig. 1 | Properties of CD8+ T cell clonal expansion, migration and (y axis). e, Migration potentials of CD8+ T cell clusters quantified by
developmental transition. a, Left, t-distributed stochastic neighbour overall STARTRAC-migr indices for each patient (n = 12). f, Comparison
embedding (t-SNE) plot of 8,530 T cells from 12 patients with CRC of migration potentials of CD8+ TEMRA, TEM and TEX cells by pairwise
showing 20 major clusters (8 for 3,628 CD8+ and 12 for 4,902 CD4+ STARTRAC-migr (pSTARTRAC-migr) indices for each patient (n = 12).
T cells; functional interpretations in Extended Data Fig. 5d). Right, g, Developmental transition of CD8+ TEM cells with other CD8+ cells
highlighted clonal T cells (n = 3,065). Each dot denotes an individual quantified by pairwise STARTRAC-tran indices for each patient (n = 12).
T cell; colour denotes cluster origin. b, Tissue preference of each cluster ***P < 0.001, Kruskal–Wallis test. h, The distribution of clonal clonotypes
estimated by the STARTRAC-dist index. +++, Ro/e > 1; ++, 0.8 < in indicated CD8+ subsets. Tumour TEM cells showing mutually exclusive
Ro/e ≤ 1; +, 0.2 ≤ Ro/e ≤ 0.8; +/−, 0 < Ro/e < 0.2; −, Ro/e = 0; in which Ro/e TCR sharing with blood TEMRA and tumour TEX cells (Extended Data
denotes the ratio of observed to expected cell number. N, normal tissue; P, Fig. 8e). NS, not significant. *P < 0.05, **P < 0.01, ***P < 0.001, two-
peripheral blood; T, tumour. c, Clonal expansion levels of CD8+ clusters sided Wilcoxon test (c, e and f). For box plots in all figures, centre lines
quantified by STARTRAC-expa for each patient (n = 12). d, Frequencies denote median values; whiskers denote 1.5 × the interquartile range;
of proliferative CD8+ T cells (x axis) versus the STARTRAC-expa index coloured dots denote outliers.
13 DeCeMBer 2018 | VOL 564 | NAtUre | 269
© 2018 Springer Nature Limited. All rights reserved.

## Page 3

reSeArCH Letter
40
20
0
–20
–40 –40 –20 0 20
t-SNE Dim 1
blood T cells were mutually exclusive with those linked to T highest clonal expansion (Fig. 2a). This cluster contained signature
EMRA EX
cells (Fig. 1h, Extended Data Fig. 8e). This pattern was also confirmed genes that include NKG7, PRF1, GNLY and GZMH—a signature that
in individual patients (Extended Data Fig. 8f). Thus, TCR clonotypes is profoundly similar to that of CD8+ T cells (Fig. 2b, Extended
EMRA
may have a role in determining the developmental trajectories between Data Fig. 9a); CD4_C03-GNLY cells were therefore designated as CD4+
T and T cells and between T and T cells. T cells. Notably, the CD4_C03-GNLY cluster showed migration
EM EX EM EMRA EMRA
In contrast to CD8+ cells, CD4+ cells exhibited lower clonal expan- properties that were comparably high to those of CD8+ T cells
EMRA
sion overall. Among all CD4+ clusters, CD4_C03-GNLY exhibited the (Fig. 2c), and it was linked to the CD4+ T population (Fig. 2d).
EM
apxe-CARTRATS
rgim-CARTRATS
nart-CARTRATSp
CD4_C03-GNLY TEMRA
Tumour Treg
TH17 P0215:C0
00031:6
P0701:C000112:3
2 miD
ENS-t
a 0.3 *** P = 2.25 × 10– * 4 P = 0. * 0 * 1 * * 5 P P 5 = = 0 3 . . 0 5 2 1 5 × 8 10–5 b CD C 8 D _C 8_ 0 C C 8 C D 0 − D 4 4 S _ 8 − L C C _ G C C D 0 Z 4 7 0 8 M A − 6 _ 1 G − C K 0 C 0 Z T M 5 D ME − 1 M A K C 6 I T 0 T D E 6 I M E T LRM CD8_ C C D 0 4 3 _ − C C 0 X 3 C 3 − D C C G C 4 R D N _ D 1 4 C L _ 8 T Y 1 C _ E 2 C 0 T M − 8 0 E R C M − A 7 / R T − I T L A L L E 2 / A A T F 3 F Y 4 E R F N T F T . T T H r E 1 e X g 7
0.2
CD4_C09−CXCL13 TH1-like
CD4_C01−CCR7 TN
0
0
.
.
0
1 CD
C
C 8
D
_ D
4
C 8
_
0 _
C
2 C
C 0
− 0
2 D
G 1
− 4
− P
A _
L R
N C
E 1
X 1
F 8
0 A
1 3
− 1
T T
F
N
P
C
O .
M
T X C P M 3 P.Treg CD4_ C C D 0
C C
4 4 _
D D
− C
4 4
T 0
_ _
C 5
C C
F −
0 1
7 C
6 1
N X
− −
C .
C I
T
L
R
X 1
C
C
M 6
0 R
T
T 5
R
FR
M
TFH
Di s
0
t
.
a
0
n
1
ce
d f RORC
0.15 ***P = 4.7 × 10–4
0.10 c **P = 0.0065 Exp
*** P = 4.56 × 10–4 * P = 0.0158 0.05 1 8 0
0.6 4 6 0.00 2
0 0.4
0.2 e RORC
0.0
noisserpxE
TNFRSF9 TIGIT SATB1
* P = 0.014 * P = 0.033 *P = 0.019 **P = 0.0028
10 Tumour Treg
5 Linked to TH17 Linked to TH1-like cells
0 Intracluster hi-expansion
NT
NT
MCT.P
MCT.P
ARMET
ARMET
MCT.N
MCT.N
MRT
MRT
HFT
HFT
MET
MET
71HT
71HT
ekil-1HT
ekil-1HT
gerT.P
gerT.P
RFT
RFT
gerT.T
gerT.T
MCT.P MCT.N MRT HFT MET 71HT ekil-1HT gerT.P RFT gerT.T
Fig. 2 | Properties of CD4+ T cell clonal expansion, migration and expression of a series of genes in three tumour Treg cell subpopulations that
developmental transition. a, Clonal expansion levels of CD4+ T cell shared TCRs with TH17 cells (n = 9 cells), CXCL13+BHLHE40+ TH1-like
clusters quantified by STARTRAC-expa indices for each patient (n = 11). cells (n = 5) and exclusive to their own respective group (n = 228).
b, Similarities of the signature gene expressions of T cell clusters. *P < 0.05, **P < 0.01, two-sided Student’s t-test. f, Representative
Distance = (1 − Pearson correlation coefficient)/2. c, Migration potentials clonotypes of tumour Treg cells (n = 1,320) with high expression of RORC
of CD4+ T cell clusters quantified by overall STARTRAC-migr indices (coloured dots in ellipse) and shared TCRs with TH17 cells (n = 244).
for each patient (n = 11). d, Developmental transition of CD4+ TEMRA Red denotes Treg cells; blue denotes TH17 cells. Exp, centred normalized
cells with other CD4+ cells quantified by pSTARTRAC-tran indices for expression. *P < 0.05, **P < 0.01, ***P < 0.001, two-sided Wilcoxon
each patient (n = 10). ***P < 0.001, Kruskal–Wallis test. e, Normalized test (a, c).
CRC CD4+ TEM TH17 TH1-like 0.75 HCC *P = 0.024
NSCLC 0.50 0.15
0.25
0.00 0.00
CD8_C04−GZMK CD8_C05−ZNF683 CD8_C06−LAYN CD4_C12−CTLA4 MSS MSI MSS MSI MSS
Tumour TEM Tumour TRM Tumour TEX Treg
124 GZMK ITM2C Fals C e XCL13 0.20 0.08 0.20 P = 0.023
TNFRSF18
0.10 0.04 0.10
RBPJ
40
SLAMF7 S100A4 0.00 0.00 0.00
GPR183 NR3C1 CD7 SNX9 MSIMSS TC P 2 L N EK FKBP5 TM T E N M FR 17 S 3 F4
20 EOMES AOAH IGFLR1 KLRB1 DNAJB1 CST7C S L A D M N D D 3 1 H H A B O H V P C L X H R E 2 40 0.10
NKG7 SIRPG RUNX3 GZMB 0.05 0
–1
T
0
umour
–
C
5
D4+ TEM
0 5
C TH D 1 4 - + li k T e EM
0.00
0.00 0.05 0.10 0.15
Frequency of proliferative cells
apxe-CARTRATS
*P = 0.033
**P = 0.0031 ***P = 5.1 × 10–4 *P = 0.014 P = 0.087 P = 0.93 P = 0.073
P = 0.79 P = 0.072 15
10
5
0 CD4+ T cells
TEMRA
Tumour T cells TEM TH1-like Treg TH17
)1
+
MPT(2gol
P = 0.21 **P = 0.0040
50 40 30
20
10
0
f
d e IFNG BHLHE40 IGFLR1 * P = 0.06 *** *** P = 6.45 × 10–18 P = 8.55 × 10–21
TBX21 EOMES RUNX3 *** *** P = 0.45 P = 5.40 × 10–18 P = 6.54 × 10–9
10 5
0
ycneuqerF
a b c
MSIMSS
bM rep
snoitatuM
)sllec
T +4DC(
ycneuqerF
MSI
)eulav
P .jda(01gol–
Significance True
Tumour TH1-like cells
Fold change, log2(gene expression)
)1 + MPT(2gol
CD4+ TEM TH17 TH1-like
MSIMSS MSIMSS g
apxe-CARTRATS
Fig. 3 | Clonal TH1-like T cells are enriched in MSI tumours. (n = 315) and CD4+ TEM cells (n = 161) in tumours. P < 0.01, Benjamini–
a, Comparison of the proportions of different CD8+ and CD4+ T cell Hochberg adjusted two-sided unpaired limma-moderated t-test; fold
clusters in tumours from patients with CRC (n = 12), HCC9 (n = 5), and change ≥ 2. e, Gene expression comparison between CXCL13+BHLHE40+
NSCLC10 (n = 14) after re-clustering of the combined dataset (Extended TH1-like cells (n = 315) and CD4+ TEM cells (n = 161). f, STARTRAC-expa
Data Fig. 10). Each dot denotes an individual patient. b, Box plot showing indices for tumour-enriched TH cells in patients with MSI (n = 4) and MSS
mutation load of patients with MSI (n = 4) and MSS (n = 8) CRC. (n = 7) CRC. g, Frequencies of proliferative cells versus STARTRAC-expa
c, Percentages of tumour-enriched TH cells in the overall CD4+ T cells from index for CD4+ cells. Each dot in b, c and f represents an individual patient.
patients with MSI (n = 4) and MSS (n = 7) CRC. d, Volcano plot showing *P < 0.05, **P < 0.01, ***P < 0.001, two-sided Wilcoxon test (a–c, e, f).
differentially expressed genes between CXCL13+BHLHE40+ TH1-like cells TPM, transcripts per million.
270 | NAtUre | VOL 564 | 13 DeCeMBer 2018
© 2018 Springer Nature Limited. All rights reserved.

## Page 4

Letter reSeArCH
The potential tumour-killing activities of the CD4_C03-GNLY cluster increased in the TCGA MSI-high patients with CRC, whereas the
should therefore be further explored. T 17 signal was enriched in the MSS cohort (Extended Data Fig. 10g).
H
Tumour-infiltrating T cells were among the highly expanded popu- Although increased overall IFNG+ T 1 cells has been suggested in MSI
reg H
lations (Fig. 2a). Most (88%) clonal CRC-infiltrating T cells contained CRC tumours6,7, of the two IFNG+ T 1-like cell subsets we identified,
reg H
TCR clonotypes exclusive to themselves, indicating their potential for only the CXCL13+BHLHE40+ T 1-like cell cluster and not another
H
recognizing tumour-associated antigens and local expansion charac- GZMK+IFNG+ T cell cluster was enriched in MSI tumours. Notably,
EM
teristics9,10 (Extended Data Fig. 9b). A few tumour T cells also shared although TBX21 showed similar expression in both subsets, other
reg
TCRs with T cells from blood (CD4_C10-FOXP3) or normal mucosa IFNγ-regulating transcription factors EOMES and RUNX324 were
reg
(CD4_C11-IL10). Several other tumour T cells shared TCRs with preferentially expressed in GZMK+ T cells, whereas BHLHE40 was
reg EM
T cells in tumours (Extended Data Fig. 9b, Supplementary Table 7), selectively expressed in CXCL13+BHLHE40+ T 1-like cells (Fig. 3d, e,
H H
indicating that they were induced T (iT ) cells19. STARTRAC-tran Supplementary Table 9); this suggests distinctive transcriptional
reg reg
analysis suggested that these potential iT cells were developmentally control for these two IFNG+ subsets. Indeed, BHLHE40 not only
reg
linked to T 17 and CXCL13+BHLHE40+ T 1-like cells (Extended Data regulates IFNγ but also represses IL-10 production25,26. Furthermore,
H H
Fig. 9c). iT cells that share TCRs with T 17 cells fell into a sub-cluster STARTRAC analyses revealed that CXCL13+BHLHE40+ T 1-like
reg H H
of a tumour T cell group with higher expression of RORC11,20 cells were clonally expanded and enriched in MSI patients, and
reg
(Fig. 2e, f). The co-expression of RORγ and FOXP3 at the protein proliferative in tumours (Fig. 3f, g). Moreover, these cells exhibited
level was confirmed by IHC (Extended Data Fig. 9d). In addition, developmental connection with GZMK+ T cells, indicating the
EM
SATB121 was selectively expressed in T cells linked to T 17 cells, potential inter-conversion of these two IFNG+ subsets (Extended
reg H
whereas BACH222 was preferentially expressed in T cells linked to Data Fig. 9c). Given the involvement of T 1-like cells in response to
reg H
CXCL13+BHLHE40+ T 1-like cells (Fig. 2e, Supplementary Table 8). anti-CTLA4 therapy in melanoma27, we speculate that the enrichment
H
By contrast, those T cells with high intra-cluster expansion had rel- of CXCL13+BHLHE40+IFNG+ T 1-like cells in MSI patients might
reg H
atively high expression of TNFRSF9 and TIGIT (Fig. 2e), suggesting contribute to their favourable response to immunotherapies.
that at least some of these cells might belong to natural T cells23. The These CXCL13+BHLHE40+ T 1-like cells in tumours showed high
reg H
roles of these different subsets of T cells needs further investigation. expression of CXCR3, HAVCR2, PDCD1, ICOS and TIGIT (Extended
reg
When comparing T cell populations across cancer types9,10 Data Fig. 11a, Supplementary Table 10). Notably, a less-characterized
(Extended Data Fig. 10a, b), we found that although the composition gene, IGFLR1, was also upregulated in these cells. IGFLR1 belongs to
and abundance of blood-derived T cells were highly similar, T cell the TNFR superfamily28 and has three potential ligands, with IGFL1
patterns were distinct in both tumours and adjacent normal tissues and IGFL3 showing high-affinity interactions. IGFLR1 was also upreg-
(Extended Data Fig. 10c–f). Notably, CRC and HCC tumours exhibited ulated in tumour T cells (Extended Data Fig. 11b, Supplementary
EX
a higher abundance of CD8+ T and CD4+ T cells, whereas NSCLC Table 11) and T cells (Fig. 4a). In vitro, suboptimal T cell activa-
EX reg reg
tumours exhibited enrichment of tumour T cells with low expres- tion was sufficient to upregulate IGFLR1 in memory CD4+ T cells
RM
sion of PDCD1 and CTLA4 but high expression of ZNF683 (Fig. 3a). (Extended Data Fig. 11c–e). Importantly, IGFL3 enhanced CD25
Likewise, the IELs were specifically present in normal mucosa and induction and IFNγ secretion in CD4+ T cells under this condition
tumours in patients with CRC (Extended Data Fig. 10e, f). (Fig. 4b–e). The degree of IFNγ induction in total CD4+ T cells was
Next, by focusing on the differences between heavily mutated MSI correlated with the induction of IGFLR1 in memory T cells (Fig. 4f). In
tumours (Fig. 3b) and MSS tumours, we found that MSI tumours addition, the IGFL3-augmented CD25 expression was observed only
exhibited abundant CXCL13+BHLHE40+ T 1-like cells, whereas in IGFLR1+ memory T cells, but not in the IGFLR1− cells in the same
H
MSS tumours were moderately enriched with T 17 cells (Fig. 3c). cultures (Fig. 4g). Furthermore, the synergistic effect by IGFL3 could
H
Accordingly, the CXCL13+BHLHE40+ T 1-like cell signal was be specifically blocked by an anti-IGFLR1 antibody (Fig. 4c–e).
H
tnuoC
IGFL3 – + + + Isotype – – + – Anti-IGFLR1 – – – +
7yC-EP
γNFI
)4DC
%(
52DC
b * P= 0.0329
* P= 0.0228
IGFL3 – + + + Isotype – – + – Anti-IGFLR1 – – – +
Control IGFL3
21.0 34.7
IGFL3 + mIgG1
36.2 21.7
noitcudorp
γNFI
)noitcudni
dlof(
c
6
g 4
2
0 0 0.5 1.0 1.5
CD45RA APC-Cy7
EP 1RLFGI
80
60
40 20 105 0
104 80 103 60
40
0 20 0103 104105 0 0103104105
CD25 BV605
tnuoC
80
60
40 20 0
Control + IGFL3 80 60
40
20 0
ControlIGFL3
+52DC
+52DC
)4DC+1RLFGI
%(
)4DC–1RLFGI
%(
a e 5
4
3
2 1 100101102103104105 0 d Isotype
Control
IGFL3
IGFL3 + mlgG1 *P = 0.0141
CD4+ T cells
101 103 105
)1
+ MPT(2gol
12 IGFLR1 CD4+ 60 * P = 0.0197* P = 0.0173
9 Exp
6 7 6 40 3 5
0 4 20 0 CD25 BV605
105
104 IGFL3 + anti-IGFLR1 + C I o G n F t L ro 3 l f
103 R2 = 0.53
0 **P = 0.0014 10–3 IGFL3 + anti-IGFLR1
105 104 P = 0.727 103
0
10–3 101 103 105
CD4 BUV395 Ratio (IGFLR1+:IGFLR1–)
noitcudorp
γNFI
)noitcudni
dlof(
CD4+ TEM T 1- 1 H lik 7 e cells T C re D g 8+ T C E D M 8+ TEX TH
Fig. 4 | IGFLR1 functions as a co-stimulatory receptor in T cells. of intracellular IFNγ expression of activated CD4+ T cells on day 2
a, Violin plots showing IGFLR1 expression in tumour-enriched T cell (n = 6 donors, n = 3 independent experiments). e, Fold changes in IFNγ
clusters, including CD4+ TEM cells (n = 185), TH17 cells (n = 244), supernatant from d measured by ELISA relative to the control group.
TH1-like cells (n = 319), Treg cells (n = 1,320), CD8+ TEM cells (n = 773) f, Correlation of IFNγ induction by IGFL3 and the ratio of IGFLR1+ to
and CD8+ TEX cells (n = 860). Black dots denote mean values; widths IGFLR1− CD4+ TMEM cells (n = 16 donors; F-test). g, Activated CD4+
denote cell densities. b, Representative histograms of CD25 expression TMEM cells were gated as IGFLR1+ and IGFLR1− cells by FACS (left).
in activated and indicated CD4+ T cells on day 2 (n = 5 donors, n = 3 Representative histograms (middle) and percentages (right) of CD25
independent experiments). mIgG1 denotes mouse anti-IgG1 control expression levels in IGFLR1+ and IGFLR1−CD4+ TMEM cells (n = 4
antibody. c, Quantification of CD25 expression in b. Symbols are donors). Two-sided paired Student’s t-test (c, e and g).
individual donors. Data are mean ± s.e.m. (n = 5; c, e). d, Flow cytometry
13 DeCeMBer 2018 | VOL 564 | NAtUre | 271
© 2018 Springer Nature Limited. All rights reserved.

## Page 5

reSeArCH Letter
To study the role of IGFLR1 in exhausted CD8+ T cells, we adopted 15. Paley, M. A. et al. Progenitor and terminal subsets of CD8+ T cells cooperate to
a protocol for low-degree stimulation of chronic stimulation CD8+ contain chronic viral infection. Science 338, 1220–1225 (2012).
16. Thommen, D. S. et al. A transcriptionally and functionally distinct PD-1+ CD8+
T (T CS ) cells (see Methods) to induce certain features of in vivo T cell pool with predictive potential in non-small-cell lung cancer treated with
exhausted T cells (Extended Data Fig. 11f–h). These CD8+ T cells PD-1 blockade. Nat. Med. 24, 994–1004 (2018).
CS
exhibited higher IGFLR1 expression than activated conventional 17. Chihara, N. et al. Induction and transcriptional regulation of the co-inhibitory
CD8+ effector T (T conv ) cells (Extended Data Fig. 11i, j). The addition 18. G ge r n iffi e t m h, o J d . W ul . e , S in o k T o c l, e C lls . . L N . & a t L u u re s t 5 e 5 r, 8 A , . 4 D 5 . 4 C – h 4 e 5 m 9 o ( k 2 i 0 n 1 es 8 ) a . nd chemokine receptors:
of IGFL3 synergized the TCR-induced HAVCR2 expression29 in these positioning cells for host defense and immunity. Annu. Rev. Immunol. 32,
cells, which could be blocked by an anti-IGFLR1 antibody (Extended 659–702 (2014).
19. Adeegbe, D. O. & Nishikawa, H. Natural and induced T regulatory cells in cancer.
Data Fig. 11k, l). Altogether, these data suggest that IGFLR1 could syn-
Front. Immunol. 4, 190 (2013).
ergize with TCR signalling and serve as a co-stimulatory molecule. 20. Sefik, E. et al. Individual intestinal symbionts induce a distinct population of
In summary, STARTRAC analyses unveiled various functional, RORγ+ regulatory T cells. Science 349, 993–997 (2015).
21. Beyer, M. et al. Repression of the genome organizer SATB1 in regulatory T cells
migratory and developmental connections among different T cell
is required for suppressive function and inhibition of effector differentiation.
subsets in CRC. Our data and previous findings in mouse models30 Nat. Immunol. 12, 898–907 (2011).
revealed TCR-dependent trajectories for T and T cells from 22. Roychoudhuri, R. et al. BACH2 represses effector programs to stabilize
EMRA EX
tumour-resident CD8+ T cells, suggesting therapeutic strategies to Treg-mediated immune homeostasis. Nature 498, 506–510 (2013).
EM 23. Zhang, Y. et al. Genome-wide DNA methylation analysis identifies
promote the conversion from T EX to T EMRA cells. The enrichment of hypomethylated genes regulated by FOXP3 in human regulatory T cells. Blood
CXCL13+BHLHE40+IFNG+ T 1-like cells in MSI patients not only 122, 2823–2836 (2013).
H
24. Djuretic, I. M. et al. Transcription factors T-bet and Runx3 cooperate to activate
provides a rationale for the high response rate to checkpoint blockade
Ifng and silence Il4 in T helper type 1 cells. Nat. Immunol. 8, 145–153 (2007).
in these patients, but also solicits therapeutic focus on these cells. The 25. Yu, F. et al. The transcription factor Bhlhe40 is a switch of inflammatory versus
compendium dataset of differentially expressed genes such as IGFLR1, antiinflammatory Th1 cell fate determination. J. Exp. Med. 215, 1813–1821
available through an interactive portal at http://crc.cancer-pku.cn, can (2018).
26. Huynh, J. P. et al. Bhlhe40 is an essential repressor of IL-10 during
be used as a resource for further T cell exploration and the identification Mycobacterium tuberculosis infection. J. Exp. Med. 215, 1823–1838 (2018).
of regulatory mechanisms and therapeutic targets. 27. Wei, S. C. et al. Distinct cellular mechanisms underlie anti-CTLA-4 and anti-PD-1
checkpoint blockade. Cell 170, 1120–1133.e17 (2017).
28. Lobito, A. A. et al. Murine insulin growth factor-like (IGFL) and human IGFL1
Online content
proteins are induced in inflammatory skin conditions and bind to a novel tumor
Any methods, additional references, Nature Research reporting summaries, source necrosis factor receptor family member, IGFLR1. J. Biol. Chem. 286, 18969–
data, statements of data availability and associated accession codes are available at 18981 (2011).
https://doi.org/10.1038/s41586-018-0694-x. 29. Singer, M. et al. A distinct gene module for dysfunction uncoupled from
activation in tumor-infiltrating T cells. Cell 166, 1500–1511.e9 (2016).
Received: 26 February 2018; Accepted: 19 October 2018; 30. Schietinger, A. et al. Tumor-specific T cell dysfunction is a dynamic antigen-
driven differentiation program initiated early during tumorigenesis. Immunity
Published online 29 October 2018.
45, 389–401 (2016).
1. Chen, D. S. & Mellman, I. Elements of cancer immunity and the cancer-immune
set point. Nature 541, 321–330 (2017). Acknowledgements We thank C. X. Ye for sample preparation and F. Wang, X.
2. Glanville, J. et al. Identifying specificity groups in the T cell receptor repertoire. Zhang and J. S. Li for assistance with FACS. We thank the Computing Platform
Nature 547, 94–98 (2017). of the CLS (Peking University). This project was supported by Beijing Advanced
3. Stubbington, M. J. T. et al. T cell fate and clonality inference from single-cell Innovation Centre for Genomics at Peking University, Key Technologies R&D
transcriptomes. Nat. Methods 13, 329–332 (2016). Program (2016YFC0900100), National Natural Science Foundation of China
4. Le, D. T. et al. PD-1 Blockade in tumors with mismatch-repair deficiency. N. Engl. (81573022, 31530036, 91742203 and 81672375) and Amgen Corporation
J. Med. 372, 2509–2520 (2015). (USA). L.Z. was supported by the Postdoctoral Foundation of CLS.
5. Le, D. T. et al. Mismatch repair deficiency predicts response of solid tumors to
PD-1 blockade. Science 357, 409–413 (2017). Reviewer information Nature thanks N. Haining, M. Suva and the other
6. Llosa, N. J. et al. The vigorous immune microenvironment of microsatellite anonymous reviewer(s) for their contribution to the peer review of this work.
instable colon cancer is balanced by multiple counter-inhibitory checkpoints.
Cancer Discov. 5, 43–51 (2015). Author contributions Z.Z., W.O. and L.Z. designed experiments. L.Z., X.Y., Q.F.,
7. Mlecnik, B. et al. Integrative analyses of colorectal cancer show immunoscore is R.G., Q.Z., J.Y.H., H.K. and X.G. performed the experiments. L.Z., L.T.Z., Y.Z., X.R.
a stronger predictor of patient survival than microsatellite instability. Immunity and X.H. analysed sequencing data. Y.L., J.Y., S.W., Y.G. and Z.S. collected clinical
44, 698–711 (2016). samples. B.K. constructed the website. L.Z., W.O. and Z.Z. wrote the manuscript
8. Tirosh, I. et al. Dissecting the multicellular ecosystem of metastatic melanoma with input from all authors.
by single-cell RNA-seq. Science 352, 189–196 (2016).
9. Zheng, C. et al. Landscape of infiltrating T cells in liver cancer revealed by Competing interests W.O., X.Y., H.K. and J.Y.H. are employees of Amgen Inc.
single-cell sequencing. Cell 169, 1342–1356.e16 (2017).
10. Guo, X. et al. Global characterization of T cells in non-small-cell lung cancer by Additional information
single-cell sequencing. Nat. Med. 24, 978–985 (2018). Extended data is available for this paper at https://doi.org/10.1038/s41586-
11. Han, A., Glanville, J., Hansmann, L. & Davis, M. M. Linking T-cell receptor 018-0694-x.
sequence to functional phenotype at the single-cell level. Nat. Biotechnol. 32, Supplementary information is available for this paper at https://doi.org/
684–692 (2014). 10.1038/s41586-018-0694-x.
12. The Cancer Genome Atlas Network. Comprehensive molecular characterization Reprints and permissions information is available at http://www.nature.com/
of human colon and rectal cancer. Nature 487, 330–337 (2012). reprints.
13. Schenkel, J. M. & Masopust, D. Tissue-resident memory T cells. Immunity 41, Correspondence and requests for materials should be addressed to Z.S., W.O.
886–897 (2014). or Z.Z.
14. Cheroutre, H., Lambolez, F. & Mucida, D. The light and dark sides of intestinal Publisher’s note: Springer Nature remains neutral with regard to jurisdictional
intraepithelial lymphocytes. Nat. Rev. Immunol. 11, 445–456 (2011). claims in published maps and institutional affiliations.
272 | NAtUre | VOL 564 | 13 DeCeMBer 2018
© 2018 Springer Nature Limited. All rights reserved.

## Page 6

Letter reSeArCH
MEthodS Primary human T cell isolation and in vitro activation. PBMCs from healthy
No statistical methods were used to predetermine sample size. The experiments donors were isolated by density gravity centrifugation (Ficoll-Paque PREMIUM;
were not randomized, and investigators were not blinded to allocation during GE Healthcare). T cell subsets were isolated from PBMCs with appropriate mag-
experiments and outcome assessment. netic beads following the manufacturer’s protocol (StemCell Technologies).
Human specimens. Twelve patients with CRC, including eight women and four Isolated T cells were cultured in RPMI-1640 supplemented with 10% heat-
men, were enrolled and pathologically diagnosed with colorectal adenocarcinoma inactivated FBS, 100 U ml−1 penicillin and streptomycin and 2-mercaptoethanol
at Peking University People’s Hospital. Written informed consent was provided (all from Gibco). Human T cells were activated with anti-CD3 (UCHT1,
by all patients. This study was approved by the Research and Ethical Committee 2 µg ml−1, BD Biosciences) and anti-CD28 (CD28.2, 2 µg ml−1, BD Biosciences).
of Peking University People’s Hospital and complied with all relevant ethical reg- When indicated, 100 ng ml−1 recombinant human IGFL3 (Adipogen) was added in
ulations. Fresh tumour and adjacent normal tissue samples (at least 2 cm from culture medium alone or with 20 µg ml−1 of anti-IGFLR1 blocking antibody (clone
matched tumour tissues) were surgically resected from the above-described 905338, R&D Systems). The same amount of mouse IgG1 antibody (R&D Systems)
patients. Patients P0701, P0909, P1212, P1228, P0215, P0411, P0413, P0825, was used as a control. Cells were collected and stained with indicated monoclonal
P0123 and P0309 had peripheral blood and paired tumour and adjacent normal antibodies (anti-human CD4, OKT4; anti-human CD8, RPA-T8; anti-human
tissues obtained, whereas patients P1012 and P1207 had only fresh tumour tissue CD45RA, HI100; anti-human CCR7, G043H7; anti-human HAVCR2, F38-2E2;
and matched peripheral blood. Their ages ranged from 35 to 82 with a median anti-human CD25, M-A251; anti-human IFNγ, B27; anti-human IGFLR1, 905338;
of 67. None of them was treated with chemotherapy or radiation before tumour Biolegend, BD Biosciences, or R&D Systems). Flow cytometry data were acquired
resection. The stages of these patients were classified according to the guidance of with an LSR-II analyser and analysed using FlowJo software (Tree Star). Cytokine
AJCC version 8. Among these patients, one was diagnosed at stage I, five at stage concentrations were measured in cell culture supernatants 40 h after stimulation
II, five at stage III, and one at stage IV. Among the four MSI-high (MSI-H) patients, with enzyme-linked immunosorbent assay (ELISA) kits specific for human IFNγ
three had positive lymph nodes (P0123, P0413 and P0909), and two had poorly (BD Bioscience). All data were from three independent experiments with more
differentiated disease (P0825 and P0909). Although we did not purposely exclude than four donors.
the stage IV patient, none of the MSI-H patients had distal metastasis, as evidenced In vitro CD8+ TCS cells. The CD8+ TCS cells were generated using an in vitro
by the enhanced computerized tomography (CT) results for abdomen, chest and chronic low-degree stimulation protocol as described in previous studies32,33.
pelvic areas before surgery. The available clinical characteristics are summarized in Purified human CD8+ T cells at 1 × 106–2 × 106 cells ml−1 were subjected to
Supplementary Table 1. For the IGFLR1 study, human peripheral blood mononu- anti-CD3 (UCHT1, 0.2 µg ml−1, BD Biosciences) and anti-CD28 (CD28.2,
clear cells (PBMCs) were obtained from 16 healthy donors after informed consent 2 µg ml−1, BD Biosciences) stimulation for 3–4 days followed by at least an addi-
and authorization by the Amgen Research Blood Donor Program. tional two rounds of re-stimulation every 3–4 days with anti-CD3 (UCHT1, 1 µg
Single-cell collection. Tumours and adjacent normal tissues were cut into approx- ml−1, BD Biosciences) and anti-CD28 (CD28.2, 2 µg ml−1, BD Biosciences) to
imately 1-mm3 pieces in the RPMI-1640 medium (Invitrogen) with 10% fetal generate CD8+ TCS cells. CD8+ TCS cells were then subjected to stimulation with or
bovine serum (FBS; Sciencell), and enzymatically digested with MACS Tumour without human IGFL3 as described above. Cells were stained with indicated mon-
Dissociation Kit (Miltenyi Biotec) for 30 min on a rotor at 37 °C, according to the oclonal antibodies (anti-human CD8, RPA-T8; anti-human HAVCR2, F38-2E2;
manufacturer’s instruction. The dissociated cells were subsequently passed through anti-human PD-1, EH12.2H7; anti-human CD39, eBioA1; anti-LAG3, 305223H;
a 40-µm cell-strainer (BD) and centrifuged at 400g for 10 min. After the superna- anti-IGFLR1, 905338; Thermal Fisher Scientific, BD Biosciences, or R&D Systems).
tant was removed, the pelleted cells were suspended in red blood cell lysis buffer T cell stimulation. Human memory CD4+ T cells were isolated from healthy donor
(Solarbio) and incubated on ice for 2 min to lyse red blood cells. After washing PBMCs to a purity of >94% with memory CD4+ T cell isolation kit following
twice with PBS (Invitrogen), the cell pellets were re-suspended in sorting buffer manufacturer’s protocol (Miltenyi Biotec). Isolated T cells were cultured in RPMI-
(PBS supplemented with 1% FBS). 1640 supplemented with 10% heat-inactivated FBS, 100 U ml−1 penicillin and
PBMCs were isolated using HISTOPAQUE-1077 (Sigma-Aldrich) solution streptomycin and 2-mercaptoethanol (all from Gibco). Human T cells were
as previously described9. In brief, 3 ml of fresh peripheral blood was collected activated with anti-CD3 (UCHT1, 2 µg ml−1, BD Biosciences) and anti-CD28
before surgery in EDTA anticoagulant tubes and subsequently layered onto (CD28.2, 2 µg ml−1, BD Biosciences) for 2 days. T cells were then rested in culture
HISTOPAQUE-1077. After centrifugation, lymphocyte cells remained at the medium for 2 days followed by 16 h starvation in RPMI-1640 plus 0.5% FBS. Next,
plasma–HISTOPAQUE-1077 interface and were carefully transferred to a T cells were collected and subjected to stimulation. For TCR stimulation, T cells
new tube and washed twice with PBS. Red blood cells were removed via the were incubated on ice for 30 min with 1 µg ml−1 anti-CD3 (OKT3, Thermo
same procedure described above. These lymphocytes were re-suspended in Fisher Scientific) and 1 µg ml−1 anti-CD28 followed by a 15-min incubation with
sorting buffer. 5 µg ml−1 anti-mouse IgG (Thermo Fisher Scientific). Cells were activated by
Single-cell sorting, reverse transcription, amplification and sequencing. incubation in a 37 °C water bath for 25 min. For IGFL3 stimulation, T cells
Single-cell suspensions were stained with antibodies against CD3, CD4, CD8 and were incubated on ice for 30 min with 100 ng ml−1 recombinant human IGFL3
CD25 (anti-human CD3, UCHT1; anti-human CD4, OKT4; anti-human CD8, (Adipogen). Cells were then activated by incubation in a 37 °C water bath for 25 min.
OKT8; anti-human CD25, BC96; eBioscience) for FACS sorting, performed on Cytokine production detection. Human memory CD4+ T cells were isolated
a BD Aria III instrument. Single cells of different subtypes including cytotoxic as described above. Cells were activated with anti-CD3 (UCHT1, 2 µg ml−1, BD
T (TC) cells, TH cells and Treg cells were enriched by gating 7AAD−CD3+CD8+, Biosciences) and anti-CD28 (CD28.2, 2 µg ml−1, BD Biosciences) or anti-CD3 and
7AAD−CD3+CD4+CD25−/int and 7AAD−CD3+CD4+ CD25hi T cells, respectively, anti-CD28 plus IGFL3 (100 ng ml−1). Cells were seeded in flat-bottom 96-well
and sorted into 96-well plates (Axygen) chilled to 4 °C, prepared with lysis buffer plates with 105 cells in 100 µl culture medium per 96 wells. Cytokine concentrations
with 1 µl 10 mM dNTP mix (Invitrogen), 1 µl 10 µM Oligo dT primer, 1.9 µl 1% were measured in cell culture supernatants 40 h after stimulation with ELISA kits
Triton X-100 (Sigma), and 0.1 µl 40 U µl−1 RNase Inhibitor (Takara). specific for human IFNγ (BD Bioscience).
The single-cell lysates were sealed and stored frozen at −80 °C immediately. Bulk DNA and RNA isolation and sequencing. Genomic DNA of peripheral
Single-cell transcriptome amplifications were performed according to the Smart- blood and tissue samples of patients with CRC were extracted using the QIAamp
Seq2 protocol9,31. The External RNA Controls Consortium (ERCC; Ambion; DNA Mini Kit (QIAGEN) according to the manufacturer’s specification.
1:4,000,000) was added into each well as the exogenous spike-in control before The concentrations of DNA were quantified using the Qubit HsDNA Kits
the reverse transcription. The amplified cDNA products were purified with (Invitrogen) and the qualities of DNA were evaluated with agarose gel electro-
1 × Agencourt XP DNA beads (Beckman). A procedure of quality control was phoresis. Exon libraries were constructed using the SureSelectXT Human All
performed following the first round of purification, which included the detection Exon V5 capture library (Agilent). Samples were sequenced on the Illumina
of CD3D by qPCR (forward primer, 5′-TCATTGCCACTCTGCTCC-3′; reverse Hiseq 4000 sequencer with 150-bp paired-end reads. For bulk RNA analysis,
primer, 5′-GTTCACTTGTTCCGAGCC-3′) and fragment analysis by analyser small fragments of tumour tissues and adjacent normal tissues were first stored
AATI. For those single-cell samples with high quality after quality control (cycle in RNAlater RNA stabilization reagent (QIAGEN) after surgical resection and
threshold <30), the DNA products were further purified with 0.5 × Agencourt XP kept on ice to avoid RNA degradation. RNA of tumour and adjacent normal
DNA beads, and the concentration of each sample was quantified by Qubit HsDNA tissue samples were extracted using the RNeasy Mini Kit (QIAGEN) according
kits (Invitrogen). Multiplex (384-plex) libraries were constructed and amplified to the manufacturer’s specification. The concentrations of RNA were quantified
using the TruePrep DNA Library Prep Kit V2 for Illumina (Vazyme Biotech). The using the NanoDrop instrument (Thermo) and the qualities of RNA were evalu-
libraries were then purified with Agencourt XP DNA beads and pooled for quality ated with fragment analyser (AATI). Libraries were constructed using NEBNext
assessment by fragment analyser. For all the 12 patients, purified libraries were Poly (A) mRNA Magnetic Isolation Module kit (NEB) and NEBNext Ultra RNA
analysed by an Illumina Hiseq 4000 sequencer with 150-bp pair-end reads. For Library Prep Kit for Illumina Paired-end Multiplexed Sequencing Library (NEB).
patient P1207, only CD8+ T cells were collected, thus this patient was not included Samples were sequenced on the Illumina Hiseq 4000 sequencer with 150-bp
when analysing CD4+ T cells. paired-end reads.
© 2018 Springer Nature Limited. All rights reserved.

## Page 7

reSeArCH Letter
Microsatellite instability testing. DNA purified from tumour tissues using were defined as the medians of all cells minus 3 × the median absolute deviation.
QIAamp DNA Mini Kit (QIAGEN) was subjected to multiplex fluorescent PCR- Furthermore, if the proportion of mitochondrial gene counts was larger than 10%,
based assay (Promega) by amplifying seven loci including five mononucleotide these cells were discarded. Only cells with the average TPM of CD3D, CD3E and
repeats (NR21, BAT26, BAT25, NR24 and Mono27) and two pentanucleotide CD3G larger than 10 were kept for subsequent analysis. We further identified
repeats (PentaC and PentaD) and was compared with DNA extracted from CD4+, CD8+, CD4−CD8− (double negative) and CD4+CD8+ (double positive)
matched adjacent normal tissues. Multiplex PCR products were analysed by ABI T cells based on the gene expression data. Given the average TPM of CD8A and
PRISM 3100 Genetic Analyzer (Applied Biosystems). Patients were defined as CD8B, one cell was considered as CD8 positive or negative if the value was larger
MSI-H status by the presence of two or more mononucleotide loci showing insta- than 30 or less than 3, respectively; given the TPM of CD4, one cell was consid-
bility. MSS was defined as no loci of instability. Among 12 patients in this study, ered as CD4 positive or negative if the value was larger than 30 or less than 3,
4 of them were MSI-H (P0413, P0825, P0123 and P0909), and the other 8 were MSS respectively. Hence, the cells can be in silico classified as CD4+CD8−, CD4−CD8+,
(P0215, P0411, P0701, P1012, P1207, P1212, P1228 and P0309). CD4+CD8+, CD4−CD8− and other cells that cannot be clearly defined. A total of
Immunohistochemistry. The specimens were collected from Peking University 52 cells were filtered out owing to the inconsistent classifications based on tran-
People’s Hospital within 30 min of the tumour resection and fixed in 10% formalin scriptome data and FACS.
for 48 h. Dehydration and embedding in paraffin was performed as the following After discarding genes with average counts of fewer than or equal to 1, the
routine methods9. These paraffin blocks were cut into 5-µm sections and adhered count table of the cells passing the above filtering was normalized using a pooling
to a glass slide. Then, the paraffin sections were placed in the 70-°C paraffin oven strategy implemented in the R function computeSumFactors35. With this strategy,
for 1 h before being deparaffinised in xylene and then rehydrated in 100%, 90% size factors for individual cells were deconvoluted from size factors of pools, the
and 70% alcohol successively. The antigens were retrieved by the Epitope Retrieval sizes of which ranged from 20, 40, 60, 80 to 100. To avoid violating the assumption
Solution (Leica Biosystems), and the sections were incubated with ready-to-use that most genes were not differentially expressed, hierarchical clustering based
primary antibodies (mouse anti-human MLH1, clone ES05; mouse anti-human on Spearman’s rank correlation was performed first, then normalization was
MSH2, clone 25D12; mouse anti-human MSH6, clone PU29; mouse anti-human performed in each cluster separately. The size factor of each cluster was further
PMS2, clone M0R4G, all from Leica Biosystems) on the BOND system (Leica re-scaled to enable comparison between clusters. The normalized data were in
Biosystems) according to the manufacturer’s protocol. log2 space. To remove the possible effects of different donors on expression, the
Multi-colour immunohistochemistry. The specimens were collected and normalized table was further centred by patient. Thus, in the centred expression
prepared for the formalin-fixed paraffin-embedded tissues sections as previously table, the mean values of the cells for each patient were zero. A total of 12,548
mentioned9. The confirmation of RORγ+ Treg cells was analysed using Opal genes and 10,805 cells were retained in the final expression table. If not explicitly
7-Colour Manual IHC Kit (PerkinElmer, NEL811001KT) according to the man- stated, ‘normalized read count’ or ‘normalized expression’ in this study refers to
ufacturer’s protocol, as previously described10. In brief, antigen was retrieved by the normalized and centred count data for simplicity.
AR9 buffer (pH 6.0, PerkinElmer) and boiled in the oven for 15 min. After a Analysis pipelines of bulk exome sequencing and RNA-seq data. The bulk exome
pre-incubation with blocking buffer at room temperature for 10 min, the sections sequencing data were cleaned following the same procedure for the scRNA-seq data
were incubated at room temperature for 1 h with rabbit anti-human CD3 (Abcam, processing. The cleaned read pairs were then processed according to the BWA-
clone SP7, 1:100), rabbit anti-human RORγ (Abcam, 1:50), and mouse anti- PICARD/GATK-strelka pipeline. In brief, the cleaned read pairs were aligned to
human FOXP3 (Abcam, clone mAbcam22510, 1:100). A secondary horseradish human genome reference version b37 (downloaded from ftp://ftp.broadinstitute.
peroxidase-conjugated antibody (PerkinElmer) were added and incubated at room org:/bundle) by the BWA-MEM algorithm36. The alignments were then sorted
temperature for 10 min. Signal amplification was performed using TSA working and de-duplicated by PICARD (Broad Institute). GATK37 was used to realign
solution diluted at 1:100 in 1× amplification diluent (PerkinElmer) and incubated multiple reads around putative INDEL by Smith–Waterman alignment algorithm
at room temperature for 10 min. The other validations by multi-colour IHC were and re-calibrate base quality. The analysis-ready bam files were input into the
performed using the same protocols with different primary antibodies as follows. GATK UnifiedGenotyper module to call SNP/INDEL and into strelka38 to call
The primary antibodies and IHC metrics used in the validation of TC, TH and Treg somatic SNV/INDEL and into ADTEx39 (version 1.0.4) to call somatic copy number
cells were rabbit anti-human CD3 (Abcam, clone SP7, 1:400), rabbit anti-human alterations. The mutations were annotated with annovar40.
CD4 (Abcam, clone EPR6855, 1:400), mouse anti-human CD8 (Abcam, clone TCR assembly. TraCeR was used to deduce the TCR sequences of each cell3. The
144B, 1:500) and mouse anti-human FOXP3 (Abcam, clone mAbcam22510, 1:500). outputs of TraCeR include the assembled nucleotide sequences for both α and β
The primary antibodies and IHC metrics used in the validation of proliferative chains, the coding potential of the nucleotide sequences (that is, productive or not),
CD8+ TEX cells were: rabbit anti-human TIM-3 (also known as HAVCR2) (Cell the translated amino acid sequence, the CDR3 sequences and the estimated TPM
Signaling, clone D5D5R, 1:100), mouse anti-human Ki67 (Abcam, B126.1, 1:200), value of α or β chains. Only cells with TPM values larger than 10 for the α chain
mouse anti-human PD-1 (Abcam, clone NAT105, 1:200) and mouse anti-CD8 and larger than 15 for the β chain were kept.
(Abcam, clone 144B, 1:200). The multispectral imaging was collected by Mantra For cells with two or more α or β chains assembled, the α–β pair that was
Quantitative Pathology Workstation (PerkinElmer, CLS140089) at 20× magnifi- productive and of the highest expression level was defined as the dominant α–β
cation and analysed by InForm Advanced Image Analysis Software (PerkinElmer) pair in the corresponding cell. If two cells had identical dominant α–β pairs, the
version 2.3. For each patient, a total of 8–15 high-power fields were taken based dominant α–β pair were identified as clonal TCRs. To integrate with the gene
on their tumour sizes. expression data, the TCR-based analysis was performed only for cells that passed
Quality control and preprocessing of single-cell RNA-seq data. Low-quality read the aforementioned quality control pipeline (total 10,805). Thus, 9,878 cells with
pairs of single-cell RNA sequencing (scRNA-seq) data were filtered out if at least TCR information were used in the integrative analysis (Supplementary Table 4).
one end of the read pair met one of the following criteria: (1) ‘N’ bases account If one cell had an α chain composed of V segment TRAV1-2 and one of the
for ≥10% of the read length; (2) bases with quality <5 account for ≥50% of the following J segments (TRAJ33, TRAJ20 and TRAJ12), the cell was classified as a
read length; and (3) the read contains adaptor sequence. The filtered read pairs MAIT cell41. If the α chain of one cell was rearranged by V segment TRAV10 and
were processed using HTSeqGenie pipeline (R package version 4.8) to obtain the J segment TRAJ18, the cell was classified as an invariant natural killer T cell42. In
gene expression table. Specially, read pairs were then mapped to human ribosomal the 9,878 cells with at least one pair of productive α and β chains, only 3 cells were
RNA sequences (download from RFam database) and the read pairs with both identified as invariant natural killer T cells, and 102 cells were identified as MAIT
ends unmapped were kept for downstream analysis. Read pairs passing this filter cells, including 71 CD8+CD4− T cells classified in silico.
for rRNA were aligned to human reference sequence (hg19) using GSNAP34, with Unsupervised clustering analysis of CRC scRNA-seq dataset. The expression
parameters ‘–novelsplicing 1 -n 10 -i 1 -M 2’. To calculate the expression levels of tables of CD8+CD4− T cells and CD8−CD4+ T cells as defined by the aforemen-
genes, the gene model file ‘knownGene.txt’ (30 June 2013 version), downloaded tioned in silico classification but excluding MAIT cells and invariant natural killer
from UCSC, was used. The R function findOverlaps was used to count the number T cells, were fed into an iteratively unsupervised clustering pipeline separately.
of uniquely mapped read pairs located in each gene and the count table tabulated Specifically, given an expression table, the top n genes with the largest variance were
as genes by cells was used for downstream analysis. The transcripts per million selected, and then the expression data of the n genes were analysed by single-cell
(TPM) table was derived from the count table and the TPM value was calculated by consensus clustering (SC3)43. n was tested from 500, 1,000, 1,500, 2,000, 2,500 and
3,000. In SC3, the distance matrices were calculated based on Spearman correla-
106×C ij /lengthofgenei tion and then transformed by calculating the eigenvectors of the graph Laplacian.
∑ C/lengthofgenei Then, the k-means algorithm was applied to the first d eigenvectors multiple times,
i ij in which d was chosen as between 4% and 7% of the total number of input cells.
in which Cij was the count value of gene i in cell j. Finally, hierarchical clustering with complete agglomeration was performed on
Low-quality cells were filtered if the library size or the number of expressed genes the SC3 consensus matrix and k clusters were inferred. The SC3 parameter k,
(counts larger than 0) was smaller than predefined thresholds. Both thresholds which was used in the k-means and hierarchical clustering, was tried from 2 to 10.
© 2018 Springer Nature Limited. All rights reserved.

## Page 8

Letter reSeArCH
For each SC3 run, the silhouette values were calculated, the consensus matrix second round analysis respectively, and for CD4+ T cell data, (120, 2) and (130, 2)
was plotted and cluster-specific genes were identified. Such information was used were used for the first and second round analysis, respectively.
to determine the optimal k and n. Once the stable clusters were determined, the Gene set enrichment analysis. Pre-ranked analysis module in GSEA47 was used
above procedure was iteratively applied to each of these clusters to reveal the sub- for gene set enrichment analysis. The gene sets we used were from the database
clusters. The in silico classified CD8+CD4− MAIT cells had distinct gene expression MSigDB48. In single cluster enrichment analysis, the normalized and centred
patterns compared with other CD8+CD4− T cells, and were defined as cluster expression data were transformed to z-scores. For each cluster, the z-scores across
‘CD8_C08-SLC4A10’. cells were averaged per gene. Each cluster had an average expression profile. The
When the clustering results were obtained, one-way ANOVA implemented z-score profile was used as input for GSEA.
by R function ‘aov’ was performed to identify the differentially expressed genes Identification of proliferative cells. The average expression of known prolifera-
among the clusters. R function TukeyHSD was used to identify which cluster pairs tion-related genes was defined as the proliferation score. These proliferation genes
showed a significant difference. A gene was defined as being significantly differen- include ZWINT, E2F1, FEN1, FOXM1, H2AFZ, HMGB2, MCM2, MCM3, MCM4,
tially expressed based on the following criteria: (1) adjusted P value (Benjamini– MCM5, MCM6, MKI67, MYBL2, PCNA, PLK1, CCND1, AURKA, BUB1, TOP2A,
Hochberg method) of F-test of less than 0.05; (2) the absolute difference of any one TYMS, DEK, CCNB1 and CCNE149. Proliferative cells were identified using an out-
significant cluster pair (P value of Tukey’s honest significant difference method less lier detection procedure implemented in the R package extremevalues. Specifically,
than 0.01) larger than 1. The significantly differentially expressed genes were cate- as most of the proliferation scores came from low-proliferation cells, a normal
gorized in the cluster that showed the highest expression (Supplementary Table 5). distribution was fitted using cells with proliferation scores between 10% and 90%
The t-SNE method implemented in R package Rtsne was used for clustering quantiles. Cells with a proliferation score larger than a threshold were classified as
visualization. To visualize the cell density on the t-SNE plot, kernel density esti- proliferative cells, and this threshold value was optimally set by the getOutliersI
mation was performed using R function ‘kde’ (ks package), and the contour lines function of the extremevalues package.
encompassing the top 10%, 20%, …90% cells with highest densities were shown. Trajectory analysis. To characterize the potential process of T cell functional
A total of 8,530 T cells, including 3,628 CD8+CD4− and 4,902 CD8−CD4+ T cells changes and determine the potential lineage differentiation between diverse T cells,
with clustering definitions, were used in the t-SNE projection. Other cells such we applied the Monocle (version 2) algorithm50 with the top 700 signature genes
as CD8+CD4+ and CD8−CD4− T cells were not included in this visualization. of CD8+ T cells excluding MAIT cells, based on the rank of F statistic generated by
To validate the clustering results from the SC3 pipeline, we also performed ANOVA (Supplementary Table 5). Cells were ordered through the inferred pseu-
clustering analysis using two additional pipelines, Seurat44 and sscClust10. Raw dotime to indicate their differentiation progress. The Monocle function relative2abs
read-count tables were provided to the Seurat pipeline. For each cell, the counts was used to convert TPM measurement into mRNAs per cell (RPC), and then the
were normalized by the total counts then multiplied by a scale factor of 100,000 CellData Set object was created with the parameter ‘expressionFamily = negbinomial’.
before transforming to the log2 scale. To identify highly variable genes, the relation- Then the CD8+ T cell differentiation trajectory was inferred after dimension reduc-
ship between mean expression and dispersion was fitted with log(VMR) (variance tion and cell ordering with the default parameters of R package Monocle.
to mean ratio) as dispersion function. The mean expression cut-offs were set at TCGA data analysis. The TCGA colon adenocarcinoma (COAD) and rectum
0.0125 and 8 for low and high limit, respectively, and dispersion cut-off was set at adenocarcinoma (READ) data were used to confirm the differences of the
0.5 for low limit. The donor covariate effect was removed by regression, and the T cell subtype compositions between patients with MSI-H (n = 62) and MSS
resulting data were used to perform PCA. The top 15 principal components were (n = 286). None of the patients from the TCGA COAD and READ had any pre-
kept and clusters were identified by the SNN algorithm. Resolution parameters vious record of immunotherapy treatment. The gene expression data and clinical
of 0.7 and 1.0 were set for CD8+ T cell data and CD4+ T cell data, respectively. data were downloaded from UCSC Xena (http://xena.ucsc.edu/). We calculated
The sscClust method is a two-round clustering pipeline that uses both PCA and the average expression of known marker genes of TH17 cells (IL17A, IL17F,
t-SNE for dimension reduction and uses a density-based clustering method. The IL23R, CCR6, RORC and CD4) and TH1-like cells (CXCL13, HAVCR2, IFNG,
normalized expression data used in SC3 analysis were also used in the sscClust CXCR3, BHLHE40 and CD4) after z-score normalization with log-transformed
analysis. In the first round, the top 1,500 genes with the highest standard deviation expression profiles. P values from the Wilcoxon test were used to determine the
were used for PCA, and top principal components were used for t-SNE, imple- statistical significance in R.
mented in R package Rtsne. The R package densityClust45 was used for density Definition of STARTRAC indices for tissue distribution, clonal expansion,
peak identification and cluster assignment. Subsequently, differentially expressed tissue migration and state transition. We present STRATRAC as a framework,
genes were identified by analysis of variance, and the top 1,000 genes were used defined by four indices, to analyse different aspects of T cells based on paired
in the second round of PCA/t-SNE/densityClust analysis. In both rounds, top single-cell transcriptomes and TCR sequences. The first index, STARTRAC-dist,
15 principal components were used. The rho and delta parameters of densityClust, uses the ratio of observed over expected cell numbers in tissues to measure the
which denote the density of each cell and the minimum distance to other cells with enrichment of T cell clusters across different tissues. Given a contingency table
density larger than the cell in consideration, were chosen based on the rho-delta of T cell clusters by tissues, we first apply chi-squared test to evaluate whether the
decision plot. Specifically, for the CD8+ T cell data, rho/delta of 40/5 and 30/3 distribution of T cell clusters across tissues significantly deviates from random
were used for the first and second round analysis, respectively; for the CD4+ T cell expectations. We then calculate the STARTRAC-dist index for each combination
data, 50/4 and 50/4 were used for first and second round analysis, respectively. of T cell clusters and tissues according the following formula:
Down-sampling analysis of CRC T cell scRNA-seq dataset. To evaluate the effect
o af f t c e e r l l d n o u w m n b - e sa rs m o p n l i c n lu g s t t h er e i n C g R r C es u T l t c s, e w ll e d i a t t e a r a t t o iv 1 e 0 ly 0 r , e 2 p 0 e 0 a , t e 5 d 0 0 th , e 1 , c 0 lu 0 s 0 t , e 1 ri , n 5 g 0 0 a , n 2 a , l 0 ys 0 i 0 s I d S i T st ARTRAC=R o/e = o ex b p se e r c v te e d d
and 3,000 cells. For each down-sampling number, 10 replicates were performed.
Each down-sampled dataset was used for clustering analysis by sscClust (for speed
in which Ro/e is the ratio of observed cell number over the expected cell number of
a given combination of T cell cluster and tissue. The expected cell number for each
considerations and similarity to the SC3 results), the resulting cluster labels were
combination of T cell clusters and tissues are obtained from the chi-squared test.
c u o s m in p g a t r h e e d n w o i r th m o a u li r z b ed en m ch u m tu a a r l k i n la f b o e r l m s, a a t s i o o n bt ( a N in M ed I f ) r i o n m de t x h 4 e 6 . w A h o h l i e g d h a e t r a s N e M t an I a in ly d s e is x , Different from the chi-squared values, which are defined as (observe e d xp − ec e te x d pected)2 and
means more accurate cluster assignment in the down-sampled dataset. The can only indicate the divergence of observations from random expectations,
sscClust pipeline was run with largely the same procedure described in the previous I d S i T st ARTRAC defined by Ro/e can indicate whether cells of a certain T cell cluster are
section but with different (rho and delta) parameters. The same (rho and delta) enriched or depleted in a specific tissue. For example, if Ro/e > 1, it suggests that
parameters were used in both rounds of clustering. The rho parameter was set at cells of the given T cell cluster are more frequently observed than random expec-
1.5, 3, 7.5, 15, 20, 20 and 20 for cell numbers ranging from 100 to 3,000, respec- tations in the specific tissue, that is, enriched. If Ro/e < 1, it suggests that cells of the
tively. For the delta parameter, values of 2 to 7 were tested and the value that gave given T cell cluster are observed with less frequency than random expectations in
the highest NMI value was chosen as the optimal parameter. the specific tissue, that is, depleted. By calculating the STARTRAC-dist indices via
Analysis of combined CRC, HCC and NSCLC T cell scRNA-seq datasets. The Ro/e, we can quantify the tissue preference of T cell clusters efficiently.
expression data of cells passing the quality control filters in the three studies The other three STARTRAC indices, STARTRAC-expa, STARTRAC-migr and
for HCC, NSCLC and CRC T cells (GEO accessions GSE98638, GSE99254 and STARTRAC-tran, are designed to measure the degree of clonal expansion, tissue
GSE108989) were fetched, and then re-processed using the same aforementioned migration, and state transition of T cell clusters upon TCR tracking, respectively.
pipeline for in silico classification and normalization. The in silico-classified The MAIT cells (CD8_C08-SLC4A10) were not included in these types of analyses
CD8+CD4− and CD8−CD4+ T cells, excluding invariant natural killer T cells, because they have distinct TCRs. For STARTRAC-expa, which uses the standard
were used in combined clustering analysis. The large combined dataset demanded TCR clonality measurement51 but is specifically applied to different T cell clusters
the use of the sscClust method for its high computational efficiency. For CD8+ in our analyses, we first adopt the normalized Shannon entropy to calculate the
T cell data, rho and delta parameters (100, 5) and (100, 3) were used for the first and evenness of the TCR repertoire of the given T cell cluster and then define the
© 2018 Springer Nature Limited. All rights reserved.

## Page 9

reSeArCH Letter
STARTRAC-expa index as 1 − evenness. Mathematically, the STARTRAC-expa After the extent of tissue migration of each clonotype is quantified by
index of a specific cluster with N clonotypes is defined by the following formula: STARTRAC-migr, given a cluster with total T clonotypes, the STARTRAC-migr
index at the cluster level ISTARTRAC can be defined as the weighted average of all
ISTARTRAC=1−evenness=1− −∑ i N =1 p i log 2 p i TCR clonotype migration m in ig d r ices contained in the cluster:
expa log N
2 T
ISTARTRAC=∑pt It
in which pi is the cell frequency of clonotype i in the cluster, and a clonotype migr
t=1
cls migr
is defined by identical, full-length, paired α and β TCR chains. Although the
definition of STARTRAC-expa is mathematically identical to the clonality scores in which pt is the ratio of the number of cells with clonotype t in cluster cls to the
cls
frequently used in bulk TCR repertoire sequencing studies51, two distinctions total number of cells in cluster cls.
should be noted. First, STARTRAC-expa is defined for T cell clusters while the Similarly, when the extent of state transition of each clonotype is quantified by
traditional TCR clonality is defined for specific specimens. A T cell cluster in STARTRAC-tran, given a cluster with total T clonotypes, the STARTRAC-tran
STARTRAC framework can consist of T cells from several tissues and patients, index at the cluster level can be defined as the weighted average of all TCR clono-
but the specimens subject to bulk TCR repertoire sequencing are typically from types state transition indices contained in the cluster:
a unique tissue and patient. Second, STARTRAC-expa uses a more stringent
T
clonotype definition. For traditional bulk TCR sequencing studies, clonotypes are ISTARTRAC=∑pt It
generally defined based on identical CDR3 (the complementarity determining tran t=1 cls tran
region 3) sequences of TCR α or β chains, owing to technological limitations.
in which pt is the ratio of the number of cells with clonotype t in cluster cls to the
However, STARTRAC-expa is defined using the strictest clonotype definition, cls
total number of cells in cluster cls.
which requires that both the full-length α and β chains of TCRs are identical at
Of note, both STARTRAC-migr and STARTRAC-tran are defined at two
the nucleotide level. Thus, although STARTRAC-expa has an identical mathemat-
different levels (clonotypes and clusters), with the clonotype-level definitions
ical formula to that of the traditional TCR clonality definition, they have distinct
describing the extent of migration and state transition of a given clonotype, and
biological meanings. STARTRAC-expa ranges from 0 to 1, with 0 indicating
the cluster-level definitions depicting the summarization of such properties of all
no clonal expansion for each clonotype while 1 indicating that the cluster is
clonotypes within a cluster.
composed of only one clonally expanded clonotype. If a cluster is composed of multiple
Besides the overall evaluation of the extents of migration and state transitions
clonotypes and each clonotype is subject to distinct extent of clonal expansion,
by STARTRAC-migr and STARTRAC-tran, we also define pairwise STARTRAC-
STARTRAC-expa will be between 0 and 1, with high STARTRAC-expa indicating
migr (pSTARTRAC-migr) and STARTRAC-tran (pSTARTRAC-tran) indices for
high clonality.
precise quantification. For example, given a clonotype t and two tissue types
Even if T cells with identical TCR clonotypes are present in different tissues or
(for example, blood and tumour), the pSTARTRAC-migr index It is calculated
in different development states, logically they could likely derive from a single naive pmigr
by the following formula:
T cell, clonally expanded initially at one location and migrated across tissues, or
have undergone state transitions. Based on this principle, we define STARTRAC- 2
migr and STARTRAC-tran to evaluate the extent of tissue migration and state It =−∑ptlog pt
p migr j 2 j
transition of each clonotype, respectively. For each clonotype, given its distribution j=1
a it c s r S o T ss A t R is T su R e A s C (p - e m ri i p g h r e in ra d l e b x l o I o t d, a a d s: jacent normal mucosa and tumour), we define in which p j t is the ratio of the number of cells with TCR clonotype t in tissue j to
migr the total number of cells with TCR clonotype t in tissues 1 and 2 (that is, blood and
I m t igr =−∑ J p j tlog 2 p j t t m um ul o a u a r s ) , S a T n A d R ∑ T 2 j R =1 A p C j t - = m 1 i . g I r n b o u th t e li r m w i o t r s d t s h , e p S n T u A m R b T e R r A o C f - t m iss ig u r e u s s t e o s t t h w e o s a a m nd e f t o h r e -
j=1 frequencies of cells between two specified tissues are re-calculated. Likewise, given
i t n h e w t h o i t c a h l n p u j t m is b th er e o ra f t c io el l o s f w th it e h n T u C m R b e c r l o o n f o c t e y ll p s e w t i a th n d T C ∑ R J clo p n t o = ty 1 p . e F t o i r n t t w is o su T e c j e t l o l a T R cl A on C o - t t y r p an e t in a d n e d x t w p o I t t r T an c i e s l l c a cl l u cu st l e a r te s d (f b o y r e th xa e m fo p ll l o e w , T in EM g f a o n r d m T u E la X : cells), the pSTAR-
j=1 j
clusters with similar clonal expansion and clonal size, the one with clonal cells 2
broadly distributed in various tissues would probably be more mobile. Similarly, It =−∑ptlog pt
the STARTRAC-tran index I
t
t
ran
can be defined as: ptran k=1 k 2 k
I t t ran =− k ∑ = K 1 p k tlog 2 p k t T i t n h E e w X t h c o e t ic a ll h l s n ) p , u k t a m n is d b t e h ∑ r e o 2 k r f = a c t 1 i e o p ll k t s o = f w t i h 1 th e . T n T u h C m u R s b , c e p lo r S n o T o f A t c y R e p l T l e s R t w A in it C h c - l T t u r s C a t n e R r u s c s l 1 o e a n s n o t d h ty e 2 p s e ( a t t m h i a n e t i f c s o l , u r T s m t E e M u r l a a k n a t d o s
STARTRAC-tran but limits the number of clusters to two, and the frequencies of
i t n h e w t h o i t c a h l n p u k t m is b th e e r r o a f t i c o e l o ls f t w h i e t h n u T m C b R e r c l o o f n c o e t l y ls p w e i t t , h ∑ T k K C = R 1 p c k l t o = no 1 ty , p an e d t i K n c is lu t s h t e e r t o k t t a o l c S e T l A ls R b T e R t A w C ee - n m i t g h r e a t n w d o S T sp A e R c T if R ie A d C c - l t u ra s n te f r o s r a c r lo e n r o e t - y c p a e lc s u a l r a e t o e b d t . a O in n ed ce , t p he a i c r o w r i r s e e -
number of cell clusters. Although both definitions use Shannon entropy for calcu- sponding indices for clusters are calculated via weighted average according to their
lation, they are distinct from the measurement of TCR clonality in bulk TCR rep- clonotype compositions. As all STARTRAC-migr and STARTRAC-tran indices
ertoire sequencing. As described above, the traditional TCR clonality is defined at are defined by Shannon entropy, high values indicate high migration and state
the sample level; however, STARTRAC-migr and STARTRAC-tran are defined transition, respectively.
primarily at the clonotype level. Given one clonotype, the evenness or diversity of Reporting summary. Further information on research design is available in
its TCR repertoire will be zero because all the cells have identical TCRs, while the the Nature Research Reporting Summary linked to this paper.
STARTRAC-migr and STARTRAC-tran indices will be non-trivial because cells of Code availability. The open source code is available at GitHub. Code for ssc-
the same clonotype can migrate across tissues or change their transcriptional states. Clust clustering is available on GitHub (https://github.com/Japrin/sscClust).
Thus, the inputs of the formulas of STARTRAC-migr and STARTRAC-tran are also Code for STARTRAC analysis is available on GitHub (https://github.com/Japrin/
different from the traditional TCR clonality measurement and STARTRAC-expa. STARTRAC).
The input of STARTRAC-migr is the observed cell frequency across tissues of a
certain clonotype, while the input of STARTRAC-tran is the observed cell frequency
Data availability
across cell clusters of a certain clonotype. By contrast, the input of STARTRAC-expa
The data that support the findings of this study are available from the correspond-
is the observed cell frequency across clonotypes of a certain cell cluster, and the
ing author upon request. Sequencing data are available at EGA (accession number
input for the traditional TCR clonality measure is the observed sequence frequency
EGAS00001002791), and processed gene expression data can be obtained from
across a TCR repertoire of a given sample. For the calculation of STARTRAC-migr,
Gene Expression Omnibus (GEO) (accession number GSE108989).
to exclude the possible influence of different extent of expansion or local prolifer-
ation of T cells, we also calculate the proliferation-normalized STARTRAC-migr
index, which normalizes the number of expanded cells of clonotypes in each tissue 31. Picelli, S. et al. Full-length RNA-seq from single cells using Smart-seq2.
Nat. Protoc. 9, 171–181 (2014).
as 1. As expected, we found a similar trend of T cell migration potentials for both
CD8+ and CD4+ T cells evaluated by this proliferation-normalized STARTRAC- 32. Emtage, P. C. et al. Second-generation anti-carcinoembryonic antigen designer
T cells resist activation-induced cell death, proliferate on tumor contact, secrete
migr as those calculated by STARTRAC-migr (data not shown). To make our cytokines, and exhibit superior antitumor activity in vivo: a preclinical
calculation consistent, we used STARTRAC-migr for subsequent analyses. evaluation. Clin. Cancer Res. 14, 8112–8122 (2008).
© 2018 Springer Nature Limited. All rights reserved.

## Page 10

Letter reSeArCH
33. Chodisetti, S. B. et al. Triggering through Toll-like receptor 2 limits chronically 42. Godfrey, D. I., Stankovic, S. & Baxter, A. G. Raising the NKT cell family.
stimulated T-helper type 1 cells from undergoing exhaustion. J. Infect. Dis. 211, Nat. Immunol. 11, 197–206 (2010).
486–496 (2015). 43. Kiselev, V. Y. et al. SC3: consensus clustering of single-cell RNA-seq data.
34. Wu, T. D. & Nacu, S. Fast and SNP-tolerant detection of complex variants and Nat. Methods 14, 483–486 (2017).
splicing in short reads. Bioinformatics 26, 873–881 (2010). 44. Butler, A., Hoffman, P., Smibert, P., Papalexi, E. & Satija, R. Integrating single-cell
35. Lun, A. T., Bach, K. & Marioni, J. C. Pooling across cells to normalize transcriptomic data across different conditions, technologies, and species.
single-cell RNA sequencing data with many zero counts. Genome Biol. 17, 75 Nat. Biotechnol. 36, 411–420 (2018).
(2016). 45. Rodriguez, A. & Laio, A. Clustering by fast search and find of density peaks.
36. Li, H. & Durbin, R. Fast and accurate long-read alignment with Burrows–Wheeler Science 344, 1492–1496 (2014).
transform. Bioinformatics 26, 589–595 (2010). 46. Strehl, A. & Ghosh, J. Cluster ensembles—a knowledge reuse framework
37. DePristo, M. A. et al. A framework for variation discovery and genotyping using for combining multiple partitions. J. Mach. Learn. Res. 3, 583–617 (2002).
next-generation DNA sequencing data. Nat. Genet. 43, 491–498 (2011). 47. Subramanian, A. et al. Gene set enrichment analysis: a knowledge-based
38. Saunders, C. T. et al. Strelka: accurate somatic small-variant calling from approach for interpreting genome-wide expression profiles. Proc. Natl Acad. Sci.
sequenced tumor-normal sample pairs. Bioinformatics 28, 1811–1817 USA 102, 15545–15550 (2005).
(2012). 48. Liberzon, A. et al. The Molecular Signatures Database (MSigDB) hallmark gene
39. Amarasinghe, K. C. et al. Inferring copy number and genotype in tumour exome set collection. Cell Syst. 1, 417–425 (2015).
data. BMC Genomics 15, 732 (2014). 49. Whitfield, M. L., George, L. K., Grant, G. D. & Perou, C. M. Common markers of
40. Wang, K., Li, M. & Hakonarson, H. ANNOVAR: functional annotation of genetic proliferation. Nat. Rev. Cancer 6, 99–106 (2006).
variants from high-throughput sequencing data. Nucleic Acids Res. 38, e164 50. Qiu, X. et al. Single-cell mRNA quantification and differential analysis with
(2010). Census. Nat. Methods 14, 309–315 (2017).
41. van Wilgenburg, B. et al. MAIT cells are activated during human viral infections. 51. Kirsch, I., Vignali, M. & Robins, H. T-cell receptor profiling in cancer. Mol. Oncol.
Nat. Commun. 7, 11653 (2016). 9, 2063–2070 (2015).
© 2018 Springer Nature Limited. All rights reserved.

## Page 11

reSeArCH Letter
Extended Data Fig. 1 | Study design and tracking T cell dynamics of estimated by the average entropy of its clonotypes across two different
patients with CRC by STARTRAC. a, The experimental flowchart of functional clusters. The detailed definitions of STARTRAC indices are in
this study. b, A cartoon illustrating four indices defined by STARTRAC Methods. c, Opal multi-colour IHC staining with anti-CD3, -CD4, -CD8
to characterize T cell dynamics. STARTRAC-dist, tissue preference and -FOXP3 antibodies to validate the existence of T cells in CRC tumours
of a cluster estimated by ratios of observed cell numbers to random (exemplified by patient P0215). Original magnification, ×20. TC, CD8+
expectations (Ro/e); STARTRAC-expa, degree of clonal expansion of a cytotoxic T cells; TH, CD4+ T helper cells. d, Gating strategy for single
cluster defined as ‘1 − evenness’, with evenness as the normalized Shannon T cell sorting in this study (exemplified by patient P0215). TC, TH and Treg
entropy of its TCR distribution; STARTRAC-migr, migratory potential of cells were enriched by sorting 7AAD−CD3+CD8+, 7AAD−CD3+CD4+
a cluster estimated by the average entropy of its clonotypes across tissues; CD25-/int and 7AAD−CD3+CD4+ CD25hi T cells, respectively.
STARTRAC-tran, potentials of developmental transitions of a cluster,
© 2018 Springer Nature Limited. All rights reserved.

## Page 12

Letter reSeArCH
Extended Data Fig. 2 | Pathological and genomic characteristics of CRC bottom). The copy number information was obtained by ADTex and
tumours in the study. a, Deficiency of mismatch repair proteins including depicted in bin count plots across chromosomes. The read count ratios
MLH1, MSH2, MSH6 and PMS2 in all MSI patients (P0413, P0825, (‘1’ in y axis means baseline copy number) and B allele frequencies (BAF)
P0909 and P0123) measured by IHC (n = 12 patients). +, proficiency; are shown. Various coloured dots in the ratio graph represent different
−, deficiency. Original magnification, ×200. b, Profiles of DNA copy copy number status of each segment. ASCNA, allele-specific copy number
numbers of two representative patients (MSI patient, top; MSS patient, alteration; HET, heterozygous; LOH, loss of heterozygosity.
© 2018 Springer Nature Limited. All rights reserved.

## Page 13

reSeArCH Letter
Extended Data Fig. 3 | See next page for caption.
© 2018 Springer Nature Limited. All rights reserved.

## Page 14

Letter reSeArCH
Extended Data Fig. 3 | Basic information of the single T cell RNA- cell numbers. Clonal cells are defined as those clonotypes containing at
seq data. a, Saturation curves of the number of detected genes against least two cells. f, t-SNE projection of 3,557 CD8+ T cells (CD8_C01-LEF1,
sequencing depth (exemplified by cell NTC-53 from patient P1228). Each n = 174; CD8_C02-GPR183, n = 169; CD8_C03-CX3CR1, n = 743;
point on the curve is derived from calculations based on the random CD8_C04-GZMK, n = 773; CD8_C05-CD6, n = 487; CD8_C06-CD160,
selection of a fraction of raw reads from each sample, representing the n = 351; CD8_C07-LAYN, n = 860) based on different clustering methods
average of 100 replicate sub-samplings. Error bars denote s.d. Each including SC3, Seurat and sscClust. Each point represents one single
line with a different colour shows how fast a gene can reach detection cell coloured by cluster label. g. Box plots showing the down-sampling
saturation at different expression levels, represented by a particular analysis of clustering performed on CD8+ and CD4+ T cell dataset. Each
TPM value. b, Unbiased coverage of gene body from 5′ to 3′ between dot represents an individual clustering of a given number of T cells. The
blood, tumours and adjacent normal tissues. c, Frequencies of the V and down-sampling and clustering were performed iteratively for each cell
J segments of the TCR α chains. d, Frequencies of the V and J segments number (n = 10 times). Each down-sampled clustering was compared
of the TCR β chains. e, Bar plots showing the number of clonotypes and to the clustering performed on the entire dataset, using the NMI index.
clonal cells in each CD8+ and CD4+ T cell cluster. The clonotypes are Higher NMI values indicate more accurate cluster assignment.
categorized as unique (n = 1) and clonal (n = 2 and n ≥ 3) based on their
© 2018 Springer Nature Limited. All rights reserved.

## Page 15

reSeArCH Letter
Extended Data Fig. 4 | Expression levels of signature genes in each T cell CD8_C05-CD6, n = 487; CD8_C06-CD160, n = 351; CD8_C07-LAYN,
cluster. a, Gene expression heat map of 8 CD8+ T cell (n = 3,628) clusters. n = 860; CD8_C08-SLC4A40, n = 71; CD4_C01-CCR7, n = 462;
Rows represent signature genes and columns represent different clusters. CD4_C02-ANXA1, n = 472; CD4_C03-GNLY, n = 190; CD4_C04-TCF7,
b, Gene expression heat map of 12 CD4+ T cell clusters (n = 4,902). n = 388; CD4_C05-CXCR6, n = 568; CD4_C06-CXCR5, n = 262; CD4_
c, t-SNE plot of expression levels of selected genes in different clusters C07-GZMK, n = 185; CD4_C08-IL23R, n = 244; CD4_C09-CXCL13,
indicated by the coloured oval corresponding to Fig. 1a. Number of cells n = 319; CD4_C10-FOXP3, n = 389; CD4_C11-IL10, n = 103; CD4_C12-
contained in each cluster: CD8_C01-LEF1, n = 174; CD8_C02-GPR183, CTLA4, n = 1,320.
n = 169; CD8_C03-CX3CR1, n = 743; CD8_C04-GZMK, n = 773;
© 2018 Springer Nature Limited. All rights reserved.

## Page 16

Letter reSeArCH
Extended Data Fig. 5 | See next page for caption.
© 2018 Springer Nature Limited. All rights reserved.

## Page 17

reSeArCH Letter
Extended Data Fig. 5 | Summary of functional properties of various showing the presence of different T cell clusters in peripheral blood
T cell clusters. a, Functional subsets of CD4+ T cell (n = 4,902) clusters (n = 2,449; CD8+ T cells, n = 1,021; CD4+ T cells, n = 1,428), adjacent
defined by a set of known marker genes. Number of cells contained in each normal tissues (n = 1,962; CD8+ T cells, n = 961; CD4+ T cells, n = 1,001)
CD4+ cluster: TN, n = 462; P.TCM, n = 472; TEMRA, n = 190; N.TCM, and tumours (n = 4,119; CD8+ T cells, n = 1,646; CD4+ T cells,
n = 388; TRM, n = 568; follicular T helper (TFH), n = 262; TEM, n = 185; n = 2,473). d, Overview of T cell cluster characteristics. STARTRAC-dist:
TH17, n = 244; TH1-like cells, n = 319; P.Treg, n = 389; N.Treg, n = 103; +++ indicates Ro/e > 1; ++, 0.8 < Ro/e ≤ 1; +, 0.2 < Ro/e ≤ 0.8; +/−, 0 <
T.Treg, n = 1,320. N, normal tissue; P, peripheral blood; T, tumour. Ro/e ≤ 0.2; −, Ro/e = 0. STARTRAC-expa: +++ indicates I
e
S
x
T
p
A
a
RTRAC > 0.10;
b, Characteristics of the CD8+ IEL T cells as defined by the expression ++, 0.06 < ISTARTRAC ≤ 0.10; +, 0.005 < ISTARTRAC ≤ 0.05; -,
expa expa
properties of a panel of functionally relevant genes in CD8+ T cells ISTARTRAC ≤ 0.005. STARTRAC-migr: +++ indicates ISTARTRAC > 0.50;
expa migr
(n = 3,628). Number of cells contained in each CD8+ cluster: TN, n = 174; ++, 0.21 < I
m
ST
ig
A
r
RTRAC ≤ 0.50; +, 0.1 < I
m
ST
ig
A
r
RTRAC ≤ 0.20; −,
TCM, n = 169; TEMRA, n = 743; TEM, n = 773; TRM, n = 487; IEL, n = 351; I
m
ST
ig
A
r
RTRAC ≤ 0.1. STARTRAC-tran, +++ indicates I
t
S
r
T
an
ARTRAC > 0.20; ++,
TEX, n = 860; MAIT, n = 71. For violin plots in a and b, colours denote 0.10 < I
t
S
r
T
an
ARTRAC ≤ 0.20; +, 0.05 < I
t
S
r
T
an
ARTRAC ≤ 0.10; −, I
t
S
r
T
an
ARTRAC ≤ 0.05.
average expression levels; widths denote cell densities. c, t-SNE plot
© 2018 Springer Nature Limited. All rights reserved.

## Page 18

Letter reSeArCH
Extended Data Fig. 6 | See next page for caption.
© 2018 Springer Nature Limited. All rights reserved.

## Page 19

reSeArCH Letter
Extended Data Fig. 6 | CD8+ TEX cells are characterized by high P < 0.01; fold change ≥ 2; two-sided unpaired limma-moderated t-
proliferation property and production of effector molecules. a, A test; Benjamini–Hochberg adjusted P value e, Violin plot showing the
subpopulation of CD8+ TEX shows high expression of MKI67 among 8,530 expression of TBX21, EOMES and PDCD1 in each CD8+ T cell (n = 3,628)
T cells. b, Gene set enrichment analysis (GSEA) showing the enrichment cluster and the low-proliferative (n = 720) or high-proliferative (n = 140)
of proliferation-related pathways in CD8+ TEX cells (n = 3,628; false TEX cell subsets. f, Most of the clonotypes of high-proliferative TEX cells
discovery rate < 0.01; labelled in red). c, Representative example of a were also found in low-proliferative TEX cells (top). Each row represents an
CRC tumour stained by multi-coloured IHC showing co-expression of individual clonotype from one patient. Venn diagram showing overlapped
Ki67, CD8, PD-1 and HAVCR2 in CD8+ TEX cells (exemplified by P0413; clonal clonotypes (≥2 cells) of high- and low-proliferative TEX cells
n = 2 patients). Original magnification, ×20. d, Volcano plot showing the (bottom). g. Characteristics of CD8+ TEX cells (n = 3,628) as defined
differentially expressed genes between high-proliferative (n = 140) and by the gene expression of a series of transcription factors, checkpoint
low-proliferative (n = 720) TEX cells. Most of the highly expressed genes receptors, and effector molecules. For violin plots in e and g, colours
in high-proliferative TEX cells are related to cell proliferation. Adjusted denote average expression levels; widths denote cell densities.
© 2018 Springer Nature Limited. All rights reserved.

## Page 20

Letter reSeArCH
Extended Data Fig. 7 | Distinct migration capabilities of different blue represent clonotypes shared by blood–normal, blood–tumour
CD8+ T cell clusters. a, Top, chord diagram showing the distribution and normal–tumour, respectively. Bottom, Venn diagram showing the
of clonotypes in blood, normal mucosa and tumours for different CD8+ distribution of expanded clonotypes in blood, tumour and normal TEMRA
T cell clusters. CD8+ TEMRA cells show remarkable TCR sharing among cells. b, Relative average expression patterns of migration-related genes
different tissues. The shadows coloured in transparent yellow, green across CD8+ T cell clusters (total n = 3,557 cells, excluding MAIT cells).
and orange represent blood, normal and tumour-specific clonotypes, Number of cells contained in each cluster: TN, n = 174; TCM, n = 169;
respectively. The bridges coloured in dark green, dark red and dark TEMRA, n = 743; TEM, n = 773; TRM, n = 487; IEL, n = 351; TEX, n = 860.
© 2018 Springer Nature Limited. All rights reserved.

## Page 21

reSeArCH Letter
Extended Data Fig. 8 | See next page for caption.
© 2018 Springer Nature Limited. All rights reserved.

## Page 22

Letter reSeArCH
Extended Data Fig. 8 | TCR sharing and state transitions of CD8+ shared TCRs with blood TEMRA and tumour TEX cells based on the number
T cell clusters implicated by STARTRAC-tran indices. a, Pie charts of clonotypes and clonal cells (related to Fig. 1h). ***P < 0.001, two-sided
showing the fraction of shared clonotypes with CD8+ TEM cells within Fisher’s exact test. f, Clonotypes of tumour TEM cells crossing different
the other indicated clusters (left). P12 represents merged data of 12 clusters showing mutually exclusive TCR sharing of tumour TEM cells with
patients with CRC. Bar plots showing the fraction of shared clonotypes blood TEMRA and tumour TEX cells. Each row represents an individual
of CD8+ TEM with other clusters within the CD8+ TEM. b, pSTARTRAC- clonotype from one patient. *P < 0.05, **P < 0.01, ***P < 0.001, two-
tran indices of CD8+ TCM, TEMRA, TRM, IEL and TEX cells for each patient sided Fisher’s exact test (based on the number of clonal cells in each
(depicted by dots). *P < 0.05, **P < 0.01, ***P < 0.001, Kruskal–Wallis patient). Number of clonal cells analysed in each patient: P1212, n = 30;
test. c, Potential developmental trajectory of CD8+ T cells (n = 3,557, P1228, n = 27; P0411, n = 11; P0825, n = 10; P1012, n = 7; P0701, n = 9;
excluding MAIT cells) inferred by Monocle2 based on gene expressions. P0123, n = 9; P0215, n = 17; P0309, n = 9; P0413, n = 2; P1207, n = 7;
d, Frequency of shared clonotypes in CD8+ TEMRA cells with various TEM P0909, n = 2.
cell subsets in each patient (n = 12). e, Statistical analysis of tumour TEM
© 2018 Springer Nature Limited. All rights reserved.

## Page 23

reSeArCH Letter
Extended Data Fig. 9 | Characterization of CD4+ TEMRA and tumour c, Developmental transition of tumour Treg cells, TH17 cells and TH1-like
Treg cells by STARTRAC analysis. a, Violin plots showing normalized cells with other CD4+ cells quantified by pSTARTRAC-tran indices for
expression of cytotoxic related molecules in 12 CD4+ (n = 4,902 cells) and each patient (n = 11). d, Representative example of a CRC tumour stained
8 CD8+ (n = 3,628) T cell clusters. Colours denote mean values; width by IHC, with white arrow showing co-expression of CD3, FOXP3 and
denotes cell densities. b, Venn diagram highlighting common clonotypes RORγ (n = 2 patients). Original magnification, ×20.
(ncell ≥ 2) shared between tumour Treg and other CD4+ T cell clusters.
© 2018 Springer Nature Limited. All rights reserved.

## Page 24

Letter reSeArCH
Extended Data Fig. 10 | See next page for caption.
© 2018 Springer Nature Limited. All rights reserved.

## Page 25

reSeArCH Letter
Extended Data Fig. 10 | Comparative analysis of T cells from different by different tissue origins. CD4+ T cell clusters with frequencies below
cancer indications based on integrated analyses. a, t-SNE plot of 8,874 3% are not labelled. e, Comparison of the fractions of CD8+ IEL (CD8_
single CD8+ T cells from this CRC study (n = 3,632), and previous HCC9 C08-CD160) and MAIT (CD8_C09-SLC4A10) cells in tumours from
(n = 1,467) and NSCLC10 (n = 3,775) studies. Nine CD8+ clusters were patients with CRC (n = 12), HCC (n = 5) and NSCLC (n = 14).
generated by sscClust based on the integrated dataset. The CRC-specific f, Comparison of the fractions of different CD8+ T cells and CD4+ T cells
IEL cells (CD8_C06-CD160) are highlighted. b, t-SNE plot of 12,635 in control tissues from patients with CRC (n = 12), HCC (n = 5) and
single CD4+ T cells from this CRC study (n = 4,929), and previous HCC9 NSCLC (n = 14). g, Validation of the enrichments of CXCL13+BHLHE40+
(n = 2,472) and NSCLC10 (n = 5,234) studies. The CRC-enriched TH17 TH1-like cells in patients with MSI-H CRC (n = 62) and TH17 cells
cells (CD4_C10-IL23R) are highlighted. Each dot represents one single in patients with MSS CRC (n = 286) in the TCGA COAD and READ
cell coloured by clusters and shaped by tumour types in a and b. cohorts by comparison of the indicated signature gene expression. Centre
c, Composition of different CD8+ T cells in each tumour type by different lines denote the median, top and bottom lines denote the 25th and 75th
tissue origins. CD8+ T cell clusters with frequencies below 3% are not percentiles. *P < 0.05, **P < 0.01, ***P < 0.001; two-sided Wilcoxon
labelled. d, Composition of different CD4+ T cells in each tumour type test (e–g).
© 2018 Springer Nature Limited. All rights reserved.

## Page 26

Letter reSeArCH
Extended Data Fig. 11 | See next page for caption.
© 2018 Springer Nature Limited. All rights reserved.

## Page 27

reSeArCH Letter
Extended Data Fig. 11 | IGFLR1 expression in activated CD4+ T cells FACS plots for HAVCR2 and IFNγ expression levels in CD8+ Tconv
and exhausted CD8+ T cells. a, Volcano plot showing differentially (activated by anti-CD3 plus anti-CD28) and TCS cells (in vitro chronically
expressed genes between tumour CXCL13+BHLHE40+ TH1-like T cells stimulated exhausted CD8+ T cells from corresponding individuals).
(n = 203) and other TH cells in tumours (n = 723; Supplementary Numbers in quadrants indicate the percentage of positive cells (n = 5
Table 10). Adjusted P < 0.01 (two-sided unpaired limma-moderated donors, n = 2 independent experiments). g, Representative histograms of
t-test; Benjamini–Hochberg adjusted P value) and fold change ≥ 2. PD-1, HAVCR2 (n = 8 donors, n = 3 independent experiments), CD39
b, Venn diagram showing the overlap of tumour CD8+ exhaustion-related and LAG3 (n = 4 donors, n = 2 independent experiments) expression
genes identified in this study (n = 68, Supplementary Table 11) with levels in CD8+ Tconv and TCS cells. h, Quantification of IFNγ levels
those from previous melanoma8 (n = 349), HCC9 (n = 82) and NSCLC10 produced by CD8+ Tconv and TEX cells from g of three donors.
(n = 90) studies. The detailed overlaps of CD8+ exhaustion-related genes i, Representative histogram of IGFLR1 expression levels in CD8+ Tconv
in different cancer types are in Supplementary Table 11. P < 2.2 × 10−16, and TCS cells. j, Expression levels of IGFLR1 in activated CD8+ Tconv and
hypergeometric test. c, CD4+ naive (TN) and memory (TMEM) T cells TCS cells determined by FACS (MFI, mean fluorescent intensity; n = 6
were gated as CD45RA+CCR7+ and CD45RA−CCR7+/− cells by FACS. donors, n = 4 independent experiments). k, Representative histograms
d, FACS plots of IGFLR1 expression in activated CD4+ T cells (n = 6 of HAVCR2 expression in TCS cells subjected to re-stimulation with
donors, n = 3 independent experiments). e, Quantification of IGFLR1 anti-CD3 alone (control) or together with recombinant human IGFL3 as
expression levels from d as a percentage of IGFLR1+ TN or TMEM CD4+ well as indicated antibodies for 2 days (n = 5 donors, n = 3 independent
subsets under suboptimal activation conditions (n = 7). Each symbol experiments). l, Quantification of HAVCR2 levels from k. Two-sided
represents a donor with mean ± s.e.m. shown (e, l). f, Representative paired Student’s t-test (e, j and l).
© 2018 Springer Nature Limited. All rights reserved.

## Page 28

1
nature
research
|
reporting
summary
April
2018
Corresponding author(s): Zemin Zhang
Reporting Summary
Nature Research wishes to improve the reproducibility of the work that we publish. This form provides structure for consistency and transparency
in reporting. For further information on Nature Research policies, see Authors & Referees and the Editorial Policy Checklist.
Statistical parameters
When statistical analyses are reported, confirm that the following items are present in the relevant location (e.g. figure legend, table legend, main
text, or Methods section).
n/a Confirmed
The exact sample size (n) for each experimental group/condition, given as a discrete number and unit of measurement
An indication of whether measurements were taken from distinct samples or whether the same sample was measured repeatedly
The statistical test(s) used AND whether they are one- or two-sided
Only common tests should be described solely by name; describe more complex techniques in the Methods section.
A description of all covariates tested
A description of any assumptions or corrections, such as tests of normality and adjustment for multiple comparisons
A full description of the statistics including central tendency (e.g. means) or other basic estimates (e.g. regression coefficient) AND
variation (e.g. standard deviation) or associated estimates of uncertainty (e.g. confidence intervals)
For null hypothesis testing, the test statistic (e.g. F, t, r) with confidence intervals, effect sizes, degrees of freedom and P value noted
Give P values as exact values whenever suitable.
For Bayesian analysis, information on the choice of priors and Markov chain Monte Carlo settings
For hierarchical and complex designs, identification of the appropriate level for tests and full reporting of outcomes
Estimates of effect sizes (e.g. Cohen's d, Pearson's r), indicating how they were calculated
Clearly defined error bars
State explicitly what error bars represent (e.g. SD, SE, CI)
Our web collection on statistics for biologists may be useful.
Software and code
Policy information about availability of computer code
Data collection No special or proprietary software was used.
Data analysis The following software was used in this study:
FlowJo v10, InForm Advanced Image Analysis v2.3, GSNAP (version 2014-10-22), TraCeR (version 2015-10-21), GSEA (version 2.2.4), bwa
(version 0.7.17), samtools (version 0.1.19), GATK (version 3.8-1-0), picard (version 2.18.9), strelka (version 1.0.14), ADTEx ( version 1.0.4),
annovar (version 2018-04-16).
R (version 3.5.0) and the additional packages: HTSeqGenie_4.8.0, scran_1.8.2, SC3_1.7.2, Seurat_2.3.2, monocle_2.8.0, Rtsne v0.13,
densityClust v0.3, ggplot2_2.2.1, ggpubr_0.1.7, VennDiagram_1.6.20, ks_1.11.2, limma_3.36.2, circlize_0.4.4, beeswarm_0.2.3,
Vennerable_3.1.0.9, ape_5.1 and ComplexHeatmap_1.18.1.
Code for sscClust clustering is available on GitHub (http://github.com/Japrin/sscClust). Code for STARTRAC analysis is available on GitHub
(https://github.com/Japrin/STARTRAC). Other ad hoc scripts for analysing data are available upon request.
For manuscripts utilizing custom algorithms or software that are central to the research but not yet described in published literature, software must be made available to editors/reviewers
upon request. We strongly encourage code deposition in a community repository (e.g. GitHub). See the Nature Research guidelines for submitting code & software for further information.

## Page 29

2
nature
research
|
reporting
summary
April
2018
Data
Policy information about availability of data
All manuscripts must include a data availability statement. This statement should provide the following information, where applicable:
- Accession codes, unique identifiers, or web links for publicly available datasets
- A list of figures that have associated raw data
- A description of any restrictions on data availability
Sequencing raw data have been uploaded to the EGA database under the accession number EGAS00001002791, and processed gene expression data can be
obtained from GEO dataset under accession number GSE108989. Such data will be publicly released upon acceptance of this manuscript. In addition, we also
developed an interactive web server (http://crc.cancer-pku.cn) for analysing, visualizing and downloading the single cell data for individual or multiple user-input
genes.
Field-specific reporting
Please select the best fit for your research. If you are not sure, read the appropriate sections before making your selection.
Life sciences Behavioural & social sciences Ecological, evolutionary & environmental sciences
For a reference copy of the document with all sections, see nature.com/authors/policies/ReportingSummary-flat.pdf
Life sciences study design
All studies must disclose on these points even when the disclosure is negative.
Sample size No statistical method was used to predetermine sample size. The sample size were chosen according to sample availability and to achieve a
sufficient cell number after sorting for subsequent processing, based on previous experiments within the lab (Zheng et al, Cell, 2017; Guo et
al, Nat Med, 2018). Statistical differences provide the rationale for sufficiency of the sample sizes.
Data exclusions For sequencing data, we excluded low-quality cells according to the criteria we established in our previous single cell studies (Zheng et al, Cell,
2017; Guo et al, Nat Med, 2018), if abnormalities exist in (1) cell library size; (2) the number of expressed genes; (3) the proportion of
mitochondrial gene counts; (4) gene expression value of CD3/CD4/CD8. After these filtering, 10,805 of total 11,138 cells remained. The details
of such cut-off lines could be checked in the section of Methods.
Replication All replications were successful, and the detailed information was provided in corresponding figure legends.
Randomization Not applicable for this study as no treatment strategies are compared.
Blinding Not applicable since there was no specific grouping.
Reporting for specific materials, systems and methods
Materials & experimental systems Methods
n/a Involved in the study n/a Involved in the study
Unique biological materials ChIP-seq
Antibodies Flow cytometry
Eukaryotic cell lines MRI-based neuroimaging
Palaeontology
Animals and other organisms
Human research participants
Antibodies
Antibodies used FACS antibodies
The antibodies used for FACS soring of single T cells were anti-human CD3 (UCHT1, eFluor450, eBioscienc 48-0038-42), anti-
human CD4 (OKT4, FITC, eBioscience, 11-0048-42), anti-human CD8a (OKT8, APC, eBioscience 17-0086-42), anti-human CD25
(BC96, PE, eBioscience 12-0259-42).
The antibodies used for primary human T cell isolation and in vitro activation were anti-human CD3 (UCHT1) and anti-CD28
(CD28.2), anti-human CD4 (OKT4); anti-human CD8 (RPA-T8), anti-human CD45RA (HI100), anti-human CCR7 (G043H7), anti-

## Page 30

3
nature
research
|
reporting
summary
April
2018
human HAVCR2 (F38-2E2), anti-human CD25 (M-A251), anti-human IFN- gamma (B27), anti-human IGFLR1 (905338), mouse
IgG1 and were from Biolegend, BD Biosciences, or R&D Systems.
The antibodies used for in vitro chronic stimulated CD8+ T cells were anti-human CD8 (RPA-T8), anti-human HAVCR2/Tim-3
(F38-2E2), anti-human PD1 (EH12.2H7), anti-human CD39 (eBioA1), anti-LAG3 (305223H), anti-IGFLR1 (905338) and were from
Thermal Fisher Scientific, BD Biosciences, or R&D Systems.
IHC antibodies
The antibodies used for validation of Tc, TH and Treg cells by multi-colour IHC were rabbit anti-human CD3 (SP7, Abcam
ab16669, 1/400), rabbit anti-human CD4 (EPR6855, Abcam ab133616, 1/400), mouse anti-human CD8 (144B, Abcam ab14147,
1/500), mouse anti-human FOXP3 (mAbcam22510, Abcam, ab22510, 1/500).
The antibodies used for validation of ROR gamma+ Treg cells by multi-colour IHC were rabbit anti-human CD3 (SP7, Abcam
ab16669, 1/100), rabbit anti-human ROR gamma (Abcam ab219496, 1/50), and mouse anti-human FOXP3 (mAbcam22510
Abcam ab22510, 1/100).
The antibodies used for validation of proliferative CD8+ Tex cells by multi-colour IHC were rabbit anti-human HAVCR2/TIM-3
(D5D5R, Cell Signaling 45208, 1/100), mouse anti-human PD1 (NAT105, Abcam ab52587, 1/200), mouse anti-human CD8 (144B,
Abcam ab17147, 1/200), and mouse anti-human Ki67 (B126.1, Abcam ab8191, 1/200).
The antibodies used for dMMR detection were mouse anti-human MLH1 (ES05, Leica Biosystems PA0610), mouse anti-human
MSH2 (25D12, Leica Biosystems PA0048), mouse anti-human MSH6 (PU29, Leica Biosystems PA0597) and mouse anti-human
PMS2 (M0R4G, Leica Biosystems).
Validation All the antibodies used in this study were commercial antibodies and were only used for applications, with validation procedures
described on the following sites of the manufacturers:
https://www.thermofisher.com; https://www.bdbiosciences.com; https://www.biolegend.com; https://www.rndsystems.com;
https://www.abcam.com; https://www.leicabiosystems.com; https://www.cellsignal.com.
Human research participants
Policy information about studies involving human research participants
Population characteristics Characteristics of CRC patients which freshly resected tumours, adjacent normal tissues, and peripheral blood were collected:
P0701, female, 68, rectum, adenocarcinoma, Ⅰ, MSS; P0909, male, 45, colon, adenocarcinoma, ⅢB, MSI; P1212, female, 42,
colon, adenocarcinoma, Ⅱ, MSS; P1228, female, 77, colon, adenocarcinoma, Ⅱ, MSS; P0215, male, 75, colon, adenocarcinoma,
IV, MSS; P0411, male, 75, rectum, adenocarcinoma, ⅡB, MSS; P0413, female, 82, colon, adenocarcinoma, ⅢB, MSI; P0825,
female, 83, colon, adenocarcinoma, ⅡB, MSI; P0123, female, 65, colon, adenocarcinoma, ⅢB, MSI; P0309, male, 55, rectum,
adenocarcinoma, ⅢC, MSS.
Characteristics of CRC patients which freshly resected tumours and peripheral blood were collected: P1012, female, 35, colon,
adenocarcinoma, ⅢC, MSS;P1207, female, 66, colon, adenocarcinoma, Ⅱ, MSS.
Recruitment Twelve patients who were pathologically diagnosed with CRC were enrolled in this study. None of them were treated with
chemotherapy or radiation prior to tumour resection. Detailed information can be found in the section of "Human specimens" in
Methods and Supplementary Table 1. There are no biases on the selection of patients.
Flow Cytometry
Plots
Confirm that:
The axis labels state the marker and fluorochrome used (e.g. CD4-FITC).
The axis scales are clearly visible. Include numbers along axes only for bottom left plot of group (a 'group' is an analysis of identical markers).
All plots are contour plots with outliers or pseudocolor plots.
A numerical value for number of cells or percentage (with statistics) is provided.
Methodology
Sample preparation Information provided in Methods section
Instrument BD Aria III and BD LSR-II analyzer
Software FlowJo v10
Cell population abundance The abundance of the relevant cell populations, determined by testing the sorted cells again by FACS, reached >99%.
Gating strategy Information available on Extended Data Fig. 1, Extended Data Fig. 11 and Methods sections.
Tick this box to confirm that a figure exemplifying the gating strategy is provided in the Supplementary Information.