"""Deterministic adapters for typed Lint tasks."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cellwiki.domain.tasks import AgentTask, LintTask
from cellwiki.domain.linting import LintInspectionResult
from cellwiki.services.central_writer import CentralWriter
from cellwiki.services.lint_inspection import LintInspection
from cellwiki.services.linting import LintFixService
from cellwiki.services.pipeline import KnowledgePipelineHarness
from cellwiki.services.quality import inspect_projection


@dataclass(frozen=True)
class TypedTaskResult:
    status: str
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    change_set_id: str | None = None


class TypedTaskExecutor:
    """Keep explicit product-task semantics behind one durable runtime seam."""

    def __init__(self, project_root: Path):
        self.project_root = Path(project_root).resolve()
        self.pipeline = KnowledgePipelineHarness(self.project_root)
        self.lint_inspection = LintInspection(self.project_root)
        self.lint = LintFixService(self.project_root)
        self.writer = CentralWriter(self.project_root)

    def execute(self, task: AgentTask, *, run_id: str) -> TypedTaskResult:
        if isinstance(task, LintTask):
            if task.action == "inspect":
                inspection = self.lint_inspection.inspect(task, run_id=run_id)
                return TypedTaskResult(
                    status="succeeded",
                    message=_lint_inspection_message(inspection),
                    data=inspection.model_dump(mode="json"),
                )
            change_set = self.lint.propose(
                task.finding_ids,
                run_id=run_id,
                snapshot_id=task.snapshot_id,
            )
            return self._publish_or_wait(change_set, kind="lint")
        raise TypeError(f"unsupported typed task: {type(task).__name__}")

    def _publish_or_wait(self, change_set, *, kind: str) -> TypedTaskResult:
        decision = self.pipeline.approval_for(
            change_set.change_set_id,
            reviewer="default-reviewer",
        )
        payload = {
            "kind": kind,
            "change_set_id": change_set.change_set_id,
            "operation_count": len(change_set.operations),
            "evidence_count": len(change_set.evidence),
            "risk": change_set.risk.value,
            "approval_policy": self.pipeline.approval_policy_status(),
        }
        if not decision.approved:
            return TypedTaskResult(
                status="waiting_approval",
                message="ChangeSet is ready for human approval.",
                data=payload,
                change_set_id=change_set.change_set_id,
            )
        commit = self.writer.commit(change_set.change_set_id, approval=None)
        quality = inspect_projection(self.project_root)
        payload["commit_id"] = commit.commit_id
        payload["quality"] = {
            key: quality.get(key)
            for key in (
                "status",
                "page_count",
                "issue_count",
                "error_count",
                "warning_count",
            )
        }
        return TypedTaskResult(
            status="succeeded",
            message="Typed task completed and the ChangeSet was published.",
            data=payload,
            change_set_id=change_set.change_set_id,
        )

    def publish_existing(self, change_set_id: str) -> TypedTaskResult:
        """Publish the ChangeSet already prepared by a waiting typed task."""

        change_set = self.writer.repository.get(change_set_id)
        commit = self.writer.commit(change_set_id, approval=None)
        quality = inspect_projection(self.project_root)
        return TypedTaskResult(
            status="succeeded",
            message="Typed task approval was applied and published.",
            data={
                "change_set_id": change_set.change_set_id,
                "operation_count": len(change_set.operations),
                "evidence_count": len(change_set.evidence),
                "commit_id": commit.commit_id,
                "quality": {
                    key: quality.get(key)
                    for key in (
                        "status",
                        "page_count",
                        "issue_count",
                        "error_count",
                        "warning_count",
                    )
                },
            },
            change_set_id=change_set_id,
        )


def _lint_inspection_message(inspection: LintInspectionResult) -> str:
    """Render the bounded result, never the complete audit artifact, for chat."""

    summary = inspection.summary
    lines = [
        "Local knowledge Lint completed.",
        "",
        (
            f"- Scope: {inspection.scope.get('kind', 'project')}"
            f" · pages: {summary.get('page_count', 0)}"
            f" · issues: {summary.get('scoped_issue_count', 0)}"
            f" · errors: {summary.get('error_count', 0)}"
            f" · warnings: {summary.get('warning_count', 0)}"
        ),
        f"- Snapshot: `{inspection.snapshot_id}`",
    ]
    if inspection.findings:
        lines.extend(["", "Findings:"])
        for finding in inspection.findings:
            lines.append(
                f"- `{finding.finding_id}` [{finding.severity.value}] "
                f"{finding.target_id}: {finding.message}"
            )
    else:
        lines.extend(["", "No findings matched this scope."])
    if inspection.next_cursor:
        lines.extend(["", f"More findings are available after `{inspection.next_cursor}`."])
    return "\n".join(lines)


__all__ = ["TypedTaskExecutor", "TypedTaskResult"]
