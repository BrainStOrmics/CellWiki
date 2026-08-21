# =============================================================================
# 变更集仓库 —— 提议的 ChangeSet 的不可变本地仓库
# =============================================================================

"""Immutable local repository for proposed ChangeSets."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import shutil
import uuid

from filelock import FileLock

from cellwiki.domain.contracts import (
    ChangeOperation,
    ChangeOperationType,
    ChangeSet,
    ChangeSetRebaseResult,
    ChangeSetRebaseStatus,
    CommitResult,
    EvidenceReference,
    ReviewItem,
    RiskLevel,
)
from cellwiki.domain.pipeline import PipelineTaskType


# ---------------------------------------------------------------------------
# ChangeSetNotFoundError —— ChangeSet 未找到异常
# ---------------------------------------------------------------------------
class ChangeSetNotFoundError(KeyError):
    pass


# ---------------------------------------------------------------------------
# ChangeSetConflictError —— ChangeSet 内容冲突异常
# 当尝试保存不同内容的已存在 ChangeSet 时抛出
# ---------------------------------------------------------------------------
class ChangeSetConflictError(ValueError):
    pass


# ---------------------------------------------------------------------------
# ChangeSetRepository —— 变更集仓库
# 提议的 ChangeSet 的不可变本地存储库，使用文件系统存储。
# 每个 ChangeSet 以 cs_<id>.json 格式存储在 data/runtime/changesets/ 目录下。
# 支持：保存（原子写入）、获取、列表（按创建时间倒序）、按目标 ID 过滤。
# 写入使用原子操作：先写 .tmp 文件再重命名，防止部分写入。
def _nested_contains(value: object, needle: str) -> bool:
    """Recursively check whether a nested dict/list contains the exact string value."""
    if isinstance(value, str):
        return value == needle
    if isinstance(value, dict):
        return any(_nested_contains(item, needle) for item in value.values())
    if isinstance(value, list):
        return any(_nested_contains(item, needle) for item in value)
    return False


# ---------------------------------------------------------------------------
# ChangeSetDeleteBlockedError —— ChangeSet 删除被阻止异常
# 当正式数据、修订链或活跃运行仍依赖该 ChangeSet 时抛出
# ---------------------------------------------------------------------------
class ChangeSetDeleteBlockedError(RuntimeError):
    """Raised when a ChangeSet cannot be deleted while formal data or a live run depends on it."""

    def __init__(self, blocking: str, detail: str, run_ids: list[str] | None = None):
        super().__init__(detail)
        self.blocking = blocking
        self.detail = detail
        self.run_ids = run_ids or []


class ChangeSetRepository:
    def __init__(self, project_root: Path):
        self.project_root = Path(project_root).resolve()
        self.directory = self.project_root / "data" / "runtime" / "changesets"

    def create_proposal(
        self,
        *,
        run_id: str,
        task_type: PipelineTaskType,
        operations: list[ChangeOperation],
        reason: str,
        risk: RiskLevel,
        project_id: str = "cellwiki",
        evidence: list[EvidenceReference] | None = None,
        review_items: list[ReviewItem] | None = None,
        revision_id: str | None = None,
        parent_change_set_id: str | None = None,
    ) -> ChangeSet:
        """Create an independent proposal from one whole-library snapshot."""

        from cellwiki.services.pipeline import KnowledgePipelineHarness

        snapshot = KnowledgePipelineHarness(self.project_root).capture_snapshot(
            task_type=task_type,
            run_id=run_id,
        )
        change_set = ChangeSet(
            change_set_id=f"cs_{uuid.uuid4().hex}",
            run_id=run_id,
            project_id=project_id,
            operations=operations,
            evidence=evidence or [],
            review_items=review_items or [],
            risk=risk,
            reason=reason,
            snapshot_id=snapshot.snapshot_id,
            base_knowledge_version=snapshot.knowledge_version,
            revision_id=revision_id,
            parent_change_set_id=parent_change_set_id,
        )
        return self.save(change_set)

    # 保存 ChangeSet，如果已存在且内容相同则幂等返回
    def save(self, change_set: ChangeSet) -> ChangeSet:
        path = self._path(change_set.change_set_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            existing = ChangeSet.model_validate_json(path.read_text(encoding="utf-8"))
            if existing != change_set:
                raise ChangeSetConflictError(
                    f"ChangeSet {change_set.change_set_id!r} already exists with different content"
                )
            return existing
        # 原子写入
        self._atomic_write(path, change_set.model_dump_json(indent=2))
        return change_set

    # 获取 ChangeSet，不存在则抛出异常
    def get(self, change_set_id: str) -> ChangeSet:
        path = self._path(change_set_id)
        if not path.exists():
            raise ChangeSetNotFoundError(change_set_id)
        return ChangeSet.model_validate_json(path.read_text(encoding="utf-8"))

    # 列出所有 ChangeSet，按创建时间倒序（最新优先）
    # 可选参数 target_id：只返回影响指定目标的 ChangeSet
    def list(self, target_id: str | None = None) -> list[ChangeSet]:
        """Return newest proposals first, optionally scoped to one domain target."""
        if not self.directory.exists():
            return []
        change_sets = [
            ChangeSet.model_validate_json(path.read_text(encoding="utf-8"))
            for path in self.directory.glob("cs_*.json")
        ]
        # 如果指定了目标 ID，过滤出影响该目标的 ChangeSet
        if target_id is not None:
            change_sets = [
                change_set
                for change_set in change_sets
                if any(operation.target_id == target_id for operation in change_set.operations)
            ]
        return sorted(change_sets, key=lambda change_set: change_set.created_at, reverse=True)

    # 硬删除一个已终止的 ChangeSet：先落 tombstone，再级联删除审计产物
    def delete(self, change_set_id: str) -> None:
        """Hard-delete a terminal proposal and its audit artifacts after writing a tombstone.

        Only non-committed ChangeSets are deletable; a committed proposal must be
        rolled back first so the formal Wiki never loses its commit lineage.
        """
        path = self._path(change_set_id)
        if not path.exists():
            raise ChangeSetNotFoundError(change_set_id)

        lock_path = self.directory / ".changesets.delete.lock"
        with FileLock(str(lock_path)):
            if not path.exists():
                raise ChangeSetNotFoundError(change_set_id)
            commit_path = self._runtime_path("commits") / f"{change_set_id}.json"
            rollback_path = self._runtime_path("rollbacks") / f"{change_set_id}.json"
            if commit_path.exists() and not rollback_path.exists():
                raise ChangeSetDeleteBlockedError(
                    blocking="committed",
                    detail="ChangeSet is committed; roll it back before deleting.",
                )
            children = [
                candidate.change_set_id
                for candidate in self.list()
                if candidate.parent_change_set_id == change_set_id
            ]
            if children:
                raise ChangeSetDeleteBlockedError(
                    blocking="has_revisions",
                    detail=f"ChangeSet has revision children: {', '.join(sorted(children))}",
                )
            run_ids = self._active_runs_for(change_set_id)
            if run_ids:
                raise ChangeSetDeleteBlockedError(
                    blocking="run_waiting",
                    detail="A live ingest run is still waiting on this ChangeSet.",
                    run_ids=run_ids,
                )
            self._write_tombstone(
                {
                    "change_set_id": change_set_id,
                    "deleted_at": datetime.now(UTC).isoformat(),
                }
            )
            # 级联删除：ChangeSet 记录 + 审批/提交/回滚审计文件 + 快照目录
            for artifact in (
                path,
                self._runtime_path("approvals") / f"{change_set_id}.json",
                self._runtime_path("commits") / f"{change_set_id}.json",
                self._runtime_path("rollbacks") / f"{change_set_id}.json",
                self._runtime_path("rollbacks") / f"{change_set_id}.audit.json",
            ):
                artifact.unlink(missing_ok=True)
            snapshot_dir = self.project_root / "data" / "runtime" / "snapshots" / f"snapshot_{change_set_id}"
            if snapshot_dir.exists():
                shutil.rmtree(snapshot_dir)

    # 找出仍在使用该 ChangeSet 的活跃运行：
    # 1) ingest 账本里真正在跑的运行（RUNNING/COMMITTING）；
    #    账本停在 AWAITING_REVIEW 只代表提案等待过审核，不代表运行还活着
    #    （通过 Agent 侧决策的提案不会写终态账本事件，不能据此永久阻止删除）。
    # 2) Agent 运行时仍暂停在等待用户审批/确认、且引用了该变更集的运行
    #    （未决策的提案本来就不显示删除按钮，这里兜底 API 层的安全）。
    def _active_runs_for(self, change_set_id: str) -> list[str]:
        from cellwiki.domain.contracts import TaskStatus
        from cellwiki.services.tasks import TaskEventRepository

        active = {
            TaskStatus.RUNNING.value,
            TaskStatus.COMMITTING.value,
        }
        ledger_run_ids = [
            run["run_id"]
            for run in TaskEventRepository(self.project_root).list_runs()
            if run.get("change_set_id") == change_set_id and run["status"] in active
        ]
        return sorted(set(ledger_run_ids) | set(self._agent_runs_paused_on(change_set_id)))

    # Agent 侧：暂停在等待用户决策且引用该变更集的运行
    def _agent_runs_paused_on(self, change_set_id: str) -> list[str]:
        from cellwiki.domain.runs import AgentRunStatus
        from cellwiki.services.runtime_store import RuntimeStore

        paused = {
            AgentRunStatus.WAITING_APPROVAL,
            AgentRunStatus.WAITING_CONFIRMATION,
        }
        store = RuntimeStore(self.project_root)
        matching: list[str] = []
        for run in store.list_runs():
            if run.status not in paused or not run.thread_id:
                continue
            for message in store.list_messages(run.thread_id):
                if _nested_contains(message.get("data"), change_set_id):
                    matching.append(run.run_id)
                    break
        return matching

    # 先落审计 tombstone，再物理删除，保证每次删除都有可追溯记录
    def _write_tombstone(self, payload: dict) -> None:
        deleted_dir = self.project_root / "data" / "runtime" / "deleted"
        deleted_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
        path = deleted_dir / f"{payload['change_set_id']}.deleted.{timestamp}.json"
        self._atomic_write(path, json.dumps(payload, ensure_ascii=False, indent=2))

    # 定位运行期审计目录（approvals/commits/rollbacks）
    def _runtime_path(self, kind: str) -> Path:
        return self.project_root / "data" / "runtime" / kind

    def rebase(self, change_set_id: str, *, run_id: str | None = None) -> ChangeSetRebaseResult:
        """Rebase a stale proposal without mutating its immutable source record."""

        from cellwiki.services.pipeline import KnowledgePipelineHarness

        change_set = self.get(change_set_id)
        pipeline = KnowledgePipelineHarness(self.project_root)
        current_version = pipeline.current_knowledge_version()
        previous_version = change_set.base_knowledge_version
        if previous_version == current_version:
            return ChangeSetRebaseResult(
                original_change_set_id=change_set_id,
                status=ChangeSetRebaseStatus.CURRENT,
                previous_base_knowledge_version=previous_version,
                current_knowledge_version=current_version,
                message="The ChangeSet already targets the current knowledge version.",
            )

        proposal_targets = {operation.target_id for operation in change_set.operations}
        committed_targets = self._committed_targets_after(change_set.created_at)
        if not committed_targets:
            return ChangeSetRebaseResult(
                original_change_set_id=change_set_id,
                status=ChangeSetRebaseStatus.CONFLICT,
                previous_base_knowledge_version=previous_version,
                current_knowledge_version=current_version,
                conflicting_target_ids=sorted(proposal_targets),
                message="The base is stale without auditable commit lineage; manual conflict review is required.",
            )
        conflicts = sorted(proposal_targets & committed_targets)
        if conflicts:
            return ChangeSetRebaseResult(
                original_change_set_id=change_set_id,
                status=ChangeSetRebaseStatus.CONFLICT,
                previous_base_knowledge_version=previous_version,
                current_knowledge_version=current_version,
                conflicting_target_ids=conflicts,
                message="The proposal overlaps targets committed after its base snapshot.",
            )

        rebase_run_id = run_id or f"rebase_{uuid.uuid4().hex}"
        snapshot = pipeline.capture_snapshot(
            task_type=PipelineTaskType.COMMIT,
            run_id=rebase_run_id,
        )
        rebased = change_set.model_copy(
            update={
                "change_set_id": f"cs_{uuid.uuid4().hex}",
                "run_id": rebase_run_id,
                "operations": [
                    operation.model_copy(
                        update={"expected_version": self._target_version(operation)}
                    )
                    for operation in change_set.operations
                ],
                "snapshot_id": snapshot.snapshot_id,
                "base_knowledge_version": current_version,
                "parent_change_set_id": change_set_id,
                "created_at": datetime.now(UTC),
            }
        )
        self.save(rebased)
        return ChangeSetRebaseResult(
            original_change_set_id=change_set_id,
            status=ChangeSetRebaseStatus.REBASED,
            rebased_change_set_id=rebased.change_set_id,
            previous_base_knowledge_version=previous_version,
            current_knowledge_version=current_version,
            message="A new ChangeSet was created on the current knowledge version.",
        )

    def _committed_targets_after(self, created_at: datetime) -> set[str]:
        commits_dir = self.project_root / "data" / "runtime" / "commits"
        targets: set[str] = set()
        if not commits_dir.exists():
            return targets
        for path in commits_dir.glob("*.json"):
            try:
                commit = CommitResult.model_validate_json(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if commit.committed_at > created_at:
                targets.update(commit.changed_targets)
        return targets

    def _target_version(self, operation: ChangeOperation) -> str:
        path: Path
        if operation.type == ChangeOperationType.UPDATE_CURATION:
            path = self.project_root / "wiki" / "curation" / "cell_types" / f"{operation.target_id}.md"
        elif operation.type == ChangeOperationType.UPSERT_EXTRACTION:
            path = self.project_root / "data" / "extraction" / f"{operation.target_id}.json"
        elif operation.type == ChangeOperationType.APPLY_LINT_FIX:
            path = self.project_root / "data" / "runtime" / "lint_fixes" / f"{operation.target_id}.json"
        else:
            return operation.expected_version or "missing"
        if not path.exists():
            return "missing"
        return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"

    # 根据 change_set_id 生成文件路径，验证 ID 格式
    def _path(self, change_set_id: str) -> Path:
        if not change_set_id.startswith("cs_"):
            raise ValueError("change_set_id must start with 'cs_'")
        return self.directory / f"{change_set_id}.json"

    # 原子写入：先写临时文件，再重命名替换
    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(path)
