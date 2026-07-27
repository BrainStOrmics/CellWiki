# =============================================================================
# 错误报告测试 —— 验证前端错误报告接收和持久化
# =============================================================================

"""Tests for error reporting API and persistence."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cellwiki.api.app import create_app


@pytest.fixture
def client(tmp_path: Path):
    """Create a test client with a temporary project root."""
    app = create_app(tmp_path, local_token="test-token")
    return TestClient(app)


def test_error_reporting_accepts_valid_report(client: TestClient):
    """Verify that POST /api/errors accepts a valid error report."""
    error_report = {
        "timestamp": "2026-07-27T10:00:00Z",
        "errorType": "uncaught",
        "message": "Test error message",
        "stack": "Error: Test error\n    at test.js:1:1",
        "context": {
            "url": "http://localhost:3000/",
            "userAgent": "Test Agent",
            "threadId": "thread_123",
            "runId": "run_456",
            "requestId": "req_789",
            "appVersion": "development",
        },
        "metadata": {"component": "TestComponent"},
    }
    
    response = client.post(
        "/api/errors",
        json=error_report,
        headers={"Authorization": "Bearer test-token"},
    )
    
    assert response.status_code == 201
    data = response.json()
    assert "error_id" in data
    assert data["status"] == "received"
    assert data["error_id"].startswith("err_")


def test_error_reporting_persists_to_disk(client: TestClient, tmp_path: Path):
    """Verify that error reports are persisted to data/runtime/errors/."""
    error_report = {
        "timestamp": "2026-07-27T10:00:00Z",
        "errorType": "api",
        "message": "API error",
        "context": {
            "url": "http://localhost:3000/",
            "userAgent": "Test Agent",
        },
    }
    
    response = client.post(
        "/api/errors",
        json=error_report,
        headers={"Authorization": "Bearer test-token"},
    )
    
    assert response.status_code == 201
    error_id = response.json()["error_id"]
    
    # Verify file was created
    errors_dir = tmp_path / "data" / "runtime" / "errors"
    assert errors_dir.exists()
    
    error_files = list(errors_dir.glob("*.json"))
    assert len(error_files) == 1
    
    # Verify content
    error_data = json.loads(error_files[0].read_text(encoding="utf-8"))
    assert error_data["error_id"] == error_id
    assert error_data["message"] == "API error"
    assert "received_at" in error_data


def test_error_reporting_lists_recent_errors(client: TestClient):
    """Verify that GET /api/errors returns recent error reports."""
    # Submit multiple errors
    for i in range(3):
        error_report = {
            "timestamp": f"2026-07-27T10:0{i}:00Z",
            "errorType": "manual",
            "message": f"Error {i}",
            "context": {
                "url": "http://localhost:3000/",
                "userAgent": "Test Agent",
            },
        }
        client.post(
            "/api/errors",
            json=error_report,
            headers={"Authorization": "Bearer test-token"},
        )
    
    # List errors
    response = client.get(
        "/api/errors",
        headers={"Authorization": "Bearer test-token"},
    )
    
    assert response.status_code == 200
    errors = response.json()
    assert len(errors) == 3
    assert all("error_id" in error for error in errors)


def test_error_reporting_rejects_invalid_error_type(client: TestClient):
    """Verify that invalid errorType is rejected."""
    error_report = {
        "timestamp": "2026-07-27T10:00:00Z",
        "errorType": "invalid_type",
        "message": "Test error",
        "context": {
            "url": "http://localhost:3000/",
            "userAgent": "Test Agent",
        },
    }
    
    response = client.post(
        "/api/errors",
        json=error_report,
        headers={"Authorization": "Bearer test-token"},
    )
    
    assert response.status_code == 422  # Validation error
