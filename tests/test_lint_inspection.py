from __future__ import annotations

import json
from pathlib import Path

from cellwiki.domain.tasks import LintTask, PageLintScope
from cellwiki.services.lint_inspection import LintInspection


def _write_page(root: Path, page_id: str) -> None:
    path = root / "wiki" / "cell_types" / f"{page_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\ndisplay_name: {page_id}\n---\n\n# {page_id}\n", encoding="utf-8")


def test_lint_inspection_returns_bounded_result_and_persists_full_artifact(tmp_path: Path):
    for index in range(30):
        _write_page(tmp_path, f"cell_{index:02d}")

    result = LintInspection(tmp_path).inspect(
        LintTask(action="inspect", limit=5),
        run_id="run_lint_bounded",
    )
    payload = result.model_dump(mode="json")

    assert len(result.findings) == 5
    assert result.next_cursor is not None
    assert len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) <= 16 * 1024
    assert "snapshot" not in payload
    assert "report" not in payload
    artifact = tmp_path / result.full_report_ref
    assert artifact.exists()
    assert result.full_report_size == artifact.stat().st_size


def test_lint_inspection_page_scope_returns_only_target_page(tmp_path: Path):
    _write_page(tmp_path, "t_cell")
    _write_page(tmp_path, "b_cell")

    result = LintInspection(tmp_path).inspect(
        LintTask(
            action="inspect",
            scope=PageLintScope(page_id="t_cell"),
            limit=20,
        ),
        run_id="run_lint_page",
    )

    assert result.scope == {"kind": "page", "page_id": "t_cell"}
    assert result.findings
    assert {finding.target_id for finding in result.findings} == {"t_cell"}
