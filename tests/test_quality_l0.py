"""L0 gate tests for quality.inspect_projection (cluster, shell, verbatim evidence)."""
import json

from cellwiki.services.quality import inspect_projection


def _write_extraction(root, name: str, data: dict) -> None:
    (root / "data" / "extraction").mkdir(parents=True, exist_ok=True)
    path = root / "data" / "extraction" / f"{name}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _paper_ref() -> dict:
    return {"paper_id": "paper_a", "title": "T", "doi": "", "year": 2024, "local_path": ""}


def test_inspect_reports_cluster_shell_and_verbatim_gaps(tmp_path):
    extractions = {
        "cluster_cell": {
            "name": "SC-C4",
            "standard_name": "sc_c4",
            "synonyms": [],
            "parent_type": None,
            "species": [], "tissues": [], "diseases": [],
            "markers": [],
            "functions": [],
            "subpopulations": [],
            "description": "",
            "paper_ref": _paper_ref(),
        },
        "shell_cell": {
            "name": "empty",
            "standard_name": "empty_shell_cell",
            "synonyms": [],
            "parent_type": None,
            "species": [], "tissues": [], "diseases": [],
            "markers": [],
            "functions": [],
            "subpopulations": [],
            "description": "",
            "paper_ref": _paper_ref(),
        },
        "bad_marker": {
            "name": "bad marker cell",
            "standard_name": "bad_marker_cell",
            "synonyms": [],
            "parent_type": None,
            "species": [], "tissues": [], "diseases": [],
            "markers": [{"gene_symbol": "FOXP3", "marker_type": "positive", "evidence": "", "strength": ""}],
            "functions": [],
            "subpopulations": [],
            "description": "Some description.",
            "paper_ref": _paper_ref(),
        },
    }
    data = {
        "paper": _paper_ref(),
        "cell_types": list(extractions.values()),
        "raw_relationships": [],
        "claims": [],
        "source_document": {"source_id": "paper_a"},
    }
    _write_extraction(tmp_path, "paper_a", data)
    report = inspect_projection(tmp_path)
    issue_types = {issue["type"] for issue in report["issues"]}
    assert "cluster_id_standard_name" in issue_types
    assert "empty_cell_type" in issue_types
    assert "missing_verbatim_marker_evidence" in issue_types
    l0 = [issue for issue in report["issues"] if issue["type"] in issue_types and issue["level"] == "L0"]
    assert all(issue["severity"] == "error" for issue in l0)
    assert report["status"] == "failed"
