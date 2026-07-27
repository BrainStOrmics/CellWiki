# =============================================================================
# LLM 结构化提取 —— 从论文文本中提取细胞类型信息
# =============================================================================
# 将长论文分割为重叠块，使用重试逻辑调用 OpenAI 兼容 API，
# 并将结果合并为经过验证的领域模型。自适应分块策略通过在截断错误时
# 二分切割来透明处理提供商的上下文限制。
# =============================================================================

"""LLM-powered structured extraction of cell type information from paper text.

Splits long papers into overlapping chunks, calls OpenAI-compatible APIs with
retry logic, and merges results into a validated domain model.  The adaptive
chunking strategy handles provider context limits transparently by bisecting
on truncation errors."""

import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage
from openai import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    PermissionDeniedError,
    RateLimitError,
    UnprocessableEntityError,
)

from cellwiki.adapters.openai_model import build_openai_chat_model
from cellwiki.config import Settings, settings
from cellwiki.models import (
    ExtractionResult,
    PaperReference,
    CellTypeExtract,
    Marker,
    MarkerType,
    FunctionalCharacteristic,
)
from cellwiki.services.operations import OperationCancelled, OperationControl

logger = logging.getLogger(__name__)

# Chunk sizing: adapt to model context. qwen3.6-plus has 128k context.
# Use 6000 token chunks to leave room for prompt + response.
CHUNK_SIZE = 6000  # tokens per chunk
CHUNK_OVERLAP = 300  # tokens of overlap between chunks
# Exponential backoff base: 5s, 10s, 20s, ... capped by max_attempts.
# Compatible gateways and local proxies may need several seconds to recover
# after a long structured request drops its connection.
RETRY_BACKOFF = 5  # seconds, multiplied by 2^attempt
# The compatible Qwen endpoint can spend excessive time honoring a large output
# ceiling even when the final JSON is small. A timeout retry uses a bounded
# fallback ceiling so it changes the request shape instead of repeating the same
# slow request.
TIMEOUT_RETRY_OUTPUT_TOKENS = 2_000


class StructuredExtractionError(RuntimeError):
    """Raised when a provider response cannot satisfy the extraction JSON contract."""

    def __init__(self, message: str, *, kind: str = "invalid_response"):
        super().__init__(message)
        self.kind = kind


@dataclass(frozen=True)
class ExtractionPolicy:
    """One explicit budget shared by transport and JSON-validation failures."""

    max_attempts: int
    request_timeout_seconds: float
    chunk_timeout_seconds: float
    max_output_tokens: int
    retry_backoff_seconds: float = RETRY_BACKOFF

    @classmethod
    def from_settings(cls, configuration: Settings = settings) -> "ExtractionPolicy":
        """Build retry and timeout budgets from the shared application settings."""
        return cls(
            max_attempts=configuration.ingest_max_attempts,
            request_timeout_seconds=configuration.openai_request_timeout_seconds,
            chunk_timeout_seconds=configuration.ingest_chunk_timeout_seconds,
            max_output_tokens=configuration.ingest_max_output_tokens,
        )

SYSTEM_PROMPT = """You are a single-cell biology expert analyzing a scientific paper.

Extract structured information about all cell types and subpopulations mentioned.
For each cell type, identify:
- The exact name used in the paper
- A standardized name using biological terminology (e.g. "regulatory_t_cell", NOT "cd4_c11_il10")
- All marker genes/proteins (positive, negative, or transcript-level)
- Tissue and disease context
- Species
- Functional characteristics and pathways
- Parent/child relationships to other cell types

IMPORTANT for standard_name:
- Use common biological names, NOT paper-internal cluster IDs like "cd4_c01_ccr7"
- Examples: "regulatory_t_cell", "cd8_exhausted_t_cell", "tumor_associated_macrophage"
- If the paper uses a novel subtype, name it by its defining feature: "spp1_positive_macrophage"

Respond ONLY with a valid JSON object matching this exact structure:
If the chunk has no cell-type facts, still return the same object with empty
`cell_types` and `relationships` arrays; never return prose or an empty response.

{
  "paper_info": {
    "title": "...",
    "doi": "...",
    "year": 2024
  },
  "cell_types": [
    {
      "name": "exact name from paper",
      "standard_name": "biological_name_lowercase_underscores",
      "synonyms": ["alt name 1", "alt name 2"],
      "parent_type": "broader cell type or null",
      "species": ["Homo sapiens", "Mus musculus"],
      "tissues": ["colorectal tumor", "peripheral blood"],
      "diseases": ["colorectal cancer"],
      "markers": [
        {"gene_symbol": "CD8A", "marker_type": "positive", "evidence": "...", "strength": "high"}
      ],
      "functions": [
        {"description": "...", "pathway": "...", "evidence": "..."}
      ],
      "subpopulations": ["child type 1", "child type 2"],
      "description": "one-sentence summary"
    }
  ],
  "relationships": [
    {"source": "cell_type_a", "relation": "is_a", "target": "cell_type_b"}
  ]
}

marker_type must be one of: "positive", "negative", "transcript".
Extract only facts explicitly supported by the supplied chunk. To keep the
response bounded, return at most 12 cell types, 15 markers per cell type,
6 functions, 6 synonyms, and 6 subpopulations. Keep each evidence string under
160 characters and each description under 200 characters. Prefer biologically relevant
mentions over incidental citations or reference-list text.
Use exact gene symbols (uppercase for human, title-case for mouse).
"""

