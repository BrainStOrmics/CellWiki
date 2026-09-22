"""Source lifecycle, attachment reads, and direct raw-source access."""

from __future__ import annotations

import io
import json
import subprocess
from pathlib import Path

import pytest

from cellwiki.agent.executor import (
    build_workspace_tools,
    clear_attachment_scope,
    set_attachment_resolver,
    set_attachment_scope,
    set_promotion_handler,
)
from cellwiki.agent.source_tools import build_source_tools
from cellwiki.services.attachment_store import AttachmentFileStore


def _git_init(root: Path) -> None:
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "t@cellwiki.local"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "Test Agent"], check=True)


def _store_md(root, thread_id, name="note.md", text="# Note\n\nFOXP3 marker\n") -> dict:
    store = AttachmentFileStore(root)
    attachment = store.store_upload(
        thread_id,
        original_name=name,
        media_type="text/markdown",
        stream=io.BytesIO(text.encode("utf-8")),
    )
    return attachment.to_payload()


def test_store_upload_md_extracts_text_fields(tmp_path: Path):
    payload = _store_md(tmp_path, "thread_a")
    assert payload["text_available"] is True
    assert payload["extracted_path"].endswith("note.md")
    assert payload["est_tokens"] > 0
    assert "FOXP3" in (payload["preview"] or "")
    assert payload["path"].startswith("data/runtime/attachments/")


def test_store_upload_rejects_unsupported_suffix(tmp_path: Path):
    with pytest.raises(ValueError, match="unsupported attachment type"):
        AttachmentFileStore(tmp_path).store_upload(
            "thread_a", original_name="x.docx", media_type="x", stream=io.BytesIO(b"abc")
        )


def test_store_upload_pdf_garbage_marks_no_text(tmp_path: Path):
    store = AttachmentFileStore(tmp_path)
    attachment = store.store_upload(
        "thread_a",
        original_name="bin.pdf",
        media_type="application/pdf",
        stream=io.BytesIO(b"%PDF-1.4\x00 garbage"),
    )
    assert attachment.to_payload()["text_available"] is False


def test_store_upload_thread_cap(tmp_path: Path, monkeypatch):
    from unittest import mock
    from cellwiki.services import attachment_store

    with mock.patch.object(attachment_store, "MAX_THREAD_ATTACHMENT_BYTES", 10):
        with pytest.raises(ValueError, match="thread attachment storage"):
            _store_md(tmp_path, "thread_a", text="x" * 64)


def test_read_file_supports_range(tmp_path: Path):
    root = tmp_path
    (root / "wiki").mkdir(exist_ok=True)
    (root / "wiki" / "big.md").write_text("0123456789abcdefghij", encoding="utf-8")
    tools = {t.name: t for t in build_workspace_tools(root)}
    payload = json.loads(
        tools["read_file"].invoke({"path": "wiki/big.md", "offset": 5, "length": 6})
    )
    assert payload["content"] == "56789a"
    assert payload["offset"] == 5
    assert payload["total_chars"] == 20
    assert payload["truncated"] is True
    assert payload["next_offset"] == 11


def test_attachment_read_guards_and_budget(tmp_path: Path):
    root = tmp_path
    thread_id = "thread_b"
    payload = _store_md(root, thread_id, name="paper.txt", text="a" * 500)
    store = AttachmentFileStore(root)
    aid = payload["attachment_id"]
    target = store.path_for(thread_id, aid)
    clear_attachment_scope()
    set_attachment_scope(
        lambda attachment_id: store.path_for(thread_id, attachment_id),
        root,
        store._thread_dir(thread_id),
        60,
    )
    try:
        tools = {t.name: t for t in build_workspace_tools(root)}
        rel = str(target.relative_to(root).as_posix())
        first = json.loads(tools["read_file"].invoke({"path": rel, "length": 100}))
        assert first["content"] == "a" * 60
        assert first["truncated"] is True
        second = json.loads(tools["read_file"].invoke({"path": rel, "length": 100}))
        assert second.get("error") == "attachment_read_budget_exceeded"
        outside = json.loads(tools["read_file"].invoke({"path": "wiki/nope.md"}))
        assert outside.get("error")
    finally:
        clear_attachment_scope()


def test_promote_attachment_moves_to_raw_and_commits(tmp_path: Path):
    root = tmp_path
    _git_init(root)
    thread_id = "thread_c"
    payload = _store_md(root, thread_id, name="paper_c.md", text="# Paper C\n\nCD8 T cells.\n")
    aid = payload["attachment_id"]
    store = AttachmentFileStore(root)
    target = store.path_for(thread_id, aid)
    promoted = []
    set_attachment_resolver(lambda attachment_id: store.path_for(thread_id, attachment_id))
    set_attachment_scope(
        lambda attachment_id: store.path_for(thread_id, attachment_id),
        root,
        store._thread_dir(thread_id),
        0,
    )
    set_promotion_handler(lambda t, a, s: promoted.append((t, a, s)))
    try:
        tools = {t.name: t for t in build_source_tools(root)}
        assert set(tools) == {"promote_attachment"}
        result = json.loads(tools["promote_attachment"].invoke({"attachment_id": aid}))
        assert result.get("ok") is True
        source_id = result["source_id"]
        raw_dir = root / "raw" / source_id
        assert raw_dir.is_dir()
        assert (raw_dir / "meta.json").is_file()
        assert (root / "data" / "runtime" / "sources" / f"{source_id}.json").is_file()
        assert not target.exists(), "runtime copy should be removed after promote"
        assert promoted == [(thread_id, aid, source_id)]
    finally:
        clear_attachment_scope()


def test_agent_file_tools_can_read_raw_and_write_contract_page(tmp_path: Path):
    root = tmp_path
    source = root / "raw" / "paper_one"
    source.mkdir(parents=True)
    (source / "paper.extracted.txt").write_text(
        "Human CD8 T cells express CD3D and CD8A.", encoding="utf-8"
    )
    tools = {t.name: t for t in build_workspace_tools(root)}
    listed = json.loads(tools["glob"].invoke({"pattern": "raw/**/*.txt"}))
    assert "raw/paper_one/paper.extracted.txt" in listed["results"]
    read = json.loads(
        tools["read_file"].invoke({"path": "raw/paper_one/paper.extracted.txt"})
    )
    assert "CD8A" in read["content"]
    written = json.loads(
        tools["write_file"].invoke(
            {
                "path": "wiki/cell_types/cd8_t_cell.md",
                "content": "# CD8 T Cell\n\n## Markers\n\n- CD8A\n",
            }
        )
    )
    assert written.get("ok") is True
    assert (root / "wiki" / "cell_types" / "cd8_t_cell.md").is_file()
