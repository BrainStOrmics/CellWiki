"""Score Agent run records against the fixed workspace case set (no model call)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from cellwiki.evaluation.agent_eval import evaluate_agent_predictions
from cellwiki.evaluation.semantic import threshold_failures


ROOT = Path(__file__).resolve().parents[1]
EVALS = ROOT / "evals" / "agent"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=EVALS / "dataset.json")
    parser.add_argument("--predictions", type=Path, default=EVALS / "reference_predictions.json")
    parser.add_argument("--thresholds", type=Path, default=EVALS / "thresholds.json")
    parser.add_argument("--workspace", type=Path, default=EVALS / "workspace")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    predictions = _load(args.predictions)
    metrics = evaluate_agent_predictions(_load(args.dataset), predictions, args.workspace)
    failures = threshold_failures(metrics, _load(args.thresholds))
    report = {
        "dataset": str(args.dataset),
        "predictions": str(args.predictions),
        "run_kind": predictions.get("run_kind", "unknown"),
        "provider": predictions.get("provider"),
        "model": predictions.get("model"),
        "metrics": metrics,
        "passed": not failures,
        "failures": failures,
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    if failures:
        raise SystemExit("agent evaluation failed release thresholds")


if __name__ == "__main__":
    main()
