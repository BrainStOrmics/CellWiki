"""Contract tests for the product command-line entry point."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_packaging_exposes_only_product_entry_points() -> None:
    configuration = tomllib.loads(
        (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )

    scripts = configuration["project"]["scripts"]

    assert scripts == {
        "cellwiki": "cellwiki.product_cli:main",
        "cellwiki-sidecar": "cellwiki.sidecar:main",
    }


def test_product_cli_parses_tui_daemon_and_development_commands() -> None:
    from cellwiki.product_cli import build_parser

    parser = build_parser()

    development = parser.parse_args(["dev", "--no-desktop", "--reuse-ports"])
    assert development.command == "dev"
    assert development.no_desktop is True
    assert development.reuse_ports is True

    serve = parser.parse_args(["serve", "--workspace", "kb", "--detach"])
    assert serve.command == "serve"
    assert serve.workspace == Path("kb")
    assert serve.detach is True

    status = parser.parse_args(["daemon", "status", "--workspace", "kb"])
    assert status.command == "daemon"
    assert status.daemon_command == "status"
    assert status.workspace == Path("kb")

    default = parser.parse_args([])
    assert default.command is None

    with pytest.raises(SystemExit):
        parser.parse_args(["ingest", "paper.pdf"])


def test_product_cli_runs_the_owned_development_runtime(monkeypatch, tmp_path: Path) -> None:
    from cellwiki import config as config_module
    from cellwiki import dev_runtime as dev_runtime_module
    from cellwiki import product_cli

    captured: dict[str, object] = {}

    class FakeDevelopmentRuntime:
        def __init__(self, project_root: Path, **options: object) -> None:
            captured["project_root"] = project_root
            captured["options"] = options

        def run(self) -> None:
            captured["ran"] = True

    monkeypatch.setattr(dev_runtime_module, "DevelopmentRuntime", FakeDevelopmentRuntime)
    monkeypatch.setattr(config_module.settings, "project_root", tmp_path)

    product_cli.main(["dev", "--no-desktop"])

    assert captured == {
        "project_root": tmp_path,
        "options": {
            "include_desktop": False,
            "reuse_ports": False,
        },
        "ran": True,
    }


def test_product_cli_hands_the_tui_to_the_typescript_client(
    monkeypatch, tmp_path: Path
) -> None:
    from cellwiki import product_cli

    captured: dict[str, object] = {}
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "shutil.which",
        lambda name: "/usr/local/bin/cellwiki-tui"
        if name == "cellwiki-tui"
        else None,
    )
    monkeypatch.setattr(
        "subprocess.call",
        lambda command, **kwargs: (
            captured.setdefault("command", command),
            captured.setdefault("env", kwargs.get("env")),
            captured.setdefault("ran", True),
            0,
        )[-1],
    )

    with pytest.raises(SystemExit) as exit_info:
        product_cli.main([])

    assert exit_info.value.code == 0
    assert captured["command"] == [
        "/usr/local/bin/cellwiki-tui",
        "--workspace",
        str(tmp_path),
    ]
    import sys

    assert captured["env"]["CELLWIKI_PYTHON"] == sys.executable


def test_product_cli_tui_requires_the_typescript_client(monkeypatch) -> None:
    from cellwiki import product_cli

    monkeypatch.setattr("shutil.which", lambda name: None)

    with pytest.raises(SystemExit) as exit_info:
        product_cli.main([])

    assert "npm install -g cellwiki-tui" in str(exit_info.value)
