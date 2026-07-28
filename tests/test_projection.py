# =============================================================================
# 投影测试 —— 验证 Wiki 投影生成的正确性
# =============================================================================

from pathlib import Path

import pytest

from cellwiki.domain.contracts import (
    ApprovalDecision,
    ChangeOperation,
    ChangeOperationType,
    ChangeSet,
    RiskLevel,
)
from cellwiki.models import CellTypeExtract, ExtractionResult, PaperReference
from cellwiki.services.central_writer import CentralWriter
from cellwiki.services.changesets import ChangeSetRepository
from cellwiki.services.projection import ProjectionService


def test_projection_keeps_curated_content_separate_and_visible(tmp_path: Path):
    extraction_dir = tmp_path / "data" / "extraction"
    extraction_dir.mkdir(parents=True)
    paper = PaperReference(paper_id="paper_1", title="Paper 1", year=2025)
    extraction = ExtractionResult(
        paper=paper,
        cell_types=[
            CellTypeExtract(
                name="Treg",
                standard_name="regulatory_t_cell",
                description="Regulatory T cells.",
                paper_ref=paper,
            )
        ],
    )
    (extraction_dir / "paper_1.json").write_text(
        extraction.model_dump_json(indent=2), encoding="utf-8"
    )

    change_set = ChangeSet(
        change_set_id="cs_projection",
        run_id="run_projection",
        project_id="cellwiki",
        risk=RiskLevel.MEDIUM,
        reason="Add curator context.",
        operations=[
            ChangeOperation(
                type=ChangeOperationType.UPDATE_CURATION,
                target_id="regulatory_t_cell",
                payload={"content": "Review this page before using it in a manuscript."},
            )
        ],
    )
    repository = ChangeSetRepository(tmp_path)
    repository.save(change_set)
    CentralWriter(tmp_path, repository=repository).commit(
        "cs_projection",
        ApprovalDecision(approved=True, decided_by="local-user"),
    )

    curation = tmp_path / "wiki" / "curation" / "cell_types" / "regulatory_t_cell.md"
    page = tmp_path / "wiki" / "cell_types" / "regulatory_t_cell.md"
    assert curation.exists()
    assert "Review this page" in page.read_text(encoding="utf-8")


def test_failed_projection_removes_newly_generated_page(tmp_path: Path):
    extraction_dir = tmp_path / "data" / "extraction"
    extraction_dir.mkdir(parents=True)
    paper = PaperReference(paper_id="paper_1", title="Paper 1", year=2025)
    extraction = ExtractionResult(
        paper=paper,
        cell_types=[
            CellTypeExtract(
                name="Treg",
                standard_name="regulatory_t_cell",
                paper_ref=paper,
            )
        ],
    )
    (extraction_dir / "paper_1.json").write_text(
        extraction.model_dump_json(indent=2), encoding="utf-8"
    )
    change_set = ChangeSet(
        change_set_id="cs_failed_projection",
        run_id="run_projection",
        project_id="cellwiki",
        risk=RiskLevel.MEDIUM,
        reason="Exercise rollback.",
        operations=[
            ChangeOperation(
                type=ChangeOperationType.UPDATE_CURATION,
                target_id="regulatory_t_cell",
                payload={"content": "temporary"},
            )
        ],
    )
    repository = ChangeSetRepository(tmp_path)
    repository.save(change_set)

    def fail_verification(_root: Path) -> None:
        raise RuntimeError("verification failed")

    writer = CentralWriter(tmp_path, repository=repository, verifier=fail_verification)
    with pytest.raises(RuntimeError, match="verification failed"):
        writer.commit(
            "cs_failed_projection",
            ApprovalDecision(approved=True, decided_by="local-user"),
        )

    assert not (tmp_path / "wiki" / "cell_types" / "regulatory_t_cell.md").exists()


def test_failed_projection_restores_all_generated_outputs_and_preserves_curation(
    tmp_path: Path,
):
    extraction_dir = tmp_path / "data" / "extraction"
    extraction_dir.mkdir(parents=True)
    paper = PaperReference(paper_id="paper_1", title="Paper 1", year=2025)
    extraction = ExtractionResult(
        paper=paper,
        cell_types=[
            CellTypeExtract(
                name="Treg",
                standard_name="regulatory_t_cell",
                tissues=["Lung"],
                diseases=["Cancer"],
                paper_ref=paper,
            )
        ],
    )
    (extraction_dir / "paper_1.json").write_text(
        extraction.model_dump_json(indent=2), encoding="utf-8"
    )

    wiki_dir = tmp_path / "wiki"
    expected_projection: dict[Path, bytes] = {}
    for directory in ("cell_types", "marker_genes", "tissues", "diseases", "conflicts"):
        path = wiki_dir / directory / "before.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"original {directory}", encoding="utf-8")
        expected_projection[path] = path.read_bytes()
    for filename in ("index.md", "overview.md", "README.md"):
        path = wiki_dir / filename
        path.write_text(f"original {filename}", encoding="utf-8")
        expected_projection[path] = path.read_bytes()

    curation = wiki_dir / "curation" / "cell_types" / "regulatory_t_cell.md"
    curation.parent.mkdir(parents=True)
    curation.write_text("original curation", encoding="utf-8")
    unrelated_curation = curation.with_name("human_note.md")
    unrelated_curation.write_text("keep this human note", encoding="utf-8")
    unrelated_wiki_file = wiki_dir / "audit_report.md"
    unrelated_wiki_file.write_text("keep this report", encoding="utf-8")

    change_set = ChangeSet(
        change_set_id="cs_complete_projection_rollback",
        run_id="run_projection",
        project_id="cellwiki",
        risk=RiskLevel.MEDIUM,
        reason="Exercise complete projection rollback.",
        operations=[
            ChangeOperation(
                type=ChangeOperationType.UPDATE_CURATION,
                target_id="regulatory_t_cell",
                payload={"content": "temporary curation"},
            )
        ],
    )
    repository = ChangeSetRepository(tmp_path)
    repository.save(change_set)

    def fail_verification(_root: Path) -> None:
        raise RuntimeError("verification failed")

    with pytest.raises(RuntimeError, match="verification failed"):
        CentralWriter(
            tmp_path,
            repository=repository,
            verifier=fail_verification,
        ).commit(
            change_set.change_set_id,
            ApprovalDecision(approved=True, decided_by="local-user"),
        )

    for path, expected in expected_projection.items():
        assert path.read_bytes() == expected
    for directory in ("cell_types", "marker_genes", "tissues", "diseases", "conflicts"):
        assert sorted(path.name for path in (wiki_dir / directory).glob("*.md")) == [
            "before.md"
        ]
    assert curation.read_text(encoding="utf-8") == "original curation"
    assert unrelated_curation.read_text(encoding="utf-8") == "keep this human note"
    assert unrelated_wiki_file.read_text(encoding="utf-8") == "keep this report"


def test_projection_removes_obsolete_manifest_without_extractions(tmp_path: Path):
    manifest = tmp_path / "wiki" / "manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text("obsolete", encoding="utf-8")

    assert ProjectionService(tmp_path).render() == []
    assert not manifest.exists()
