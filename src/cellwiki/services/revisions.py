"""Persistence and orchestration for review-driven ingest revisions."""

from __future__ import annotations

from datetime import UTC, datetime
import uuid
from pathlib import Path

from cellwiki.domain.contracts import ChangeOperationType, ChangeSet
from cellwiki.domain.revisions import IngestRevision, ReviewComment, RevisionStatus
from cellwiki.services.changesets import ChangeSetRepository
from cellwiki.services.ingest import IngestService


class IngestRevisionNotFoundError(KeyError):
    """Raised when a requested ingest revision does not exist."""


class IngestRevisionConflictError(ValueError):
    """Raised when a revision identity would overwrite a different record."""


class IngestRevisionRepository:
    """Store revision lifecycle records separately from immutable ChangeSets."""

    def __init__(self, project_root: Path):
        self.directory = Path(project_root).resolve() / "data" / "runtime" / "revisions"

    def create(self, revision: IngestRevision) -> IngestRevision:
        path = self._path(revision.revision_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            existing = self.get(revision.revision_id)
            if existing != revision:
                raise IngestRevisionConflictError(
                    f"revision {revision.revision_id!r} already exists with different content"
                )
            return existing
        self._atomic_write(path, revision.model_dump_json(indent=2))
        return revision

    def update(self, revision: IngestRevision) -> IngestRevision:
        path = self._path(revision.revision_id)
        if not path.exists():
            raise IngestRevisionNotFoundError(revision.revision_id)
        self._atomic_write(path, revision.model_dump_json(indent=2))
        return revision

    def get(self, revision_id: str) -> IngestRevision:
        path = self._path(revision_id)
        if not path.exists():
            raise IngestRevisionNotFoundError(revision_id)
        return IngestRevision.model_validate_json(path.read_text(encoding="utf-8"))

    def list(self, *, source_id: str | None = None) -> list[IngestRevision]:
        if not self.directory.exists():
            return []
        revisions = [
            IngestRevision.model_validate_json(path.read_text(encoding="utf-8"))
            for path in self.directory.glob("revision_*.json")
        ]
        if source_id is not None:
            revisions = [revision for revision in revisions if revision.source_id == source_id]
        return sorted(revisions, key=lambda revision: revision.created_at, reverse=True)

    def _path(self, revision_id: str) -> Path:
        if not revision_id.startswith("revision_"):
            raise ValueError("revision_id must start with 'revision_'")
        return self.directory / f"{revision_id}.json"

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(path)


class IngestRevisionService:
    """Turn review feedback into a new same-source ingest proposal."""

    def __init__(
        self,
        project_root: Path,
        *,
        ingest: IngestService | None = None,
        changesets: ChangeSetRepository | None = None,
        repository: IngestRevisionRepository | None = None,
    ):
        self.project_root = Path(project_root).resolve()
        self.ingest = ingest or IngestService(self.project_root)
        self.changesets = changesets or ChangeSetRepository(self.project_root)
        self.repository = repository or IngestRevisionRepository(self.project_root)

    def request_revision(
        self,
        change_set_id: str,
        *,
        reviewer: str,
        comments: list[str],
    ) -> IngestRevision:
        """Persist reviewer feedback without changing the original ChangeSet."""

        change_set = self.changesets.get(change_set_id)
        if any(operation.type is not ChangeOperationType.UPSERT_EXTRACTION for operation in change_set.operations):
            raise ValueError("only extraction ChangeSets support ingest revisions")
        if (self.project_root / "data" / "runtime" / "commits" / f"{change_set_id}.json").exists():
            raise ValueError("a committed ChangeSet cannot be revised")
        normalized = [comment.strip() for comment in comments if comment.strip()]
        if not normalized:
            raise ValueError("at least one non-empty review comment is required")
        source_id = change_set.operations[0].target_id
        revision = IngestRevision(
            revision_id=f"revision_{uuid.uuid4().hex}",
            source_id=source_id,
            parent_change_set_id=change_set_id,
            parent_revision_id=change_set.revision_id,
            comments=[
                ReviewComment(
                    comment_id=f"comment_{uuid.uuid4().hex}",
                    author=reviewer,
                    body=comment,
                )
                for comment in normalized
            ],
        )
        return self.repository.create(revision)

    def prepare_revision(
        self,
        revision_id: str,
        *,
        run_id: str,
        cancellation_id: str | None = None,
        agent_draft_run_id: str,
    ) -> ChangeSet:
        """Finalize a staged ingest-agent draft as the revision's extraction."""

        revision = self.repository.get(revision_id)
        if revision.change_set_id is not None:
            return self.changesets.get(revision.change_set_id)
        running = revision.model_copy(
            update={
                "status": RevisionStatus.RUNNING,
                "run_id": run_id,
                "updated_at": datetime.now(UTC),
                "error_message": None,
            }
        )
        self.repository.update(running)
        try:
            change_set = self.ingest.prepare_change_set(
                revision.source_id,
                run_id,
                agent_draft_run_id=agent_draft_run_id,
                revision_id=revision.revision_id,
                parent_change_set_id=revision.parent_change_set_id,
                parent_revision_id=revision.parent_revision_id,
                cancellation_id=cancellation_id,
            )
        except Exception as error:
            if str(error).startswith("ingest is agent-only"):
                # Missing-draft precondition failures return the revision to
                # REQUESTED so the coordinator can retry with a staged draft.
                self.repository.update(
                    running.model_copy(
                        update={
                            "status": RevisionStatus.REQUESTED,
                            "run_id": None,
                            "error_message": str(error),
                            "updated_at": datetime.now(UTC),
                        }
                    )
                )
            else:
                self.repository.update(
                    running.model_copy(
                        update={
                            "status": RevisionStatus.FAILED,
                            "error_message": str(error),
                            "updated_at": datetime.now(UTC),
                        }
                    )
                )
            raise
        self.repository.update(
            running.model_copy(
                update={
                    "status": RevisionStatus.READY,
                    "change_set_id": change_set.change_set_id,
                    "snapshot_id": change_set.snapshot_id,
                    "updated_at": datetime.now(UTC),
                }
            )
        )
        return change_set

    def get(self, revision_id: str) -> IngestRevision:
        return self.repository.get(revision_id)

    def list(self, *, source_id: str | None = None) -> list[IngestRevision]:
        return self.repository.list(source_id=source_id)
