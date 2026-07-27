"""Score a semantic prediction file and enforce the checked-in release thresholds."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from cellwiki.evaluation.semantic import evaluate_semantic_predictions, threshold_failures


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "evals" / "semantic" / "dataset.json"
DEFAULT_PREDICTIONS = ROOT / "evals" / "semantic" / "reference_predictions.json"
DEFAULT_THRESHOLDS = ROOT / "evals" / "semantic" / "thresholds.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--predictions", type=Path, default=DEFAULT_PREDICTIONS)
    parser.add_argument("--thresholds", type=Path, default=DEFAULT_THRESHOLDS)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    predictions = _load(args.predictions)
    metrics = evaluate_semantic_predictions(_load(args.dataset), predictions)
    failures = threshold_failures(metrics, _load(args.thresholds))
    report = {
        "dataset": str(args.dataset),
        "predictions": str(args.predictions),
        "run_kind": predictions.get("run_kind", "unknown"),
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
        raise SystemExit("semantic evaluation failed release thresholds")


if __name__ == "__main__":
    main()
