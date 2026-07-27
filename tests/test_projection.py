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
