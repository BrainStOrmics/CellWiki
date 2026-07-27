"""Project-scoped knowledge pipeline state, leases, snapshots, and approval policy."""

from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator
import uuid

from filelock import FileLock, Timeout

from cellwiki.domain.contracts import (
    ApprovalDecision,
    ApprovalPolicy,
    KnowledgeSnapshot,
    PipelineTaskType,
)
from cellwiki.services.approvals import ApprovalRepository
from cellwiki.services.changesets import ChangeSetRepository
from cellwiki.services.quality import inspect_projection


class PipelineBusyError(RuntimeError):
    """Raised when another mutating knowledge pipeline task owns the project lease."""


class SnapshotNotFoundError(KeyError):
    """Raised when a persisted pipeline snapshot cannot be found."""


@dataclass(frozen=True)
class PipelineLease:
    """The state captured when a mutating pipeline task acquired the project lease."""

    snapshot: KnowledgeSnapshot
    task_type: PipelineTaskType
    run_id: str


class KnowledgePipelineHarness:
    """Coordinate whole-project reads before Ingest, Lint, and formal writes.

    The harness deliberately treats Markdown, formal extraction, and registered
    source metadata as truth inputs. Runtime ChangeSets and lint findings are
    inventory only; they never become part of ``knowledge_version``. Derived
    indexes therefore cannot make a stale pipeline appear current.
    """

    def __init__(self, project_root: Path):
        self.project_root = Path(project_root).resolve()
        self.runtime_dir = self.project_root / "data" / "runtime" / "pipeline"
        self.snapshot_dir = self.runtime_dir / "snapshots"
        # CentralWriter owns this project-wide lock. Reusing the exact path
        # keeps ingest, lint proposals, research refresh, and publication in
        # one serialization domain.
        self.lock_path = self.project_root / "data" / "runtime" / "cellwiki.lock"
        self.active_path = self.runtime_dir / "active.json"
        self.policy_path = self.runtime_dir / "approval_policy.json"

    def current_knowledge_version(self) -> str:
        """Return a content-based version of the formal knowledge inputs."""

        return self._formal_state()["knowledge_version"]

    def capture_snapshot(
        self,
        *,
        task_type: PipelineTaskType,
        run_id: str,
    ) -> KnowledgeSnapshot:
        """Capture and persist the complete state visible to a pipeline task."""

        formal = self._formal_state()
        change_sets = ChangeSetRepository(self.project_root).list()
        approvals = ApprovalRepository(self.project_root)
        pending = []
        for change_set in change_sets:
            commit_path = self.project_root / "data" / "runtime" / "commits" / f"{change_set.change_set_id}.json"
            if commit_path.exists():
                continue
            decision = approvals.get(change_set.change_set_id)
            pending.append(
                {
                    "change_set_id": change_set.change_set_id,
                    "run_id": change_set.run_id,
                    "risk": change_set.risk.value,
                    "approval": decision.approved if decision is not None else None,
                }
            )

        report = inspect_projection(self.project_root)
        snapshot = KnowledgeSnapshot(
            snapshot_id=f"snapshot_{uuid.uuid4().hex}",
            task_type=task_type,
            run_id=run_id,
            knowledge_version=formal["knowledge_version"],
            inventory={
                "formal": {
                    "wiki_pages": formal["wiki_pages"],
                    "extractions": formal["extractions"],
                    "sources": formal["sources"],
                    "files": formal["files"],
                },
                "pending_changesets": pending,
                "lint": {
                    "status": report.get("status", "unknown"),
                    "issue_count": int(report.get("issue_count", 0)),
                },
            },
        )
        self._write_json(self.snapshot_dir / f"{snapshot.snapshot_id}.json", snapshot.model_dump(mode="json"))
        return snapshot

    def get_snapshot(self, snapshot_id: str) -> KnowledgeSnapshot:
        path = self.snapshot_dir / f"{snapshot_id}.json"
        if not path.exists():
            raise SnapshotNotFoundError(snapshot_id)
        return KnowledgeSnapshot.model_validate_json(path.read_text(encoding="utf-8"))

    @contextmanager
    def acquire(self, *, task_type: PipelineTaskType, run_id: str) -> Iterator[PipelineLease]:
        """Acquire the project lease, snapshot the whole state, and release it safely."""

        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        lock = FileLock(str(self.lock_path), timeout=0)
        try:
            lock.acquire()
        except Timeout as error:
            raise PipelineBusyError(
                "another CellWiki knowledge pipeline task is already running"
            ) from error

        snapshot: KnowledgeSnapshot | None = None
        try:
            snapshot = self.capture_snapshot(task_type=task_type, run_id=run_id)
            self._write_json(
                self.active_path,
                {
                    "run_id": run_id,
                    "task_type": task_type.value,
                    "snapshot_id": snapshot.snapshot_id,
                    "started_at": datetime.now(UTC).isoformat(),
                },
            )
            yield PipelineLease(snapshot=snapshot, task_type=task_type, run_id=run_id)
        finally:
            if snapshot is not None and self.active_path.exists():
                try:
                    active = json.loads(self.active_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    active = {}
                if active.get("snapshot_id") == snapshot.snapshot_id:
                    self.active_path.unlink(missing_ok=True)
            lock.release()

    def active_task(self) -> dict[str, Any] | None:
        """Return the currently recorded lease without exposing lock internals."""

        if not self.active_path.exists():
            return None
        try:
            return json.loads(self.active_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def approval_policy(self) -> ApprovalPolicy:
        if not self.policy_path.exists():
            return ApprovalPolicy.AUTO_ALL
        try:
            payload = json.loads(self.policy_path.read_text(encoding="utf-8"))
            return ApprovalPolicy(payload.get("policy", ApprovalPolicy.AUTO_ALL.value))
        except (OSError, json.JSONDecodeError, ValueError):
            return ApprovalPolicy.AUTO_ALL

    def set_approval_policy(self, policy: ApprovalPolicy) -> ApprovalPolicy:
        self._write_json(self.policy_path, {"policy": policy.value, "updated_at": datetime.now(UTC).isoformat()})
        return policy

    def approval_for(self, change_set_id: str, *, reviewer: str) -> ApprovalDecision:
        """Return the policy result without persisting a manual pending decision."""

        if self.approval_policy() is ApprovalPolicy.AUTO_ALL:
            return ApprovalDecision(
                approved=True,
                decided_by="policy:auto_all",
                reason=f"ChangeSet {change_set_id} was auto-approved by the project policy.",
            )
        return ApprovalDecision(
            approved=False,
            decided_by=f"pending:{reviewer}",
            reason=f"ChangeSet {change_set_id} is awaiting review by {reviewer}.",
        )

    def _formal_state(self) -> dict[str, Any]:
        roots = [
            self.project_root / "wiki",
            self.project_root / "data" / "extraction",
            self.project_root / "data" / "runtime" / "sources",
        ]
        # SourceRecord lifecycle metadata changes during a normal Ingest (parser
        # version, parse hash, analyzed status). It remains in the snapshot
        # inventory, but only formal Wiki/extraction content participates in the
        # publication base version; target-level versions cover each extraction.
        version_roots = set(roots[:2])
        files: list[dict[str, Any]] = []
        digest = hashlib.sha256()
        for root in roots:
            if not root.exists():
                continue
            for path in sorted(item for item in root.rglob("*") if item.is_file()):
                relative = path.relative_to(self.project_root).as_posix()
                content = path.read_bytes()
                file_hash = hashlib.sha256(content).hexdigest()
                if root in version_roots:
                    digest.update(relative.encode("utf-8"))
                    digest.update(b"\0")
                    digest.update(content)
                files.append({"path": relative, "size": len(content), "sha256": file_hash})
        return {
            "knowledge_version": f"sha256:{digest.hexdigest()}",
            "wiki_pages": sum(1 for item in files if item["path"].startswith("wiki/") and item["path"].endswith(".md")),
            "extractions": sum(1 for item in files if item["path"].startswith("data/extraction/") and item["path"].endswith(".json")),
            "sources": sum(1 for item in files if item["path"].startswith("data/runtime/sources/") and item["path"].endswith(".json")),
            "files": files,
        }

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
