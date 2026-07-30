# =============================================================================
# Lint 服务 —— 产品接口背后的 Lint 检查和受控修复提案
# =============================================================================

"""Lint inspection and controlled repair proposals behind a small product interface."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from cellwiki.domain.contracts import (
    ChangeOperation,
    ChangeOperationType,
    ChangeSet,
    RiskLevel,
    KnowledgeSnapshot,
    PipelineTaskType,
)
from cellwiki.services.changesets import ChangeSetRepository
from cellwiki.services.pipeline import KnowledgePipelineHarness
from cellwiki.services.quality import inspect_projection


# ---------------------------------------------------------------------------
# LintFixService —— Lint 修复服务
# 将确定性的可自动修复的 lint 发现项转换为可审查的 ChangeSet，
# 但不直接应用它们。生成的 ChangeSet 需要经过审批流程才能生效。
# 支持迭代次数限制，防止同一目标的无限修复循环。
# 使用 lint_fixes 目录中的标记文件追踪迭代次数。
# ---------------------------------------------------------------------------
class LintFixService:
    """Turn deterministic auto-fixable findings into reviewable ChangeSets without applying them."""

    def __init__(self, project_root: Path, *, pipeline: KnowledgePipelineHarness | None = None):
        self.project_root = Path(project_root).resolve()
        self.repository = ChangeSetRepository(self.project_root)
        self.pipeline = pipeline or KnowledgePipelineHarness(self.project_root)

    # 检查投影质量，返回报告
    def inspect(self) -> dict:
        return inspect_projection(self.project_root)

    # 根据指定的 finding_id 列表生成修复 ChangeSet
    def propose(
        self,
        finding_ids: list[str],
        *,
        run_id: str,
        max_iterations: int = 3,
        snapshot_id: str | None = None,
    ) -> ChangeSet:
        with self.pipeline.acquire(task_type=PipelineTaskType.LINT, run_id=run_id) as lease:
            if snapshot_id:
                requested = self.pipeline.get_snapshot(snapshot_id)
                if requested.knowledge_version != lease.snapshot.knowledge_version:
                    raise RuntimeError(
                        "Lint inspection snapshot is stale; inspect again before proposing fixes"
                    )
            return self._propose(
                finding_ids,
                run_id=run_id,
                max_iterations=max_iterations,
                snapshot=lease.snapshot,
            )

    def _propose(
        self,
        finding_ids: list[str],
        *,
        run_id: str,
        max_iterations: int,
        snapshot: KnowledgeSnapshot,
    ) -> ChangeSet:
        if not finding_ids:
            raise ValueError("at least one finding ID is required")
        report = self.inspect()
        # 构建 finding_id -> finding 的映射
        findings = {finding["finding_id"]: finding for finding in report["issues"]}
        selected = []
        # 验证每个 finding 是否可自动修复
        for finding_id in finding_ids:
            finding = findings.get(finding_id)
            if finding is None:
                raise KeyError(f"lint finding is no longer open: {finding_id}")
            if not finding["auto_fixable"] or not finding.get("suggested_operation"):
                raise ValueError(f"lint finding is not auto-fixable: {finding_id}")
            selected.append(finding)

        # 按 target_id 分组，同一目标的多个 finding 合并为一个操作
        operations = []
        findings_by_target: dict[str, list[dict]] = {}
        for finding in selected:
            findings_by_target.setdefault(finding["target_id"], []).append(finding)

        for target_id, target_findings in findings_by_target.items():
            # 检查迭代次数限制
            marker = self.project_root / "data" / "runtime" / "lint_fixes" / f"{target_id}.json"
            iteration = 1
            if marker.exists():
                previous = json.loads(marker.read_text(encoding="utf-8"))
                iteration = int(previous.get("iteration", 0)) + 1
            if iteration > max_iterations:
                raise RuntimeError(
                    f"lint repair for {target_id} exceeded the {max_iterations}-iteration limit"
                )
            # 创建一个操作，包含该目标的所有 finding
            operations.append(
                ChangeOperation(
                    type=ChangeOperationType.APPLY_LINT_FIX,
                    target_id=target_id,
                    # 使用标记文件的哈希作为期望版本，实现乐观锁
                    expected_version=_version(marker),
                    payload={
                        "action": "rebuild_projection",
                        # 同一目标下的多个 finding 通过一次投影重建解决
                        "finding_ids": [finding["finding_id"] for finding in target_findings],
                        "iteration": iteration,
                    },
                )
            )

        # 生成 ChangeSet ID：基于 finding_ids 和 run_id 的哈希
        material = "\0".join(sorted(finding_ids) + [run_id])
        change_set = ChangeSet(
            change_set_id=f"cs_lint_{hashlib.sha256(material.encode('utf-8')).hexdigest()[:20]}",
            run_id=run_id,
            project_id="cellwiki",
            operations=operations,
            risk=RiskLevel.LOW,
            reason=f"Repair {len(selected)} deterministic projection finding(s).",
            snapshot_id=snapshot.snapshot_id,
            base_knowledge_version=snapshot.knowledge_version,
        )
        self.repository.save(change_set)
        return change_set


# 计算文件版本（用于乐观锁）
def _version(path: Path) -> str:
    if not path.exists():
        return "missing"
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"
