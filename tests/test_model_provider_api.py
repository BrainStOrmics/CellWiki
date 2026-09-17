# =============================================================================
# 供应商目录 API 测试 —— 端点契约、脱敏与 run 级模型解析链
# =============================================================================
# 契约重点：
# 1. 任何响应不包含 key 明文（configured + hint 脱敏）。
# 2. 解析链：request.model → 目录默认选择 → legacy .env（run 快照随之）。
# 3. 目录默认已配置但不可用时显式 422，不静默回退 legacy。
# =============================================================================

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cellwiki.api.app import create_app
from cellwiki.config import settings
from cellwiki.domain.runs import AgentEventType
from cellwiki.services.agent_runtime import AgentRuntimeManager, RuntimeSignal


class _EchoAdapter:
    """Minimal protocol adapter: one final response per run."""

    def __init__(self) -> None:
        self.calls = 0

    def execute(self, *, thread_id: str, message, context):
        self.calls += 1
        yield RuntimeSignal(type=AgentEventType.MESSAGE_DELTA, message="ok ")
        yield RuntimeSignal(
            type=AgentEventType.FINAL_RESPONSE,
            message="ok",
            data={"answer": "ok", "file_paths": []},
        )

    def close(self) -> None:
        return None


@pytest.fixture()
def client(tmp_path: Path):
    adapter = _EchoAdapter()
    manager = AgentRuntimeManager(tmp_path, adapter=adapter)
    try:
        with TestClient(create_app(tmp_path, agent_runtime=manager)) as test_client:
            yield test_client
    finally:
        manager.close()


