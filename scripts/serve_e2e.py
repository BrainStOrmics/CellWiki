"""Start a deterministic local Product API project for Playwright smoke tests."""

from __future__ import annotations

import os
from pathlib import Path

import uvicorn

from cellwiki.api.app import create_app
from cellwiki.domain.runs import AgentEventType, AgentRun, AgentRunStatus
from cellwiki.services.runtime_store import RuntimeStore


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "build" / "e2e-project"
FIXTURE_THREAD_ID = "thread_e2e_history"
FIXTURE_RUN_ID = "run_e2e_history"


def seed_project() -> None:
    """Create an idempotent fixture while keeping all generated data under build/."""

    wiki = PROJECT / "wiki" / "cell_types"
    wiki.mkdir(parents=True, exist_ok=True)
    (wiki / "regulatory_t_cell.md").write_text(
        """---
display_name: Regulatory T cell
cl_id: CL:0000815
---
# Regulatory T cell

## Generated knowledge

FOXP3 and IL2RA are evidence-linked markers in the fixture.

## Human curation

Activation state must be considered before interpreting a single marker.
""",
        encoding="utf-8",
    )
    source_path = PROJECT / "fixture_source.md"
    source_path.write_text(
        "Fixture source: regulatory T-cell marker context and activation caveats.",
        encoding="utf-8",
    )
    # 阶段 0 后无独立 source registry：fixture 源文件直接写入即可
    seed_agent_history()
    # Reset only the generated fixture settings so repeated local runs always
    # exercise the documented default-Chinese then switch-to-English flow.
    (PROJECT / ".env").write_text("APP_LANGUAGE=zh-CN\n", encoding="utf-8")


def seed_agent_history() -> None:
    """Create a completed transcript so browser tests cover durable projections."""

    # The E2E project is disposable. Recreate its runtime truth so local runs
    # cannot accumulate unrelated threads and make the browser fixture order-dependent.
    runtime_db = PROJECT / "data" / "runtime" / "cellwiki.db"
    runtime_db.unlink(missing_ok=True)
    store = RuntimeStore(PROJECT)
    run = AgentRun(
        run_id=FIXTURE_RUN_ID,
        thread_id=FIXTURE_THREAD_ID,
        project_id="cellwiki",
        page_id="regulatory_t_cell",
        input_message="Which markers support this cell type?",
        model_name="fixture-model",
        status=AgentRunStatus.SUCCEEDED,
    )
    store.create_run(run)
    store.append_event(
        FIXTURE_RUN_ID,
        AgentEventType.TOOL_STARTED,
        message="Reading the current Wiki page",
        data={"tool_name": "read_wiki_page"},
    )
    store.append_event(
        FIXTURE_RUN_ID,
        AgentEventType.TOOL_COMPLETED,
        message="Wiki page loaded",
        data={"tool_name": "read_wiki_page"},
    )
    store.append_event(
        FIXTURE_RUN_ID,
        AgentEventType.SUBAGENT_STARTED,
        message="Evidence sub-agent started",
        data={"agent": "evidence-reviewer"},
    )
    store.append_event(
        FIXTURE_RUN_ID,
        AgentEventType.SUBAGENT_COMPLETED,
        message="Evidence sub-agent completed",
        data={"agent": "evidence-reviewer"},
    )
    store.append_event(
        FIXTURE_RUN_ID,
        AgentEventType.PROGRESS,
        message="Evidence ledger assembled",
        progress=75,
        data={"stage": "evidence"},
    )
    store.append_event(
        FIXTURE_RUN_ID,
        AgentEventType.VERIFICATION,
        message="Projection verification passed",
        progress=100,
        data={"status": "passed"},
    )
    answer = (
        "## Evidence summary\n\n"
        "FOXP3 and IL2RA are the strongest fixture markers for this page.\n\n"
        "| Marker | Role |\n| --- | --- |\n| FOXP3 | lineage |\n| IL2RA | activation |\n\n"
        "```text\nEvidence ledger verified\n```"
    )
    store.append_message(
        thread_id=FIXTURE_THREAD_ID,
        run_id=FIXTURE_RUN_ID,
        role="assistant",
        content=answer,
        data={
            "answer": answer,
            "citations": [{"page_id": "regulatory_t_cell", "locator": "Generated knowledge"}],
            "confidence": "high",
            "missing_evidence": [],
        },
    )


if __name__ == "__main__":
    seed_project()
    # Tests bind only loopback and use the development no-token adapter. Packaged
    # security is covered separately by Product API and sidecar smoke tests.
    os.environ.setdefault("APP_LANGUAGE", "zh-CN")
    port = int(os.environ.get("CELLWIKI_E2E_API_PORT", "18000"))
    uvicorn.run(create_app(PROJECT), host="127.0.0.1", port=port, log_level="warning")
