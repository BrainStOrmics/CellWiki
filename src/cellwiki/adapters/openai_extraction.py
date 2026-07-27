"""OpenAI-compatible Adapter for the governed ingest extraction Interface."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from cellwiki.adapters.openai_model import provider_request_options
from cellwiki.adapters.openai_structured_output import extract_cell_types_from_chunk
from cellwiki.config import Settings, settings
from cellwiki.domain.contracts import SourceRecord
from cellwiki.domain.documents import DocumentChunk
from cellwiki.domain.extraction import ExtractionResult
from cellwiki.services.operations import OperationControl


class OpenAIChunkExtractor:
    """Adapt the validated structured-output client to chunk-level ingest."""

    name = "openai-cell-extractor"
    version = "4"

    def __init__(self, configuration: Settings = settings):
        self.configuration = configuration

    @property
    def cache_identity(self) -> str:
        """Hash every non-secret provider input that can change extraction output."""

        material = json.dumps(
            {
                "base_url": self.configuration.openai_base_url.rstrip("/"),
                "model": self.configuration.openai_model,
                "protocol": self.configuration.openai_api_protocol,
                "max_output_tokens": self.configuration.ingest_max_output_tokens,
                "request_options": provider_request_options(
                    self.configuration.openai_base_url,
                    self.configuration.openai_model,
                    purpose="structured",
                ),
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:20]
        return f"{self.name}:{self.version}:{digest}"

    def extract(
        self,
        chunk: DocumentChunk,
        source: SourceRecord,
        *,
        control: OperationControl | None = None,
        review_feedback: list[str] | None = None,
    ) -> ExtractionResult:
        """Extract one bounded chunk through the OpenAI-compatible implementation."""

        return extract_cell_types_from_chunk(
            chunk.text,
            Path(source.stored_path),
            control=control,
            configuration=self.configuration,
            review_feedback=review_feedback,
        )
