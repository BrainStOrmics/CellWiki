# =============================================================================
# 线程附件领域模型
# =============================================================================
# 附件是线程范围内的临时 Agent 上下文：上传后不登记为 Source、不 ingest、
# 不进入 git 治理，仅对该线程的 run 可见（AGENTS.md 边界）。记录存 SQLite
# （RuntimeStore），文件存 data/runtime/attachments/<thread_id>/（gitignored）。
# 上传时服务端解析 md/txt/pdf：文本型直接读取，PDF 用 pdfplumber 提取纯文本
# （v1 不做 OCR），text_available 表示是否拿到可读文本。
# =============================================================================

"""Thread-scoped temporary Agent attachment contract."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from cellwiki.domain.contracts import ContractModel
from pydantic import Field


class ThreadAttachment(ContractModel):
    """One uploaded file owned by one Agent thread (temporary, not governed)."""

    attachment_id: str
    thread_id: str
    original_name: str
    media_type: str = "application/octet-stream"
    size_bytes: int = Field(default=0, ge=0)
    content_hash: str = ""
    text_hash: str | None = None
    text_available: bool = False          # 是否成功解析出可读文本
    extracted_path: str | None = None     # 提取文本产物的工作区相对路径
    est_tokens: int = Field(default=0, ge=0)  # 估算 token（字符/4）
    preview: str | None = None            # 正文预览（上限 2000 字符）
    path: str | None = None               # 存储文件的工作区相对路径
    promoted_source_id: str | None = None # 提升后的正式源 ID（promote 后填写）
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def to_payload(self) -> dict[str, Any]:
        return {
            "attachment_id": self.attachment_id,
            "thread_id": self.thread_id,
            "original_name": self.original_name,
            "media_type": self.media_type,
            "size_bytes": self.size_bytes,
            "content_hash": self.content_hash,
            "text_hash": self.text_hash,
            "text_available": self.text_available,
            "extracted_path": self.extracted_path,
            "est_tokens": self.est_tokens,
            "preview": self.preview,
            "path": self.path,
            "promoted_source_id": self.promoted_source_id,
            "created_at": self.created_at.isoformat(),
        }


__all__ = ["ThreadAttachment"]
