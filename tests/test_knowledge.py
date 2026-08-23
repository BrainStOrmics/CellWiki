# =============================================================================
# 知识库测试 —— 验证知识库合并和去重逻辑
# =============================================================================

"""Tests for knowledge base merging and deduplication."""


from cellwiki.models import (
    Marker, MarkerType, PaperReference,
    CellTypeExtract, ExtractionResult, WikiCellType,
)
from cellwiki.knowledge import merge_to_wiki, deduplicate_by_cl_id


def make_cell_type(name, standard_name, paper_id, cl_id=None, markers=None):
    """Helper to create a CellTypeExtract with minimal fields."""
    paper = PaperReference(
        paper_id=paper_id,
        title=f"Paper {paper_id}",
        year=2024,
    )
    marker_list = markers or []
    return CellTypeExtract(
        name=name,
        standard_name=standard_name,
        cl_id=cl_id,
        description=f"Description of {name}",
        markers=marker_list,
        paper_ref=paper,
    )


class TestMergeToWiki:
    def test_merge_single_extraction(self, sample_extraction):
        wiki = merge_to_wiki([sample_extraction])
        assert "cd8_t_cell" in wiki
        assert wiki["cd8_t_cell"].display_name != ""
        assert len(wiki["cd8_t_cell"].references) == 1

    def test_merge_two_extractions_same_cell_type(self, sample_extraction):
        ext2 = ExtractionResult(
            paper=PaperReference(
                paper_id="test_paper_2",
                title="Second Paper",
                doi="10.5678/test.2025",
                year=2025,
            ),
            cell_types=[
                CellTypeExtract(
                    name="CD8+ T cell",
                    standard_name="cd8_t_cell",
                    description="Cytotoxic T cells from paper 2",
                    markers=[
                        Marker(
                            gene_symbol="CD8B",
                            marker_type=MarkerType.TRANSCRIPT,
                            evidence="scRNA-seq",
                        )
                    ],
                    paper_ref=PaperReference(
                        paper_id="test_paper_2",
                        title="Second Paper",
                        year=2025,
                    ),
                )
            ],
        )
        wiki = merge_to_wiki([sample_extraction, ext2])
        assert "cd8_t_cell" in wiki
        # Should have markers from both papers
        assert "CD3D" in wiki["cd8_t_cell"].markers
        assert "CD8B" in wiki["cd8_t_cell"].markers
        # Should have references from both papers
        assert len(wiki["cd8_t_cell"].references) == 2

    def test_merge_different_cell_types(self, sample_extraction):
        ext2 = ExtractionResult(
            paper=sample_extraction.paper,
            cell_types=[
                CellTypeExtract(
                    name="B cell",
                    standard_name="b_cell",
                    description="B lymphocytes",
                    paper_ref=sample_extraction.paper,
                )
            ],
        )
        wiki = merge_to_wiki([sample_extraction, ext2])
        assert "cd8_t_cell" in wiki
        assert "b_cell" in wiki

    def test_marker_conflict_detection(self):
        ext1 = ExtractionResult(
            paper=PaperReference(paper_id="p1", title="P1", year=2024),
            cell_types=[
                CellTypeExtract(
                    name="T cell",
                    standard_name="t_cell",
                    markers=[
                        Marker(gene_symbol="CD44", marker_type=MarkerType.POSITIVE, evidence="FACS")
                    ],
                    paper_ref=PaperReference(paper_id="p1", title="P1", year=2024),
                )
            ],
        )
        ext2 = ExtractionResult(
            paper=PaperReference(paper_id="p2", title="P2", year=2024),
            cell_types=[
                CellTypeExtract(
                    name="T cell",
                    standard_name="t_cell",
                    markers=[
                        Marker(gene_symbol="CD44", marker_type=MarkerType.NEGATIVE, evidence="Flow")
                    ],
                    paper_ref=PaperReference(paper_id="p2", title="P2", year=2024),
                )
            ],
        )
        wiki = merge_to_wiki([ext1, ext2])
        cd44_entries = wiki["t_cell"].markers["CD44"]
        # Should have both entries
        assert len(cd44_entries) == 2
        # One should be marked as conflict
        assert any(e.get("conflict") for e in cd44_entries)


class TestDeduplicateByCLID:
    def test_no_dupes(self):
        wiki = {
            "cd8_t_cell": WikiCellType(standard_name="cd8_t_cell", display_name="CD8 T Cell", cl_id="CL:0000625"),
            "cd4_t_cell": WikiCellType(standard_name="cd4_t_cell", display_name="CD4 T Cell", cl_id="CL:0000494"),
        }
        result = deduplicate_by_cl_id(wiki)
        assert len(result) == 2

    def test_merge_same_cl_id(self):
        wiki = {
            "cd8_t_cell": WikiCellType(
                standard_name="cd8_t_cell",
                display_name="CD8 T Cell",
                cl_id="CL:0000625",
                description="First description",
            ),
            "cd8_temra_cell": WikiCellType(
                standard_name="cd8_temra_cell",
                display_name="CD8 TEMRA Cell",
                cl_id="CL:0000625",
                description="Longer description that should be kept",
            ),
        }
        result = deduplicate_by_cl_id(wiki)
        # Should merge into one
        assert len(result) == 1
        canonical = result["cd8_t_cell"]
        # Should have merged aliases
        assert "CD8 TEMRA Cell" in canonical.aliases or "cd8_temra_cell" in canonical.aliases

    def test_skip_root_cl_id(self):
        wiki = {
            "unknown_cell": WikiCellType(
                standard_name="unknown_cell",
                display_name="Unknown Cell",
                cl_id="CL:0000000",
            ),
            "another_unknown": WikiCellType(
                standard_name="another_unknown",
                display_name="Another Unknown",
                cl_id="CL:0000000",
            ),
        }
        result = deduplicate_by_cl_id(wiki)
        # CL:0000000 should NOT trigger deduplication
        assert len(result) == 2

    def test_no_cl_id_kept_separate(self):
        wiki = {
            "novel_cell": WikiCellType(standard_name="novel_cell", display_name="Novel Cell"),
            "another_novel": WikiCellType(standard_name="another_novel", display_name="Another Novel"),
        }
        result = deduplicate_by_cl_id(wiki)
        assert len(result) == 2
