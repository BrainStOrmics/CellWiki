# =============================================================================
# 线程附件文件存储
# =============================================================================
# 附件文件按线程存放于 data/runtime/attachments/<thread_id>/，属于可再生的
# 运行时数据（.gitignore 已排除 data/runtime/）。文件名做净化：只保留 basename，
# 拒绝路径分隔符、.. 与保留名；内容哈希去重；单文件大小受限。
# =============================================================================

"""Thread-scoped attachment file storage (runtime data, outside git governance)."""

from __future__ import annotations

import hashlib
import re
import uuid
from pathlib import Path
from typing import BinaryIO

from cellwiki.domain.attachments import ThreadAttachment

MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024  # 10 MB per file
MAX_ATTACHMENTS_PER_UPLOAD = 20

_SAFE_NAME_RE = re.compile(r"[^0-9A-Za-z._-一-鿿 ]")


def sanitize_file_name(raw: str) -> str:
    """Keep only the basename and printable, portable characters."""
    name = Path(raw or "file").name
    name = _SAFE_NAME_RE.sub("_", name).strip(" .")
    return (name or "file")[:160]


class AttachmentFileStore:
    """Own the on-disk layout for thread-scoped temporary attachments."""

    def __init__(self, project_root: Path):
        self.root = Path(project_root).resolve() / "data" / "runtime" / "attachments"

    def _thread_dir(self, thread_id: str) -> Path:
        safe = sanitize_file_name(thread_id) or "thread"
        return self.root / safe

    def store_upload(
        self,
        thread_id: str,
        *,
        original_name: str,
        media_type: str,
        stream: BinaryIO,
    ) -> ThreadAttachment:
        """Persist one uploaded file and return its thread-scoped record."""
        directory = self._thread_dir(thread_id)
        directory.mkdir(parents=True, exist_ok=True)
        safe_name = sanitize_file_name(original_name)
        attachment_id = f"att_{uuid.uuid4().hex}"
        digest = hashlib.sha256()
        size = 0
        # 先写临时文件，哈希/大小合法后才落定名称，避免半写文件进入记录
        staging = directory / f".{attachment_id}.staging"
        try:
            with staging.open("wb") as target:
                while chunk := stream.read(64 * 1024):
                    size += len(chunk)
                    if size > MAX_ATTACHMENT_BYTES:
                        raise ValueError(
                            f"attachment exceeds the {MAX_ATTACHMENT_BYTES}-byte limit"
                        )
                    digest.update(chunk)
                    target.write(chunk)
            final_name = f"{attachment_id[:12]}__{safe_name}"
            final_path = directory / final_name
            staging.replace(final_path)
        except Exception:
            staging.unlink(missing_ok=True)
            raise
        raw = digest.hexdigest()
        text_hash = None
        try:
            text = final_path.read_bytes()
            if b"\x00" not in text and len(text) <= 4 * 1024 * 1024:
                text_hash = hashlib.sha256(
                    text.decode("utf-8", errors="replace").encode("utf-8")
                ).hexdigest()
        except OSError:
            pass
        return ThreadAttachment(
            attachment_id=attachment_id,
            thread_id=thread_id,
            original_name=safe_name,
            media_type=media_type or "application/octet-stream",
            size_bytes=size,
            content_hash=raw,
            text_hash=text_hash,
        )

    def path_for(self, thread_id: str, attachment_id: str) -> Path | None:
        """Resolve one attachment's file path within its thread directory (no traversal)."""
        directory = self._thread_dir(thread_id)
        if not directory.is_dir():
            return None
        prefix = attachment_id[:12] + "__"
        for candidate in directory.iterdir():
            if candidate.is_file() and candidate.name.startswith(prefix):
                return candidate
        return None

    def delete_thread(self, thread_id: str) -> int:
        """Remove every stored file for a thread; returns the count removed."""
        directory = self._thread_dir(thread_id)
        if not directory.is_dir():
            return 0
        removed = 0
        for candidate in directory.iterdir():
            if candidate.is_file():
                candidate.unlink(missing_ok=True)
                removed += 1
        try:
            directory.rmdir()
        except OSError:
            pass
        return removed


__all__ = ["AttachmentFileStore", "MAX_ATTACHMENT_BYTES", "MAX_ATTACHMENTS_PER_UPLOAD", "sanitize_file_name"]
