# =============================================================================
# 统一运行查询测试 —— 验证跨系统运行记录查询
# =============================================================================

"""Tests for unified run query service and API."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cellwiki.api.app import create_app
from cellwiki.domain.runs import AgentRun, AgentRunStatus
from cellwiki.services.runtime_store import RuntimeStore
from cellwiki.services.run_query import UnifiedRunQueryService
from cellwiki.services.tasks import TaskEventRepository
from cellwiki.domain.contracts import IngestStage, TaskStatus


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    """Create a temporary project root with test data."""
    # Create Agent run
    runtime_store = RuntimeStore(tmp_path)
    agent_run = AgentRun(
        run_id="run_agent_test",
        thread_id="thread_test",
        input_message="Test agent query",
        status=AgentRunStatus.SUCCEEDED,
    )
    runtime_store.create_run(agent_run)
    
    # Create Ingest task
    task_repo = TaskEventRepository(tmp_path)
    task_repo.record(
        run_id="run_ingest_test",
        source_id="source_test",
        stage=IngestStage.SOURCE_READ,
        status=TaskStatus.RUNNING,
        message="Reading source",
        progress=10,
    )
    
    return tmp_path


def test_unified_query_lists_both_agent_and_ingest_runs(project_root: Path):
    """Verify that unified query returns both Agent and Ingest runs."""
    service = UnifiedRunQueryService(project_root)
    runs = service.list_runs()
    
    assert len(runs) == 2
    
    run_types = {run.run_type for run in runs}
    assert run_types == {"agent", "ingest"}
    
    run_ids = {run.run_id for run in runs}
    assert run_ids == {"run_agent_test", "run_ingest_test"}


def test_unified_query_filters_by_type(project_root: Path):
    """Verify that unified query can filter by run type."""
    service = UnifiedRunQueryService(project_root)
    
    # Filter for Agent runs only
    agent_runs = service.list_runs(run_type="agent")
    assert len(agent_runs) == 1
    assert agent_runs[0].run_type == "agent"
    assert agent_runs[0].run_id == "run_agent_test"
    
    # Filter for Ingest runs only
    ingest_runs = service.list_runs(run_type="ingest")
    assert len(ingest_runs) == 1
    assert ingest_runs[0].run_type == "ingest"
    assert ingest_runs[0].run_id == "run_ingest_test"


def test_unified_query_gets_run_details(project_root: Path):
    """Verify that unified query can get detailed run information."""
    service = UnifiedRunQueryService(project_root)
    
    # Get Agent run details
    agent_details = service.get_run_details("run_agent_test")
    assert agent_details is not None
    assert agent_details["run_type"] == "agent"
    assert "run" in agent_details
    assert "events" in agent_details
    
    # Get Ingest run details
    ingest_details = service.get_run_details("run_ingest_test")
    assert ingest_details is not None
    assert ingest_details["run_type"] == "ingest"
    assert "events" in ingest_details
    
    # Non-existent run
    missing = service.get_run_details("run_nonexistent")
    assert missing is None


def test_unified_runs_api_endpoint(project_root: Path):
    """Verify that GET /api/runs returns unified run list."""
    app = create_app(project_root, local_token="test-token")
    client = TestClient(app)
    
    response = client.get(
        "/api/runs",
        headers={"Authorization": "Bearer test-token"},
    )
    
    assert response.status_code == 200
    runs = response.json()
    assert len(runs) == 2
    
    run_types = {run["run_type"] for run in runs}
    assert run_types == {"agent", "ingest"}


def test_unified_runs_api_filters_by_type(project_root: Path):
    """Verify that GET /api/runs?run_type=agent filters correctly."""
    app = create_app(project_root, local_token="test-token")
    client = TestClient(app)
    
    response = client.get(
        "/api/runs?run_type=agent",
        headers={"Authorization": "Bearer test-token"},
    )
    
    assert response.status_code == 200
    runs = response.json()
    assert len(runs) == 1
    assert runs[0]["run_type"] == "agent"


def test_unified_runs_api_gets_details(project_root: Path):
    """Verify that GET /api/runs/{run_id} returns run details."""
    app = create_app(project_root, local_token="test-token")
    client = TestClient(app)
    
    response = client.get(
        "/api/runs/run_agent_test",
        headers={"Authorization": "Bearer test-token"},
    )
    
    assert response.status_code == 200
    details = response.json()
    assert details["run_type"] == "agent"
    assert "run" in details
    assert "events" in details


def test_unified_runs_api_returns_404_for_missing_run(project_root: Path):
    """Verify that GET /api/runs/{run_id} returns 404 for non-existent run."""
    app = create_app(project_root, local_token="test-token")
    client = TestClient(app)
    
    response = client.get(
        "/api/runs/run_nonexistent",
        headers={"Authorization": "Bearer test-token"},
    )
    
    assert response.status_code == 404
