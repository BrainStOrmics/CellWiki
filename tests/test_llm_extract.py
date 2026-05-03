"""Tests for LLM extraction with mock mode."""

import json
import pytest
from unittest.mock import patch, MagicMock

from cellwiki.models import ExtractionResult, PaperReference
from pathlib import Path

from cellwiki.llm_extract import (
    _parse_llm_response, _validate_gene_symbol, extract_cell_types_from_paper,
)


class TestParseLLMResponse:
    def test_valid_response(self, mock_llm_response):
        result = _parse_llm_response(mock_llm_response)
        assert result is not None
        assert isinstance(result, dict)
        assert len(result["cell_types"]) == 1
        assert result["cell_types"][0]["standard_name"] == "cd4_t_cell"

    def test_invalid_json(self):
        with pytest.raises(json.JSONDecodeError):
            _parse_llm_response("not json")

    def test_missing_cell_types(self):
        result = _parse_llm_response('{"other_field": "value"}')
        assert isinstance(result, dict)
        assert "cell_types" not in result

    def test_empty_cell_types(self):
        result = _parse_llm_response('{"cell_types": []}')
        assert isinstance(result, dict)
        assert result["cell_types"] == []


class TestValidateGeneSymbol:
    def test_valid_symbols(self):
        assert _validate_gene_symbol("CD3D") is True
        assert _validate_gene_symbol("CD8A") is True
        assert _validate_gene_symbol("IL10") is True
        assert _validate_gene_symbol("CXCR5") is True

    def test_invalid_symbols(self):
        # Contains special characters
        assert _validate_gene_symbol("RORγ") is False
        assert _validate_gene_symbol("MHC class I") is False
        assert _validate_gene_symbol("F4/80") is False
        # Too long
        assert _validate_gene_symbol("A" * 50) is False
        # Empty
        assert _validate_gene_symbol("") is False


class TestMockLLMExtraction:
    def test_extract_with_mocked_openai(self, mock_llm_response):
        """Test extraction pipeline with a mocked OpenAI client."""
        mock_choice = MagicMock()
        mock_choice.message.content = mock_llm_response
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response

        with patch("cellwiki.llm_extract.OpenAI", return_value=mock_client):
            result = extract_cell_types_from_paper(
                text="This is a paper about CD4+ T cells and their markers.",
                pdf_path=Path("/tmp/test_paper.pdf"),
            )
            assert result is not None
            assert len(result.cell_types) == 1
            assert result.cell_types[0].standard_name == "cd4_t_cell"
