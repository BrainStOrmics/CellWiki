# =============================================================================
# BFCL 校准 adapter 合同测试 —— 无网络、无 BFCL 环境
# =============================================================================
# 真实 BFCL 运行需要隔离环境与模型配置，是显式 opt-in；这里的合同是：
# pin 常量、命令构造、multi_turn 展开、报告 partial 语义，以及主项目
# pyproject.toml 永不引入 bfcl 依赖。
# =============================================================================

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "run_bfcl_calibration", REPO_ROOT / "scripts" / "run_bfcl_calibration.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def bfcl():
    return _load_script()


def test_pin_commit_is_frozen(bfcl):
    assert bfcl.BFCL_PIN_COMMIT == "6ea57973c7a6097fd7c5915698c54c17c5b1b6c8"


def test_multi_turn_expands_to_four_official_subcategories(bfcl):
    assert bfcl.resolve_categories("multi_turn") == [
        "multi_turn_base",
        "multi_turn_miss_func",
        "multi_turn_miss_param",
        "multi_turn_long_context",
    ]
    assert bfcl.resolve_categories("multi_turn_base") == ["multi_turn_base"]


def test_commands_use_single_thread_and_recorded_verbatim(bfcl):
    commands = bfcl.build_bfcl_commands("bfcl", "some-model", "multi_turn_base")
    assert commands[0] == [
        "bfcl",
        "generate",
        "--model",
        "some-model",
        "--test-category",
        "multi_turn_base",
        "--num-threads",
        "1",
    ]
    assert commands[1] == [
        "bfcl",
        "evaluate",
        "--model",
        "some-model",
        "--test-category",
        "multi_turn_base",
    ]


def test_pyproject_never_declares_bfcl_dependency(bfcl):
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8").casefold()
    assert "bfcl-eval" not in pyproject
    assert "berkeley-function-call-leaderboard" not in pyproject


def test_verify_pin_refuses_unpinned_checkout(bfcl, tmp_path: Path):
    import subprocess

    repo = tmp_path / "gorilla"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "eval@example.com"],
        check=True,
    )
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "eval"], check=True)
    (repo / "README.md").write_text("probe\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "probe"], check=True)
    with pytest.raises(RuntimeError, match="pin"):
        bfcl.verify_pin(repo)


def test_report_always_declares_bfcl_track_and_partial_reason(bfcl, tmp_path: Path):
    out_dir = tmp_path / "bfcl-run"
    path = bfcl.write_report(
        out_dir,
        status="partial",
        reason="no_bfcl_environment",
        model=None,
        categories=bfcl.resolve_categories("multi_turn"),
    )
    report = json.loads(path.read_text(encoding="utf-8"))
    assert report["track"] == "bfcl"
    assert report["status"] == "partial"
    assert report["not_executed_reason"] == "no_bfcl_environment"
    assert report["model_config"] is None
    assert report["bfcl_pin_commit"] == bfcl.BFCL_PIN_COMMIT


def test_completed_report_records_artifacts_and_head(bfcl, tmp_path: Path):
    out_dir = tmp_path / "bfcl-run"
    path = bfcl.write_report(
        out_dir,
        status="completed",
        reason=None,
        model="some-model",
        categories=bfcl.resolve_categories("multi_turn"),
        head_commit=bfcl.BFCL_PIN_COMMIT,
        commands=[["bfcl", "generate"]],
        artifacts=["score/some-model/multi_turn_base/score.csv"],
    )
    report = json.loads(path.read_text(encoding="utf-8"))
    assert report["status"] == "completed"
    assert report["bfcl_head_commit"] == bfcl.BFCL_PIN_COMMIT
    assert report["artifacts"] == ["score/some-model/multi_turn_base/score.csv"]


def test_main_dry_run_writes_planned_report(bfcl, tmp_path: Path, monkeypatch):
    out_dir = tmp_path / "dry"
    argv = [
        "run_bfcl_calibration.py",
        "--dry-run",
        "--out-dir",
        str(out_dir),
    ]
    monkeypatch.setattr("sys.argv", argv)
    exit_code = bfcl.main()
    assert exit_code == 0
    report = json.loads((out_dir / "report.json").read_text(encoding="utf-8"))
    assert report["status"] == "planned"
    assert report["not_executed_reason"] == "dry_run"
    assert report["track"] == "bfcl"
    assert report["commands"], "dry-run must record the planned commands"


def test_main_without_model_or_dry_run_fails(bfcl, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "sys.argv", ["run_bfcl_calibration.py", "--out-dir", str(tmp_path / "x")]
    )
    with pytest.raises(SystemExit):
        bfcl.main()
