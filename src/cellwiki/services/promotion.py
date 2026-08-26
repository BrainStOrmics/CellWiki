# =============================================================================
# 附件提升为正式源（promotion）
# =============================================================================
# 用户同意后，把线程临时附件提升为 raw/<source_id>/ 正式源：复制原件与
# 提取文本、写 meta.json、登记 data/runtime/sources/<source_id>.json
# （stored_path 指向 raw/ 内的文件），再交给调用方做 git add/commit 与
# 运行时附件副本清理。该流程在 ADR-0007 的 git 治理内运行：提交进入当前
# run，run 结束时统一汇聚为 pending diff 供用户审批。
# =============================================================================

"""Promote a thread attachment into the raw/ formal source area."""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cellwiki.services.attachment_store import sanitize_file_name

SOURCE_ID_PARTS = 20  # src_ + 20 hex


def new_source_id() -> str:
    """Generate a source id matching the existing src_<20hex> registry shape."""
    digest = hashlib.sha256(uuid.uuid4().hex.encode("utf-8")).hexdigest()
    return f"src_{digest[:SOURCE_ID_PARTS]}"


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _display_name(path: Path) -> str:
    """Strip the attachment prefix (att_xxxx__) from the stored file name."""
    name = path.name
    marker = "__"
    if marker in name:
        return name.split(marker, 1)[1]
    return name


def promote_to_raw(
    project_root: Path,
    *,
    attachment_path: Path,
    source_type: str = "paper",
) -> dict[str, Any]:
    """Copy an attachment (plus extracted text) into raw/<source_id>/ and register it.

    Returns the registered source record; does not delete runtime files or commit.
    """
    root = Path(project_root).resolve()
    attachment_path = attachment_path.resolve()
    raw_dir = root / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    source_id = new_source_id()
    dest_dir = raw_dir / source_id
    dest_dir.mkdir(parents=True, exist_ok=True)

    display_name = _display_name(attachment_path)
    safe_name = sanitize_file_name(display_name) or attachment_path.name
    stored = dest_dir / safe_name
    shutil.copy2(attachment_path, stored)

    sidecar = attachment_path.with_name(attachment_path.name + ".extracted.txt")
    sidecar_name: str | None = None
    if sidecar.is_file():
        sidecar_name = f"{Path(safe_name).stem}.extracted.txt"
        shutil.copy2(sidecar, dest_dir / sidecar_name)

    created_at = datetime.now(UTC).isoformat()
    meta: dict[str, Any] = {
        "source_id": source_id,
        "original_name": safe_name,
        "extracted_file": sidecar_name,
        "content_hash": _sha256(stored.read_bytes()),
        "promoted_at": created_at,
    }
    (dest_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    parser = "pdf" if stored.suffix.lower() == ".pdf" else "plain-text"
    text_bytes = stored.read_bytes()
    text_hash: str | None = None
    if sidecar_name:
        sidecar_path = dest_dir / sidecar_name
        if sidecar_path.is_file():
            text_hash = _sha256(sidecar_path.read_bytes())
    record: dict[str, Any] = {
        "source_id": source_id,
        "source_type": source_type,
        "original_name": safe_name,
        "stored_path": str(stored),
        "content_hash": _sha256(text_bytes),
        "text_hash": text_hash,
        "status": "registered",
        "parser_name": parser,
        "metadata": {
            "file_name": safe_name,
            "extracted_file": sidecar_name,
            "promoted_from": attachment_path.name,
            "promoted_at": created_at,
        },
        "created_at": created_at,
    }
    registry_dir = root / "data" / "runtime" / "sources"
    registry_dir.mkdir(parents=True, exist_ok=True)
    (registry_dir / f"{source_id}.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return record


__all__ = ["promote_to_raw", "new_source_id"]
