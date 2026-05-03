"""LLM-powered structured extraction of cell type information from paper text."""

import json
import logging
import re
import time
from pathlib import Path

from openai import OpenAI, APIError

from cellwiki.config import settings
from cellwiki.models import (
    ExtractionResult,
    PaperReference,
    CellTypeExtract,
    Marker,
    MarkerType,
    FunctionalCharacteristic,
)

logger = logging.getLogger(__name__)

# Chunk sizing: adapt to model context. qwen3.6-plus has 128k context.
# Use 6000 token chunks to leave room for prompt + response.
CHUNK_SIZE = 6000  # tokens per chunk
CHUNK_OVERLAP = 300  # tokens of overlap between chunks
MAX_RETRIES = 3
RETRY_BACKOFF = 2  # seconds, multiplied by 2^attempt

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
Be thorough - extract ALL cell types mentioned, even minor ones.
Use exact gene symbols (uppercase for human, title-case for mouse).
"""


def _estimate_tokens(text: str) -> int:
    """Rough token count using whitespace-based heuristic."""
    return len(re.findall(r"\b\w+\b|[^\s\w]", text))


def _split_text(text: str, max_tokens: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split text into overlapping chunks by approximate token count.

    Respects page boundaries ('--- Page N ---') as preferred split points.
    """
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
    # Remove markdown code fences if present
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    # Try to find JSON object if response has extra text
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to extract JSON from larger text
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group())
        raise


def _call_llm_with_retry(client: OpenAI, messages: list[dict], attempt: int = 0) -> str | None:
    """Call LLM with exponential backoff retry."""
    try:
        response = client.chat.completions.create(
            model=settings.openai_model,
            messages=messages,
            temperature=0,
            response_format={"type": "json_object"},
        )
        return response.choices[0].message.content
    except APIError as e:
        if attempt >= MAX_RETRIES - 1:
            logger.error(f"LLM API call failed after {MAX_RETRIES} attempts: {e}")
            return None
        wait = RETRY_BACKOFF * (2 ** attempt)
        logger.warning(f"LLM API error (attempt {attempt + 1}/{MAX_RETRIES}), retrying in {wait}s: {e}")
        time.sleep(wait)
        return _call_llm_with_retry(client, messages, attempt + 1)
    except Exception as e:
        logger.error(f"Unexpected error in LLM call: {e}")
        if attempt < MAX_RETRIES - 1:
            wait = RETRY_BACKOFF * (2 ** attempt)
            time.sleep(wait)
            return _call_llm_with_retry(client, messages, attempt + 1)
        return None


def _validate_gene_symbol(symbol: str) -> bool:
    """Basic validation: gene symbols are short alphanumeric strings."""
    return bool(re.match(r"^[A-Za-z0-9\-]+$", symbol)) and len(symbol) < 30


def extract_cell_types_from_paper(text: str, pdf_path: Path) -> ExtractionResult:
    """Send paper text to OpenAI for structured cell type extraction.

    Handles long papers by chunking and merging results.
    Includes retry logic and error handling.
    """
    client = OpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url or None,
    )

    chunks = _split_text(text)
    logger.info(f"Paper split into {len(chunks)} chunk(s)")
    print(f"  Paper split into {len(chunks)} chunk(s)")

    all_cell_types = []
    all_relationships = []
    paper_info = {}
    failed_chunks = []

    for i, chunk in enumerate(chunks):
        logger.info(f"Processing chunk {i + 1}/{len(chunks)}")
        print(f"  Processing chunk {i + 1}/{len(chunks)}...")

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Extract cell type information from this paper:\n\n{chunk}"},
        ]

        content = _call_llm_with_retry(client, messages)
        if content is None:
            logger.error(f"Chunk {i + 1} failed after retries, skipping")
            failed_chunks.append(i + 1)
            continue

        try:
            data = _parse_llm_response(content)
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error in chunk {i + 1}: {e}")
            print(f"  Warning: JSON parse error in chunk {i + 1}, skipping")
            failed_chunks.append(i + 1)
            continue

        if not paper_info and "paper_info" in data:
            paper_info = data["paper_info"]

        if "cell_types" in data:
            all_cell_types.extend(data["cell_types"])

        if "relationships" in data:
            all_relationships.extend(data["relationships"])

    if failed_chunks:
        logger.warning(f"Failed chunks: {failed_chunks}")
        print(f"  Warning: {len(failed_chunks)} chunk(s) failed: {failed_chunks}")

    # Build ExtractionResult
    paper_ref = PaperReference(
        paper_id=pdf_path.stem,
        title=paper_info.get("title", pdf_path.stem),
        doi=paper_info.get("doi", ""),
        year=paper_info.get("year", 0),
        local_path=str(pdf_path),
    )

    cell_type_objs = []
    for ct in all_cell_types:
        markers = []
        for m in ct.get("markers", []):
            gene = m.get("gene_symbol", "")
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
                evidence=m.get("evidence", ""),
                strength=m.get("strength", ""),
            ))

        functions = []
        for f in ct.get("functions", []):
            functions.append(FunctionalCharacteristic(
                description=f.get("description", ""),
                pathway=f.get("pathway", ""),
                evidence=f.get("evidence", ""),
            ))

        cell_type_objs.append(CellTypeExtract(
            name=ct.get("name", ""),
            standard_name=ct.get("standard_name", ""),
            cl_id=None,
            synonyms=ct.get("synonyms", []),
            parent_type=ct.get("parent_type"),
            species=ct.get("species", []),
            tissues=ct.get("tissues", []),
            diseases=ct.get("diseases", []),
            markers=markers,
            functions=functions,
            subpopulations=ct.get("subpopulations", []),
            description=ct.get("description", ""),
            paper_ref=paper_ref,
        ))

    # Deduplicate by standard_name within same paper
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
