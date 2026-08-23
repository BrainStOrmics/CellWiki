# =============================================================================
# 产品安全测试 —— 验证打包模式下的 API 认证机制
# =============================================================================
# 打包模式使用随机 token 保护所有非零安全级别的本地变更端点；
# 开发模式（空 token）保持本地变更兼容。记忆端点已随旧架构移除，
# 这里用保留的设置端点验证同样的认证规则。
# =============================================================================

"""Packaged-mode Product API rejects unauthenticated local mutation requests."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from cellwiki.api.app import create_app

_SETTINGS_PAYLOAD = {
    "openai_base_url": "http://127.0.0.1:1",
    "openai_model": "test-model",
    "openai_api_protocol": "chat_completions",
    "openai_api_key": None,
    "clear_openai_api_key": False,
}


def test_desktop_token_protects_all_mutating_routes(tmp_path: Path):
    client = TestClient(create_app(tmp_path, local_token="launch-secret"))

    assert client.get("/health").status_code == 200
    unauthorized = client.post("/api/settings", json=_SETTINGS_PAYLOAD)
    authorized = client.post(
        "/api/settings",
        json=_SETTINGS_PAYLOAD,
        headers={"Authorization": "Bearer launch-secret"},
    )

    assert unauthorized.status_code == 401
    assert authorized.status_code == 200
    assert authorized.json()["openai_model"] == "test-model"


def test_development_mode_keeps_local_mutation_compatible(tmp_path: Path):
    client = TestClient(create_app(tmp_path, local_token=""))
    response = client.post("/api/settings", json=_SETTINGS_PAYLOAD)
    assert response.status_code == 200


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