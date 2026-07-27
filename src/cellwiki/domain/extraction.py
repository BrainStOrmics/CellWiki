"""Domain contracts for evidence-grounded scientific extraction."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from cellwiki.domain.contracts import Claim


class MarkerType(str, Enum):
    """Supported protein and transcript marker directions."""

    POSITIVE = "positive"
    NEGATIVE = "negative"
    TRANSCRIPT = "transcript"


class Marker(BaseModel):
    """One gene marker grounded in source evidence."""

    gene_symbol: str
    marker_type: MarkerType
    evidence: str = ""
    strength: str = ""


class FunctionalCharacteristic(BaseModel):
    """One source-grounded function or pathway associated with a cell type."""

    description: str
    pathway: str = ""
    evidence: str = ""


class PaperReference(BaseModel):
    """Minimal source identity carried through extraction and projection."""

    paper_id: str
    title: str
    doi: str = ""
    year: int = 0
    local_path: str = ""


class CellTypeExtract(BaseModel):
    """One candidate cell type extracted from a registered source."""

    name: str
    standard_name: str
    cl_id: str | None = None
    synonyms: list[str] = Field(default_factory=list)
    parent_type: str | None = None
    species: list[str] = Field(default_factory=list)
    tissues: list[str] = Field(default_factory=list)
    diseases: list[str] = Field(default_factory=list)
    markers: list[Marker] = Field(default_factory=list)
    functions: list[FunctionalCharacteristic] = Field(default_factory=list)
    subpopulations: list[str] = Field(default_factory=list)
    description: str = ""
    paper_ref: PaperReference


class ExtractionResult(BaseModel):
    """Grounded extraction candidates and Claims produced from one source."""

    paper: PaperReference
    cell_types: list[CellTypeExtract] = Field(default_factory=list)
    raw_relationships: list[dict] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    source_document: dict = Field(default_factory=dict)

