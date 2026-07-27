# =============================================================================
# 任务服务 —— 用户可见的导入任务事件的追加式持久化
# =============================================================================

"""Append-only persistence for user-visible ingest task events."""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any

from cellwiki.domain.contracts import IngestStage, TaskEvent, TaskStatus


# 运行 ID 的正则验证：字母数字开头，最长 128 字符
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


# ---------------------------------------------------------------------------
# TaskEventRepository —— 任务事件仓库
# 用户可见的导入任务事件的追加式持久化存储。
# 每个事件独立持久化，即使应用重启，已完成运行的记录也不会丢失。
# 存储结构：data/runtime/tasks/<run_id>/evt_<uuid>.json
# 写入使用原子操作，对完全相同的事件重试幂等。
# ---------------------------------------------------------------------------
class TaskEventRepository:
    """Persist each event independently so completed runs survive app restarts."""

    def __init__(self, project_root: Path):
        self.directory = Path(project_root) / "data" / "runtime" / "tasks"

    # 追加一条事件记录，对完全相同的重试保持幂等
    def record(
        self,
        *,
        run_id: str,
        source_id: str,
        stage: IngestStage,
        status: TaskStatus,
        message: str,
        progress: int,
        change_set_id: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> TaskEvent:
        """Append one event, while keeping exact retries idempotent for the UI."""
        events = self.list_events(run_id)
        normalized_detail = detail or {}
        # 幂等性检查：如果最后一条事件与当前完全相同，直接返回
        if events:
            latest = events[-1]
            if (
                latest.source_id == source_id
                and latest.stage == stage
                and latest.status == status
                and latest.message == message
                and latest.progress == progress
                and latest.change_set_id == change_set_id
                and latest.detail == normalized_detail
            ):
                return latest

        # 创建新事件
        event = TaskEvent(
            event_id=f"evt_{uuid.uuid4().hex}",
            run_id=run_id,
            source_id=source_id,
            stage=stage,
            status=status,
            message=message,
            progress=progress,
            change_set_id=change_set_id,
            detail=normalized_detail,
        )
        # 原子写入
        run_directory = self._run_directory(run_id)
        run_directory.mkdir(parents=True, exist_ok=True)
        path = run_directory / f"{event.event_id}.json"
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(event.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(path)
        return event

    # 获取指定运行的确定性时间线（按创建时间排序）
    def list_events(self, run_id: str) -> list[TaskEvent]:
        """Return a deterministic timeline for one run."""
        run_directory = self._run_directory(run_id)
        if not run_directory.exists():
            return []
        events = [
            TaskEvent.model_validate_json(path.read_text(encoding="utf-8"))
            for path in run_directory.glob("evt_*.json")
        ]
        return sorted(events, key=lambda event: (event.created_at, event.event_id))

    # 从不可变事件账本构建轻量级运行摘要
    def list_runs(self, source_id: str | None = None) -> list[dict[str, Any]]:
        """Build lightweight run summaries from the immutable event ledger."""
        if not self.directory.exists():
            return []
        summaries: list[dict[str, Any]] = []
        for run_directory in self.directory.iterdir():
            if not run_directory.is_dir() or not _RUN_ID.fullmatch(run_directory.name):
                continue
            events = self.list_events(run_directory.name)
            if not events or (source_id is not None and events[-1].source_id != source_id):
                continue
            first, latest = events[0], events[-1]
            summaries.append(
                {
                    "run_id": latest.run_id,
                    "source_id": latest.source_id,
                    "status": latest.status.value,
                    "stage": latest.stage.value,
                    "progress": latest.progress,
                    "message": latest.message,
                    "change_set_id": latest.change_set_id,
                    "event_count": len(events),
                    "started_at": first.created_at.isoformat(),
                    "updated_at": latest.created_at.isoformat(),
                }
            )
        # 按更新时间倒序排列
        return sorted(summaries, key=lambda item: item["updated_at"], reverse=True)

    # 生成运行目录路径，验证 run_id 格式防止路径遍历
    def _run_directory(self, run_id: str) -> Path:
        if not _RUN_ID.fullmatch(run_id):
            raise ValueError("run_id must be a domain identifier, not a file path")
        return self.directory / run_id