# Tool calling gives reasoning-capable providers a typed result channel.  The
# model may reason internally, but the ingest pipeline only accepts arguments
# returned by this function and never treats reasoning summaries as data.
EXTRACTION_TOOL = {
    "type": "function",
    "function": {
        "name": "emit_cell_type_extraction",
        "description": "Return the validated cell-type extraction for this paper chunk.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "paper_info": {"type": "object"},
                "cell_types": {"type": "array", "items": {"type": "object"}},
                "relationships": {"type": "array", "items": {"type": "object"}},
            },
            "required": ["paper_info", "cell_types", "relationships"],
            "additionalProperties": False,
        },
    },
}


def _estimate_tokens(text: str) -> int:
    """Rough token count using whitespace-based heuristic.

    Avoids a tokenizer dependency for chunk-boundary decisions.  Underestimates
    dense CJK text but that is acceptable — it only means slightly smaller chunks
    rather than correctness issues.
    """
    return len(re.findall(r"\b\w+\b|[^\s\w]", text))


def _split_text(text: str, max_tokens: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split text into overlapping chunks by approximate token count.

    Respects page boundaries ('--- Page N ---') as preferred split points.
    """
    # Split on page boundaries first so each chunk starts at a natural break
    # point.  This preserves figure/table captions that span pages and prevents
    # mid-sentence splits that confuse the LLM.
    page_sections = re.split(r"(?=--- Page \d+ ---\n)", text)
    page_sections = [s.strip() for s in page_sections if s.strip()]

    # If the whole text fits, don't split
    if _estimate_tokens(text) <= max_tokens:
        return [text]

    chunks = []
    current = ""
    for section in page_sections:
        if _estimate_tokens(current + section) > max_tokens and current:
            chunks.append(current)
            # Carry trailing tokens from the prior chunk as overlap so the LLM
            # has context for relationships that span the split boundary.
            words = current.split()
            overlap_text = " ".join(words[-overlap:]) if len(words) > overlap else current
            current = overlap_text + "\n" + section
        else:
            current = current + "\n" + section if current else section

    if current:
        chunks.append(current)

    return chunks


def _parse_llm_response(text: str) -> dict:
    """Extract JSON from LLM response, handling markdown code fences and trailing text."""
    text = text.strip()
    # Remove markdown code fences — some providers wrap JSON in ```json blocks.
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    # Try to find JSON object if response has extra text
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Fallback for providers that embed the JSON inside prose or
        # chain-of-thought output.  The first top-level {} is typically
        # the structured response.
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group())
        raise


def _call_structured_with_retry(
    model: BaseChatModel,
    messages: list[dict],
    *,
    policy: ExtractionPolicy,
    control: OperationControl | None = None,
) -> dict:
    """Use one total attempt budget for transport and structured-output failures."""

    started = time.monotonic()
    last_error: Exception | None = None
    output_tokens = policy.max_output_tokens
    # Track last_state separately from last_error so we can map it to a
    # human-readable reason string when all attempts are exhausted.
    last_state = "invalid_response"
    for attempt_index in range(policy.max_attempts):
        attempt = attempt_index + 1
        if control is not None:
            control.raise_if_cancelled()
        elapsed = time.monotonic() - started
        # Enforce a hard deadline across all retries so a single stuck chunk
        # does not consume the entire pipeline timeout.
        if elapsed >= policy.chunk_timeout_seconds:
            raise StructuredExtractionError(
                f"structured extraction timed out after {elapsed:.1f}s",
                kind="request_timeout",
            )
        if control is not None:
            control.report(
                "request_started",
                attempt=attempt,
                max_attempts=policy.max_attempts,
                attempt_elapsed_seconds=elapsed,
            )

        attempt_started = time.monotonic()
        try:
            remaining_seconds = max(0.1, policy.chunk_timeout_seconds - elapsed)
            response = model.invoke(
                messages,
                tools=[EXTRACTION_TOOL],
                # Some reasoning-compatible gateways reject the OpenAI
                # ``required``/named-function form while thinking is enabled.
                # ``auto`` is accepted by those gateways; the system prompt
                # still requires the extraction tool and the JSON path remains
                # available for providers that choose not to emit a tool call.
                tool_choice="auto",
                response_format={"type": "json_object"},
                max_completion_tokens=output_tokens,
                timeout=min(policy.request_timeout_seconds, remaining_seconds),
            )
            if _response_is_truncated(response):
                raise StructuredExtractionError(
                    "provider truncated structured response at the output limit",
                    kind="truncated_response",
                )
            tool_calls = getattr(response, "tool_calls", None) or []
            if tool_calls:
                arguments = tool_calls[0].get("args") or tool_calls[0].get("arguments")
                if isinstance(arguments, dict):
                    data = arguments
                else:
                    data = _parse_llm_response(str(arguments or ""))
                if control is not None:
                    control.report(
                        "request_completed",
                        attempt=attempt,
                        max_attempts=policy.max_attempts,
                        attempt_elapsed_seconds=time.monotonic() - attempt_started,
                    )
                return data
            content = _message_text(response)
            if not content:
                # A few compatible providers expose their final JSON through this
                # extension. It is parsed as output only and is never persisted as
                # reasoning or shown in the conversation transcript.
                content = str(response.additional_kwargs.get("reasoning_content") or "")
            if not content:
                raise StructuredExtractionError(
                    "provider returned no response content",
                    kind="empty_response",
                )
            data = _parse_llm_response(content)
            if control is not None:
                control.report(
                    "request_completed",
                    attempt=attempt,
                    max_attempts=policy.max_attempts,
                    attempt_elapsed_seconds=time.monotonic() - attempt_started,
                )
            return data
        except OperationCancelled:
            raise
        except Exception as error:
            last_error = error
            state = _classify_provider_error(error)
            last_state = state
            if control is not None:
                control.report(
                    state,
                    attempt=attempt,
                    max_attempts=policy.max_attempts,
                    attempt_elapsed_seconds=time.monotonic() - attempt_started,
                    error=str(error)[:300],
                )
            if state in {
                "truncated_response",
                "authentication_error",
                "permission_error",
                "invalid_request",
            }:
                # Repeating the same oversized request wastes the entire budget.
                # Authentication, permission, and request-shape failures are also
                # deterministic, so retries only waste time and provider quota.
                if isinstance(error, StructuredExtractionError):
                    raise
                raise StructuredExtractionError(str(error), kind=state) from error
            if state == "request_timeout":
                output_tokens = min(policy.max_output_tokens, TIMEOUT_RETRY_OUTPUT_TOKENS)
            if attempt >= policy.max_attempts:
                break
            wait = policy.retry_backoff_seconds * (2**attempt_index)
            remaining_seconds = policy.chunk_timeout_seconds - (
                time.monotonic() - started
            )
            if remaining_seconds <= 0:
                raise StructuredExtractionError(
                    "structured extraction exhausted the chunk deadline",
                    kind="request_timeout",
                ) from error
            wait = min(wait, remaining_seconds)
            logger.warning(
                "Extraction attempt %s/%s failed (%s); retrying in %.1fs: %s",
                attempt,
                policy.max_attempts,
                state,
                wait,
                error,
            )
            if control is None:
                time.sleep(wait)
            else:
                control.wait(wait)

    reason = {
        "request_timeout": "request timed out",
        "connection_error": "provider connection failed",
        "authentication_error": "provider authentication failed",
        "permission_error": "provider permission denied",
        "rate_limit": "provider rate limit exceeded",
        "truncated_response": "provider truncated the structured response",
        "empty_response": "provider returned an empty response",
        "invalid_json": "provider returned invalid JSON",
        "invalid_request": "provider rejected the request shape",
        "invalid_response": "invalid structured response",
    }[last_state]
    raise StructuredExtractionError(
        f"structured output failed after {policy.max_attempts} attempts; {reason}: {last_error}",
        kind=last_state,
    )


def _is_timeout_error(error: Exception) -> bool:
    """Check if an exception represents a timeout, regardless of the exception type.

    httpx, urllib, and provider gateways each raise distinct types; inspect the
    string representation to catch all variants without fragile imports.
    """
    text = f"{type(error).__name__}: {error}".lower()
    return (
        isinstance(error, (TimeoutError, APITimeoutError))
        or "timeout" in text
        or "timed out" in text
    )


def _classify_provider_error(error: Exception) -> str:
    """Map transport, HTTP, and parsing failures to stable ingest error kinds."""

    if isinstance(error, StructuredExtractionError):
        return error.kind
    if _is_timeout_error(error):
        return "request_timeout"
    if isinstance(error, (APIConnectionError, ConnectionError)):
        return "connection_error"
    if isinstance(error, AuthenticationError):
        return "authentication_error"
    if isinstance(error, PermissionDeniedError):
        return "permission_error"
    if isinstance(error, RateLimitError):
        return "rate_limit"
    if isinstance(error, (BadRequestError, UnprocessableEntityError)):
        return "invalid_request"
    if isinstance(error, json.JSONDecodeError):
        return "invalid_json"

    text = f"{type(error).__name__}: {error}".lower()
    if "length limit" in text or "finish reason was length" in text:
        return "truncated_response"
    if "connection" in text or "connect" in text:
        return "connection_error"
    if "401" in text or "authentication" in text or "api key" in text:
        return "authentication_error"
    if "403" in text or "permission" in text or "forbidden" in text:
        return "permission_error"
    if "429" in text or "rate limit" in text:
        return "rate_limit"
    return "invalid_response"


def _message_text(message: BaseMessage) -> str:
    """Normalize Chat Completions strings and Responses API text blocks."""

    text = message.text
    return text if isinstance(text, str) else str(text)


def _response_is_truncated(message: BaseMessage) -> bool:
    """Recognize output-limit termination metadata from both provider protocols."""

    metadata = message.response_metadata
    if metadata.get("finish_reason") == "length":
        return True
    if metadata.get("status") != "incomplete":
        return False
    details = metadata.get("incomplete_details")
    reason = details.get("reason") if isinstance(details, dict) else str(details or "")
    return reason in {"max_output_tokens", "max_tokens"}


def _validate_gene_symbol(symbol: str) -> bool:
    """Basic validation: gene symbols are short alphanumeric strings."""
    return bool(re.match(r"^[A-Za-z0-9\-]+$", symbol)) and len(symbol) < 30


def extract_cell_types_from_paper(
    text: str,
    pdf_path: Path,
    *,
    control: OperationControl | None = None,
    policy: ExtractionPolicy | None = None,
    configuration: Settings = settings,
    _already_chunked: bool = False,
    review_feedback: list[str] | None = None,
) -> ExtractionResult:
    """Send paper text to OpenAI for structured cell type extraction.

    Handles long papers by chunking and merging results.
    Includes retry logic and error handling.
    """
    active_policy = policy or ExtractionPolicy.from_settings(configuration)
    model = build_openai_chat_model(
        configuration,
        timeout_seconds=active_policy.request_timeout_seconds,
        max_retries=0,
        purpose="structured",
    )
    # Spawn a watcher thread that forcibly closes the HTTP client when the
    # user cancels the operation.  This unblocks any in-flight request so
    # the pipeline can shut down promptly rather than waiting for a timeout.
    watcher_stop = threading.Event()
    watcher = _watch_cancellation(model.root_client, control, watcher_stop)

    chunks = [text] if _already_chunked else _split_text(text)
    # When _already_chunked is True the caller has already split (e.g. the
    # adaptive chunker) and we should treat the whole text as a single chunk.
    logger.info(f"Paper split into {len(chunks)} chunk(s)")
    print(f"  Paper split into {len(chunks)} chunk(s)")

    all_cell_types = []
    all_relationships = []
    paper_info = {}
    try:
        for i, chunk in enumerate(chunks):
            logger.info(f"Processing chunk {i + 1}/{len(chunks)}")
            print(f"  Processing chunk {i + 1}/{len(chunks)}...")

            feedback_instruction = ""
            if review_feedback:
                feedback_instruction = (
                    "\n\nReviewer feedback to address in this re-ingest:\n"
                    + "\n".join(f"- {item}" for item in review_feedback)
                )
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"Extract cell type information from this paper:\n\n{chunk}"
                        f"{feedback_instruction}"
                    ),
                },
            ]

            data = _call_structured_with_retry(
                model,
                messages,
                policy=active_policy,
                control=control,
            )

            if not paper_info and isinstance(data.get("paper_info"), dict):
                # Keep the first chunk's paper_info (title, DOI, year) and
                # ignore subsequent chunks' metadata to avoid overwriting
                # with potentially inconsistent values.
                paper_info = data["paper_info"]

            if isinstance(data.get("cell_types"), list):
                all_cell_types.extend(data["cell_types"][:12])

            if isinstance(data.get("relationships"), list):
                all_relationships.extend(data["relationships"][:100])
    finally:
        watcher_stop.set()
        if watcher is not None:
            watcher.join(timeout=0.2)
        model.root_client.close()

    # Build ExtractionResult
    paper_ref = PaperReference(
        paper_id=pdf_path.stem,
        # Structured-output providers commonly encode unavailable metadata as
        # JSON null. Normalize it at this adapter boundary before domain validation.
        title=_string_or_default(paper_info.get("title"), pdf_path.stem),
        doi=_string_or_default(paper_info.get("doi"), ""),
        year=_integer_or_default(paper_info.get("year"), 0),
        local_path=str(pdf_path),
    )

    cell_type_objs = []
    for ct in all_cell_types:
        if not isinstance(ct, dict):
            continue
        markers = []
        for m in _list_or_empty(ct.get("markers"))[:15]:
            if not isinstance(m, dict):
                continue
            gene = _string_or_default(m.get("gene_symbol"), "")
            if gene and not _validate_gene_symbol(gene):
                logger.warning(f"Skipping invalid gene symbol: {gene}")
                continue
            try:
                mtype = MarkerType(m["marker_type"])
            except (KeyError, ValueError):
                mtype = MarkerType.TRANSCRIPT
            markers.append(Marker(
                gene_symbol=gene,
                marker_type=mtype,
                evidence=_string_or_default(m.get("evidence"), ""),
                strength=_string_or_default(m.get("strength"), ""),
            ))

        functions = []
        for f in _list_or_empty(ct.get("functions"))[:6]:
            if not isinstance(f, dict):
                continue
            functions.append(FunctionalCharacteristic(
                description=_string_or_default(f.get("description"), ""),
                pathway=_string_or_default(f.get("pathway"), ""),
                evidence=_string_or_default(f.get("evidence"), ""),
            ))

        cell_type_objs.append(CellTypeExtract(
            name=_string_or_default(ct.get("name"), ""),
            standard_name=_string_or_default(ct.get("standard_name"), ""),
            cl_id=None,
            synonyms=[str(value) for value in _list_or_empty(ct.get("synonyms"))[:6]],
            parent_type=_optional_string(ct.get("parent_type")),
            species=[str(value) for value in _list_or_empty(ct.get("species"))],
            tissues=[str(value) for value in _list_or_empty(ct.get("tissues"))],
            diseases=[str(value) for value in _list_or_empty(ct.get("diseases"))],
            markers=markers,
            functions=functions,
            subpopulations=[str(value) for value in _list_or_empty(ct.get("subpopulations"))[:6]],
            description=_string_or_default(ct.get("description"), ""),
            paper_ref=paper_ref,
        ))

    # Deduplicate by standard_name within same paper.
    # When the same cell type appears in multiple chunks, merge its markers,
    # functions, and other collection fields rather than keeping duplicates.
    seen = {}
    for ct in cell_type_objs:
        if ct.standard_name in seen:
            existing = seen[ct.standard_name]
            existing.markers.extend(ct.markers)
            existing.functions.extend(ct.functions)
            existing.synonyms.extend(ct.synonyms)
            existing.tissues.extend(ct.tissues)
            existing.diseases.extend(ct.diseases)
            existing.species.extend(ct.species)
        else:
            seen[ct.standard_name] = ct

    logger.info(f"Extracted {len(seen)} unique cell types from {pdf_path.name}")

    return ExtractionResult(
        paper=paper_ref,
        cell_types=list(seen.values()),
        raw_relationships=all_relationships,
    )


def extract_cell_types_from_chunk(
    text: str,
    pdf_path: Path,
    *,
    control: OperationControl | None = None,
    policy: ExtractionPolicy | None = None,
    configuration: Settings = settings,
    review_feedback: list[str] | None = None,
) -> ExtractionResult:
    """Extract one grounded chunk, splitting only when the provider truncates it."""

    return _extract_chunk_adaptively(
        text,
        pdf_path,
        control=control,
        policy=policy or ExtractionPolicy.from_settings(configuration),
        configuration=configuration,
        depth=0,
        review_feedback=review_feedback,
    )


def _extract_chunk_adaptively(
    text: str,
    pdf_path: Path,
    *,
    control: OperationControl | None,
    policy: ExtractionPolicy,
    configuration: Settings,
    depth: int,
    review_feedback: list[str] | None,
) -> ExtractionResult:
    try:
        return extract_cell_types_from_paper(
            text,
            pdf_path,
            control=control,
            policy=policy,
            configuration=configuration,
            _already_chunked=True,
            review_feedback=review_feedback,
        )
    except StructuredExtractionError as error:
        # A reasoning provider can time out and then return an empty reasoning
        # envelope for the same large input. Retrying that exact payload is not
        # useful; reduce the evidence window just as we do for truncation.
        adaptive_failure_kinds = {
            "truncated_response",
            "request_timeout",
            "empty_response",
        }
        if error.kind not in adaptive_failure_kinds or depth >= 3 or len(text) < 1_200:
            raise
        left, right = _split_adaptive_text(text)
        logger.warning(
            "Structured response was truncated; splitting %s characters into %s and %s",
            len(text),
            len(left),
            len(right),
        )
        results = [
            _extract_chunk_adaptively(
                part,
                pdf_path,
                control=control,
                policy=policy,
                configuration=configuration,
                depth=depth + 1,
                review_feedback=review_feedback,
            )
            for part in (left, right)
        ]
        return ExtractionResult(
            paper=results[0].paper,
            cell_types=[cell for result in results for cell in result.cell_types],
            raw_relationships=[
                relationship
                for result in results
                for relationship in result.raw_relationships
            ],
        )


def _split_adaptive_text(text: str) -> tuple[str, str]:
    """Bisect near a textual boundary without dropping source characters."""

    midpoint = len(text) // 2
    lower = max(1, midpoint - len(text) // 5)
    upper = min(len(text) - 1, midpoint + len(text) // 5)
    candidates: list[int] = []
    for marker in ("\n\n", "\n", ". ", "; ", ", ", " "):
        before = text.rfind(marker, lower, midpoint + 1)
        after = text.find(marker, midpoint, upper)
        if before >= 0:
            candidates.append(before + len(marker))
        if after >= 0:
            candidates.append(after + len(marker))
    split_at = min(candidates, key=lambda value: abs(value - midpoint)) if candidates else midpoint
    left, right = text[:split_at].strip(), text[split_at:].strip()
    if not left or not right:
        left, right = text[:midpoint].strip(), text[midpoint:].strip()
    return left, right


def _watch_cancellation(
    client: Any,
    control: OperationControl | None,
    stop: threading.Event,
) -> threading.Thread | None:
    """Close the HTTP client when cancellation is requested to unblock an active read."""

    if control is None:
        return None

    def watch() -> None:
        while not stop.wait(0.1):
            if control.cancelled:
                # Closing httpx from the watcher interrupts most in-flight transports;
                # the bounded request timeout remains the fallback for providers that do not.
                client.close()
                return

    thread = threading.Thread(target=watch, name="cellwiki-extraction-cancel", daemon=True)
    thread.start()
    return thread


def _list_or_empty(value):
    """Return the list unchanged, or [] for None/scalar — safe for JSON field access."""
    return value if isinstance(value, list) else []


def _string_or_default(value, default: str) -> str:
    """Coerce to str, falling back to the given default for None or empty input."""
    return str(value) if value not in (None, "") else default


def _optional_string(value) -> str | None:
    """Like _string_or_default but returns None for missing values (nullable field)."""
    return str(value) if value not in (None, "") else None


def _integer_or_default(value, default: int) -> int:
    """Coerce to int, falling back to the given default for None/empty/non-numeric."""
    try:
        return int(value) if value not in (None, "") else default
    except (TypeError, ValueError):
        return default
