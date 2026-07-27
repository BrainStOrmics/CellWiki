# =============================================================================
# 测试共享夹具 —— CellWiki 测试的共享测试夹具和模拟数据
# =============================================================================

"""Shared test fixtures and mock data for CellWiki tests."""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from cellwiki.models import (
    Marker, MarkerType, FunctionalCharacteristic, PaperReference,
    CellTypeExtract, ExtractionResult, WikiCellType,
)


@pytest.fixture
def sample_paper():
    """Create a sample PaperReference."""
    return PaperReference(
        paper_id="test_paper_1",
        title="Test Paper on T Cells",
        doi="10.1234/test.2024",
        year=2024,
        local_path="/tmp/test.pdf",
    )


@pytest.fixture
def sample_marker():
    """Create a sample Marker."""
    return Marker(
        gene_symbol="CD3D",
        marker_type=MarkerType.POSITIVE,
        evidence="FACS gating",
        strength="high",
    )


@pytest.fixture
def sample_function():
    """Create a sample FunctionalCharacteristic."""
    return FunctionalCharacteristic(
        description="Anti-tumor immunity",
        pathway="T cell receptor signaling",
        evidence="scRNA-seq analysis",
    )


@pytest.fixture
def sample_cell_type(sample_paper, sample_marker, sample_function):
    """Create a sample CellTypeExtract."""
    return CellTypeExtract(
        name="CD8+ T cell",
        standard_name="cd8_t_cell",
        cl_id="CL:0000625",
        description="Cytotoxic T lymphocytes that kill target cells",
        parent_type="t_cell",
        synonyms=["cytotoxic T cell", "CTL"],
        markers=[sample_marker],
        functions=[sample_function],
        species=["Homo sapiens"],
        tissues=["colorectal tumor"],
        diseases=["colorectal cancer"],
        subpopulations=[],
        paper_ref=sample_paper,
    )


@pytest.fixture
def sample_extraction(sample_cell_type):
    """Create a sample ExtractionResult."""
    return ExtractionResult(
        paper=PaperReference(
            paper_id="test_paper_1",
            title="Test Paper",
            doi="10.1234/test.2024",
            year=2024,
            local_path="/tmp/test.pdf",
        ),
        cell_types=[sample_cell_type],
    )


@pytest.fixture
def mock_llm_response():
    """Return a mock LLM JSON response for cell type extraction."""
    return json.dumps({
        "cell_types": [
            {
                "name": "CD4+ T cell",
                "standard_name": "cd4_t_cell",
                "description": "Helper T lymphocytes",
                "parent_type": "t_cell",
                "synonyms": ["helper T cell"],
                "markers": [
                    {"gene_symbol": "CD4", "marker_type": "positive", "evidence": "FACS", "strength": "high"}
                ],
                "functions": [
                    {"description": "Helper function", "pathway": "cytokine signaling", "evidence": "scRNA-seq"}
                ],
                "species": ["Homo sapiens"],
                "tissues": ["blood"],
                "diseases": [],
                "subpopulations": []
            }
        ]
    })


@pytest.fixture
def tmp_wiki_dir(tmp_path):
    """Create a temporary wiki directory structure."""
    wiki_dir = tmp_path / "wiki"
    cell_types_dir = wiki_dir / "cell_types"
    cell_types_dir.mkdir(parents=True)
    extraction_dir = tmp_path / "extraction"
    extraction_dir.mkdir(parents=True)
    references_dir = tmp_path / "references"
    references_dir.mkdir(parents=True)
    return {
        "wiki_dir": wiki_dir,
        "cell_types_dir": cell_types_dir,
        "extraction_dir": extraction_dir,
        "references_dir": references_dir,
    }


@pytest.fixture
def patched_settings(tmp_wiki_dir):
    """Patch settings to use temporary directories."""
    with patch("cellwiki.config.settings") as mock_settings:
        mock_settings.wiki_dir = tmp_wiki_dir["wiki_dir"]
        mock_settings.wiki_cell_types_dir = tmp_wiki_dir["cell_types_dir"]
        mock_settings.extraction_dir = tmp_wiki_dir["extraction_dir"]
        mock_settings.references_dir = tmp_wiki_dir["references_dir"]
        yield mock_settings
