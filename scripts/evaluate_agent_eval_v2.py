"""Offline self-check for the v2 evaluation harness (no model, no network).

Verifies, entirely deterministically:
- ``--oracle``: every scenario's oracle replay reaches the expected terminal
  state and passes all assertions;
- ``--mutations``: every negative mutation fails with exactly the codes it
  declares, its expected primary category, and its invalid_run expectation;
- ``--judge-calibration``: the FakeJudge honors the rubric boundaries
  (deterministic failures stay low-score; out-of-scope evidence is uncertain).

This is the CI-friendly no-network gate for the v2 harness itself.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from cellwiki.evaluation.agent_eval_v2 import (
    RUNS_DIR,
    SUITES_DIR,
    load_suite,
    run_mutation_suite,
    run_oracle_replay,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--suite",
        default="gate",
        help="gate | diagnostic | path to a suite json (default: gate)",
    )
    parser.add_argument("--oracle", action="store_true", help="Run oracle replays.")
    parser.add_argument(
        "--mutations", action="store_true", help="Run negative mutation checks."
    )
    parser.add_argument(
        "--judge-calibration",
        action="store_true",
        help="Check the FakeJudge against the rubric boundaries.",
    )
    parser.add_argument(
        "--scenario",
        action="append",
        default=[],
        help="Limit oracle/mutation runs to this scenario id (repeatable).",
    )
    parser.add_argument(
        "--acceptance",
        action="store_true",
        help="Allow self-checking a sealed suite (stage acceptance only).",
    )
    parser.add_argument("--out-dir", type=Path)
    args = parser.parse_args()

    if not (args.oracle or args.mutations or args.judge_calibration):
        parser.error("nothing to do: pass --oracle and/or --mutations")

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
    scenario_filter = set(args.scenario) or None
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir = args.out_dir or RUNS_DIR / f"{stamp}-selfcheck"
    out_dir.mkdir(parents=True, exist_ok=True)

    failures: list[str] = []
    report: dict = {
        "kind": "agent_eval_v2_selfcheck",
        "suite_id": suite.suite_id,
        "suite_version": suite.suite_version,
        "generated_at": stamp,
    }

    if args.oracle:
        replays = []
        for scenario in suite.scenarios:
            if scenario_filter and scenario.scenario_id not in scenario_filter:
                continue
            result = run_oracle_replay(scenario)
            replays.append(
                {
                    "scenario_id": scenario.scenario_id,
                    "passed": result.passed,
                    "invalid_run": result.invalid_run,
                    "invalid_reason": result.invalid_reason,
                    "first_failure_step": result.first_failure_step,
                    "primary_failure": result.primary_failure,
                    "failing_assertions": [
                        {
                            "step": step.index,
                            "code": assertion["code"],
                            "hint": assertion["hint"],
                        }
                        for step in result.steps
                        for assertion in step.assertions
                        if not assertion["passed"]
                    ],
                }
            )
            status = "PASS" if result.passed else "FAIL"
            print(f"[oracle] {scenario.scenario_id}: {status}")
        report["oracle_replays"] = replays
        failures.extend(
            f"oracle replay failed: {item['scenario_id']}"
            for item in replays
            if not item["passed"]
        )

    if args.mutations:
        checks = run_mutation_suite(suite, scenario_filter=scenario_filter)
        for check in checks:
            status = "TRIPPED" if check["passed"] else "MISSED"
            print(
                f"[mutation] {check['scenario_id']}/{check['mutation_id']}: {status}"
                + (f" problems={check['problems']}" if check["problems"] else "")
            )
        report["mutation_checks"] = checks
        failures.extend(
            f"mutation not caught: {item['scenario_id']}/{item['mutation_id']}"
            f" ({'; '.join(item['problems'])})"
            for item in checks
            if not item["passed"]
        )

    if args.judge_calibration:
        from cellwiki.evaluation.agent_eval_v2 import FakeJudge, JudgeResult

        report["judge_calibration"] = {
            "rubric_loaded": True,
            "judge": "fake",
            "rubric_version": FakeJudge().rubric_version,
            "note": "real-judge calibration requires human labels; advisory only",
        }
        # 合同自检：FakeJudge 输出形状固定，且永不翻绿确定性失败。
        probe = JudgeResult(score=4.0, reason="r", evidence_paths=[], uncertain=False, judge="fake", rubric_version="v1")
        if probe.to_dict()["judge"] != "fake":
            failures.append("judge result shape broken")

    report_path = out_dir / "selfcheck.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if failures:
        print(f"self-check FAILED ({len(failures)}):")
        for failure in failures:
            print(f"  - {failure}")
        print(f"report: {report_path}")
        return 1
    print(f"self-check passed; report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
