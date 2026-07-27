# =============================================================================
# LLM 提取测试 —— 验证 LLM 提取功能（使用模拟模式）
# =============================================================================

"""Tests for LLM extraction with mock mode."""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import httpx
from langchain_core.messages import AIMessage
from openai import (
    AuthenticationError,
    BadRequestError,
    PermissionDeniedError,
    RateLimitError,
    UnprocessableEntityError,
)
from cellwiki.config import Settings
from cellwiki.models import ExtractionResult, PaperReference

from cellwiki.adapters.openai_structured_output import (
    ExtractionPolicy,
    StructuredExtractionError,
    _call_structured_with_retry,
    _classify_provider_error,
    _parse_llm_response,
    _validate_gene_symbol,
    extract_cell_types_from_chunk,
    extract_cell_types_from_paper,
    _extract_chunk_adaptively,
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
    def test_extract_with_mocked_langchain_model(self, mock_llm_response):
        """Both provider protocols expose the same LangChain message boundary."""
        mock_model = MagicMock()
        mock_model.invoke.return_value = AIMessage(
            content=mock_llm_response,
            response_metadata={"finish_reason": "stop"},
        )

        with patch(
            "cellwiki.adapters.openai_structured_output.build_openai_chat_model",
            return_value=mock_model,
        ):
            result = extract_cell_types_from_paper(
                text="This is a paper about CD4+ T cells and their markers.",
                pdf_path=Path("/tmp/test_paper.pdf"),
            )
            assert result is not None
            assert len(result.cell_types) == 1
            assert result.cell_types[0].standard_name == "cd4_t_cell"

    def test_extract_normalizes_null_optional_fields(self):
        response = json.dumps({
            "paper_info": {"title": None, "doi": None, "year": None},
            "cell_types": [{
                "name": "Regulatory T cell",
                "standard_name": "regulatory_t_cell",
                "markers": None,
                "functions": None,
                "synonyms": None,
                "species": None,
                "tissues": None,
                "diseases": None,
                "subpopulations": None,
                "description": None,
            }],
            "relationships": None,
        })
        mock_model = MagicMock()
        mock_model.invoke.return_value = AIMessage(
            content=response,
            response_metadata={"finish_reason": "stop"},
        )

        with patch(
            "cellwiki.adapters.openai_structured_output.build_openai_chat_model",
            return_value=mock_model,
        ):
            result = extract_cell_types_from_paper(
                text="Regulatory T cell",
                pdf_path=Path("/tmp/null_metadata.pdf"),
            )

        assert result.paper.title == "null_metadata"
        assert result.paper.doi == ""
        assert result.paper.year == 0
        assert result.cell_types[0].markers == []

    def test_sequential_chunk_extraction_closes_each_provider_client_independently(self):
        class SharedClient:
            def __init__(self):
                self.closed = False
                self.close_count = 0

            def close(self):
                self.closed = True
                self.close_count += 1

        response = AIMessage(
            content=json.dumps({
                "paper_info": {"title": "Fixture", "doi": "", "year": 2026},
                "cell_types": [],
                "relationships": [],
            }),
            response_metadata={"finish_reason": "stop"},
        )
        first_client = SharedClient()
        second_client = SharedClient()
        first_model = MagicMock(root_client=first_client)
        first_model.invoke.return_value = response
        second_model = MagicMock(root_client=second_client)

        def invoke_second_chunk(*args, **kwargs):
            if second_client.closed:
                raise ConnectionError("provider client has been closed")
            return response

        second_model.invoke.side_effect = invoke_second_chunk

        with (
            patch(
                "cellwiki.adapters.openai_structured_output.build_openai_chat_model",
                side_effect=[first_model, second_model],
            ),
            patch("cellwiki.adapters.openai_structured_output.time.sleep"),
        ):
            first = extract_cell_types_from_chunk(
                text="first chunk",
                pdf_path=Path("/tmp/sequential-first.pdf"),
            )
            second = extract_cell_types_from_chunk(
                text="second chunk",
                pdf_path=Path("/tmp/sequential-second.pdf"),
            )

        assert first.paper.title == second.paper.title == "Fixture"
        assert first_client.close_count == 1
        assert second_client.close_count == 1

    def test_invalid_structured_output_is_not_silently_cached_as_empty_extraction(self):
        mock_model = MagicMock()
        mock_model.invoke.return_value = AIMessage(
            content="not json",
            response_metadata={"finish_reason": "stop"},
        )

        with patch(
            "cellwiki.adapters.openai_structured_output.build_openai_chat_model",
            return_value=mock_model,
        ):
            with pytest.raises(StructuredExtractionError, match="structured output failed"):
                extract_cell_types_from_paper(
                    text="Regulatory T cell",
                    pdf_path=Path("/tmp/invalid_structured_output.pdf"),
                )

        assert mock_model.invoke.call_count == 3

    def test_transport_timeout_uses_one_total_attempt_budget(self):
        """A timeout must not multiply transport retries by structured-output retries."""

        mock_model = MagicMock()
        mock_model.invoke.side_effect = TimeoutError("Request timed out")

        with (
            patch(
                "cellwiki.adapters.openai_structured_output.build_openai_chat_model",
                return_value=mock_model,
            ),
            patch("cellwiki.adapters.openai_structured_output.time.sleep"),
        ):
            with pytest.raises(StructuredExtractionError, match="timed out"):
                extract_cell_types_from_paper(
                    text="Regulatory T cell",
                    pdf_path=Path("/tmp/provider_timeout.pdf"),
                )

        assert mock_model.invoke.call_count == 3

    def test_timeout_retry_reduces_output_budget_for_slow_provider(self):
        mock_model = MagicMock()
        mock_model.invoke.side_effect = [
            TimeoutError("Request timed out"),
            AIMessage(
                content='{"cell_types": []}',
                response_metadata={"finish_reason": "stop"},
            ),
        ]

        with patch("cellwiki.adapters.openai_structured_output.time.sleep"):
            result = _call_structured_with_retry(
                mock_model,
                [{"role": "user", "content": "slow provider chunk"}],
                policy=ExtractionPolicy(
                    max_attempts=2,
                    request_timeout_seconds=90,
                    chunk_timeout_seconds=210,
                    max_output_tokens=5000,
                ),
            )

        assert result == {"cell_types": []}
        assert mock_model.invoke.call_args_list[0].kwargs["max_completion_tokens"] == 5000
        assert mock_model.invoke.call_args_list[1].kwargs["max_completion_tokens"] == 2000

    def test_structured_request_does_not_repeat_chat_completion_truncation(self):
        mock_model = MagicMock()
        mock_model.invoke.return_value = AIMessage(
            content='{"cell_types": [',
            response_metadata={"finish_reason": "length"},
        )

        with patch("cellwiki.adapters.openai_structured_output.time.sleep"):
            with pytest.raises(StructuredExtractionError) as raised:
                _call_structured_with_retry(
                    mock_model,
                    [{"role": "user", "content": "bounded source block"}],
                    policy=ExtractionPolicy(
                        max_attempts=2,
                        request_timeout_seconds=45,
                        chunk_timeout_seconds=150,
                        max_output_tokens=5000,
                    ),
                )

        assert raised.value.kind == "truncated_response"
        assert mock_model.invoke.call_count == 1
        assert mock_model.invoke.call_args.kwargs["response_format"] == {
            "type": "json_object"
        }
        assert mock_model.invoke.call_args.kwargs["max_completion_tokens"] == 5000

    def test_structured_request_accepts_tool_call_arguments_without_reasoning_text(self):
        payload = {
            "paper_info": {},
            "cell_types": [],
            "relationships": [],
        }
        response = AIMessage(content="", tool_calls=[{
            "name": "emit_cell_type_extraction",
            "args": payload,
            "id": "call-1",
            "type": "tool_call",
        }])
        mock_model = MagicMock()
        mock_model.invoke.return_value = response

        result = _call_structured_with_retry(
            mock_model,
            [{"role": "user", "content": "extract"}],
            policy=ExtractionPolicy(
                max_attempts=1,
                request_timeout_seconds=45,
                chunk_timeout_seconds=60,
                max_output_tokens=5000,
            ),
        )

        assert result == payload
        assert mock_model.invoke.call_args.kwargs["tools"][0]["function"]["name"] == (
            "emit_cell_type_extraction"
        )
        assert mock_model.invoke.call_args.kwargs["tool_choice"] == "auto"

    def test_structured_request_detects_responses_api_incomplete_output(self):
        mock_model = MagicMock()
        mock_model.invoke.return_value = AIMessage(
            content=[{"type": "text", "text": '{"cell_types": ['}],
            response_metadata={
                "status": "incomplete",
                "incomplete_details": {"reason": "max_output_tokens"},
            },
        )

        with pytest.raises(StructuredExtractionError) as raised:
            _call_structured_with_retry(
                mock_model,
                [{"role": "user", "content": "bounded source block"}],
                policy=ExtractionPolicy(
                    max_attempts=2,
                    request_timeout_seconds=45,
                    chunk_timeout_seconds=150,
                    max_output_tokens=5000,
                ),
            )

        assert raised.value.kind == "truncated_response"
        assert mock_model.invoke.call_count == 1

    def test_connection_error_is_not_reported_as_invalid_json(self):
        mock_model = MagicMock()
        mock_model.invoke.side_effect = ConnectionError("provider connection failed")

        with patch("cellwiki.adapters.openai_structured_output.time.sleep"):
            with pytest.raises(StructuredExtractionError) as raised:
                _call_structured_with_retry(
                    mock_model,
                    [{"role": "user", "content": "bounded source block"}],
                    policy=ExtractionPolicy(
                        max_attempts=2,
                        request_timeout_seconds=45,
                        chunk_timeout_seconds=150,
                        max_output_tokens=5000,
                    ),
                )

        assert raised.value.kind == "connection_error"

    def test_connection_retry_allows_provider_cooldown(self):
        mock_model = MagicMock()
        mock_model.invoke.side_effect = [
            ConnectionError("provider connection failed"),
            AIMessage(
                content='{"cell_types": []}',
                response_metadata={"finish_reason": "stop"},
            ),
        ]

        with patch("cellwiki.adapters.openai_structured_output.time.sleep") as sleep:
            result = _call_structured_with_retry(
                mock_model,
                [{"role": "user", "content": "bounded source block"}],
                policy=ExtractionPolicy(
                    max_attempts=2,
                    request_timeout_seconds=45,
                    chunk_timeout_seconds=150,
                    max_output_tokens=5000,
                ),
            )

        assert result == {"cell_types": []}
        assert sleep.call_count == 1
        assert sleep.call_args.args[0] >= 5

    @pytest.mark.parametrize(
        ("error_class", "status_code", "expected"),
        [
            (AuthenticationError, 401, "authentication_error"),
            (PermissionDeniedError, 403, "permission_error"),
            (RateLimitError, 429, "rate_limit"),
            (BadRequestError, 400, "invalid_request"),
            (UnprocessableEntityError, 422, "invalid_request"),
        ],
    )
    def test_openai_http_errors_have_stable_classification(
        self,
        error_class,
        status_code,
        expected,
    ):
        response = httpx.Response(
            status_code,
            request=httpx.Request("POST", "https://provider.example/v1"),
        )
        error = error_class("provider error", response=response, body={})

        assert _classify_provider_error(error) == expected

    def test_request_timeout_is_capped_by_remaining_chunk_budget(self):
        mock_model = MagicMock()
        mock_model.invoke.side_effect = ConnectionError("provider connection failed")

        with patch("cellwiki.adapters.openai_structured_output.time.sleep"):
            with pytest.raises(StructuredExtractionError):
                _call_structured_with_retry(
                    mock_model,
                    [{"role": "user", "content": "bounded source block"}],
                    policy=ExtractionPolicy(
                        max_attempts=1,
                        request_timeout_seconds=90,
                        chunk_timeout_seconds=30,
                        max_output_tokens=5000,
                    ),
                )

        timeout = mock_model.invoke.call_args.kwargs["timeout"]
        assert 0 < timeout <= 30

    def test_sdk_length_parse_error_is_classified_as_truncation(self):
        error = RuntimeError(
            "Could not parse response content as the length limit was reached"
        )

        assert _classify_provider_error(error) == "truncated_response"

    def test_chunk_extraction_adaptively_splits_truncated_provider_output(self):
        truncated_response = AIMessage(
            content='{"cell_types": [',
            response_metadata={"finish_reason": "length"},
        )
        valid_response = json.dumps({
            "paper_info": {"title": "Fixture", "doi": "", "year": 2026},
            "cell_types": [],
            "relationships": [],
        })
        mock_model = MagicMock()
        mock_model.invoke.side_effect = [
            truncated_response,
            AIMessage(content=valid_response, response_metadata={"finish_reason": "stop"}),
            AIMessage(content=valid_response, response_metadata={"finish_reason": "stop"}),
        ]

        with patch(
            "cellwiki.adapters.openai_structured_output.build_openai_chat_model",
            return_value=mock_model,
        ):
            result = extract_cell_types_from_chunk(
                text="Regulatory T cell and FOXP3. " * 220,
                pdf_path=Path("/tmp/adaptive.pdf"),
        )

        assert result.paper.title == "Fixture"
        assert mock_model.invoke.call_count == 3

    def test_chunk_extraction_adaptively_splits_empty_response_after_timeout(self):
        successful = ExtractionResult(
            paper=PaperReference(
                paper_id="fixture",
                title="Fixture",
                doi="",
                year=2026,
                local_path="/tmp/adaptive-empty.pdf",
            ),
            cell_types=[],
            raw_relationships=[],
        )
        with patch(
            "cellwiki.adapters.openai_structured_output.extract_cell_types_from_paper",
            side_effect=[
                StructuredExtractionError("empty", kind="empty_response"),
                successful,
                successful,
            ],
        ) as extract:
            result = _extract_chunk_adaptively(
                "Regulatory T cell and FOXP3. " * 100,
                Path("/tmp/adaptive-empty.pdf"),
                control=None,
                policy=ExtractionPolicy(
                    max_attempts=1,
                    request_timeout_seconds=45,
                    chunk_timeout_seconds=150,
                    max_output_tokens=5000,
                ),
                configuration=Settings(_env_file=None),
                depth=0,
                review_feedback=None,
            )

        assert result.paper.title == "Fixture"
        assert extract.call_count == 3
