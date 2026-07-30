"""Typed product tasks that bypass natural-language Coordinator routing."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from cellwiki.domain.contracts import ContractModel


class IngestTask(ContractModel):
    kind: Literal["ingest"] = "ingest"
    source_id: str = Field(min_length=1, max_length=256)


class IngestRevisionTask(ContractModel):
    kind: Literal["ingest_revision"] = "ingest_revision"
    change_set_id: str = Field(min_length=1, max_length=256)
    comments: list[str] = Field(min_length=1, max_length=20)
    reviewer: str = Field(default="default-reviewer", min_length=1, max_length=200)


class ProjectLintScope(ContractModel):
    kind: Literal["project"] = "project"


class PageLintScope(ContractModel):
    kind: Literal["page"] = "page"
    page_id: str = Field(min_length=1, max_length=256)


LintScope = Annotated[
    ProjectLintScope | PageLintScope,
    Field(discriminator="kind"),
]


class LintTask(ContractModel):
    kind: Literal["lint"] = "lint"
    action: Literal["inspect", "propose_fix"] = "inspect"
    scope: LintScope = Field(default_factory=ProjectLintScope)
    limit: int = Field(default=5, ge=1, le=20)
    cursor: str | None = Field(default=None, max_length=256)
    snapshot_id: str | None = Field(default=None, max_length=256)
    finding_ids: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_action_inputs(self) -> "LintTask":
        if self.action == "propose_fix":
            if not self.snapshot_id:
                raise ValueError("propose_fix requires snapshot_id")
            if not self.finding_ids:
                raise ValueError("propose_fix requires at least one finding_id")
        return self


AgentTask = Annotated[
    IngestTask | IngestRevisionTask | LintTask,
    Field(discriminator="kind"),
]


class TaskProposal(ContractModel):
    """A mutating typed task extracted from chat but not yet authorized to run."""

    task: AgentTask
    reason: str = Field(min_length=1, max_length=500)
    requires_confirmation: Literal[True] = True


__all__ = [
    "AgentTask",
    "IngestRevisionTask",
    "IngestTask",
    "LintScope",
    "LintTask",
    "PageLintScope",
    "ProjectLintScope",
    "TaskProposal",
]
