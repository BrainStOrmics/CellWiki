from __future__ import annotations

import json
from pathlib import Path

from cellwiki.agent.tools import build_read_tools
from cellwiki.domain.contracts import ChangeOperation, ChangeOperationType, ChangeSet, RiskLevel
from cellwiki.services.changesets import ChangeSetRepository


def _pending_change_set() -> ChangeSet:
    return ChangeSet(
        change_set_id="cs_pending_query",
        run_id="run_pending_query",
        project_id="cellwiki",
        operations=[
            ChangeOperation(
                type=ChangeOperationType.UPDATE_CURATION,
                target_id="regulatory_t_cell",
                payload={"content": "pending"},
            )
        ],
        risk=RiskLevel.LOW,
        reason="pending query fixture",
    )


def test_query_tools_return_formal_scope_version_and_source_provenance(tmp_path: Path) -> None:
    page = tmp_path / "wiki" / "cell_types" / "regulatory_t_cell.md"
    page.parent.mkdir(parents=True)
    page.write_text(
        "---\n"
        "display_name: Regulatory T Cell\n"
        "references:\n"
        "  - paper_id: src_formal\n"
        "    title: Formal paper\n"
        "---\n\n# Regulatory T Cell\n\nFOXP3 marker.",
        encoding="utf-8",
    )
    ChangeSetRepository(tmp_path).save(_pending_change_set())
    tools = {tool.name: tool for tool in build_read_tools(tmp_path)}

    search = json.loads(tools["search_wiki"].invoke({"query": "FOXP3", "limit": 5}))
    page_result = json.loads(tools["read_wiki_page"].invoke({"page_id": "regulatory_t_cell"}))

    assert search["scope"] == "formal"
    assert search["knowledge_version"].startswith("sha256:")
    assert search["pending_change_set_count"] == 1
    assert search["results"][0]["state"] == "formal"
    assert search["results"][0]["source_ids"] == ["src_formal"]
    assert page_result["scope"] == "formal"
    assert page_result["source_ids"] == ["src_formal"]
    assert page_result["knowledge_version"] == search["knowledge_version"]

