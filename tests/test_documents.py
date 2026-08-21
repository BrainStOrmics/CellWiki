# =============================================================================
# 文档合约测试 —— 验证页面感知解析、分块和声明级证据
# =============================================================================

"""Contract tests for page-aware parsing, chunking, and claim-level evidence."""

from __future__ import annotations

from pathlib import Path

import pytest

from cellwiki.domain.contracts import Claim, EvidenceReference
from cellwiki.services.parsing import DocumentParsingService, PdfPlumberParser
from cellwiki.services.sources import SourceRegistry


FIXTURES = Path(__file__).parent / "fixtures"


def test_markdown_parser_retains_sections_and_uses_deterministic_cache(tmp_path: Path):
    registry = SourceRegistry(tmp_path)
    source = registry.register(FIXTURES / "sample_source.md", source_type="paper")
    parsing = DocumentParsingService(tmp_path)

    first = parsing.parse(source)
    cached = parsing.parse(source)
    rebuilt = parsing.parse(source, force=True)

    assert first == cached
    assert first.parse_hash == rebuilt.parse_hash
    assert first.parser_config["encoding"] == "utf-8"
    assert first.pages[0].page_number == 1
    assert [block.section for block in first.all_blocks() if block.section][-1] == "Context"


def test_pdf_adapter_keeps_real_page_numbers(monkeypatch, tmp_path: Path):
    class FakePage:
        width = 600
        height = 800

        def __init__(self, text: str):
            self.text = text

        def extract_text(self, **_kwargs):
            return self.text

    class FakePdf:
        metadata = {"Title": "Fixture paper", "Author": "CellWiki"}
        pages = [FakePage("INTRODUCTION\n\nPage one evidence."), FakePage("RESULTS\n\nPage two evidence.")]

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr("cellwiki.services.parsing.pdfplumber.open", lambda _path: FakePdf())
    path = tmp_path / "fixture.pdf"
    path.write_bytes(b"fixture")
    source = SourceRegistry(tmp_path).register(path, source_type="paper")

    document = PdfPlumberParser().parse(source)

    assert [page.page_number for page in document.pages] == [1, 2]
    assert document.block(document.pages[1].blocks[-1].block_id).page_number == 2
    assert document.metadata["page_count"] == 2


def test_real_pdf_fixtures_preserve_pages_and_two_column_text(tmp_path: Path):
    registry = SourceRegistry(tmp_path)
    page_aware = registry.register(FIXTURES / "page_aware_source.pdf", source_type="paper")
    two_column = registry.register(FIXTURES / "two_column_source.pdf", source_type="paper")
    parser = DocumentParsingService(tmp_path)

    page_document = parser.parse(page_aware)
    column_document = parser.parse(two_column)

    assert len(page_document.pages) == 3
    assert "FOXP3" in " ".join(block.text for block in page_document.pages[1].blocks)
    assert page_document.pages[1].blocks[0].page_number == 2
    assert len(column_document.pages) == 2
    first_page = " ".join(block.text for block in column_document.pages[0].blocks)
    assert "Regulatory T cell" in first_page
    assert "CD8 T cell" in first_page


def test_claim_requires_valid_source_evidence():
    evidence = EvidenceReference(
        source_id="src_fixture",
        page_start=2,
        page_end=2,
        block_id="block_0002_0001_fixture",
        excerpt="FOXP3 was detected.",
    )
    claim = Claim(
        claim_id="claim_fixture",
        subject="regulatory_t_cell",
        predicate="expresses",
        object="FOXP3",
        evidence=[evidence],
    )

    assert claim.evidence[0].page_start == 2
    with pytest.raises(ValueError, match="at least one evidence"):
        Claim(
            claim_id="claim_without_evidence",
            subject="regulatory_t_cell",
            predicate="expresses",
            object="FOXP3",
            evidence=[],
        )


def test_evidence_rejects_reversed_page_ranges():
    with pytest.raises(ValueError, match="page_end"):
        EvidenceReference(source_id="src_fixture", page_start=4, page_end=3)
