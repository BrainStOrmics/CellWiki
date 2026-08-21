"""Phase A guard tests: canonical merge, document grounding, agent draft finalize, staging store."""

from cellwiki.domain.documents import DocumentBlock, ParsedDocument, ParsedPage
from cellwiki.domain.extraction import (
    CellTypeExtract,
    PaperReference,
    ExtractionResult,
    Marker,
    MarkerType,
)
from cellwiki.domain.contracts import SourceRecord
from cellwiki.services.ingest import (
    _evidence_for_term_document,
    _finalize_agent_draft,
    _ground_extraction_document,
    _merge_extractions,
)
from cellwiki.services.ingest_draft import AgentIngestDraftStore


def _source() -> SourceRecord:
    return SourceRecord(
        source_id="src_test",
        source_type="paper",
        original_name="t.md",
        stored_path="data/references/t.md",
        content_hash="ch",
    )


def _document() -> ParsedDocument:
    blocks = [
        DocumentBlock(
            block_id="b1",
            page_number=1,
            order=0,
            text="Tumor tissue contained LRRC15+ fibroblasts and terminal exhausted CD8+ T cells with high ENTPD1 and TIGIT expression.",
            section="Results",
        ),
        DocumentBlock(
            block_id="b2",
            page_number=1,
            order=1,
            text="Terminal exhausted CD8+ T cells expressed LAG3 and LAYN in peritumoral regions.",
            section="Results",
        ),
    ]
    page = ParsedPage(page_number=1, blocks=blocks)
    return ParsedDocument(
        source_id="src_test",
        source_hash="h",
        parser_name="unit",
        parser_version="1",
        parser_config={},
        parse_hash="ph",
        pages=[page],
    )


def _paper() -> PaperReference:
    return PaperReference(paper_id="src_test", title="T", doi="", year=2024)


def test_document_grounding_normalizes_whitespace_and_case():
    document = _document()
    evidence = _evidence_for_term_document(_source(), document, "tumor tissue contained LRRC15+ fibroblasts")
    assert evidence is not None
    assert evidence.block_id == "b1"
    assert "LRRC15+ fibroblasts" in evidence.excerpt
    # Case-insensitive across a newline boundary (whitespace normalization)
    evidence2 = _evidence_for_term_document(_source(), document, "terminal exhausted\nCD8+ T cells")
    assert evidence2 is not None
    assert evidence2.block_id in {"b1", "b2"}


def test_document_grounding_misses_absent_term():
    assert _evidence_for_term_document(_source(), _document(), "a phrase that never appears") is None


def test_ground_extraction_document_drops_cluster_entity_and_grounds_marker():
    source = _source()
    document = _document()
    extraction = ExtractionResult(
        paper=_paper(),
        cell_types=[
            CellTypeExtract(
                name="LRRC15+ fibroblasts",
                standard_name="lrrc15_positive_fibroblast",
                markers=[Marker(gene_symbol="LRRC15", marker_type=MarkerType.POSITIVE, evidence="LRRC15+ fibroblasts")],
                paper_ref=_paper(),
            ),
            CellTypeExtract(name="SC-C4", standard_name="SC-C4", paper_ref=_paper()),
            CellTypeExtract(
                name="cluster_c01",
                standard_name="cd4_c01_ccr7_t_cell",
                paper_ref=_paper(),
            ),
        ],
    )
    grounded, gaps = _ground_extraction_document(source, document, extraction)
    names = [cell.standard_name for cell in grounded.cell_types]
    assert names == ["lrrc15_positive_fibroblast"]
    gap_types = [gap.type for gap in gaps]
    assert gap_types.count("cluster_id_standard_name") == 2
    kept = grounded.cell_types[0]
    assert kept.markers and kept.markers[0].evidence


def test_merge_extractions_merges_case_variants_into_one_key():
    source = _source()
    document = _document()
    first = ExtractionResult(
        paper=_paper(),
        cell_types=[
            CellTypeExtract(
                name="LRRC15+ fibroblasts",
                standard_name="lrRC15_positive_fibroblast",
                markers=[Marker(gene_symbol="LRRC15", marker_type=MarkerType.POSITIVE)],
                paper_ref=_paper(),
            )
        ],
    )
    second = ExtractionResult(
        paper=_paper(),
        cell_types=[
            CellTypeExtract(
                name="LRRC15+ fibroblast",
                standard_name="lrrc15_positive_fibroblast",
                markers=[Marker(gene_symbol="COL1A1", marker_type=MarkerType.POSITIVE)],
                paper_ref=_paper(),
            )
        ],
    )
    merged, conflicts = _merge_extractions(source, document, [first, second])
    assert len(merged.cell_types) == 1
    cell = merged.cell_types[0]
    assert cell.standard_name == "lrrc15_positive_fibroblast"
    assert "lrRC15_positive_fibroblast" in cell.synonyms
    assert {m.gene_symbol for m in cell.markers} == {"LRRC15", "COL1A1"}


def test_finalize_agent_draft_grounds_and_flags_excess_ungrounded(tmp_path):
    source = _source()
    document = _document()
    payload = {
        "paper_info": {"title": "T", "doi": "", "year": 2024},
        "cell_types": [
            {
                "name": "LRRC15+ fibroblasts",
                "standard_name": "lrrc15_positive_fibroblast",
                "markers": [{"gene_symbol": "LRRC15", "marker_type": "positive", "evidence": "LRRC15+ fibroblasts"}],
                "description": "Tumor stroma fibroblasts.",
            },
            {
                "name": "A cell that is never mentioned",
                "standard_name": "never_mentioned_cell",
                "markers": [{"gene_symbol": "TIGIT", "marker_type": "positive", "evidence": "totally invented"}],
            },
        ],
    }
    extraction, review_items = _finalize_agent_draft(source, document, payload)
    assert extraction.paper.paper_id == "src_test"
    assert [c.standard_name for c in extraction.cell_types] == ["lrrc15_positive_fibroblast"]
    assert extraction.claims
    types = [item.type for item in review_items]
    assert "ungrounded_entity" in types
    assert "excessive_ungrounded_entities" in types


def test_staging_store_round_trip(tmp_path):
    store = AgentIngestDraftStore(tmp_path)
    payload = {"paper_info": {"title": "T"}, "cell_types": [{"name": "x", "standard_name": "x_cell"}]}
    path = store.save("src_1", "run_1", payload)
    assert path.is_file()
    record = store.load("src_1", "run_1")
    assert record["payload"]["cell_types"][0]["standard_name"] == "x_cell"
    assert store.list_for("src_1") == ["run_1"]
    assert store.load("src_1", "missing") is None
    assert store.delete("src_1", "run_1") is True
    assert store.load("src_1", "run_1") is None
