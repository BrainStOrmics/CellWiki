# =============================================================================
# 数据保留测试 —— 验证自动清理和存储统计功能
# =============================================================================

"""Tests for data retention service and cleanup functionality."""

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cellwiki.api.app import create_app
from cellwiki.services.retention import RetentionPolicy, RetentionService


@pytest.fixture
def project_with_old_data(tmp_path: Path) -> Path:
    """Create a project with old error reports and task events."""
    # Create old error reports
    errors_dir = tmp_path / "data" / "runtime" / "errors"
    errors_dir.mkdir(parents=True)
    
    old_time = datetime.now(UTC) - timedelta(days=100)  # Older than 90-day retention
    for i in range(5):
        error_file = errors_dir / f"old_error_{i}.json"
        error_file.write_text(json.dumps({"error_id": f"err_{i}"}), encoding="utf-8")
        # Set old modification time
        old_timestamp = old_time.timestamp()
        error_file.touch()
        os.utime(error_file, (old_timestamp, old_timestamp))
    
    # Create recent error reports
    for i in range(3):
        error_file = errors_dir / f"recent_error_{i}.json"
        error_file.write_text(json.dumps({"error_id": f"err_recent_{i}"}), encoding="utf-8")
    
    # Create old task events
    tasks_dir = tmp_path / "data" / "runtime" / "tasks"
    old_run_dir = tasks_dir / "run_old"
    old_run_dir.mkdir(parents=True)
    
    old_event = old_run_dir / "evt_old.json"
    old_event.write_text(json.dumps({"event_id": "evt_old"}), encoding="utf-8")
    old_timestamp = old_time.timestamp()
    old_event.touch()
    os.utime(old_event, (old_timestamp, old_timestamp))
    
    # Create recent task events
    recent_run_dir = tasks_dir / "run_recent"
    recent_run_dir.mkdir(parents=True)
    recent_event = recent_run_dir / "evt_recent.json"
    recent_event.write_text(json.dumps({"event_id": "evt_recent"}), encoding="utf-8")
    
    # Create old temp files
    runtime_dir = tmp_path / "data" / "runtime"
    old_tmp = runtime_dir / "old_temp.tmp"
    old_tmp.write_text("temp data", encoding="utf-8")
    old_tmp.touch()
    os.utime(old_tmp, (old_timestamp, old_timestamp))
    
    return tmp_path


def test_retention_service_cleans_old_error_reports(project_with_old_data: Path):
    """Verify that retention service deletes old error reports."""
    service = RetentionService(project_with_old_data)
    
    deleted = service.cleanup_error_reports()
    
    # Should delete 5 old error reports
    assert deleted == 5
    
    # Recent errors should remain
    errors_dir = project_with_old_data / "data" / "runtime" / "errors"
    remaining = list(errors_dir.glob("*.json"))
    assert len(remaining) == 3
    assert all("recent" in f.name for f in remaining)


def test_retention_service_cleans_old_task_events(project_with_old_data: Path):
    """Verify that retention service deletes old task events."""
    service = RetentionService(project_with_old_data)
    
    deleted = service.cleanup_task_events()
    
    # Should delete 1 old event file
    assert deleted == 1
    
    # Old run directory should be removed
    tasks_dir = project_with_old_data / "data" / "runtime" / "tasks"
    assert not (tasks_dir / "run_old").exists()
    
    # Recent run should remain
    assert (tasks_dir / "run_recent").exists()


def test_retention_service_cleans_old_temp_files(project_with_old_data: Path):
    """Verify that retention service deletes old temporary files."""
    service = RetentionService(project_with_old_data)
    
    deleted = service.cleanup_temp_files()
    
    # Should delete 1 old temp file
    assert deleted == 1
    
    # Temp file should be gone
    runtime_dir = project_with_old_data / "data" / "runtime"
    assert not (runtime_dir / "old_temp.tmp").exists()


def test_retention_service_cleanup_all(project_with_old_data: Path):
    """Verify that cleanup_all runs all cleanup tasks."""
    service = RetentionService(project_with_old_data)
    
    results = service.cleanup_all()
    
    assert results["error_reports"] == 5
    assert results["task_events"] == 1
    assert results["temp_files"] == 1


def test_retention_service_respects_disabled_policy(project_with_old_data: Path):
    """Verify that cleanup is skipped when auto_cleanup_enabled is False."""
    policy = RetentionPolicy(auto_cleanup_enabled=False)
    service = RetentionService(project_with_old_data, policy=policy)
    
    results = service.cleanup_all()
    
    # Should return empty dict when disabled
    assert results == {}
    
    # Old files should still exist
    errors_dir = project_with_old_data / "data" / "runtime" / "errors"
    assert len(list(errors_dir.glob("*.json"))) == 8


def test_retention_service_gets_storage_stats(project_with_old_data: Path):
    """Verify that storage statistics are calculated correctly."""
    service = RetentionService(project_with_old_data)
    
    stats = service.get_storage_stats()
    
    assert "error_reports" in stats
    assert stats["error_reports"]["count"] == 8
    assert stats["error_reports"]["total_size_mb"] > 0
    
    assert "task_events" in stats
    assert stats["task_events"]["count"] == 2


def test_retention_api_cleanup_endpoint(project_with_old_data: Path):
    """Verify that POST /api/retention/cleanup triggers cleanup."""
    app = create_app(project_with_old_data, local_token="test-token")
    client = TestClient(app)
    
    response = client.post(
        "/api/retention/cleanup",
        headers={"Authorization": "Bearer test-token"},
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"
    assert data["total_deleted"] == 7  # 5 errors + 1 task + 1 temp


def test_retention_api_stats_endpoint(project_with_old_data: Path):
    """Verify that GET /api/retention/stats returns storage statistics."""
    app = create_app(project_with_old_data, local_token="test-token")
    client = TestClient(app)
    
    response = client.get(
        "/api/retention/stats",
        headers={"Authorization": "Bearer test-token"},
    )
    
    assert response.status_code == 200
    data = response.json()
    assert "storage" in data
    assert "policy" in data
    assert "error_reports" in data["storage"]


def test_retention_api_policy_endpoint(project_with_old_data: Path):
    """Verify that GET /api/retention/policy returns policy configuration."""
    app = create_app(project_with_old_data, local_token="test-token")
    client = TestClient(app)
    
    response = client.get(
        "/api/retention/policy",
        headers={"Authorization": "Bearer test-token"},
    )
    
    assert response.status_code == 200
    policy = response.json()
    assert policy["error_reports_max_age_days"] == 30
    assert policy["auto_cleanup_enabled"] is True
