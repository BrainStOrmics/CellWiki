"""Run the opt-in real-model ingest baseline; this script is intentionally outside pytest."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from cellwiki.config import settings
from cellwiki.services.ingest import IngestService
from cellwiki.services.sources import SourceRegistry


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
THRESHOLDS = {
    "entity_recall": 1.0,
    "marker_recall": 1.0,
    "evidence_completeness": 1.0,
}


def _recall(expected: set[str], actual: set[str]) -> float:
    return len(expected & actual) / len(expected) if expected else 1.0


def main() -> None:
    if not settings.openai_api_key:
        raise SystemExit("OPENAI_API_KEY is required for the opt-in real-model evaluation")
    expected = json.loads((FIXTURES / "expected_ingest.json").read_text(encoding="utf-8"))

    # A temporary project keeps evaluation caches and proposals out of the repository.
    with tempfile.TemporaryDirectory(prefix="cellwiki_ingest_eval_") as directory:
        project = Path(directory)
        source = SourceRegistry(project).register(
            FIXTURES / "page_aware_source.pdf",
            source_type="paper",
        )
        change_set = IngestService(project).prepare_change_set(source.source_id, "eval_real_model")
        extraction = change_set.operations[0].payload

    cells = extraction.get("cell_types", [])
    actual_entities = {str(cell.get("standard_name", "")) for cell in cells}
    actual_markers = {
        str(marker.get("gene_symbol", "")).upper()
        for cell in cells
        for marker in cell.get("markers", [])
    }
    required = set(expected["required_evidence_fields"])
    evidence_rows = [item.model_dump(mode="json") for item in change_set.evidence]
    complete = sum(required <= {key for key, value in row.items() if value not in (None, "")} for row in evidence_rows)
    metrics = {
        "entity_recall": _recall(set(expected["cell_types"]), actual_entities),
        "marker_recall": _recall(set(expected["markers"]), actual_markers),
        "evidence_completeness": complete / len(evidence_rows) if evidence_rows else 0.0,
    }
    print(json.dumps({"model": settings.openai_model, "metrics": metrics}, indent=2))
    failed = [name for name, threshold in THRESHOLDS.items() if metrics[name] < threshold]
    if failed:
        raise SystemExit(f"ingest evaluation failed thresholds: {', '.join(failed)}")


if __name__ == "__main__":
    main()

