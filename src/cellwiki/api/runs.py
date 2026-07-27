# =============================================================================
# 统一运行查询 API —— 跨系统的运行记录查询端点
# =============================================================================
# 提供 GET /api/runs 端点，返回 Agent 和 Ingest 运行的统一视图，
# 支持按类型筛选和分页。
# =============================================================================

"""Unified runs API for cross-system run visibility.

Provides GET /api/runs endpoint that returns a unified view of both Agent
and Ingest runs, with filtering by type and pagination.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status

from cellwiki.services.run_query import UnifiedRunQueryService, UnifiedRunSummary


def create_runs_router(project_root: Path) -> APIRouter:
    """Create unified runs router with proper project root binding."""
    router = APIRouter(prefix="/api/runs", tags=["runs"])
    query_service = UnifiedRunQueryService(project_root)
    
    @router.get("", response_model=list[UnifiedRunSummary])
    def list_runs(
        run_type: str | None = Query(None, pattern="^(agent|ingest)$"),
        limit: int = Query(100, ge=1, le=500),
    ) -> list[UnifiedRunSummary]:
        """List runs from both Agent and Ingest systems.
        
        Args:
            run_type: Filter by run type ("agent" or "ingest"), or omit for both
            limit: Maximum number of runs to return (1-500, default 100)
        
        Returns:
            List of unified run summaries, sorted by updated_at descending
        """
        return query_service.list_runs(run_type=run_type, limit=limit)
    
    @router.get("/{run_id}")
    def get_run_details(run_id: str) -> dict[str, Any]:
        """Get detailed information about a specific run.
        
        Args:
            run_id: The run identifier
        
        Returns:
            Detailed run information including events
        
        Raises:
            404: If run not found
        """
        details = query_service.get_run_details(run_id)
        if details is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Run {run_id} not found",
            )
        return details
    
    return router
