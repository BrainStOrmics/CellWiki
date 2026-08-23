# =============================================================================
# 数据保留管理 API —— 清理和存储统计端点
# =============================================================================
# 提供 POST /api/retention/cleanup 端点手动触发清理，
# 以及 GET /api/retention/stats 端点查看存储统计信息。
# =============================================================================

"""Retention management API for cleanup and storage statistics.

Provides POST /api/retention/cleanup endpoint to manually trigger cleanup,
and GET /api/retention/stats endpoint to view storage statistics.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, status

from cellwiki.services.retention import RetentionService


def create_retention_router(project_root: Path) -> APIRouter:
    """Create retention management router with proper project root binding."""
    router = APIRouter(prefix="/api/retention", tags=["retention"])
    
    @router.post("/cleanup", status_code=status.HTTP_200_OK)
    def trigger_cleanup() -> dict[str, Any]:
        """Manually trigger data retention cleanup.
        
        Returns:
            Dictionary with counts of deleted items by category
        """
        service = RetentionService(project_root)
        results = service.cleanup_all()
        return {
            "status": "completed",
            "deleted": results,
            "total_deleted": sum(results.values()),
        }
    
    @router.get("/stats")
    def get_storage_stats() -> dict[str, Any]:
        """Get storage statistics for monitored directories.
        
        Returns:
            Dictionary with storage statistics
        """
        service = RetentionService(project_root)
        stats = service.get_storage_stats()
        return {
            "storage": stats,
            "policy": service.policy.model_dump(),
        }
    
    @router.get("/policy")
    def get_retention_policy() -> dict[str, Any]:
        """Get the current retention policy configuration.
        
        Returns:
            Current retention policy settings
        """
        service = RetentionService(project_root)
        return service.policy.model_dump()
    
    return router
