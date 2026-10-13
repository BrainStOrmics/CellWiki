"""Contracts and a loopback smoke test for the local CellWiki daemon."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from cellwiki.services import local_daemon
from cellwiki.services.local_daemon import (
    DAEMON_API_VERSION,
    DaemonCoordinates,
    DaemonVersionMismatch,
)
from cellwiki.tui.client import DaemonClient


def _use_isolated_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CELLWIKI_DAEMON_DIR", str(tmp_path / "daemon-state"))


def _coordinates(workspace: Path, *, pid: int = 999_999, port: int = 1) -> DaemonCoordinates:
    return DaemonCoordinates(
        schema_version=local_daemon.DAEMON_SCHEMA_VERSION,
        pid=pid,
        port=port,
        workspace=str(workspace.resolve()),
        package_version=local_daemon.application_version(),
        api_version=DAEMON_API_VERSION,
        started_at="2026-10-14T00:00:00+00:00",
        log_path=str(workspace / "data" / "runtime" / "logs" / "daemon.log"),
    )


def test_state_dir_is_workspace_scoped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _use_isolated_state(tmp_path, monkeypatch)

    first = local_daemon.workspace_state_dir(tmp_path / "kb")
    again = local_daemon.workspace_state_dir(tmp_path / "kb")
    other = local_daemon.workspace_state_dir(tmp_path / "other")

    assert first == again
    assert first != other
    assert first.parent == tmp_path / "daemon-state"


def test_discovery_round_trip_and_private_permissions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_isolated_state(tmp_path, monkeypatch)
    workspace = tmp_path / "kb"
    state_dir = local_daemon.workspace_state_dir(workspace)
    coordinates = _coordinates(workspace)

    local_daemon.write_coordinates(state_dir, coordinates)
    local_daemon.write_control_token(state_dir, "control-secret")

    assert local_daemon.read_coordinates(state_dir) == coordinates
    assert local_daemon.read_control_token(state_dir) == "control-secret"
    if os.name != "nt":
        assert (state_dir / local_daemon.DISCOVERY_FILE_NAME).stat().st_mode & 0o777 == 0o600
        assert (state_dir / local_daemon.CONTROL_TOKEN_FILE_NAME).stat().st_mode & 0o777 == 0o600


def test_read_coordinates_rejects_unknown_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_isolated_state(tmp_path, monkeypatch)
    workspace = tmp_path / "kb"
    state_dir = local_daemon.workspace_state_dir(workspace)
    state_dir.mkdir(parents=True, exist_ok=True)
    payload = _coordinates(workspace).to_payload()
    payload["schema_version"] = local_daemon.DAEMON_SCHEMA_VERSION + 1
    (state_dir / local_daemon.DISCOVERY_FILE_NAME).write_text(
        json.dumps(payload), encoding="utf-8"
    )

    assert local_daemon.read_coordinates(state_dir) is None


def test_stale_registration_is_reported_and_cleaned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_isolated_state(tmp_path, monkeypatch)
    workspace = tmp_path / "kb"
    state_dir = local_daemon.workspace_state_dir(workspace)
    local_daemon.write_coordinates(state_dir, _coordinates(workspace))
    local_daemon.write_control_token(state_dir, "stale-token")

    assert local_daemon.daemon_status(workspace)["state"] == "stale"
    assert local_daemon.stop_daemon(workspace) is True
    assert not (state_dir / local_daemon.DISCOVERY_FILE_NAME).exists()
    assert not (state_dir / local_daemon.CONTROL_TOKEN_FILE_NAME).exists()


@pytest.mark.skipif(os.name == "nt", reason="daemon smoke is Linux-first")
def test_daemon_lifecycle_smoke(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _use_isolated_state(tmp_path, monkeypatch)
    workspace = tmp_path / "kb"
    workspace.mkdir()

    coordinates = local_daemon.ensure_daemon(workspace, timeout=120)
    try:
        assert coordinates.pid > 0
        assert local_daemon.pid_alive(coordinates.pid)
        assert local_daemon.check_health(coordinates)

        client = DaemonClient.connect(workspace)
        assert client.list_threads() == []

        reused = local_daemon.ensure_daemon(workspace, timeout=30)
        assert reused.pid == coordinates.pid

        second = subprocess.run(
            [
                sys.executable,
                "-m",
                "cellwiki.product_cli",
                "serve",
                "--workspace",
                str(workspace),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert second.returncode != 0
        assert "already running" in (second.stdout + second.stderr)

        state_dir = local_daemon.workspace_state_dir(workspace)
        discovery_path = state_dir / local_daemon.DISCOVERY_FILE_NAME
        payload = json.loads(discovery_path.read_text(encoding="utf-8"))
        payload["api_version"] = "cellwiki-daemon-v0"
        discovery_path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(DaemonVersionMismatch):
            local_daemon.ensure_daemon(workspace, timeout=10)
    finally:
        local_daemon.stop_daemon(workspace)

    assert local_daemon.daemon_status(workspace)["state"] == "absent"
