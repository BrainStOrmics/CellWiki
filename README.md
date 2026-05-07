# CellWiki

A self-maintaining single-cell multi-omics knowledge base built using the LLM Wiki pattern.

Instead of retrieving from raw documents at query time like traditional RAG, CellWiki uses an LLM to incrementally build and maintain a persistent wiki — a structured, interlinked collection of Markdown pages that sits between curated scientific papers and the user. Knowledge is compiled once and kept current, not re-derived on every query.

## Overview

CellWiki automates the lifecycle of single-cell biology knowledge:

1. **Extract** — Automatically extract cell types, marker genes, tissues, diseases, methods, and trajectories from single-cell biology papers (PDFs)
2. **Integrate** — Merge information across papers, detecting contradictions and building consensus
3. **Reason** — Infer relationships (cell type ↔ gene ↔ tissue ↔ disease ↔ trajectory) across modalities
4. **Query** — Answer structured questions with citations back to sources
5. **Self-maintain** — Automatically detect knowledge gaps, broken links, and stale claims; propose updates

The project currently focuses on **tumor immunology** (T cell exhaustion, tumor microenvironment), with 96 cell type wiki pages already generated from example papers.

## Architecture

```
Raw Sources (PDFs) ──► LLM Extraction ──► Wiki Pages (Markdown)
                           │                      │
                     Contradiction           Schema Rules
                     Detection               (schema.md)
                           │                      │
                     Knowledge Graph ◄─────── Multi-Omics Merger
```

### LangGraph Subgraphs

CellWiki v2.0 uses LangGraph state machines for four composable workflows:

| Subgraph | Description |
|----------|-------------|
| **Ingest** | Two-step pipeline: LLM analysis → human review interrupt → wiki generation |
| **Query** | Entity match → graph expansion → budget-aware context assembly → LLM synthesis |
| **Lint** | Self-healing loop: scan → classify → auto-fix → recheck |
| **Research** | Gap-driven: generate queries → web search → synthesize → propose updates |

All subgraphs persist state to SQLite, enabling cross-session recovery and state history inspection.

## Entity Model

Six entity types with defined schemas and relationships:

| Entity | Description | Pages |
|--------|-------------|-------|
| `cell_type` | Identity/state/context triplet model | 96 |
| `marker_gene` | Specificity/sensitivity/stability/detectability scoring | Planned |
| `tissue` | Cell type abundance mapping | Planned |
| `disease` | Cell type/gene associations | Planned |
| `method` | Experimental technique descriptions | Planned |
| `trajectory` | State transition paths | Planned |

Each page includes YAML frontmatter with structured metadata, evidence tier classification (Tier 1–5), and source citations.

## Installation

```bash
git clone https://github.com/BrainStOrmics/CellWiki.git
cd CellWiki
pip install -e .              # Core installation
pip install -e ".[dev]"       # Include testing dependencies
pip install -e ".[analysis]"  # Include graph analysis (NetworkX, Louvain)
```

### Requirements

- Python >= 3.10
- OpenAI-compatible API key (configured for qwen3.6-plus by default)

### Configuration

Set environment variables or create a `.env` file:

```env
OPENAI_API_KEY=your_api_key
OPENAI_BASE_URL=your_api_base_url   # Optional, for non-OpenAI providers
OPENAI_MODEL=qwen3.6-plus           # Default model
```

## Usage

### Initialize Workspace

```bash
cellwiki init
```

Downloads the Cell Ontology, initializes workspace directories, and generates the index.

### Ingest Papers

```bash
# Interactive mode with human review
cellwiki ingest paper.pdf

# Batch mode (skip review)
cellwiki ingest --no-review paper.pdf
```

### Query the Wiki

```bash
# v1: Simple lookup
cellwiki query "CD8+ T cell"

# v2: LangGraph-powered query with graph expansion
cellwiki query-v2 "What markers distinguish exhausted CD8+ T cells in the tumor microenvironment?"
```

### Knowledge Graph

```bash
cellwiki graph    # Generate JSON, DOT, Mermaid, and SVG visualizations
```

### Audit & Review

```bash
cellwiki audit    # Run audit checks (missing CL IDs, marker conflicts, orphan pages)
cellwiki review   # Interactive review of audit issues
```

### Maintenance

```bash
cellwiki lint-v2          # Run self-healing lint with auto-fix
cellwiki lint-v2 --no-fix # Report only, no fixes
cellwiki list             # List all cell types
cellwiki status           # Show wiki status panel
cellwiki diff             # Show what the last paper changed
```

### Checkpoint Management

```bash
cellwiki memory list      # List all checkpoints
cellwiki memory history   # Show checkpoint history
cellwiki memory stats     # Show checkpoint database stats
cellwiki memory cleanup   # Clean old checkpoints
```

### Debug

```bash
cellwiki debug graph      # Visualize LangGraph structure
cellwiki debug trace      # Trace execution flow
cellwiki debug history    # Show state history
```

## Wiki Structure

```
wiki/
├── index.md              # Global index of all pages
├── overview.md           # Knowledge base overview
├── log.md                # Append-only operation log
├── contradictions.md     # Contradiction tracking
├── statistics.md         # Quality metrics
├── cell_types/           # Cell type pages (96 generated)
├── marker_genes/         # Marker gene pages
├── tissues/              # Tissue pages
├── diseases/             # Disease pages
├── methods/              # Method pages
├── trajectories/         # Trajectory pages
└── state_spaces/         # State space definitions
```

## Tech Stack

| Package | Purpose |
|---------|---------|
| `openai` | LLM API calls |
| `pdfplumber` | PDF text extraction |
| `pydantic` | Data model validation |
| `langgraph` | State machine orchestration |
| `langchain-core` | LangGraph foundation |
| `networkx` | Knowledge graph analysis |
| `graphviz` | Graph visualization |
| `rich` | Terminal formatting |

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