def _create_provider(
    client: TestClient,
    provider_id: str = "gw-a",
    *,
    with_key: bool = True,
    models: list[str] | None = None,
) -> dict:
    response = client.post(
        "/api/model-providers",
        json={
            "provider_id": provider_id,
            "name": f"Gateway {provider_id}",
            "base_url": "https://gw.example.com/v1",
            "protocol": "chat_completions",
            "models": [{"id": model} for model in (models or ["model-a"])],
            "api_key": "sk-live-key-9876" if with_key else None,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


# ---------------------------------------------------------------------------
# CRUD 与脱敏
# ---------------------------------------------------------------------------
def test_provider_crud_roundtrip_and_sanitization(client: TestClient) -> None:
    view = _create_provider(client)
    provider = next(item for item in view["providers"] if item["id"] == "gw-a")
    assert provider["api_key_configured"] is True
    assert provider["api_key_hint"] == "••••9876"
    assert "sk-live-key-9876" not in view.__str__()

    updated = client.put(
        "/api/model-providers/gw-a",
        json={"name": "Renamed", "models": [{"id": "model-b"}]},
    )
    assert updated.status_code == 200
    assert updated.json()["providers"][0]["name"] == "Renamed"
    # 未带 api_key 的更新保留已存密钥。
    assert updated.json()["providers"][0]["api_key_configured"] is True

    default = client.put(
        "/api/model-providers/default-selection",
        json={"provider_id": "gw-a", "model_id": "model-b"},
    )
    assert default.status_code == 200
    assert default.json()["default_selection"] == {
        "provider_id": "gw-a",
        "model_id": "model-b",
    }

    deleted = client.delete("/api/model-providers/gw-a")
    assert deleted.status_code == 200
    assert deleted.json()["providers"] == []
    assert deleted.json()["default_selection"] is None


def test_provider_model_input_window_roundtrip(client: TestClient) -> None:
    created = client.post(
        "/api/model-providers",
        json={
            "provider_id": "gw-window",
            "name": "Gateway Window",
            "models": [
                {"id": "model-a", "max_input_tokens": 131_072},
                {"id": "model-b"},
            ],
        },
    )
    assert created.status_code == 201, created.text
    models = created.json()["providers"][0]["models"]
    assert models[0]["max_input_tokens"] == 131_072
    assert models[1]["max_input_tokens"] is None

    updated = client.put(
        "/api/model-providers/gw-window",
        json={"models": [{"id": "model-a", "max_input_tokens": 65_536}]},
    )
    assert updated.status_code == 200
    assert updated.json()["providers"][0]["models"][0]["max_input_tokens"] == 65_536


def test_provider_validation_and_not_found(client: TestClient) -> None:
    assert client.post(
        "/api/model-providers",
        json={"name": "X", "protocol": "bogus", "models": [{"id": "m"}]},
    ).status_code == 422
    _create_provider(client)
    duplicate = client.post(
        "/api/model-providers",
        json={"provider_id": "gw-a", "name": "Dup", "models": [{"id": "m"}]},
    )
    assert duplicate.status_code == 422
    assert client.put(
        "/api/model-providers/missing", json={"name": "Y"}
    ).status_code == 404
    assert client.delete("/api/model-providers/missing").status_code == 404
    assert client.post("/api/model-providers/missing/test").status_code == 404
    assert client.post("/api/model-providers/missing/fetch-models").status_code == 404


def test_fetch_models_proxies_and_never_returns_key(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _create_provider(client)
    seen: dict[str, str] = {}

    def fake_fetch(base_url: str, api_key: str, **_: object) -> list[str]:
        seen["base_url"] = base_url
        seen["api_key"] = api_key
        return ["model-a", "model-b"]

    import cellwiki.adapters.openai_model as adapter_module

    monkeypatch.setattr(adapter_module, "fetch_provider_models", fake_fetch)
    response = client.post("/api/model-providers/gw-a/fetch-models")
    assert response.status_code == 200
    assert response.json() == {"models": ["model-a", "model-b"]}
    assert seen == {
        "base_url": "https://gw.example.com/v1",
        "api_key": "sk-live-key-9876",
    }


def test_fetch_models_requires_key(client: TestClient) -> None:
    _create_provider(client, with_key=False)
    response = client.post("/api/model-providers/gw-a/fetch-models")
    assert response.status_code == 422
    assert "no API key" in response.json()["detail"]


def test_provider_accepts_anthropic_protocol_and_fetch_passes_it(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = client.post(
        "/api/model-providers",
        json={
            "provider_id": "claude",
            "name": "Claude",
            "base_url": "",
            "protocol": "anthropic",
            "models": [{"id": "claude-sonnet-4-5-20250929"}],
            "api_key": "sk-ant-live-4321",
        },
    )
    assert created.status_code == 201, created.text
    provider = next(p for p in created.json()["providers"] if p["id"] == "claude")
    assert provider["protocol"] == "anthropic"
    assert provider["api_key_hint"] == "••••4321"
    assert "sk-ant-live-4321" not in created.text

    seen: dict[str, object] = {}

    def fake_fetch(base_url: str, api_key: str, **kwargs: object) -> list[str]:
        seen.update({"base_url": base_url, "api_key": api_key}, **kwargs)
        return ["claude-sonnet-4-5-20250929"]

    import cellwiki.adapters.openai_model as adapter_module

    monkeypatch.setattr(adapter_module, "fetch_provider_models", fake_fetch)
    response = client.post("/api/model-providers/claude/fetch-models")
    assert response.status_code == 200, response.text
    assert response.json() == {"models": ["claude-sonnet-4-5-20250929"]}
    # anthropic 允许空 base_url（官方默认端点）；协议透传给适配层。
    assert seen == {
        "base_url": "",
        "api_key": "sk-ant-live-4321",
        "protocol": "anthropic",
    }
    assert "sk-ant-live-4321" not in response.text


def test_provider_test_uses_stored_key(client: TestClient) -> None:
    _create_provider(client)
    response = client.post("/api/model-providers/gw-a/test")
    # 探测目标是不可达网关：返回 ok=False 而非异常，且不泄漏 key。
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert "sk-live-key-9876" not in payload["message"]


# ---------------------------------------------------------------------------
# run 级解析链
# ---------------------------------------------------------------------------
def _start_run(client: TestClient, thread_id: str = "thread_model", **extra: object):
    return client.post(
        "/api/agent/runs", json={"message": "hi", "thread_id": thread_id, **extra}
    )


def _wait_terminal(client: TestClient, run_id: str) -> dict:
    import time

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        detail = client.get(f"/api/agent/runs/{run_id}").json()
        if detail["status"] in {"succeeded", "failed", "cancelled", "unfinished"}:
            return detail
        time.sleep(0.02)
    raise AssertionError(f"run {run_id} did not finish")


def test_run_with_explicit_model_snapshots_selection(client: TestClient) -> None:
    _create_provider(client, models=["model-a", "model-b"])
    started = _start_run(
        client, model={"provider_id": "gw-a", "model_id": "model-b"}
    )
    assert started.status_code == 202, started.text
    detail = _wait_terminal(client, started.json()["run_id"])
    assert detail["status"] == "succeeded"
    assert detail["model_name"] == "model-b"
    assert detail["model_provider_id"] == "gw-a"

    diagnostics = client.get(f"/api/agent/runs/{detail['run_id']}/diagnostics").json()
    assert diagnostics["model"] == "model-b"
    assert diagnostics["model_provider"] == "gw-a"


def test_run_without_model_uses_catalog_default(client: TestClient) -> None:
    _create_provider(client, models=["model-a", "model-b"])
    assert (
        client.put(
            "/api/model-providers/default-selection",
            json={"provider_id": "gw-a", "model_id": "model-b"},
        ).status_code
        == 200
    )
    started = _start_run(client)
    assert started.status_code == 202
    detail = _wait_terminal(client, started.json()["run_id"])
    assert detail["model_name"] == "model-b"
    assert detail["model_provider_id"] == "gw-a"


def test_run_without_catalog_falls_back_to_legacy(client: TestClient) -> None:
    started = _start_run(client)
    assert started.status_code == 202
    detail = _wait_terminal(client, started.json()["run_id"])
    assert detail["model_name"] == (settings.openai_model or "")
    assert detail["model_provider_id"] == ""


def test_run_with_unknown_provider_returns_404(client: TestClient) -> None:
    response = _start_run(client, model={"provider_id": "missing", "model_id": "m"})
    assert response.status_code == 404


def test_run_with_keyless_default_still_records_selection(client: TestClient) -> None:
    """e2e/评测契约：注入协议型 adapter 的 run 不需要真实 key。

    目录默认缺 key 不在提交时拦截（否则 e2e 的 legacy .env 导入即 keyless
    会全挂）；快照照常记录 provider/model，真实模型构建期才校验 key。
    """
    _create_provider(client, with_key=False)
    client.put(
        "/api/model-providers/default-selection",
        json={"provider_id": "gw-a", "model_id": "model-a"},
    )
    response = _start_run(client)
    assert response.status_code == 202, response.text
    detail = _wait_terminal(client, response.json()["run_id"])
    assert detail["status"] == "succeeded"
    assert detail["model_name"] == "model-a"
    assert detail["model_provider_id"] == "gw-a"


def test_fetch_draft_models_proxies_without_saving_catalog(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, object] = {}

    def fake_fetch(base_url: str, api_key: str, *, protocol: str) -> list[str]:
        seen.update({"base_url": base_url, "api_key": api_key, "protocol": protocol})
        return ["model-x"]

    import cellwiki.adapters.openai_model as adapter_module

    monkeypatch.setattr(adapter_module, "fetch_provider_models", fake_fetch)
    response = client.post(
        "/api/model-providers/fetch-models",
        json={
            "base_url": "https://gw.example/v1",
            "protocol": "chat_completions",
            "api_key": "sk-draft-key",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"models": ["model-x"]}
    assert seen == {
        "base_url": "https://gw.example/v1",
        "api_key": "sk-draft-key",
        "protocol": "chat_completions",
    }
    assert "sk-draft-key" not in response.text
    # 草稿拉取不落目录：目录仍为空。
    assert client.get("/api/model-providers").json()["providers"] == []

    missing_key = client.post(
        "/api/model-providers/fetch-models",
        json={"base_url": "https://gw.example/v1", "protocol": "chat_completions"},
    )
    assert missing_key.status_code == 422
    bad_url = client.post(
        "/api/model-providers/fetch-models",
        json={"base_url": "not-a-url", "protocol": "chat_completions", "api_key": "k"},
    )
    assert bad_url.status_code == 422
    bad_protocol = client.post(
        "/api/model-providers/fetch-models",
        json={"base_url": "https://gw.example/v1", "protocol": "bogus", "api_key": "k"},
    )
    assert bad_protocol.status_code == 422
