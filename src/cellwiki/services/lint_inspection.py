"""Bounded Lint inspection backed by a complete persisted audit artifact."""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

from cellwiki.domain.contracts import PipelineTaskType
from cellwiki.domain.linting import (
    LintFindingSummary,
    LintInspectionResult,
    LintLevel,
    LintSeverity,
)
from cellwiki.domain.tasks import LintTask, PageLintScope
from cellwiki.services.pipeline import KnowledgePipelineHarness
from cellwiki.services.quality import inspect_projection


class LintInspection:
    """Keep whole-project audit detail behind a compact task Interface."""

    MAX_RESULT_BYTES = 16 * 1024

    def __init__(self, project_root: Path):
        self.project_root = Path(project_root).resolve()
        self.pipeline = KnowledgePipelineHarness(self.project_root)

    def inspect(self, task: LintTask, *, run_id: str) -> LintInspectionResult:
        if task.action != "inspect":
            raise ValueError("LintInspection accepts inspect tasks only")

        with self.pipeline.acquire(task_type=PipelineTaskType.LINT, run_id=run_id) as lease:
            report = inspect_projection(self.project_root)
            artifact_ref, artifact_sha256, artifact_size = self._persist_artifact(
                run_id=run_id,
                snapshot=lease.snapshot.model_dump(mode="json"),
                report=report,
                scope=task.scope.model_dump(mode="json"),
            )

            scoped = self._scoped_findings(report["issues"], task.scope)
            summaries = [self._summary(item) for item in scoped]
            start = self._cursor_start(summaries, task.cursor)
            candidates = summaries[start : start + task.limit]
            bounded = self._fit_result(
                candidates,
                snapshot_id=lease.snapshot.snapshot_id,
                knowledge_version=lease.snapshot.knowledge_version,
                scope=task.scope.model_dump(mode="json"),
                report=report,
                scoped_count=len(scoped),
                next_cursor=(
                    candidates[-1].finding_id
                    if candidates and start + len(candidates) < len(summaries)
                    else None
                ),
                artifact_ref=artifact_ref,
                artifact_sha256=artifact_sha256,
                artifact_size=artifact_size,
            )
            return bounded

    @staticmethod
    def _scoped_findings(issues: list[dict], scope) -> list[dict]:
        if isinstance(scope, PageLintScope):
            return [
                issue
                for issue in issues
                if issue.get("target_id") == scope.page_id or issue.get("page_id") == scope.page_id
            ]
        return list(issues)

    @staticmethod
    def _summary(issue: dict) -> LintFindingSummary:
        message = str(issue.get("message") or issue.get("detail") or "")
        if len(message) > 500:
            message = f"{message[:497]}..."
        return LintFindingSummary(
            finding_id=str(issue["finding_id"]),
            level=LintLevel(str(issue["level"])),
            severity=LintSeverity(str(issue["severity"])),
            category=str(issue.get("category", "unknown")),
            target_id=str(issue.get("target_id") or issue.get("page_id") or ""),
            locator=str(issue.get("locator", "")),
            message=message,
            blocking=bool(issue.get("blocking", False)),
            auto_fixable=bool(issue.get("auto_fixable", False)),
        )

    @staticmethod
    def _cursor_start(findings: list[LintFindingSummary], cursor: str | None) -> int:
        if not cursor:
            return 0
        for index, finding in enumerate(findings):
            if finding.finding_id == cursor:
                return index + 1
        raise ValueError("Lint cursor is no longer present in the current report")

    def _fit_result(
        self,
        findings: list[LintFindingSummary],
        *,
        snapshot_id: str,
        knowledge_version: str,
        scope: dict[str, str],
        report: dict,
        scoped_count: int,
        next_cursor: str | None,
        artifact_ref: str,
        artifact_sha256: str,
        artifact_size: int,
    ) -> LintInspectionResult:
        selected = list(findings)
        while True:
            effective_cursor = next_cursor if len(selected) == len(findings) else (
                selected[-1].finding_id if selected else next_cursor
            )
            result = LintInspectionResult(
                snapshot_id=snapshot_id,
                knowledge_version=knowledge_version,
                scope=scope,
                summary={
                    "status": str(report.get("status", "unknown")),
                    "page_count": int(report.get("page_count", 0)),
                    "issue_count": int(report.get("issue_count", 0)),
                    "scoped_issue_count": scoped_count,
                    "error_count": int(report.get("error_count", 0)),
                    "warning_count": int(report.get("warning_count", 0)),
                    "auto_fixable_count": sum(
                        bool(item.get("auto_fixable")) for item in report.get("issues", [])
                    ),
                },
                findings=selected,
                next_cursor=effective_cursor,
                full_report_ref=artifact_ref,
                full_report_sha256=artifact_sha256,
                full_report_size=artifact_size,
            )
            size = len(
                json.dumps(result.model_dump(mode="json"), ensure_ascii=False).encode("utf-8")
            )
            if size <= self.MAX_RESULT_BYTES:
                return result
            if not selected:
                raise RuntimeError("Lint result metadata exceeds the desktop payload limit")
            selected.pop()

    def _persist_artifact(
        self,
        *,
        run_id: str,
        snapshot: dict,
        report: dict,
        scope: dict[str, str],
    ) -> tuple[str, str, int]:
        relative = Path("data") / "runtime" / "agent_artifacts" / run_id / "lint-report.json"
        path = self.project_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "run_id": run_id,
            "scope": scope,
            "snapshot": snapshot,
            "report": report,
        }
        content = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_bytes(content)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
        return relative.as_posix(), hashlib.sha256(content).hexdigest(), len(content)


__all__ = ["LintInspection"]
