"""Audited admin batch approval for ChangeSets.

One explicit high-privilege action records a single immutable batch record
(reason, role, decided_by) and commits every listed ChangeSet.  The CentralWriter
boundary keeps the commit path identical to the single-decision flow; this
service only orchestrates and audits it.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from cellwiki.domain.contracts import ApprovalDecision, ChangeSetRebaseStatus
from cellwiki.services.approvals import ApprovalRepository
from cellwiki.services.central_writer import CentralWriter, VersionConflictError
from cellwiki.services.changesets import ChangeSetRepository


class AdminBatchApprovalService:
    """Approve and commit several ChangeSets under one auditable batch."""

    def __init__(self, project_root: Path | str):
        root = Path(project_root).resolve()
        self.root = root
        self.changesets = ChangeSetRepository(root)
        self.approvals = ApprovalRepository(root)
        self.writer = CentralWriter(root)
        self.batches_dir = root / "data" / "runtime" / "approvals" / "batches"

    def approve_batch(
        self,
        change_set_ids: list[str],
        *,
        decided_by: str,
        reason: str,
        role: str = "admin",
        batch_id: str | None = None,
    ) -> dict[str, Any]:
        """Approve+commit a list of ChangeSets and persist one audit record."""
        if not reason.strip():
            raise ValueError("batch approval requires a non-empty reason")
        if decided_by.startswith("agent-"):
            raise ValueError("model-generated approvals are not accepted")
        if not change_set_ids:
            raise ValueError("batch approval requires at least one change_set_id")
        effective_id = batch_id or f"batch_{uuid.uuid4().hex}"
        results: list[dict[str, Any]] = []
        for change_set_id in change_set_ids:
            try:
                decision = ApprovalDecision(
                    approved=True,
                    decided_by=decided_by,
                    reason=f"{reason} [batch {effective_id}]",
                )
                committed_id = change_set_id
                rebased_from: str | None = None
                try:
                    commit = self.writer.commit(change_set_id, approval=decision)
                except VersionConflictError:
                    # 批量审批时后续条目快照已过期：先在当前知识版本上 rebase，
                    # 再提交新 ChangeSet，保持不可变原记录与审计链完整。
                    rebase = self.changesets.rebase(change_set_id)
                    if rebase.status is not ChangeSetRebaseStatus.REBASED:
                        raise
                    assert rebase.rebased_change_set_id is not None
                    committed_id = rebase.rebased_change_set_id
                    rebased_from = change_set_id
                    rebased_decision = ApprovalDecision(
                        approved=True,
                        decided_by=decided_by,
                        reason=f"{reason} [batch {effective_id}]",
                    )
                    commit = self.writer.commit(committed_id, approval=rebased_decision)
                entry: dict[str, Any] = {
                    "change_set_id": change_set_id,
                    "status": "committed",
                    "commit_id": commit.commit_id,
                }
                if rebased_from is not None:
                    entry["committed_change_set_id"] = committed_id
                    entry["rebased_from"] = rebased_from
                results.append(entry)
            except Exception as error:
                results.append(
                    {
                        "change_set_id": change_set_id,
                        "status": "error",
                        "error": str(error),
                    }
                )
        record = {
            "batch_id": effective_id,
            "decided_by": decided_by,
            "role": role,
            "reason": reason,
            "change_set_ids": change_set_ids,
            "results": results,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        path = self.batches_dir / f"{effective_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
        return {"batch_id": effective_id, "results": results, "audit_path": str(path)}
