# =============================================================================
# 质量检查测试 —— 验证 Wiki 投影质量检查逻辑
# =============================================================================

from pathlib import Path

import pytest

from cellwiki.models import CellTypeExtract, ExtractionResult, Marker, MarkerType, PaperReference
from cellwiki.services.quality import ProjectionQualityError, inspect_projection, verify_projection
from cellwiki.services.linting import LintFixService


def test_projection_quality_reports_structural_page_errors(tmp_path: Path):
    pages = tmp_path / "wiki" / "cell_types"
    pages.mkdir(parents=True)
    (pages / "bad_page.md").write_text("Body without a title.", encoding="utf-8")

    report = inspect_projection(tmp_path)

    assert report["status"] == "failed"
    assert report["issues"][0]["type"] == "invalid_frontmatter"
    assert report["issues"][1]["type"] == "missing_title"
    assert report["issues"][0]["level"] == "L0"
    assert report["issues"][0]["finding_id"].startswith("lint_")
    assert report["issues"][0]["finding_id"] == inspect_projection(tmp_path)["issues"][0]["finding_id"]
    with pytest.raises(ProjectionQualityError, match="projection lint failed"):
        verify_projection(tmp_path)


def test_projection_quality_separates_advisory_lint_from_gating_errors(tmp_path: Path):
    pages = tmp_path / "wiki" / "cell_types"
    pages.mkdir(parents=True)
    (pages / "t_cell.md").write_text(
        "---\nstandard_name: t_cell\nreferences: []\n---\n\n# T Cell\n\n[Parent](missing.md)",
        encoding="utf-8",
    )

    report = inspect_projection(tmp_path)

    assert report["status"] == "passed_with_warnings"
    assert report["error_count"] == 0
    assert report["warning_count"] == 2
    assert report["levels"]["L0"]["status"] == "passed"
    assert {issue["type"] for issue in report["issues"]} == {"missing_references", "broken_local_link"}
    verify_projection(tmp_path)


def test_read_only_lint_writes_nothing_and_groups_repairs_by_target(tmp_path: Path):
    pages = tmp_path / "wiki" / "cell_types"
    pages.mkdir(parents=True)
    page = pages / "repair_me.md"
    page.write_text("---\nreferences: [paper_1]\n---\n\nBody without a title.", encoding="utf-8")
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}

    service = LintFixService(tmp_path)
    report = service.inspect()
    after = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}

    assert before == after
    repairable = [item["finding_id"] for item in report["issues"] if item["auto_fixable"]]
    change_set = service.propose(repairable, run_id="run_grouped_lint")
    assert len(repairable) == 2
    assert len(change_set.operations) == 1
    assert set(change_set.operations[0].payload["finding_ids"]) == set(repairable)


def test_l1_lint_reports_missing_claims_marker_format_and_direction_conflict(tmp_path: Path):
    extraction_dir = tmp_path / "data" / "extraction"
    extraction_dir.mkdir(parents=True)
    paper = PaperReference(paper_id="src_fixture", title="Fixture")
    extraction = ExtractionResult(
        paper=paper,
        cell_types=[
            CellTypeExtract(
                name="Regulatory T cell",
                standard_name="regulatory_t_cell",
                paper_ref=paper,
                markers=[
                    Marker(gene_symbol="FOXP3 bad", marker_type=MarkerType.POSITIVE),
                    Marker(gene_symbol="FOXP3 bad", marker_type=MarkerType.NEGATIVE),
                ],
            )
        ],
    )
    (extraction_dir / "src_fixture.json").write_text(
        extraction.model_dump_json(indent=2), encoding="utf-8"
    )

    report = inspect_projection(tmp_path)
    types = {finding["type"] for finding in report["issues"]}

    assert report["levels"]["L1"]["status"] == "warning"
    assert "missing_claim_evidence" in types
    assert "invalid_marker_symbol" in types
    assert "marker_direction_conflict" in types
