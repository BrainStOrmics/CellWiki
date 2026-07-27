"""Build the user-facing Wiki projection from formal facts and curation."""

from __future__ import annotations

import json
from pathlib import Path

from cellwiki.adapters.wiki_renderer import CellWikiMarkdownRenderer
from cellwiki.domain.extraction import ExtractionResult
from cellwiki.services.rendering import WikiProjectionRenderer


class ProjectionService:
    """Load formal extraction records and materialize disposable Wiki Markdown."""

    def __init__(
        self,
        project_root: Path,
        *,
        renderer: WikiProjectionRenderer | None = None,
    ):
        self.project_root = Path(project_root).resolve()
        self.extraction_dir = self.project_root / "data" / "extraction"
        self.wiki_dir = self.project_root / "wiki"
        self.curation_dir = self.wiki_dir / "curation" / "cell_types"
        self.renderer = renderer or CellWikiMarkdownRenderer()

    def render(self) -> list[str]:
        """Rebuild all generated pages and return their stable page identifiers."""

        extractions = self._load_extractions()
        if not extractions:
            return []
        return self.renderer.render(
            extractions,
            wiki_dir=self.wiki_dir,
            curation_dir=self.curation_dir,
        )

    def _load_extractions(self) -> list[ExtractionResult]:
        """Load approved extraction truth in deterministic filename order."""

        if not self.extraction_dir.exists():
            return []
        return [
            ExtractionResult(**json.loads(path.read_text(encoding="utf-8")))
            for path in sorted(self.extraction_dir.glob("*.json"))
        ]
