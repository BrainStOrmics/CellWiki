"""Strict annotation evidence contracts, independent of model providers."""

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class AnnotationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)


class AnnotationCluster(AnnotationModel):
    id: str = Field(min_length=1, max_length=128)
    n_cells: int | None = Field(default=None, gt=0)
    fraction_in_dataset: float | None = Field(default=None, ge=0, le=1)
    parent_cell_type: str | None = Field(default=None, max_length=300)
    current_cell_type: str | None = Field(default=None, max_length=300)
    current_confidence: float | None = Field(default=None, ge=0, le=1)


class AnnotationRequest(AnnotationModel):
    request_id: str = Field(min_length=1, max_length=128)
    species: str = Field(min_length=1, max_length=300)
    tissue: str = Field(min_length=1, max_length=300)
    disease: str | None = Field(default=None, max_length=300)
    cluster: AnnotationCluster
    top_markers: list[str] = Field(min_length=1, max_length=50)
    low_or_absent_markers: list[str] = Field(default_factory=list, max_length=30)
    max_candidates: int = Field(default=3, ge=1, le=5)

    @field_validator("top_markers", "low_or_absent_markers")
    @classmethod
    def normalize_markers(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        if any(not value or len(value) > 128 for value in normalized):
            raise ValueError("marker symbols must contain 1-128 characters")
        return list({value.casefold(): value for value in normalized}.values())

    @model_validator(mode="after")
    def disjoint_markers(self) -> "AnnotationRequest":
        if {value.casefold() for value in self.top_markers}.intersection(
            value.casefold() for value in self.low_or_absent_markers
        ):
            raise ValueError("positive and low/absent marker lists must not overlap")
        return self


class AnnotationContext(AnnotationModel):
    species: Literal["matched", "mismatched", "unknown"]
    tissue: Literal["matched", "cross_context", "mismatched", "unknown"]
    disease: Literal["matched", "cross_context", "mismatched", "unknown"]


class AnnotationEvidence(AnnotationModel):
    evidence_id: str
    evidence_tier: int | None = Field(ge=1, le=5)
    claim: str
    paper_id: str
    title: str | None
    doi: str | None
    url: str | None
    page_path: str
    locator: str


class AnnotationCandidate(AnnotationModel):
    candidate_id: str
    standard_name: str
    display_name: str
    aliases: list[str]
    parent_type: str | None
    ontology_id: str | None
    support_score: None = None
    support_level: Literal["strong", "moderate", "weak"]
    supporting_markers: list[str]
    expected_absent_markers: list[str]
    contradictory_markers: list[str]
    context_match: AnnotationContext
    rationale: str
    evidence_ids: list[str]


class AnnotationResponse(AnnotationModel):
    request_id: str
    status: Literal["matched", "ambiguous", "no_match"]
    recommendation: AnnotationCandidate | None
    alternative_candidates: list[AnnotationCandidate]
    evidence: list[AnnotationEvidence]
    warnings: list[str]
    knowledge_version: str
    algorithm_version: str = "annotation-v1"
