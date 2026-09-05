# =============================================================================
# 线程附件文件存储
# =============================================================================
# 附件文件按线程存放于 data/runtime/attachments/<thread_id>/，属于可再生的
# 运行时数据（.gitignore 已排除 data/runtime/）。文件名做净化：只保留 basename，
# 拒绝路径分隔符、.. 与保留名；内容哈希去重；单文件大小受限（100MB），
# 每线程累计上限 500MB。上传时服务端解析：md/txt 直接读取文本，PDF 用
# pdfplumber 提取纯文本（v1 无 OCR，失败标记 text_available=False）。
# =============================================================================

"""Thread-scoped attachment file storage (runtime data, outside git governance)."""

from __future__ import annotations

import hashlib
import re
import uuid
from pathlib import Path
from typing import BinaryIO

from cellwiki.domain.attachments import ThreadAttachment

MAX_ATTACHMENT_BYTES = 100 * 1024 * 1024        # 单文件上限 100MB
MAX_ATTACHMENTS_PER_UPLOAD = 20
MAX_THREAD_ATTACHMENT_BYTES = 500 * 1024 * 1024  # 每线程累计上限 500MB
MAX_EXTRACTED_CHARS = 5_000_000                 # 提取文本长度上限
MAX_PREVIEW_CHARS = 2000                        # 附件清单 preview 上限
SUPPORTED_ATTACHMENT_SUFFIXES = frozenset({".pdf", ".md", ".txt"})

_SAFE_NAME_RE = re.compile(r"[^0-9A-Za-z._-一-鿿 ]")


def sanitize_file_name(raw: str) -> str:
    """Keep only the basename and printable, portable characters."""
    name = Path(raw or "file").name
    name = _SAFE_NAME_RE.sub("_", name).strip(" .")
    return (name or "file")[:160]


class AttachmentFileStore:
    """Own the on-disk layout for thread-scoped temporary attachments."""

    def __init__(self, project_root: Path):
        self.project_root = Path(project_root).resolve()
        self.root = self.project_root / "data" / "runtime" / "attachments"

    def _thread_dir(self, thread_id: str) -> Path:
        safe = sanitize_file_name(thread_id) or "thread"
        return self.root / safe

    def thread_total_bytes(self, thread_id: str) -> int:
        """Sum of stored file sizes for one thread (excludes staging files)."""
        directory = self._thread_dir(thread_id)
        if not directory.is_dir():
            return 0
        return sum(
            candidate.stat().st_size
            for candidate in directory.iterdir()
            if candidate.is_file() and not candidate.name.endswith(".staging")
        )

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
        suffix = Path(original_name or "").suffix.lower()
        if suffix not in SUPPORTED_ATTACHMENT_SUFFIXES:
            raise ValueError(
                f"unsupported attachment type '{suffix or 'unknown'}': pdf/md/txt only"
            )
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
        # 每线程累计上限：超出即删除该文件并报错（防止多附件堆满磁盘）
        if self.thread_total_bytes(thread_id) > MAX_THREAD_ATTACHMENT_BYTES:
            final_path.unlink(missing_ok=True)
            raise ValueError(
                f"thread attachment storage exceeds {MAX_THREAD_ATTACHMENT_BYTES} bytes"
            )
        text, text_available = self._extract_text(final_path)
        text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest() if text else None
        extracted_rel: str | None = None
        if text_available:
            if suffix == ".pdf":
                sidecar = final_path.with_name(final_path.name + ".extracted.txt")
                sidecar.write_text(text or "", encoding="utf-8")
                extracted_rel = str(sidecar.relative_to(self.project_root).as_posix())
            else:
                extracted_rel = str(final_path.relative_to(self.project_root).as_posix())
        content_text = text or ""
        return ThreadAttachment(
            attachment_id=attachment_id,
            thread_id=thread_id,
            original_name=safe_name,
            media_type=media_type or "application/octet-stream",
            size_bytes=size,
            content_hash=digest.hexdigest(),
            text_hash=text_hash,
            text_available=text_available,
            extracted_path=extracted_rel,
            est_tokens=(len(content_text) + 3) // 4,
            preview=content_text[:MAX_PREVIEW_CHARS] or None,
            path=str(final_path.relative_to(self.project_root).as_posix()),
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

    def delete_attachment(self, thread_id: str, attachment_id: str) -> int:
        """Remove one attachment's stored files (original plus extracted sidecar)."""
        directory = self._thread_dir(thread_id)
        if not directory.is_dir():
            return 0
        prefix = attachment_id[:12] + "__"
        removed = 0
        for candidate in directory.iterdir():
            if candidate.is_file() and candidate.name.startswith(prefix):
                candidate.unlink(missing_ok=True)
                removed += 1
        return removed

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

    # ---- 文本提取（v1：md/txt 直读，PDF pdfplumber，无 OCR）----
    def _extract_text(self, path: Path) -> tuple[str | None, bool]:
        """Return (extracted text or None, text_available). Never raises."""
        try:
            if path.suffix.lower() == ".pdf":
                return self._extract_pdf_text(path)
            data = path.read_bytes()
            if b"\x00" in data:
                return None, False
            return data.decode("utf-8", errors="replace"), True
        except Exception:
            return None, False

    @staticmethod
    def _extract_pdf_text(path: Path) -> tuple[str | None, bool]:
        import pdfplumber

        parts: list[str] = []
        total = 0
        with pdfplumber.open(str(path)) as pdf:
            for page in pdf.pages[:250]:
                page_text = page.extract_text() or ""
                if page_text:
                    parts.append(page_text)
                    total += len(page_text)
                if total >= MAX_EXTRACTED_CHARS:
                    break
        text = "\n".join(parts)[:MAX_EXTRACTED_CHARS]
        if not text.strip():
            return None, False
        return text, True


__all__ = [
    "AttachmentFileStore",
    "MAX_ATTACHMENT_BYTES",
    "MAX_ATTACHMENTS_PER_UPLOAD",
    "MAX_THREAD_ATTACHMENT_BYTES",
    "SUPPORTED_ATTACHMENT_SUFFIXES",
    "sanitize_file_name",
]
