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


def test_product_cli_accepts_only_the_desktop_development_command() -> None:
    from cellwiki.product_cli import build_parser

    parser = build_parser()
    arguments = parser.parse_args(["dev", "--no-desktop", "--reuse-ports"])

    assert arguments.command == "dev"
    assert arguments.no_desktop is True
    assert arguments.reuse_ports is True

    with pytest.raises(SystemExit):
        parser.parse_args(["ingest", "paper.pdf"])


def test_product_cli_runs_the_owned_development_runtime(monkeypatch, tmp_path: Path) -> None:
    from cellwiki import product_cli

    captured: dict[str, object] = {}

    class FakeDevelopmentRuntime:
        def __init__(self, project_root: Path, **options: object) -> None:
            captured["project_root"] = project_root
            captured["options"] = options

        def run(self) -> None:
            captured["ran"] = True

    monkeypatch.setattr(product_cli, "DevelopmentRuntime", FakeDevelopmentRuntime)
    monkeypatch.setattr(product_cli.settings, "project_root", tmp_path)

    product_cli.main(["dev", "--no-desktop"])

    assert captured == {
        "project_root": tmp_path,
        "options": {
            "include_desktop": False,
            "reuse_ports": False,
        },
        "ran": True,
    }
