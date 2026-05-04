# CellWiki — Purpose

## What is this?

CellWiki is a **self-maintaining single-cell multi-omics knowledge base** built using the LLM Wiki pattern (Karpathy, 2024). Instead of retrieving from raw documents at query time (RAG), the LLM **incrementally builds and maintains a persistent wiki** — a structured, interlinked collection of markdown pages that sits between curated sources and the user.

The knowledge is compiled once and then *kept current*, not re-derived on every query.

## Goals

1. **Extract** — Automatically extract cell types, marker genes, tissues, diseases, methods, and trajectories from single-cell papers
2. **Integrate** — Merge information across papers, detecting contradictions and building consensus
3. **Reason** — Infer relationships (cell type ↔ gene ↔ tissue ↔ disease ↔ trajectory) across modalities
4. **Query** — Answer structured questions with citations back to sources
5. **Self-maintain** — Automatically detect knowledge gaps, broken links, and stale claims; propose updates

## Key Research Questions

### Cell Type Definition
- What defines a cell type? Lineage identity, functional state, spatial context, or all three?
- How do we handle cells that exist on a continuum (e.g., exhaustion trajectory)?
- When does a subpopulation become a distinct type vs. a transient state?

### Marker Specificity
- What makes a gene a good cell type marker? Specificity, sensitivity, stability, detectability?
- How do we evaluate markers across platforms (scRNA-seq vs. CITE-seq vs. spatial)?
- What is the negative evidence — where is a marker NOT expressed?

### Trajectory & Dynamics
- How do cells transition between states (differentiation, activation, exhaustion)?
- What are the key transcription factors driving state transitions?
- Which transitions are reversible? Which are locked by epigenetic memory?

### Multi-omics Concordance
- Does transcriptomic identity match proteomic identity? When do they diverge?
- How does spatial context change functional interpretation of a cell type?
- Can we predict protein abundance from RNA? Metabolic state from transcriptome?

### Knowledge Quality
- How do we grade evidence? (Tier 1: experimental validation → Tier 5: LLM inference)
- How do we handle contradictions between papers?
- What knowledge gaps should trigger new research?

## Evolving Thesis

As CellWiki grows, these are the hypotheses we are building evidence for:

1. **Cell types are state-context functions**, not discrete categories. A cell's identity = (lineage identity × current state × spatial/disease context × time).

2. **Multi-omics agreement is the gold standard** for cell type definition. Single-modality claims are hypotheses; multi-modality concordance is evidence.

3. **Contradictions are data, not noise.** When two papers disagree on a cell type's markers, the difference often reveals a biological sub-structure (e.g., tissue-specific subtypes) that was previously invisible.

4. **The knowledge graph reveals what papers don't.** Bridge nodes (genes connecting multiple cell type communities) are likely master regulators. Isolated pages signal knowledge gaps worth investigating.

5. **Negative knowledge is as important as positive.** Knowing where a marker is NOT expressed is critical for panel design and gating strategies.

## Role Division

- **Human**: Curates sources, guides analysis, asks questions, makes judgment calls on contradictions
- **LLM**: Reads papers, extracts entities, maintains the wiki, detects gaps, proposes updates, answers queries

## Sources

Raw sources are stored in `raw/sources/` and are immutable. The LLM reads from them but never modifies them.
