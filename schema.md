# CellWiki Schema v2.0

> This document defines the structure, conventions, and workflows for CellWiki.
> It is read by the LLM during every ingest, query, and lint operation.

## Purpose

CellWiki is a self-maintaining single-cell multi-omics knowledge base. It extracts, integrates, and reasons about cell biology knowledge from curated papers, forming a queryable, traceable state-space图谱.

## Entity Types

| Type | Path | Naming | Example |
|------|------|--------|---------|
| cell_type | wiki/cell_types/{lineage}/{name}.md | snake_case | regulatory_t_cell |
| marker_gene | wiki/marker_genes/{symbol}.md | Standard gene symbol (UPPERCASE) | FOXP3, CD3D |
| tissue | wiki/tissues/{name}.md | snake_case | lymph_node |
| disease | wiki/diseases/{category}/{name}.md | snake_case | NSCLC |
| method | wiki/methods/{name}.md | snake_case | scRNA-seq_10x |
| trajectory | wiki/trajectories/{name}.md | snake_case | T_naive_to_exhausted |

## Naming Conventions

- **cell_type**: snake_case, no spaces (e.g., `regulatory_t_cell`, not `Regulatory T Cell`)
- **marker_gene**: Standard gene symbol, UPPERCASE for human (e.g., `CD3D`, `FOXP3`)
- **tissue/disease/method/trajectory**: snake_case
- **All page filenames**: No spaces, use underscores
- **Display names**: Use proper biological nomenclature (e.g., "CD8+ T cell", "Treg")

## Page Structure

Every wiki page MUST have YAML frontmatter with entity-type-specific required fields.

### Cell Type frontmatter
```yaml
entity_type: "cell_type"
identity: "T_cell"
state: "regulatory"
display_name: "Regulatory T Cell (Treg)"
cl_id: "CL:0000815"
lineage: "T_cells"
species: ["homo_sapiens"]
tissues: ["blood", "lymph_node"]
evidence_tier: 2
source_count: 15
last_updated: "2026-05-04"
```

### Marker Gene frontmatter
```yaml
entity_type: "marker_gene"
gene_symbol: "FOXP3"
gene_name: "Forkhead box P3"
gene_id_ensembl: "ENSG00000048998"
specificity: "Treg (canonical)"
evidence_tier: 1
source_count: 20
last_updated: "2026-05-04"
```

### Trajectory frontmatter
```yaml
entity_type: "trajectory"
display_name: "T Cell Exhaustion Trajectory"
start_state: "naive_cd8_t_cell"
end_state: "terminally_exhausted_cd8_t_cell"
intermediate_states: ["stem_like_exhausted", "progenitor_exhausted"]
evidence_tier: 2
source_count: 8
last_updated: "2026-05-04"
```

## Ingest Workflow (Two-Step Chain)

### Step 1: Analysis
1. Read the source paper (PDF/Markdown text)
2. Extract all entities: cell types, marker genes, tissues, diseases, methods
3. Identify relationships between entities
4. Compare with existing wiki pages — which need updating? which are new?
5. Detect contradictions with existing knowledge
6. Mark uncertainties that need human review
7. Output: Structured IngestAnalysis (NOT wiki pages yet)

### Step 2: Generation
1. Take the IngestAnalysis as input
2. For each entity:
   - New entity → Create page with template
   - Existing entity → Merge new information (union, never overwrite)
3. Update index.md with new/updated entries
4. Append to log.md with parseable format
5. Update statistics.md
6. If contradictions detected → update contradictions.md
7. Generate review items for human judgment

**Key principle**: A single source may touch 10-15 wiki pages. Knowledge compounds.

## Lint Workflow

Periodically run health checks on the wiki:

1. **Index consistency**: Does index.md match actual wiki/ directory contents?
2. **Link validity**: Do all [[wikilinks]] point to existing pages?
3. **Frontmatter completeness**: Does every page have required YAML fields?
4. **Stale pages**: Flag pages not updated in >30 days
5. **Contradiction review**: Check if new literature has resolved existing contradictions
6. **Orphan detection**: Find pages with no inbound links
7. **Missing entities**: Find entity names mentioned in pages but lacking their own page

Auto-fixable issues (index, broken links, frontmatter) are repaired automatically.
Non-fixable issues (contradictions, missing knowledge) go to review queue.

## Query Workflow

1. **Entity Match**: Parse query, identify entity types (gene? cell type? tissue?), exact + fuzzy match
2. **Graph Expansion**: From matched pages, follow relationships (cell_type → markers → related cell_types)
3. **Context Assembly**: Select pages within token budget, prioritized by relevance
4. **Synthesis**: LLM generates answer with citations [1], [2], etc.
5. **File back**: Good answers saved to wiki/queries/ as new pages (explorations compound)

## Evidence Tiers

Every claim MUST be tagged with an evidence tier:

| Tier | Definition | Example |
|------|-----------|---------|
| 1 | Direct experimental validation (KO, functional assay, spatial colocalization) | FOXP3 KO abolishes Treg function |
| 2 | Multi-omics concordance (RNA + protein + epigenetics agree) | scRNA-seq + CITE-seq + ATAC-seq consistent |
| 3 | Single-omics + multiple independent papers (>=3) | 3+ papers report same marker |
| 4 | Single paper report | First observation |
| 5 | LLM inference / hypothesis / unvalidated | Inferred from co-expression |

## Contradiction Handling

When the same entity has conflicting information across sources:

1. **Detect**: During ingest, compare new extraction with existing wiki data
2. **Classify**: Is it a technical artifact (different platform/batch) or biological difference (different tissue/disease)?
3. **Record**: Log to contradictions.md with sources, status, and involved pages
4. **Resolve**:
   - Technical → Annotate as platform-specific difference
   - Biological → Refine entity definition (split into subtypes if needed)
   - Unknown → Mark as unresolved; trigger Deep Research if needed
5. **Track**: Each contradiction has a lifecycle: detected → classified → resolving → resolved/unresolved

## Raw Sources

- Stored in `raw/sources/` (papers), `raw/datasets/` (metadata), `raw/ontologies/` (CL, GO)
- **Immutable**: The LLM reads from sources but NEVER modifies them
- Each source has a unique ID (DOI, PMID, GEO accession)

## Wiki Pages

- Stored in `wiki/{entity_type}/`
- **LLM-owned**: The LLM creates, updates, and maintains all wiki pages
- Human reads, reviews, and guides — does NOT write pages directly

## Cross-References

- Use `[[wikilink]]` syntax: `[[regulatory_t_cell]]`, `[[FOXP3]]`
- Every related entity should be wikilinked
- Lint checks for broken wikilinks periodically
