# =============================================================================
# 中央写入器 —— 唯一允许将已批准的 ChangeSet 应用到正式数据的模块
# =============================================================================

"""The only module allowed to apply an approved ChangeSet to formal data."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from pathlib import Path
import json
import uuid

from filelock import FileLock

from cellwiki.domain.contracts import (
    ApprovalDecision,
    ChangeOperation,
    ChangeOperationType,
    CommitResult,
    PipelineTaskType,
)
from cellwiki.services.changesets import ChangeSetRepository
from cellwiki.services.approvals import ApprovalRepository
from cellwiki.services.projection import ProjectionService
from cellwiki.services.quality import verify_projection
from cellwiki.services.pipeline import KnowledgePipelineHarness


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 审批必需异常 —— ChangeSet 未经过审批时抛出
# ---------------------------------------------------------------------------
class ApprovalRequiredError(PermissionError):
    pass


# ---------------------------------------------------------------------------
# 版本冲突异常 —— 乐观锁检测到版本变更时抛出
# ---------------------------------------------------------------------------
class VersionConflictError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# 投影迁移异常 —— 旧版 Wiki 尚未迁移为正式 extraction 时拒绝首次发布
# ---------------------------------------------------------------------------
class ProjectionBootstrapRequiredError(RuntimeError):
    pass


# 验证器类型：接收项目根目录，无返回值，失败时抛出异常
Verifier = Callable[[Path], None]


# ---------------------------------------------------------------------------
# CentralWriter —— 中央写入器
# 唯一允许将已批准的 ChangeSet 应用到正式数据的模块。
# 执行原子化的提交流程：验证审批 → 快照备份 → 应用变更 → 验证结果 → 记录提交。
# 使用文件锁（FileLock）确保并发安全。
# 支持回滚：每次提交前创建快照，回滚时从快照恢复。
# 验证器确保投影在提交后仍然有效。
# ---------------------------------------------------------------------------
class CentralWriter:
    """Validate, snapshot, apply, verify, and record formal changes atomically."""

    def __init__(
        self,
        project_root: Path,
        repository: ChangeSetRepository | None = None,
        verifier: Verifier | None = None,
        projector: ProjectionService | None = None,
    ):
        self.project_root = Path(project_root).resolve()
        self.repository = repository or ChangeSetRepository(self.project_root)
        self.verifier = verifier or verify_projection
        self.projector = projector or ProjectionService(self.project_root)
        self.runtime_dir = self.project_root / "data" / "runtime"
        self.pipeline = KnowledgePipelineHarness(self.project_root)
        self.approvals = ApprovalRepository(self.project_root)
        self.transactions_dir = self.runtime_dir / "transactions"
        self._recover_transactions()

    def commit(
        self,
        change_set_id: str,
        approval: ApprovalDecision | None,
    ) -> CommitResult:
        existing = self._read_commit(change_set_id)
        if existing is not None:
            return existing
        change_set = self.repository.get(change_set_id)
        if change_set.project_id != "cellwiki":
            raise ValueError(f"unsupported project: {change_set.project_id}")
        if approval is None:
            # An explicit persisted decision is authoritative. This prevents a
            # delayed Assistant commit from turning a user rejection into an
            # auto-approved write after the project policy is read again.
            approval = self.approvals.get(change_set_id)
            if approval is None:
                approval = self.pipeline.approval_for(
                    change_set_id,
                    reviewer="default-reviewer",
                )
        if not approval.approved:
            raise ApprovalRequiredError("an explicit approval is required before commit")
        if approval.decided_by.startswith("agent-"):
            raise ApprovalRequiredError("model-generated approvals are not accepted")
        # Persist both human and policy decisions at the write boundary so a
        # direct Agent tool call cannot publish without an auditable decision.
        approval = self.approvals.save(change_set_id, approval)
        # Publication is a first-class Pipeline task. This makes the active
        # task/snapshot visible to the Product API while CentralWriter applies
        # and verifies the formal projection under the same project lease.
        with self.pipeline.acquire(
            task_type=PipelineTaskType.COMMIT,
            run_id=change_set.run_id,
        ) as lease:
            return self._commit_with_lease(
                change_set,
                approval,
                current_knowledge_version=lease.snapshot.knowledge_version,
            )

    def _commit_with_lease(
        self,
        change_set,
        approval: ApprovalDecision,
        *,
        current_knowledge_version: str,
    ) -> CommitResult:
        """Apply one proposal while the caller owns the project Pipeline lease."""

        existing = self._read_commit(change_set.change_set_id)
        if existing is not None:
            return existing

        if change_set.base_knowledge_version is not None:
            if current_knowledge_version != change_set.base_knowledge_version:
                raise VersionConflictError(
                    "knowledge version changed after the pipeline snapshot: "
                    f"expected {change_set.base_knowledge_version}, got {current_knowledge_version}"
                )

        targets = [(operation, self._target_path(operation)) for operation in change_set.operations]
        self._ensure_projection_baseline(change_set)
        self._check_versions(targets)
        before = {path: path.read_bytes() if path.exists() else None for _, path in targets}
        before.update(self._projection_files())
        snapshot_id = f"snapshot_{change_set.change_set_id}"
        self._write_snapshot(snapshot_id, before)
        transaction_id = f"txn_{uuid.uuid4().hex}"
        self._write_transaction(
            transaction_id,
            {
                "transaction_id": transaction_id,
                "change_set_id": change_set.change_set_id,
                "snapshot_id": snapshot_id,
                "stage": "prepared",
            },
        )

        try:
            for operation, path in targets:
                self._apply(operation, path)
            self.projector.render()
            self.verifier(self.project_root)
        except Exception:
            self._restore(before)
            self._remove_new_projection_files(before)
            self._discard_transaction_journal(transaction_id)
            raise

        result = CommitResult(
            commit_id=f"commit_{change_set.change_set_id}",
            change_set_id=change_set.change_set_id,
            status="committed",
            changed_targets=[operation.target_id for operation, _ in targets],
            snapshot_id=snapshot_id,
            transaction_id=transaction_id,
        )
        try:
            # This atomic marker is the point of no return. Before it exists,
            # any error restores the snapshot; afterwards, startup recovery
            # keeps the verified publication and only removes stale journals.
            self._write_commit(result)
        except Exception:
            self._restore(before)
            self._remove_new_projection_files(before)
            self._discard_transaction_journal(transaction_id)
            raise
        self._discard_transaction_journal(transaction_id)
        return result

    def _target_path(self, operation: ChangeOperation) -> Path:
        if operation.type == ChangeOperationType.UPDATE_CURATION:
            return self.project_root / "wiki" / "curation" / "cell_types" / f"{operation.target_id}.md"
        if operation.type == ChangeOperationType.UPSERT_EXTRACTION:
            return self.project_root / "data" / "extraction" / f"{operation.target_id}.json"
        if operation.type == ChangeOperationType.APPLY_LINT_FIX:
            return self.runtime_dir / "lint_fixes" / f"{operation.target_id}.json"
        raise NotImplementedError(f"operation {operation.type.value!r} is not supported in v1")

    def _ensure_projection_baseline(self, change_set) -> None:
        """Prevent the first extraction publication from deleting legacy Wiki pages."""

        if not any(
            operation.type == ChangeOperationType.UPSERT_EXTRACTION
            for operation in change_set.operations
        ):
            return
        extraction_dir = self.project_root / "data" / "extraction"
        if any(extraction_dir.glob("*.json")):
            return
        legacy_paths = {
            path
            for path in ProjectionService.managed_output_paths(self.project_root)
            if path.is_file()
        }
        if legacy_paths:
            raise ProjectionBootstrapRequiredError(
                "existing Wiki projection is not backed by formal extraction records; "
                "migrate the legacy Wiki before publishing the first extraction"
            )

    def _check_versions(self, targets: list[tuple[ChangeOperation, Path]]) -> None:
        for operation, path in targets:
            if operation.expected_version is None:
                continue
            actual = self._version(path)
            if actual != operation.expected_version:
                raise VersionConflictError(
                    f"{operation.target_id} changed: expected {operation.expected_version}, got {actual}"
                )

    def _apply(self, operation: ChangeOperation, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if operation.type == ChangeOperationType.UPDATE_CURATION:
            content = operation.payload.get("content")
            if not isinstance(content, str):
                raise ValueError("update_curation requires a string content field")
            self._atomic_write(path, content.encode("utf-8"))
            return
        if operation.type == ChangeOperationType.UPSERT_EXTRACTION:
            from cellwiki.domain.extraction import ExtractionResult

            extraction = ExtractionResult.model_validate(operation.payload)
            self._atomic_write(path, extraction.model_dump_json(indent=2).encode("utf-8"))
            return
        if operation.type == ChangeOperationType.APPLY_LINT_FIX:
            if operation.payload.get("action") != "rebuild_projection":
                raise ValueError("v1 lint fixes only support a controlled projection rebuild")
            # The marker makes the requested repair auditable; ProjectionService performs the repair.
            self._atomic_write(
                path,
                json.dumps(operation.payload, ensure_ascii=False, indent=2).encode("utf-8"),
            )
            return
        raise NotImplementedError(operation.type.value)

    def _write_snapshot(self, snapshot_id: str, before: dict[Path, bytes | None]) -> None:
        snapshot_dir = self.runtime_dir / "snapshots" / snapshot_id
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        manifest = []
        for index, (path, content) in enumerate(before.items()):
            relative = path.relative_to(self.project_root).as_posix()
            entry = {"path": relative, "existed": content is not None}
            if content is not None:
                filename = f"{index:04d}.bin"
                (snapshot_dir / filename).write_bytes(content)
                entry["file"] = filename
            manifest.append(entry)
        self._atomic_write(
            snapshot_dir / "manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
        )

    def _transaction_path(self, transaction_id: str) -> Path:
        return self.transactions_dir / f"{transaction_id}.json"

    def _write_transaction(self, transaction_id: str, payload: dict) -> None:
        self.transactions_dir.mkdir(parents=True, exist_ok=True)
        current = self._transaction_path(transaction_id)
        previous = {}
        if current.exists():
            try:
                previous = json.loads(current.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                previous = {}
        previous.update(payload)
        self._atomic_write(
            current,
            json.dumps(previous, ensure_ascii=False, indent=2).encode("utf-8"),
        )

    def _discard_transaction_journal(self, transaction_id: str) -> None:
        try:
            self._transaction_path(transaction_id).unlink(missing_ok=True)
        except OSError:
            # A verified commit remains authoritative. Leaving the journal is
            # safe because startup recovery removes it when the commit exists.
            logger.warning(
                "Could not remove publication transaction journal %s",
                transaction_id,
                exc_info=True,
            )

    def _recover_transactions(self) -> None:
        """Finish or roll back transactions left by an interrupted process."""

        if not self.transactions_dir.exists():
            return
        self.pipeline.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with FileLock(str(self.pipeline.lock_path)):
            for journal_path in sorted(self.transactions_dir.glob("txn_*.json")):
                journal = json.loads(journal_path.read_text(encoding="utf-8"))
                change_set_id = str(journal["change_set_id"])
                if self._commit_path(change_set_id).exists():
                    journal_path.unlink(missing_ok=True)
                    continue
                snapshot_id = str(journal["snapshot_id"])
                before = self._read_snapshot(snapshot_id)
                self._restore(before)
                self._remove_new_projection_files(before)
                journal_path.unlink(missing_ok=True)

    def _read_snapshot(self, snapshot_id: str) -> dict[Path, bytes | None]:
        snapshot_dir = self.runtime_dir / "snapshots" / snapshot_id
        manifest_path = snapshot_dir / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"snapshot manifest is missing: {snapshot_id}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        before: dict[Path, bytes | None] = {}
        for entry in manifest:
            destination = (self.project_root / entry["path"]).resolve()
            if self.project_root not in destination.parents:
                raise ValueError("snapshot path escaped the CellWiki project")
            before[destination] = (
                (snapshot_dir / entry["file"]).read_bytes()
                if entry["existed"]
                else None
            )
        return before

    @staticmethod
    def _restore(before: dict[Path, bytes | None]) -> None:
        for path, content in before.items():
            if content is None:
                path.unlink(missing_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                CentralWriter._atomic_write(path, content)

    def _remove_new_projection_files(self, before: dict[Path, bytes | None]) -> None:
        for path in ProjectionService.managed_output_paths(self.project_root):
            if path not in before:
                path.unlink(missing_ok=True)

    def _projection_files(self) -> dict[Path, bytes | None]:
        """Capture generated outputs so a failed verification cannot leak a projection."""
        return {
            path: path.read_bytes() if path.exists() else None
            for path in ProjectionService.managed_output_paths(self.project_root)
        }

    def _commit_path(self, change_set_id: str) -> Path:
        return self.runtime_dir / "commits" / f"{change_set_id}.json"

    def get_commit(self, change_set_id: str) -> CommitResult | None:
        """Expose commit state to the Product API without exposing file paths."""
        return self._read_commit(change_set_id)

    def get_rollback(self, change_set_id: str) -> CommitResult | None:
        """Return the recorded rollback state without exposing snapshot paths."""

        path = self.runtime_dir / "rollbacks" / f"{change_set_id}.json"
        if not path.exists():
            return None
        return CommitResult.model_validate_json(path.read_text(encoding="utf-8"))

    def _read_commit(self, change_set_id: str) -> CommitResult | None:
        path = self._commit_path(change_set_id)
        if not path.exists():
            return None
        return CommitResult.model_validate_json(path.read_text(encoding="utf-8"))

    def _write_commit(self, result: CommitResult) -> None:
        path = self._commit_path(result.change_set_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._atomic_write(path, result.model_dump_json(indent=2).encode("utf-8"))

    def rollback(
        self,
        change_set_id: str,
        *,
        decided_by: str,
        reason: str,
    ) -> CommitResult:
        """Restore an applied ChangeSet snapshot and record an idempotent rollback result."""

        commit = self._read_commit(change_set_id)
        if commit is None:
            raise KeyError(f"ChangeSet {change_set_id} has no committed snapshot")
        rollback_path = self.runtime_dir / "rollbacks" / f"{change_set_id}.json"
        if rollback_path.exists():
            return CommitResult.model_validate_json(rollback_path.read_text(encoding="utf-8"))

        lock_path = self.runtime_dir / "cellwiki.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with FileLock(str(lock_path)):
            if rollback_path.exists():
                return CommitResult.model_validate_json(rollback_path.read_text(encoding="utf-8"))
            self._require_latest_active_commit(change_set_id)
            snapshot_dir = self.runtime_dir / "snapshots" / commit.snapshot_id
            manifest_path = snapshot_dir / "manifest.json"
            if not manifest_path.exists():
                raise FileNotFoundError(f"snapshot manifest is missing: {commit.snapshot_id}")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            before: dict[Path, bytes | None] = {}
            for entry in manifest:
                destination = (self.project_root / entry["path"]).resolve()
                if self.project_root not in destination.parents and destination != self.project_root:
                    raise ValueError("snapshot path escaped the CellWiki project")
                if entry["existed"]:
                    content = (snapshot_dir / entry["file"]).read_bytes()
                    before[destination] = content
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    self._atomic_write(destination, content)
                else:
                    before[destination] = None
                    destination.unlink(missing_ok=True)
            self._remove_new_projection_files(before)
            self.verifier(self.project_root)
            result = CommitResult(
                commit_id=f"rollback_{change_set_id}",
                change_set_id=change_set_id,
                status="rolled_back",
                changed_targets=commit.changed_targets,
                snapshot_id=commit.snapshot_id,
            )
            rollback_path.parent.mkdir(parents=True, exist_ok=True)
            payload = result.model_dump(mode="json")
            payload["decided_by"] = decided_by
            payload["reason"] = reason
            # CommitResult remains the stable return contract; audit metadata stays alongside it.
            self._atomic_write(
                rollback_path,
                result.model_dump_json(indent=2).encode("utf-8"),
            )
            audit_path = rollback_path.with_suffix(".audit.json")
            self._atomic_write(
                audit_path,
                json.dumps(payload, ensure_ascii=False, indent=2, default=str).encode("utf-8"),
            )
            return result

    def _require_latest_active_commit(self, change_set_id: str) -> None:
        """Prevent an old snapshot from silently erasing knowledge committed afterwards."""

        commits_dir = self.runtime_dir / "commits"
        active = []
        if commits_dir.exists():
            for path in commits_dir.glob("*.json"):
                candidate = CommitResult.model_validate_json(path.read_text(encoding="utf-8"))
                if self.get_rollback(candidate.change_set_id) is None:
                    active.append(candidate)
        if not active:
            raise KeyError(f"ChangeSet {change_set_id} has no active commit")
        latest = max(active, key=lambda result: result.committed_at)
        if latest.change_set_id != change_set_id:
            raise VersionConflictError(
                f"cannot roll back {change_set_id} after later commit {latest.change_set_id}"
            )

    @staticmethod
    def _atomic_write(path: Path, content: bytes) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(content)
        temporary.replace(path)

    @staticmethod
    def _version(path: Path) -> str:
        if not path.exists():
            return "missing"
        return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"
