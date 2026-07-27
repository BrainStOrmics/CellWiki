# =============================================================================
# 统一运行查询服务 —— 跨 Agent 和 Ingest 的运行记录查询
# =============================================================================
# 提供统一的查询接口，使用户能够在单一视图中查看 Agent 运行和
# Ingest 任务，支持按时间、状态和类型筛选。
# =============================================================================

"""Unified run query service for cross-system run visibility.

Provides a unified query interface that allows users to view both Agent runs
and Ingest tasks in a single view, with filtering by time, status, and type.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from cellwiki.services.runtime_store import RuntimeStore
from cellwiki.services.tasks import TaskEventRepository


RunType = Literal["agent", "ingest"]


class UnifiedRunSummary(BaseModel):
    """Unified summary of a run, whether Agent or Ingest."""
    run_id: str
    run_type: RunType
    status: str
    started_at: str
    updated_at: str
    summary: str
    metadata: dict[str, Any] = {}


class UnifiedRunQueryService:
    """Query service that unifies Agent runs and Ingest tasks."""
    
    def __init__(self, project_root: Path):
        self.project_root = Path(project_root)
        self.runtime_store = RuntimeStore(self.project_root)
        self.task_repository = TaskEventRepository(self.project_root)
    
    def list_runs(
        self,
        *,
        run_type: RunType | None = None,
        limit: int = 100,
    ) -> list[UnifiedRunSummary]:
        """List runs from both Agent and Ingest systems.
        
        Args:
            run_type: Filter by run type ("agent" or "ingest"), or None for both
            limit: Maximum number of runs to return
        
        Returns:
            List of unified run summaries, sorted by updated_at descending
        """
        runs: list[UnifiedRunSummary] = []
        
        # Query Agent runs
        if run_type is None or run_type == "agent":
            agent_runs = self.runtime_store.list_runs(limit=limit)
            for run in agent_runs:
                runs.append(
                    UnifiedRunSummary(
                        run_id=run.run_id,
                        run_type="agent",
                        status=run.status.value,
                        started_at=run.created_at.isoformat(),
                        updated_at=run.updated_at.isoformat(),
                        summary=f"Agent run: {run.input_message[:50]}..." if len(run.input_message) > 50 else f"Agent run: {run.input_message}",
                        metadata={
                            "thread_id": run.thread_id,
                            "project_id": run.project_id,
                            "retry_count": run.retry_count,
                        },
                    )
                )
        
        # Query Ingest tasks
        if run_type is None or run_type == "ingest":
            task_runs = self.task_repository.list_runs()
            for task in task_runs[:limit]:
                runs.append(
                    UnifiedRunSummary(
                        run_id=task["run_id"],
                        run_type="ingest",
                        status=task["status"],
                        started_at=task["started_at"],
                        updated_at=task["updated_at"],
                        summary=f"Ingest task: {task['message']}",
                        metadata={
                            "source_id": task["source_id"],
                            "stage": task["stage"],
                            "progress": task["progress"],
                            "event_count": task["event_count"],
                        },
                    )
                )
        
        # Sort by updated_at descending
        runs.sort(key=lambda r: r.updated_at, reverse=True)
        
        return runs[:limit]
    
    def get_run_details(self, run_id: str) -> dict[str, Any] | None:
        """Get detailed information about a specific run.
        
        Args:
            run_id: The run identifier
        
        Returns:
            Detailed run information, or None if not found
        """
        # Try Agent run first
        try:
            agent_run = self.runtime_store.get_run(run_id)
            events = self.runtime_store.list_events(run_id)
            return {
                "run_type": "agent",
                "run": agent_run.model_dump(mode="json"),
                "events": [event.model_dump(mode="json") for event in events],
            }
        except KeyError:
            pass
        
        # Try Ingest task
        events = self.task_repository.list_events(run_id)
        if events:
            return {
                "run_type": "ingest",
                "events": [event.model_dump(mode="json") for event in events],
            }
        
        return None
