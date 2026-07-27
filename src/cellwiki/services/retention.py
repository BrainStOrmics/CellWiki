# =============================================================================
# 数据保留服务 —— 自动清理旧的日志和运行记录
# =============================================================================
# 提供可配置的数据保留策略，自动清理过期的错误报告、运行事件和
# 临时文件，防止磁盘空间无限增长。
# =============================================================================

"""Data retention service for automatic cleanup of old logs and run records.

Provides configurable retention policies that automatically clean up expired
error reports, run events, and temporary files to prevent unbounded disk growth.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class RetentionPolicy(BaseModel):
    """Configuration for data retention policies."""
    
    # Error reports retention
    error_reports_max_age_days: int = Field(default=30, ge=1, le=365)
    error_reports_max_count: int = Field(default=1000, ge=100, le=10000)
    
    # Ingest task events retention
    task_events_max_age_days: int = Field(default=90, ge=7, le=365)
    
    # Temporary files cleanup
    temp_files_max_age_hours: int = Field(default=24, ge=1, le=168)
    
    # Enable/disable automatic cleanup
    auto_cleanup_enabled: bool = True


class RetentionService:
    """Service that enforces data retention policies."""
    
    def __init__(self, project_root: Path, policy: RetentionPolicy | None = None):
        self.project_root = Path(project_root)
        self.policy = policy or RetentionPolicy()
    
    def cleanup_all(self) -> dict[str, int]:
        """Run all cleanup tasks and return counts of deleted items.
        
        Returns:
            Dictionary with counts of deleted items by category
        """
        if not self.policy.auto_cleanup_enabled:
            logger.info("Automatic cleanup is disabled")
            return {}
        
        results = {
            "error_reports": self.cleanup_error_reports(),
            "task_events": self.cleanup_task_events(),
            "temp_files": self.cleanup_temp_files(),
        }
        
        total = sum(results.values())
        if total > 0:
            logger.info(f"Retention cleanup completed: {results}")
        
        return results
    
    def cleanup_error_reports(self) -> int:
        """Clean up old error reports based on age and count limits.
        
        Returns:
            Number of error reports deleted
        """
        errors_dir = self.project_root / "data" / "runtime" / "errors"
        if not errors_dir.exists():
            return 0
        
        error_files = sorted(errors_dir.glob("*.json"), key=lambda p: p.stat().st_mtime)
        deleted = 0
        
        # Delete by age
        cutoff_time = datetime.now(UTC) - timedelta(days=self.policy.error_reports_max_age_days)
        for error_file in error_files:
            mtime = datetime.fromtimestamp(error_file.stat().st_mtime, UTC)
            if mtime < cutoff_time:
                error_file.unlink()
                deleted += 1
        
        # Delete by count (keep most recent)
        remaining_files = sorted(errors_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if len(remaining_files) > self.policy.error_reports_max_count:
            for old_file in remaining_files[self.policy.error_reports_max_count:]:
                old_file.unlink()
                deleted += 1
        
        return deleted
    
    def cleanup_task_events(self) -> int:
        """Clean up old Ingest task events based on age.
        
        Returns:
            Number of task event files deleted
        """
        tasks_dir = self.project_root / "data" / "runtime" / "tasks"
        if not tasks_dir.exists():
            return 0
        
        deleted = 0
        cutoff_time = datetime.now(UTC) - timedelta(days=self.policy.task_events_max_age_days)
        
        # Iterate through task run directories
        for run_dir in tasks_dir.iterdir():
            if not run_dir.is_dir():
                continue
            
            # Check if all events in this run are old
            event_files = list(run_dir.glob("evt_*.json"))
            if not event_files:
                # Empty directory, remove it
                run_dir.rmdir()
                continue
            
            # Get the most recent event time
            latest_mtime = max(f.stat().st_mtime for f in event_files)
            latest_time = datetime.fromtimestamp(latest_mtime, UTC)
            
            # If the entire run is old, delete it
            if latest_time < cutoff_time:
                for event_file in event_files:
                    event_file.unlink()
                    deleted += 1
                run_dir.rmdir()
        
        return deleted
    
    def cleanup_temp_files(self) -> int:
        """Clean up temporary files (.tmp) from runtime and cache directories.
        
        Returns:
            Number of temporary files deleted
        """
        deleted = 0
        cutoff_time = datetime.now(UTC) - timedelta(hours=self.policy.temp_files_max_age_hours)
        
        # Clean from runtime and cache directories
        for subdir in ["runtime", "cache"]:
            target_dir = self.project_root / "data" / subdir
            if not target_dir.exists():
                continue
            
            for tmp_file in target_dir.rglob("*.tmp"):
                mtime = datetime.fromtimestamp(tmp_file.stat().st_mtime, UTC)
                if mtime < cutoff_time:
                    tmp_file.unlink()
                    deleted += 1
        
        return deleted
    
    def get_storage_stats(self) -> dict[str, Any]:
        """Get storage statistics for monitored directories.
        
        Returns:
            Dictionary with storage statistics
        """
        stats = {}
        
        # Error reports
        errors_dir = self.project_root / "data" / "runtime" / "errors"
        if errors_dir.exists():
            error_files = list(errors_dir.glob("*.json"))
            stats["error_reports"] = {
                "count": len(error_files),
                "total_size_mb": sum(f.stat().st_size for f in error_files) / (1024 * 1024),
            }
        
        # Task events
        tasks_dir = self.project_root / "data" / "runtime" / "tasks"
        if tasks_dir.exists():
            task_files = list(tasks_dir.rglob("evt_*.json"))
            stats["task_events"] = {
                "count": len(task_files),
                "total_size_mb": sum(f.stat().st_size for f in task_files) / (1024 * 1024),
            }
        
        # Runtime database
        runtime_db = self.project_root / "data" / "runtime" / "cellwiki.db"
        if runtime_db.exists():
            stats["runtime_database"] = {
                "size_mb": runtime_db.stat().st_size / (1024 * 1024),
            }
        
        return stats
