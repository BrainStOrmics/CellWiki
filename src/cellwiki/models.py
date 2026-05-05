"""Pydantic data models for CellWiki extraction, knowledge base, and wiki pages."""

from enum import Enum, IntEnum
from typing import Optional

from pydantic import BaseModel, Field


class MarkerType(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    TRANSCRIPT = "transcript"


class Marker(BaseModel):
    gene_symbol: str
    marker_type: MarkerType
    evidence: str = ""
    strength: str = ""


class FunctionalCharacteristic(BaseModel):
    description: str
    pathway: str = ""
    evidence: str = ""


class PaperReference(BaseModel):
    paper_id: str
    title: str
    doi: str = ""
    year: int = 0
    local_path: str = ""


class CellTypeExtract(BaseModel):
    """One cell type extracted from a single paper."""

    name: str
    standard_name: str
    cl_id: Optional[str] = None
    synonyms: list[str] = Field(default_factory=list)
    parent_type: Optional[str] = None
    species: list[str] = Field(default_factory=list)
    tissues: list[str] = Field(default_factory=list)
    diseases: list[str] = Field(default_factory=list)
    markers: list[Marker] = Field(default_factory=list)
    functions: list[FunctionalCharacteristic] = Field(default_factory=list)
    subpopulations: list[str] = Field(default_factory=list)
    description: str = ""
    paper_ref: PaperReference


class ExtractionResult(BaseModel):
    """All cell types extracted from a single paper."""

    paper: PaperReference
    cell_types: list[CellTypeExtract] = Field(default_factory=list)
    raw_relationships: list[dict] = Field(default_factory=list)


class EvidenceTier(IntEnum):
    """Evidence tier for claims and annotations."""
    TIER_1 = 1  # Direct experimental validation (KO, functional assay, spatial colocalization)
    TIER_2 = 2  # Multi-omics concordance (RNA + protein + epigenetics agree)
    TIER_3 = 3  # Single-omics + multiple independent papers (>=3)
    TIER_4 = 4  # Single paper report
    TIER_5 = 5  # LLM inference / hypothesis / unvalidated


class MarkerGene(BaseModel):
    """A marker gene page in the wiki."""

    gene_symbol: str
    gene_name: str = ""
    gene_id_ensembl: str = ""
    gene_id_ncbi: str = ""
    chromosome: str = ""
    protein_name: str = ""
    cell_types_expressed: list[str] = Field(default_factory=list)
    specificity: str = ""  # e.g., "T cell lineage"
    evidence_tier: EvidenceTier = EvidenceTier.TIER_5
    source_count: int = 0
    last_updated: str = ""
    # Assessment scores
    specificity_score: str = ""
    sensitivity_score: str = ""
    stability_score: str = ""
    detectability_score: str = ""
    # Negative evidence
    negative_evidence: list[dict] = Field(default_factory=list)
    # [{"cell_type": "B cell", "evidence": "Not detected", "sources": ["paper1"]}]
    # Co-expression
    co_expression: list[dict] = Field(default_factory=list)
    # [{"gene": "CD25", "cell_type": "Treg", "correlation": 0.85}]
    # Multi-omics
    epigenetic_features: str = ""
    protein_data: str = ""
    # References
    references: list[dict] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)


class Tissue(BaseModel):
    """A tissue/organ page in the wiki."""

    name: str
    display_name: str = ""
    uberon_id: str = ""  # UBERON ontology ID
    description: str = ""
    cell_types_found: dict[str, str] = Field(default_factory=dict)
    # key: cell_type_id, value: abundance ("high"/"moderate"/"low"/"rare")
    source_count: int = 0
    last_updated: str = ""
    references: list[dict] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)


class Disease(BaseModel):
    """A disease association page in the wiki."""

    name: str
    display_name: str = ""
    category: str = ""  # e.g., "cancer", "autoimmune", "infectious"
    mondo_id: str = ""  # MONDO ontology ID
    description: str = ""
    associated_cell_types: dict[str, str] = Field(default_factory=dict)
    # key: cell_type_id, value: role ("increased", "decreased", "altered")
    associated_genes: list[str] = Field(default_factory=list)
    source_count: int = 0
    last_updated: str = ""
    references: list[dict] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)


