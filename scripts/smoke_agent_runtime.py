"""Opt-in real-model smoke test for Deep Agents, SQLite runs, and stable events."""

from __future__ import annotations

import json
import time
from pathlib import Path

from cellwiki.domain.contracts import WikiAgentContext
from cellwiki.domain.runs import AgentRunStatus, RunBudget
from cellwiki.services.agent_runtime import AgentRuntimeManager


ROOT = Path(__file__).resolve().parents[1]
TERMINAL = {
    AgentRunStatus.SUCCEEDED,
    AgentRunStatus.WAITING_APPROVAL,
    AgentRunStatus.REJECTED,
    AgentRunStatus.FAILED,
    AgentRunStatus.CANCELLED,
}


def main() -> None:
    manager = AgentRuntimeManager(ROOT)
    try:
        thread_id = f"smoke_{int(time.time())}"
        run = manager.start(
            thread_id=thread_id,
            message=(
                "Using only CellWiki evidence, briefly explain what the current "
                "regulatory_t_cell page says and cite the page ID."
            ),
            context=WikiAgentContext(
                project_id="cellwiki",
                page_id="regulatory_t_cell",
                thread_id=thread_id,
            ),
            budget=RunBudget(max_model_calls=6, max_runtime_seconds=150, max_retries=1),
        )
        deadline = time.monotonic() + 160
        while time.monotonic() < deadline:
            current = manager.store.get_run(run.run_id)
            if current.status in TERMINAL:
                break
            time.sleep(0.2)
        else:
            manager.cancel(run.run_id)
            raise SystemExit("Agent runtime smoke test exceeded its outer timeout")

        events = manager.store.list_events(run.run_id)
        final = next((event for event in reversed(events) if event.type.value == "final_response"), None)
        final_data = final.data if final and isinstance(final.data, dict) else {}
        citations = final_data.get("citations", [])
        # Report contract evidence without echoing potentially sensitive Wiki content.
        final_summary = {
            "answer_chars": len(str(final_data.get("answer", ""))),
            "citation_page_ids": [
                citation.get("page_id")
                for citation in citations
                if isinstance(citation, dict) and citation.get("page_id")
            ],
            "confidence": final_data.get("confidence"),
            "missing_evidence_count": len(final_data.get("missing_evidence", [])),
        } if final else None
        print(json.dumps({
            "run_id": run.run_id,
            "status": current.status.value,
            "error_type": current.error_type.value if current.error_type else None,
            "usage": current.usage.model_dump(mode="json"),
            "event_types": [event.type.value for event in events],
            "final_response": final_summary,
        }, ensure_ascii=False, indent=2))
        if current.status != AgentRunStatus.SUCCEEDED or final is None or not citations:
            raise SystemExit("Agent runtime smoke test did not produce a successful final response")
    finally:
        manager.close()


if __name__ == "__main__":
    main()
