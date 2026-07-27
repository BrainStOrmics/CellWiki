# =============================================================================
# 产品安全测试 —— 验证打包模式下的 API 认证机制
# =============================================================================

"""Packaged-mode Product API rejects unauthenticated local mutation requests."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from cellwiki.api.app import create_app


def test_desktop_token_protects_all_mutating_routes(tmp_path: Path):
    client = TestClient(create_app(tmp_path, local_token="launch-secret"))
    payload = {
        "candidate_id": "candidate_api",
        "project_id": "cellwiki",
        "kind": "stable",
        "content": "Use claim-level evidence.",
    }

    assert client.get("/health").status_code == 200
    unauthorized = client.post("/api/memories", json=payload)
    authorized = client.post(
        "/api/memories",
        json=payload,
        headers={"Authorization": "Bearer launch-secret"},
    )

    assert unauthorized.status_code == 401
    assert authorized.status_code == 201
    assert authorized.json()["project_id"] == "cellwiki"


def test_development_mode_keeps_local_mutation_compatible(tmp_path: Path):
    client = TestClient(create_app(tmp_path, local_token=""))
    response = client.post(
        "/api/memories",
        json={
            "candidate_id": "candidate_dev",
            "project_id": "cellwiki",
            "kind": "episode",
            "content": "Development run completed.",
        },
    )
    assert response.status_code == 201


def test_cors_allows_dynamic_loopback_dev_ports_but_not_remote_origins(tmp_path: Path):
    client = TestClient(create_app(tmp_path, local_token=""))

    loopback = client.get(
        "/health",
        headers={"Origin": "http://127.0.0.1:15174"},
    )
    localhost = client.get(
        "/health",
        headers={"Origin": "http://localhost:43123"},
    )
    remote = client.get(
        "/health",
        headers={"Origin": "http://192.168.1.20:15174"},
    )

    assert loopback.headers["access-control-allow-origin"] == "http://127.0.0.1:15174"
    assert localhost.headers["access-control-allow-origin"] == "http://localhost:43123"
    assert "access-control-allow-origin" not in remote.headers
