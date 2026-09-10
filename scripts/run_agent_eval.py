"""Opt-in real-model Agent evaluation; every case runs in a fresh fixture workspace.

This script is intentionally outside pytest: it needs a configured provider key and
spends real tokens. It writes predictions and report files under
evals/agent/runs/<timestamp>/ so a gold reference file can never be overwritten by a
model run (see evals/agent/README.md).
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from cellwiki.config import settings
from cellwiki.domain.contracts import WikiAgentContext
from cellwiki.domain.runs import AgentEventType, AgentRunStatus, RunBudget
from cellwiki.evaluation.agent_eval import evaluate_agent_predictions
from cellwiki.evaluation.semantic import threshold_failures
from cellwiki.services.agent_runtime import AgentRuntimeManager
from cellwiki.services.quality import inspect_projection
from cellwiki.services.workspace import ensure_workspace


ROOT = Path(__file__).resolve().parents[1]
EVALS = ROOT / "evals" / "agent"
FIXTURE = EVALS / "workspace"
WRITE_TOOLS = {"write_file", "edit_file", "delete_file", "rename_file"}
STOP_STATUSES = {
    AgentRunStatus.SUCCEEDED,
    AgentRunStatus.WAITING_APPROVAL,
    AgentRunStatus.WAITING_CONFIRMATION,
    AgentRunStatus.REJECTED,
    AgentRunStatus.FAILED,
    AgentRunStatus.CANCELLED,
    AgentRunStatus.UNFINISHED,
}


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=str(root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    return completed.stdout


def _prepare(case_id: str) -> Path:
    """Copy the tracked fixture into a disposable workspace and commit its baseline."""

    work = ROOT / "build" / "agent-eval" / case_id
    if work.exists():
        shutil.rmtree(work)
    work.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(FIXTURE, work)
    ensure_workspace(work)
    _git(work, "add", "-A")
    _git(work, "commit", "-m", "chore(eval): fixture baseline")
    return work


def _changed_paths(root: Path, snapshot: str | None) -> list[str]:
    paths: set[str] = set()
    if snapshot:
        paths.update(line for line in _git(root, "diff", "--name-only", snapshot, "HEAD").splitlines() if line)
    for line in _git(root, "status", "--porcelain").splitlines():
        candidate = line[3:].strip().strip('"')
        if candidate:
            paths.add(candidate.replace("\\", "/"))
    return sorted(paths)


def _write_calls(events: list) -> list[str]:
    calls: list[str] = []
    for event in events:
        if event.type != AgentEventType.TOOL_STARTED:
            continue
        data = event.data if isinstance(event.data, dict) else {}
        if str(data.get("tool_name")) not in WRITE_TOOLS:
            continue
        display = data.get("args_display") if isinstance(data.get("args_display"), dict) else {}
        path = str(display.get("path") or display.get("file") or "")
        if path and path not in calls:
            calls.append(path)
    return calls


def _run_case(case: dict, max_model_calls: int, timeout_seconds: int) -> dict:
    case_id = str(case["case_id"])
    work = _prepare(case_id)
    thread_id = f"eval_{case_id}"
    manager = AgentRuntimeManager(work)
    started = time.monotonic()
    try:
        run = manager.start(
            thread_id=thread_id,
            message=str(case["prompt"]),
            context=WikiAgentContext(project_id="cellwiki-eval", thread_id=thread_id),
            budget=RunBudget(
                max_model_calls=max_model_calls,
                max_runtime_seconds=timeout_seconds,
                max_retries=0,
            ),
        )
        deadline = started + timeout_seconds + 60
        current = run
        while time.monotonic() < deadline:
            current = manager.store.get_run(run.run_id)
            if current.status in STOP_STATUSES:
                break
            time.sleep(0.5)
        events = manager.store.list_events(run.run_id)
        answer = next(
            (event.message for event in reversed(events) if event.type == AgentEventType.FINAL_RESPONSE),
            "",
        )
        return {
            "case_id": case_id,
            "final_status": current.status.value,
            "error_type": current.error_type.value if current.error_type else None,
            "error_message": (current.error_message or "")[:300] or None,
            "answer": answer,
            "changed_paths": _changed_paths(work, current.snapshot_commit),
            "write_calls": _write_calls(events),
            "lint_status": inspect_projection(work)["status"],
            "workspace": str(work),
            "usage": current.usage.model_dump(mode="json"),
        }
    finally:
        manager.close()


def main() -> None:
    if not settings.openai_api_key:
        raise SystemExit("OPENAI_API_KEY is required for the opt-in real-model evaluation")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=EVALS / "dataset.json")
    parser.add_argument("--thresholds", type=Path, default=EVALS / "thresholds.json")
    parser.add_argument("--case", action="append", default=[], help="Run only this case id (repeatable).")
    parser.add_argument("--max-model-calls", type=int, default=40)
    parser.add_argument("--timeout-seconds", type=int, default=600)
    parser.add_argument("--out-dir", type=Path)
    args = parser.parse_args()

    dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
    cases = [
        case
        for case in dataset["cases"]
        if not args.case or str(case["case_id"]) in set(args.case)
    ]
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir = args.out_dir or EVALS / "runs" / stamp
    out_dir.mkdir(parents=True, exist_ok=True)

    predictions = {
        "schema_version": 1,
        "run_kind": "real_model",
        "provider": urlparse(settings.openai_base_url or "").hostname or "openai",
        "model": settings.openai_model,
        "api_protocol": settings.openai_api_protocol,
        "generated_at": stamp,
        "cases": [],
    }
    for case in cases:
        print(f"[eval] {case['case_id']} ...", flush=True)
        record = _run_case(case, args.max_model_calls, args.timeout_seconds)
        predictions["cases"].append(record)
        print(f"[eval] {case['case_id']} -> {record['final_status']}", flush=True)

    predictions_path = out_dir / "predictions.json"
    predictions_path.write_text(
        json.dumps(predictions, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    metrics = evaluate_agent_predictions(dataset, predictions, FIXTURE)
    failures = threshold_failures(metrics, json.loads(args.thresholds.read_text(encoding="utf-8")))
    report = {
        "run_kind": "real_model",
        "predictions": str(predictions_path),
        "metrics": metrics,
        "passed": not failures,
        "failures": failures,
    }
    (out_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if failures:
        raise SystemExit("agent evaluation failed release thresholds")


if __name__ == "__main__":
    main()
