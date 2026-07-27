"""Stable extraction Interface consumed by the governed ingest Module."""

from __future__ import annotations

from typing import Protocol

from cellwiki.domain.contracts import SourceRecord
from cellwiki.domain.documents import DocumentChunk
from cellwiki.domain.extraction import ExtractionResult
from cellwiki.services.operations import OperationControl


class ChunkExtractor(Protocol):
    """Extract structured candidates from one evidence-aware document chunk."""

    name: str
    version: str

    @property
    def cache_identity(self) -> str: ...

    def extract(
        self,
        chunk: DocumentChunk,
        source: SourceRecord,
        *,
        control: OperationControl | None = None,
        review_feedback: list[str] | None = None,
    ) -> ExtractionResult: ...
