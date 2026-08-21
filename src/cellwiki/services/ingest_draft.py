"""Staging store for agent-produced ingest extraction drafts.

Drafts live under ``data/runtime/agent_ingest_drafts/<source_id>/<run_id>.json``.
A draft is *candidate* data: it can never become formal knowledge until the
deterministic guards in ``IngestService.prepare_change_set`` finalize it into a
ChangeSet and the approval/CentralWriter boundary completes.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


class AgentIngestDraftStore:
    """Read/write staged extraction drafts for one source."""

    def __init__(self, project_root: Path | str):
        self.root = Path(project_root).resolve()
        self.base = self.root / "data" / "runtime" / "agent_ingest_drafts"

    def path_for(self, source_id: str, run_id: str) -> Path:
        safe_run = "".join(ch for ch in run_id if ch.isalnum() or ch in "-_.") or "draft"
        return self.base / source_id / f"{safe_run}.json"

    def save(
        self,
        source_id: str,
        run_id: str,
        payload: dict[str, Any],
        *,
        revision: int = 0,
        grounding: dict[str, Any] | None = None,
        created_at_iso: str | None = None,
    ) -> Path:
        """Atomically persist one draft revision."""
        path = self.path_for(source_id, run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "source_id": source_id,
            "run_id": run_id,
            "status": "draft",
            "revision": revision,
            "payload": payload,
            "grounding": grounding or {},
            "created_at": created_at_iso or _now_iso(),
            "updated_at": _now_iso(),
        }
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
        return path

    def load(self, source_id: str, run_id: str) -> dict[str, Any] | None:
        path = self.path_for(source_id, run_id)
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def list_for(self, source_id: str) -> list[str]:
        directory = self.base / source_id
        if not directory.is_dir():
            return []
        return sorted(path.stem for path in directory.glob("*.json"))

    def delete(self, source_id: str, run_id: str) -> bool:
        path = self.path_for(source_id, run_id)
        if path.is_file():
            path.unlink()
            return True
        return False


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
