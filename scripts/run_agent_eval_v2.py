"""Opt-in real-model runner for the v2 multi-turn evaluation (bypass track).

Runs every (scenario, trial) with a fresh workspace copy, drives the real
product graph through AgentRuntimeManager, and writes report.json / report.md
plus optional baseline-diff.json under evals/agent_v2/runs/<timestamp>/.
This script is intentionally outside pytest: it needs a configured provider
key and spends real tokens. v1 (scripts/run_agent_eval.py) stays untouched.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from cellwiki.config import settings
from cellwiki.evaluation.agent_eval_v2 import (
    RUNS_DIR,
    SUITES_DIR,
    Scenario,
    ScenarioRunner,
    Suite,
    build_report,
    diff_reports,
    load_suite,
    prepare_trial_workspace,
    render_report_md,
    score_trial,
    _remove_tree,
)

EXIT_PASS = 0
EXIT_BLOCKED = 1
EXIT_FLAKE = 2


def _provider() -> str:
    return urlparse(settings.openai_base_url or "").hostname or "openai"


def _run_trial(
    scenario: Scenario,
    suite: Suite,
    trial: int,
    results_dir: Path,
) -> dict:
    workspace = prepare_trial_workspace(scenario, trial=trial)
    evidence_dir = results_dir / scenario.scenario_id / f"trial-{trial}" / "steps"
    runner = ScenarioRunner(
        scenario,
        workspace=workspace,
        thread_id=f"evalv2_{scenario.scenario_id}_t{trial}",
        trial=trial,
        evidence_dir=evidence_dir,
    )
    result_path = results_dir / scenario.scenario_id / f"trial-{trial}" / "result.json"
    try:
        result = score_trial(runner.run(), scenario)
    finally:
        # 证据与结果先落盘：Windows 上真实图路径的 SQLite checkpointer 在进程
        # 生存期内持有 checkpoints.sqlite 句柄，之后的清理可能失败（v1 同款
        # 约束：每个 trial 用独立目录，从不依赖事后删除）。
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(
            json.dumps(result.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    try:
        _remove_tree(workspace)
    except (PermissionError, OSError):
        # 句柄仍被持有：保留工作区到下次运行覆盖同一路径，不影响评测结果。
        print(f"[eval-v2] note: workspace kept (in use): {workspace}")
    return result.to_dict()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--suite",
        default="gate",
        help="gate | diagnostic | path to a suite json (default: gate)",
    )
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument(
        "--scenario",
        action="append",
        default=[],
        help="Run only this scenario id (repeatable; single-failure reproduction).",
    )
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument(
        "--baseline",
        type=Path,
        help="Path to a previous report.json for baseline-diff.json.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate the suite and print the plan without model calls.",
    )
    parser.add_argument(
        "--acceptance",
        action="store_true",
        help="Allow running a sealed suite (stage acceptance only).",
    )
    args = parser.parse_args()

    suite_path = (
        SUITES_DIR / f"{args.suite}.json"
        if not args.suite.endswith(".json")
        else Path(args.suite)
    )
    suite = load_suite(suite_path)
    if suite.layer == "sealed" and not args.acceptance:
        raise SystemExit(
            "sealed suite runs only at stage acceptance; pass --acceptance to override"
        )
    scenarios = [
        scenario
        for scenario in suite.scenarios
        if not args.scenario or scenario.scenario_id in set(args.scenario)
    ]
    if not scenarios:
        parser.error("no scenario matched --scenario filter")

    if args.dry_run:
        for scenario in scenarios:
            print(
                f"[dry-run] {scenario.scenario_id}: {len(scenario.steps)} steps, "
                f"oracle={scenario.oracle}, mutations={len(scenario.mutations)}"
            )
        return EXIT_PASS

    if not settings.openai_api_key:
        raise SystemExit(
            "OPENAI_API_KEY is required for the real-model v2 evaluation; "
            "offline checks live in scripts/evaluate_agent_eval_v2.py"
        )

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir = args.out_dir or RUNS_DIR / stamp
    results_dir = out_dir / "results"
    results_dir.mkdir(parents=True, exist_ok=True)

    from cellwiki.evaluation.agent_eval_v2 import TrialResult

    results: list = []
    for scenario in scenarios:
        for trial in range(1, args.trials + 1):
            print(
                f"[eval-v2] {scenario.scenario_id} trial {trial}/{args.trials} ...",
                flush=True,
            )
            result = _run_trial(scenario, suite, trial, results_dir)
            results.append(TrialResult.from_dict(result))
            print(
                f"[eval-v2] {scenario.scenario_id} trial {trial}/{args.trials} "
                f"-> passed={result['passed']} invalid={result['invalid_run']}",
                flush=True,
            )

    report = build_report(
        suite,
        results,
        provider=_provider(),
        model=settings.openai_model,
        api_protocol=settings.openai_api_protocol,
        generated_at=stamp,
    )
    report_path = out_dir / "report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (out_dir / "report.md").write_text(render_report_md(report), encoding="utf-8")

    if args.baseline:
        baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
        diff = diff_reports(baseline, report)
        (out_dir / "baseline-diff.json").write_text(
            json.dumps(diff, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    print(json.dumps(report["reliability"], ensure_ascii=False, indent=2))
    print(f"gate: {report['gate']['verdict']}  report: {report_path}")
    if report["gate"]["verdict"] in {"blocked", "invalid"}:
        return EXIT_BLOCKED
    if report["gate"]["verdict"] == "flake":
        return EXIT_FLAKE
    return EXIT_PASS


if __name__ == "__main__":
    raise SystemExit(main())
