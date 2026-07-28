"""Persistent, immutable approval decisions for ChangeSets."""

from __future__ import annotations

from pathlib import Path

from filelock import FileLock

from cellwiki.domain.contracts import ApprovalDecision


class ApprovalConflictError(ValueError):
    """Raised when a finalized decision is replaced with a different one."""


class ApprovalRepository:
    """Keep one auditable decision per ChangeSet.

    The lock covers the existence check and atomic replace. This makes the
    immutable-decision invariant true for concurrent desktop/API requests.
    """

    def __init__(self, project_root: Path):
        self.directory = Path(project_root) / "data" / "runtime" / "approvals"
        self.lock_path = self.directory / ".decisions.lock"

    def save(self, change_set_id: str, decision: ApprovalDecision) -> ApprovalDecision:
        path = self._path(change_set_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with FileLock(str(self.lock_path)):
            if path.exists():
                existing = ApprovalDecision.model_validate_json(
                    path.read_text(encoding="utf-8")
                )
                if (
                    existing.approved == decision.approved
                    and existing.decided_by == decision.decided_by
                    and existing.reason == decision.reason
                ):
                    return existing
                raise ApprovalConflictError(
                    f"ChangeSet {change_set_id!r} already has a final decision"
                )
            temporary = path.with_suffix(".json.tmp")
            temporary.write_text(decision.model_dump_json(indent=2), encoding="utf-8")
            temporary.replace(path)
            return decision

    def get(self, change_set_id: str) -> ApprovalDecision | None:
        path = self._path(change_set_id)
        if not path.exists():
            return None
        return ApprovalDecision.model_validate_json(path.read_text(encoding="utf-8"))

    def _path(self, change_set_id: str) -> Path:
        if not change_set_id.startswith("cs_"):
            raise ValueError("change_set_id must start with 'cs_'")
        return self.directory / f"{change_set_id}.json"
