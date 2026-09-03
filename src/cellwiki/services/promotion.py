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


__all__ = ["promote_to_raw", "new_source_id", "scan_raw_sources"]


# ---------------------------------------------------------------------------
# 预置 raw/ 源登记（方案 B：产品侧扫描，用户发起，Agent 白名单不变）
# ---------------------------------------------------------------------------
# 附件晋升（promote_to_raw）只覆盖"用户上传 -> 确认 -> 复制进 raw/"这一通路。
# 用户直接放进 raw/<目录名>/ 的预置资料（论文 PDF/正文）此前没有登记入口，
# ingest_sources 因此报 "source record not found"。扫描登记补齐这条产品通路：
# source_id = 目录名，stored_path 指向目录内已存在的正文，不复制、不移动、
# 不写 raw/、不产生 git 变更（只写 data/runtime/sources/*.json）。重复扫描按
# source_id 幂等。附件路径的哈希型 source_id 与本通路的目录名型互不影响。
_TEXT_SUFFIXES = (".md", ".txt")


def _safe_source_id(name: str) -> bool:
    """目录名作为 source_id：只接受无路径分隔、无特殊字符的可读名。"""
    if not name or name in {".", ".."}:
        return False
    if "/" in name or "\\" in name or ":" in name:
        return False
    if name.startswith((".", "~")):
        return False
    return all(ch not in '<>|"?*%' for ch in name)


def _pick_body(directory: Path) -> tuple[Path | None, Path | None]:
    """Locate one preplaced source's readable body inside its raw/ directory.

    Returns (stored_path, extracted_sidecar_or_None). Prefers an existing
    ``*.extracted.txt`` sidecar's parent document; a bare .md/.txt is directly
    readable; a PDF without its sidecar is "needs_extraction" (returned with
    the pdf path so the caller can register it as such, not silently skipped).
    """
    files = sorted(
        (p for p in directory.iterdir() if p.is_file()), key=lambda p: p.name.lower()
    )
    # 1) an extracted-text sidecar sitting next to its document wins
    for path in files:
        if path.name.endswith(".extracted.txt"):
            document = path.with_name(path.name[: -len(".extracted.txt")])
            if document.is_file():
                return document, path
    # 2) a directly-readable markdown/text body
    for path in files:
        if path.suffix.lower() in _TEXT_SUFFIXES and path.name != "meta.json":
            return path, None
    # 3) a PDF with no sidecar -> needs extraction (register, don't drop)
    for path in files:
        if path.suffix.lower() == ".pdf":
            return path, None
    return None, None


def scan_raw_sources(project_root: Path) -> dict[str, Any]:
    """Register preplaced ``raw/<source_id>/`` directories the user dropped in.

    Idempotent by directory name: a missing record is created, an existing
    ``preplaced_scan`` record is refreshed in place, and an attachment-promoted
    (hash ``src_*``) record is never touched. Writes only
    ``data/runtime/sources/<id>.json`` -- never copies, moves, deletes, or
    stages anything under ``raw/``, so this produces no pending diff.
    """
    root = Path(project_root).resolve()
    raw_dir = root / "raw"
    registry_dir = root / "data" / "runtime" / "sources"
    counts = {"added": 0, "updated": 0, "skipped": 0, "needs_extraction": 0}
    registered: list[str] = []
    issues: list[dict[str, str]] = []
    if not raw_dir.is_dir():
        return {**counts, "sources": registered, "issues": issues}

    for directory in sorted(raw_dir.iterdir(), key=lambda p: p.name.lower()):
        if not directory.is_dir():
            continue
        source_id = directory.name
        if not _safe_source_id(source_id):
            counts["skipped"] += 1
            issues.append(
                {"source_id": source_id, "reason": "directory name is not a safe id"}
            )
            continue
        record_path = registry_dir / f"{source_id}.json"
        existing: dict[str, Any] | None = None
        if record_path.is_file():
            try:
                loaded = json.loads(record_path.read_text(encoding="utf-8"))
                existing = loaded if isinstance(loaded, dict) else None
            except (OSError, ValueError):
                existing = None
        # 附件晋升记录（有 promoted_from 且非本通路登记）不覆盖，交由其通路管理。
        if existing is not None and (existing.get("metadata") or {}).get("promoted_from"):
            counts["skipped"] += 1
            issues.append(
                {"source_id": source_id, "reason": "existing attachment-promoted record"}
            )
            continue

        body, sidecar = _pick_body(directory)
        if body is None:
            counts["skipped"] += 1
            issues.append(
                {"source_id": source_id, "reason": "no readable source file in directory"}
            )
            continue

        needs_extraction = body.suffix.lower() == ".pdf" and sidecar is None
        status = "needs_extraction" if needs_extraction else "registered"
        if needs_extraction:
            counts["needs_extraction"] += 1
        stored_name = body.name
        safe_name = sanitize_file_name(stored_name) or stored_name
        created_at = (
            str(existing.get("created_at"))
            if existing is not None and existing.get("created_at")
            else datetime.now(UTC).isoformat()
        )
        record: dict[str, Any] = {
            "source_id": source_id,
            "source_type": "paper",
            "original_name": safe_name,
            "stored_path": str(body),
            "content_hash": _sha256(body.read_bytes()),
            "text_hash": _sha256(sidecar.read_bytes()) if sidecar is not None else None,
            "status": status,
            "parser_name": "pdf" if body.suffix.lower() == ".pdf" else "plain-text",
            "metadata": {
                "file_name": safe_name,
                "extracted_file": sidecar.name if sidecar is not None else None,
                "registration": "preplaced_scan",
            },
            "created_at": created_at,
        }
        registry_dir.mkdir(parents=True, exist_ok=True)
        record_path.write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if existing is None:
            counts["added"] += 1
        else:
            counts["updated"] += 1
        registered.append(source_id)

    return {**counts, "sources": registered, "issues": issues}
