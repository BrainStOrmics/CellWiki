"""Structured contracts for formal CellWiki queries."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import Field

from cellwiki.domain.contracts import ContractModel


class QueryScope(str, Enum):
    """Knowledge state visible to the default Query path."""

    FORMAL = "formal"


class QueryHit(ContractModel):
    page_id: str
    title: str
    snippet: str
    score: int
    state: QueryScope = QueryScope.FORMAL
    source_ids: list[str] = Field(default_factory=list)


class QueryResponse(ContractModel):
    query: str
    scope: QueryScope = QueryScope.FORMAL
    knowledge_version: str
    results: list[QueryHit] = Field(default_factory=list)
    pending_change_set_count: int = Field(default=0, ge=0)
    missing_evidence: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class QueryPage(ContractModel):
    page_id: str
    path: str
    frontmatter: dict[str, Any] = Field(default_factory=dict)
    markdown: str
    scope: QueryScope = QueryScope.FORMAL
    knowledge_version: str
    source_ids: list[str] = Field(default_factory=list)


__all__ = ["QueryHit", "QueryPage", "QueryResponse", "QueryScope"]
