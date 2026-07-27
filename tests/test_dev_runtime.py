# =============================================================================
# 开发运行时测试 —— 验证拥有进程的开发运行时接口
# =============================================================================

"""Tests for the owned-process development runtime interface."""

from pathlib import Path

import pytest

from cellwiki.dev_runtime import DevelopmentProcessSpec, DevelopmentRuntime


def test_development_runtime_builds_the_three_expected_processes(monkeypatch, tmp_path: Path):
    (tmp_path / "frontend").mkdir()
    monkeypatch.setattr("cellwiki.dev_runtime.shutil.which", lambda _name: "npm.cmd")

    specs = DevelopmentRuntime(tmp_path).specs()

    assert [spec.name for spec in specs] == ["product-api", "agent-runtime", "desktop"]
    assert [spec.port for spec in specs] == [8000, 2024, 5173]
    assert "uvicorn" in specs[0].command
    assert any("langgraph_cli.cli" in argument for argument in specs[1].command)
    assert specs[2].command == ("npm.cmd", "run", "desktop:dev")


def test_development_runtime_requires_explicit_port_reuse(monkeypatch, tmp_path: Path):
    runtime = DevelopmentRuntime(tmp_path, include_agent=False, include_desktop=False)
    spec = DevelopmentProcessSpec("product-api", 8000, ("python",), tmp_path)
    monkeypatch.setattr("cellwiki.dev_runtime._port_is_open", lambda _port: True)

    with pytest.raises(RuntimeError, match="--reuse-ports"):
        runtime._start(spec)

    approved = DevelopmentRuntime(
        tmp_path,
        include_agent=False,
        include_desktop=False,
        reuse_ports=True,
    )
    approved._start(spec)
    assert approved.owned == []


def test_development_runtime_preflight_checks_project_venv_node_and_rust(
    monkeypatch, tmp_path: Path
):
    (tmp_path / ".venv" / "Scripts").mkdir(parents=True)
    (tmp_path / "frontend" / "node_modules").mkdir(parents=True)
    tauri = tmp_path / "frontend" / "src-tauri" / "tauri.conf.json"
    tauri.parent.mkdir(parents=True)
    tauri.write_text("{}", encoding="utf-8")
    python = tmp_path / ".venv" / "Scripts" / "python.exe"
    python.write_bytes(b"")
    monkeypatch.setattr("cellwiki.dev_runtime.sys.executable", str(python))
    monkeypatch.setattr(
        "cellwiki.dev_runtime.shutil.which",
        lambda name: name if name in {"npm.cmd", "npm", "cargo.exe", "cargo"} else None,
    )

    DevelopmentRuntime(tmp_path)._validate_environment()

    monkeypatch.setattr("cellwiki.dev_runtime.shutil.which", lambda name: None)
    with pytest.raises(RuntimeError, match="npm"):
        DevelopmentRuntime(tmp_path)._validate_environment()
