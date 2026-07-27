"""Contract tests for the product and legacy command-line entry points."""

from __future__ import annotations

import tomllib
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_packaging_exposes_product_and_explicit_legacy_entry_points() -> None:
    configuration = tomllib.loads(
        (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )

    scripts = configuration["project"]["scripts"]

    assert scripts["cellwiki"] == "cellwiki.product_cli:main"
    assert scripts["cellwiki-legacy"] == "cellwiki.legacy.cli:main"


def test_product_cli_accepts_only_the_desktop_development_command() -> None:
    from cellwiki.product_cli import build_parser

    parser = build_parser()
    arguments = parser.parse_args(
        ["dev", "--no-agent", "--no-desktop", "--reuse-ports"]
    )

    assert arguments.command == "dev"
    assert arguments.no_agent is True
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

    product_cli.main(["dev", "--no-agent", "--no-desktop"])

    assert captured == {
        "project_root": tmp_path,
        "options": {
            "include_agent": False,
            "include_desktop": False,
            "reuse_ports": False,
        },
        "ran": True,
    }


def test_legacy_cli_is_explicitly_named_and_does_not_expose_product_dev(
    monkeypatch, capsys
) -> None:
    from cellwiki.legacy import cli as legacy_cli

    monkeypatch.setattr(sys, "argv", ["cellwiki-legacy", "--help"])

    with pytest.raises(SystemExit) as exit_info:
        legacy_cli.main()

    output = capsys.readouterr().out
    assert exit_info.value.code == 0
    assert output.startswith("usage: cellwiki-legacy")
    assert "Start the complete Agentic CellWiki desktop development runtime" not in output
