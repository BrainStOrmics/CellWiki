"""Typed product tasks that bypass natural-language Coordinator routing."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from cellwiki.domain.contracts import ContractModel


class IngestTask(ContractModel):
    kind: Literal["ingest"] = "ingest"
    source_id: str = Field(min_length=1, max_length=256)


class IngestRevisionTask(ContractModel):
    kind: Literal["ingest_revision"] = "ingest_revision"
    change_set_id: str = Field(min_length=1, max_length=256)
    comments: list[str] = Field(min_length=1, max_length=20)
    reviewer: str = Field(default="default-reviewer", min_length=1, max_length=200)


class LintTask(ContractModel):
    kind: Literal["lint"] = "lint"
    action: Literal["inspect", "propose_fix"] = "inspect"
    limit: int = Field(default=5, ge=1, le=20)
    finding_ids: list[str] = Field(default_factory=list, max_length=100)


AgentTask = Annotated[
    IngestTask | IngestRevisionTask | LintTask,
    Field(discriminator="kind"),
]


__all__ = ["AgentTask", "IngestRevisionTask", "IngestTask", "LintTask"]
