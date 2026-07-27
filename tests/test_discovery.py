# =============================================================================
# 发现服务测试 —— 验证可重建的 FTS5 和溯源图投影
# =============================================================================

"""Repository-level tests for rebuildable FTS5 and provenance graph projections."""

from __future__ import annotations

import json
from pathlib import Path

from cellwiki.domain.discovery import GraphEdgeType, GraphNodeType, SearchDocumentType
from cellwiki.services.discovery import DiscoveryIndex
from cellwiki.services.sources import SourceRegistry


def _seed_project(root: Path) -> str:
    wiki_dir = root / "wiki" / "cell_types"
    wiki_dir.mkdir(parents=True)
    (wiki_dir / "regulatory_t_cell.md").write_text(
        "---\ndisplay_name: Regulatory T cell\n---\n# Regulatory T cell\n\nFOXP3 marker.\n",
        encoding="utf-8",
    )
    source_file = root / "paper.md"
    source_file.write_text("Regulatory T cells express FOXP3.", encoding="utf-8")
    registry = SourceRegistry(root)
    source = registry.register(source_file, source_type="paper")
    registry.update_metadata(source.source_id, {"paper_identity": {"title": "Treg paper", "year": 2025}})
    extraction_dir = root / "data" / "extraction"
    extraction_dir.mkdir(parents=True)
    extraction = {
        "paper": {"paper_id": source.source_id},
        "cell_types": [
            {
                "name": "Regulatory T cell",
                "standard_name": "regulatory_t_cell",
                "markers": [{"gene_symbol": "FOXP3", "marker_type": "positive"}],
            }
        ],
        "claims": [
            {
                "claim_id": "claim_foxp3",
                "subject": "regulatory_t_cell",
                "predicate": "expresses",
                "object": "FOXP3",
                "qualifiers": {"species": "human"},
                "confidence": "high",
                "evidence": [
                    {
                        "evidence_id": "ev_foxp3",
                        "source_id": source.source_id,
                        "locator": "page:2:block:results",
                        "block_id": "block_results",
                        "page_start": 2,
                        "page_end": 2,
                        "section": "Results",
                        "excerpt": "Regulatory T cells express FOXP3.",
                    }
                ],
            }
        ],
    }
    (extraction_dir / f"{source.source_id}.json").write_text(
        json.dumps(extraction, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return source.source_id


def test_fts_search_and_graph_keep_claim_source_provenance(tmp_path: Path):
    source_id = _seed_project(tmp_path)
    index = DiscoveryIndex(tmp_path)

    status = index.rebuild()
    results = index.search("FOXP3", types=[SearchDocumentType.CLAIM, SearchDocumentType.EVIDENCE])
    graph = index.graph(focus="cell_type:regulatory_t_cell")

    assert status.document_count >= 5
    assert {item.type for item in results} == {
        SearchDocumentType.CLAIM,
        SearchDocumentType.EVIDENCE,
    }
    expresses = next(edge for edge in graph.edges if edge.type == GraphEdgeType.EXPRESSES)
    assert expresses.claim_id == "claim_foxp3"
    assert expresses.source_id == source_id
    assert expresses.evidence_count == 1


def test_discovery_index_is_disposable_and_refreshes_after_truth_change(tmp_path: Path):
    source_id = _seed_project(tmp_path)
    index = DiscoveryIndex(tmp_path)
    initial = index.rebuild()

    index.delete_index()
    assert not index.db_path.exists()
    assert SourceRegistry(tmp_path).get(source_id).source_id == source_id
    rebuilt = index.refresh()
    assert rebuilt.rebuilt is True
    assert rebuilt.document_count == initial.document_count

    page = tmp_path / "wiki" / "cell_types" / "regulatory_t_cell.md"
    page.write_text(page.read_text(encoding="utf-8") + "\nIL2RA is also discussed.\n", encoding="utf-8")
    refreshed = index.refresh()
    assert refreshed.rebuilt is True
    assert index.search("IL2RA")[0].page_id == "regulatory_t_cell"


def test_graph_type_filter_preserves_adjacent_provenance(tmp_path: Path):
    _seed_project(tmp_path)
    index = DiscoveryIndex(tmp_path)
    index.rebuild()

    graph = index.graph(node_types=[GraphNodeType.CELL_TYPE])

    assert any(node.type == GraphNodeType.CELL_TYPE for node in graph.nodes)
    assert any(node.type == GraphNodeType.MARKER for node in graph.nodes)
    assert any(edge.type == GraphEdgeType.EXPRESSES for edge in graph.edges)
