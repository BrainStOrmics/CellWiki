"""Stable Wiki projection rendering Interface."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from cellwiki.domain.extraction import ExtractionResult


class WikiProjectionRenderer(Protocol):
    """Materialize rebuildable Wiki pages from approved extraction records."""

    def render(
        self,
        extractions: list[ExtractionResult],
        *,
        wiki_dir: Path,
        curation_dir: Path,
    ) -> list[str]: ...
