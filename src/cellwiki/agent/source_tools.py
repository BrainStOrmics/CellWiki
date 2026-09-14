"""Source-lifecycle tools that do not perform schema-specific extraction."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool, tool

from cellwiki.agent.executor import get_attachment_scope, get_promotion_handler
from cellwiki.services.git_executor import GitExecutor
from cellwiki.services.promotion import promote_to_raw


def _tool_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)


def build_source_tools(project_root: Path) -> list[BaseTool]:
    """Provide source acquisition helpers that do not own page extraction."""

    root = Path(project_root).resolve()

    @tool("promote_attachment")
    def promote_attachment(attachment_id: str, source_type: str = "paper") -> str:
        """Promote one uploaded attachment into the formal raw/<source_id>/ source area.
        Call only after the user confirmed ingestion via ask_user_question. Copies
        the original (plus extracted text) into raw/, registers the source, commits
        the change, and removes the runtime copy."""
        resolver, _ws_root, thread_dir = get_attachment_scope()
        if resolver is None:
            return _tool_json({"error": "no active run context"})
        try:
            target = resolver(attachment_id)
        except Exception as error:
            return _tool_json({"error": f"cannot resolve attachment: {error}"})
        if target is None:
            return _tool_json({"error": "attachment_not_found"})
        try:
            record = promote_to_raw(root, attachment_path=target, source_type=source_type)
        except Exception as error:
            return _tool_json({"error": f"promote failed: {str(error)[:300]}"})
        source_id = str(record.get("source_id") or "")
        git_error = None
        try:
            git = GitExecutor(root)
            git.run("add", f"raw/{source_id}")
            git.run("commit", "-m", f"ingest: promote {source_id}")
        except Exception as error:
            git_error = str(error)[:300]
        removed = 0
        for candidate in (target, target.with_name(target.name + ".extracted.txt")):
            try:
                if candidate.is_file():
                    candidate.unlink()
                    removed += 1
            except OSError:
                pass
        handler = get_promotion_handler()
        if handler is not None and thread_dir is not None:
            try:
                handler(thread_dir.name, attachment_id, source_id)
            except Exception:
                pass
        return _tool_json(
            {
                "ok": True,
                "source_id": source_id,
                "raw_path": f"raw/{source_id}",
                "stored_path": record.get("stored_path"),
                "removed_runtime_files": removed,
                "git_error": git_error,
            }
        )

    return [promote_attachment]


__all__ = ["build_source_tools", "promote_to_raw"]