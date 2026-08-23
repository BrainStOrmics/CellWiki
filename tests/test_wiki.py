# =============================================================================
# Wiki 测试 —— 验证 Wiki 页面生成和标题格式化
# =============================================================================

"""Tests for wiki page generation and title formatting."""

from unittest.mock import patch

from cellwiki.models import WikiCellType
from cellwiki.adapters.markdown_renderer import _proper_title_case, generate_cell_type_page


class TestProperTitleCase:
    def test_basic_snake_case(self):
        assert _proper_title_case("cd8_t_cell") == "CD8 T Cell"

    def test_cd4_cd8(self):
        assert "CD4" in _proper_title_case("cd4_naive_t_cell")
        assert "CD8" in _proper_title_case("cd8_memory_t_cell")

    def test_macrophage(self):
        result = _proper_title_case("tumor_associated_macrophage")
        assert "Tumor" in result
        assert "Macrophage" in result

    def test_mait_cell(self):
        result = _proper_title_case("mait_cell")
        assert "MAIT" in result

    def test_regulatory_t_cell(self):
        result = _proper_title_case("regulatory_t_cell")
        assert "T Cell" in result

    def test_temra(self):
        result = _proper_title_case("cd8_temra_t_cell")
        assert "TEMRA" in result or "Temra" in result


class TestGenerateCellTypePage:
    def test_generate_basic_page(self, patched_settings, tmp_path):
        wt = WikiCellType(
            standard_name="test_cell",
            display_name="Test Cell",
            description="A test cell type",
            cl_id="CL:0000001",
        )
        with patch("cellwiki.adapters.markdown_renderer.settings", patched_settings):
            generate_cell_type_page("test_cell", wt)

        page_path = patched_settings.wiki_cell_types_dir / "test_cell.md"
        assert page_path.exists()

        content = page_path.read_text()
        assert "---" in content
        assert "test_cell" in content
        assert "Test Cell" in content

    def test_page_with_markers(self, patched_settings):
        wt = WikiCellType(
            standard_name="marker_cell",
            display_name="Marker Cell",
            markers={
                "CD3": [{"marker_type": "positive", "evidence": "FACS", "paper_id": "p1"}],
            },
            references=[{"paper_id": "p1", "title": "Test Paper", "doi": "", "year": 2024}],
        )
        with patch("cellwiki.adapters.markdown_renderer.settings", patched_settings):
            generate_cell_type_page("marker_cell", wt)

        page_path = patched_settings.wiki_cell_types_dir / "marker_cell.md"
        content = page_path.read_text()
        assert "CD3" in content
        assert "positive" in content

    def test_page_with_conflicts(self, patched_settings):
        wt = WikiCellType(
            standard_name="conflict_cell",
            display_name="Conflict Cell",
            markers={
                "CD44": [
                    {"marker_type": "positive", "evidence": "FACS", "paper_id": "p1"},
                    {"marker_type": "negative", "evidence": "Flow", "paper_id": "p2", "conflict": True},
                ],
            },
        )
        with patch("cellwiki.adapters.markdown_renderer.settings", patched_settings):
            generate_cell_type_page("conflict_cell", wt)

        page_path = patched_settings.wiki_cell_types_dir / "conflict_cell.md"
        content = page_path.read_text()
        assert "CD44" in content
        assert "CONFLICT" in content
