"""Read-only formal knowledge queries for the Product API and Agent tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cellwiki.api.reader import WikiReader
from cellwiki.domain.query import QueryHit, QueryPage, QueryResponse
from cellwiki.services.changesets import ChangeSetRepository
from cellwiki.services.pipeline import KnowledgePipelineHarness


class FormalQueryService:
    """Expose only the published Wiki projection through a structured contract."""

    def __init__(
        self,
        project_root: Path,
        *,
        reader: WikiReader | None = None,
        pipeline: KnowledgePipelineHarness | None = None,
        changesets: ChangeSetRepository | None = None,
    ):
        self.project_root = Path(project_root).resolve()
        self.reader = reader or WikiReader(self.project_root)
        self.pipeline = pipeline or KnowledgePipelineHarness(self.project_root)
        self.changesets = changesets or ChangeSetRepository(self.project_root)

    def search(self, query: str, limit: int = 20) -> QueryResponse:
        normalized_query = " ".join(query.split())
        raw_results = self.reader.search(normalized_query, limit=max(1, min(limit, 100)))
        results: list[QueryHit] = []
        for item in raw_results:
            page = self.reader.read_page(str(item["page_id"]))
            results.append(
                QueryHit(
                    page_id=str(item["page_id"]),
                    title=str(page["frontmatter"].get("display_name") or item["page_id"]),
                    snippet=str(item["snippet"]),
                    score=int(item["score"]),
                    source_ids=_source_ids(page["frontmatter"]),
                )
            )
        return QueryResponse(
            query=normalized_query,
            knowledge_version=self.pipeline.current_knowledge_version(),
            results=results,
            pending_change_set_count=self._pending_change_set_count(),
            warnings=(
                ["pending_changesets_excluded"]
                if self._pending_change_set_count()
                else []
            ),
        )

    def read_page(self, page_id: str) -> QueryPage:
        page = self.reader.read_page(page_id)
        return QueryPage(
            page_id=page["page_id"],
            path=page["path"],
            frontmatter=page["frontmatter"],
            markdown=page["markdown"],
            knowledge_version=self.pipeline.current_knowledge_version(),
            source_ids=_source_ids(page["frontmatter"]),
        )

    def _pending_change_set_count(self) -> int:
        commits_dir = self.project_root / "data" / "runtime" / "commits"
        return sum(
            not (commits_dir / f"{change_set.change_set_id}.json").exists()
            for change_set in self.changesets.list()
        )


def _source_ids(frontmatter: dict[str, Any]) -> list[str]:
    """Extract stable source IDs from renderer-owned reference metadata."""

    values: list[str] = []
    references = frontmatter.get("references", [])
    if isinstance(references, list):
        for reference in references:
            if isinstance(reference, dict):
                source_id = reference.get("source_id") or reference.get("paper_id")
                if isinstance(source_id, str) and source_id and source_id not in values:
                    values.append(source_id)
    sources = frontmatter.get("sources", [])
    if isinstance(sources, list):
        for source_id in sources:
            if isinstance(source_id, str) and source_id and source_id not in values:
                values.append(source_id)
    return values
