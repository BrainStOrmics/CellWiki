"""Pydantic data models for CellWiki extraction, knowledge base, and wiki pages."""

from enum import Enum
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
