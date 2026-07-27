"""Contracts for review-driven ingest revisions."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum

from pydantic import Field

from cellwiki.domain.contracts import ContractModel


class RevisionStatus(str, Enum):
    """Lifecycle of a reviewer-requested re-ingest."""

    REQUESTED = "requested"
    RUNNING = "running"
    READY = "ready"
    FAILED = "failed"


class ReviewComment(ContractModel):
    """One durable reviewer instruction attached to a revision."""

    comment_id: str
    author: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=4000)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class IngestRevision(ContractModel):
    """A same-source review request that produces a new immutable ChangeSet."""

    revision_id: str
    project_id: str = "cellwiki"
    source_id: str
    parent_change_set_id: str
    parent_revision_id: str | None = None
    comments: list[ReviewComment] = Field(min_length=1)
    status: RevisionStatus = RevisionStatus.REQUESTED
    run_id: str | None = None
    change_set_id: str | None = None
    snapshot_id: str | None = None
    error_message: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


__all__ = ["IngestRevision", "ReviewComment", "RevisionStatus"]
