"""Deterministic adapters for typed Ingest, Revision, and Lint tasks."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cellwiki.domain.contracts import PipelineTaskType
from cellwiki.domain.tasks import AgentTask, IngestRevisionTask, IngestTask, LintTask
from cellwiki.services.central_writer import CentralWriter
from cellwiki.services.ingest import IngestService
from cellwiki.services.linting import LintFixService
from cellwiki.services.pipeline import KnowledgePipelineHarness
from cellwiki.services.revisions import IngestRevisionService
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
        self.ingest = IngestService(self.project_root)
        self.revisions = IngestRevisionService(self.project_root, ingest=self.ingest)
        self.lint = LintFixService(self.project_root)
        self.writer = CentralWriter(self.project_root)

    def execute(self, task: AgentTask, *, run_id: str) -> TypedTaskResult:
        if isinstance(task, IngestTask):
            change_set = self.ingest.prepare_change_set(
                task.source_id,
                run_id,
                cancellation_id=run_id,
            )
            return self._publish_or_wait(change_set, kind="ingest")
        if isinstance(task, IngestRevisionTask):
            revision = self.revisions.request_revision(
                task.change_set_id,
                reviewer=task.reviewer,
                comments=task.comments,
            )
            change_set = self.revisions.prepare_revision(
                revision.revision_id,
                run_id=run_id,
                cancellation_id=run_id,
            )
            return self._publish_or_wait(change_set, kind="ingest_revision")
        if isinstance(task, LintTask):
            if task.action == "inspect":
                with self.pipeline.acquire(task_type=PipelineTaskType.LINT, run_id=run_id) as lease:
                    return TypedTaskResult(
                        status="succeeded",
                        message="Lint inspection completed.",
                        data={
                            "snapshot": lease.snapshot.model_dump(mode="json"),
                            "report": self.lint.inspect(),
                        },
                    )
            change_set = self.lint.propose(task.finding_ids, run_id=run_id)
            return self._publish_or_wait(change_set, kind="lint")
        raise TypeError(f"unsupported typed task: {type(task).__name__}")

    def _publish_or_wait(self, change_set, *, kind: str) -> TypedTaskResult:
        decision = self.pipeline.approval_for(
            change_set.change_set_id,
            reviewer="default-reviewer",
        )
        payload = {
            "kind": kind,
            "change_set": change_set.model_dump(mode="json"),
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
        payload["commit"] = commit.model_dump(mode="json")
        payload["quality"] = inspect_projection(self.project_root)
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
        return TypedTaskResult(
            status="succeeded",
            message="Typed task approval was applied and published.",
            data={
                "change_set": change_set.model_dump(mode="json"),
                "commit": commit.model_dump(mode="json"),
                "quality": inspect_projection(self.project_root),
            },
            change_set_id=change_set_id,
        )


__all__ = ["TypedTaskExecutor", "TypedTaskResult"]