class Method(BaseModel):
    """An experimental method page in the wiki."""

    name: str
    display_name: str = ""
    description: str = ""
    category: str = ""  # e.g., "transcriptomics", "proteomics", "epigenomics"
    applicable_scenarios: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    source_count: int = 0
    last_updated: str = ""
    references: list[dict] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)


class TrajectoryState(BaseModel):
    """A single state within a trajectory."""

    name: str
    cell_type_id: str = ""
    key_markers: list[str] = Field(default_factory=list)
    function: str = ""
    proliferation: str = ""  # "high"/"moderate"/"low"/"none"
    icb_responsive: str = ""  # "yes"/"partial"/"limited"/"no"
    key_regulators: list[dict] = Field(default_factory=list)
    # [{"tf": "TCF7", "role": "stemness maintenance"}]


class Trajectory(BaseModel):
    """A differentiation/state transition trajectory page."""

    name: str
    display_name: str = ""
    description: str = ""
    start_state: str = ""  # cell_type_id
    end_state: str = ""  # cell_type_id
    intermediate_states: list[str] = Field(default_factory=list)  # cell_type_ids
    states: list[TrajectoryState] = Field(default_factory=list)
    key_regulators: list[dict] = Field(default_factory=list)
    therapeutic_interventions: list[str] = Field(default_factory=list)
    context: list[str] = Field(default_factory=list)  # e.g., ["chronic_infection", "cancer"]
    species: list[str] = Field(default_factory=list)
    evidence_tier: EvidenceTier = EvidenceTier.TIER_5
    source_count: int = 0
    last_updated: str = ""
    references: list[dict] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)


class IngestAnalysis(BaseModel):
    """Structured analysis output from Step 1 of the ingest chain."""

    entities: list[dict] = Field(default_factory=list)
    # [{"type": "cell_type", "name": "...", "standard_name": "...", "markers": [...]}]
    relationships: list[dict] = Field(default_factory=list)
    # [{"source": "...", "relation": "...", "target": "..."}]
    contradictions: list[dict] = Field(default_factory=list)
    # [{"entity": "...", "description": "..."}]
    existing_pages_touched: list[str] = Field(default_factory=list)
    new_pages_needed: list[str] = Field(default_factory=list)
    confidence: str = "medium"  # "high"/"medium"/"low"
    uncertainties: list[str] = Field(default_factory=list)


class WikiCellType(BaseModel):
    """Merged, canonical representation of one cell type in the wiki."""

    standard_name: str
    display_name: str = ""
    cl_id: Optional[str] = None
    aliases: set[str] = Field(default_factory=set)
    parent_type: Optional[str] = None
    description: str = ""
    markers: dict[str, list[dict]] = Field(default_factory=dict)
    functions: dict[str, list[dict]] = Field(default_factory=dict)
    contexts: dict[str, dict] = Field(default_factory=dict)
    subpopulations: set[str] = Field(default_factory=set)
    references: list[dict] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)  # e.g., "CD44: positive vs negative"

    # === CellWiki v2.0 extended fields ===
    identity: str = ""  # Lineage identity (e.g., "T_cell")
    state: str = ""  # Current state (e.g., "exhausted", "naive")
    context: dict = Field(default_factory=dict)
    # {tissue, disease, species, spatial_zone, timepoint}
    temporal_stability: str = ""  # "stable"/"transient"/"oscillating"
    evidence_tier: EvidenceTier = EvidenceTier.TIER_5
    negative_markers: list[dict] = Field(default_factory=list)
    multi_omics_features: dict = Field(default_factory=dict)
    # {epigenetic: "...", proteomic: "...", spatial: "..."}
    open_questions: list[str] = Field(default_factory=list)


# ============================================================
# CellWiki v2.0 — Extended Entity Models
# ============================================================


class IngestResult(BaseModel):
    """Output from Step 2 of the ingest chain."""

    updated_pages: list[str] = Field(default_factory=list)
    new_pages: list[str] = Field(default_factory=list)
    review_items: list[dict] = Field(default_factory=list)
    log_entry: dict = Field(default_factory=dict)

