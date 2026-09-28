# =============================================================================
# 工作区记忆合并（ADR-0016 切片 3）
# =============================================================================
# Phase 2 是唯一写方：把候选合并成成型记忆文件与摘要。复用当前模型产出结构化
# 合并结果（话题条目 + 四个摘要段），由本模块做确定性校验后落盘：
# - 话题家族必须落在固定枚举内，枚举外整批拒绝；
# - 摘要必须满足 v1 首行 + 四个固定 heading + <10,000 bytes；
# - 用户手动编辑过的条目（derived_hash 不一致）跳过自动合并，保持用户内容优先；
# - 已消费的候选标记 merged，被拒的标记 rejected，不进入 prompt。
# =============================================================================

"""Single-writer consolidation of memory candidates into artifacts (ADR-0016)."""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any, Callable

from cellwiki.adapters.openai_model import build_model_from_spec
from cellwiki.domain.memory import (
    MemoryCandidate,
    MemoryCandidateStatus,
    MemoryEntry,
    MemoryKind,
    MemoryTopicFamily,
)
from cellwiki.services.agent_memory import (
    MEMORY_SUMMARY_MAX_BYTES,
    WorkspaceMemoryStore,
    render_summary,
    validate_summary_body,
)
from cellwiki.services.environment import _extract_json_object
from cellwiki.services.model_catalog import ModelCatalogService

REQUEST_TIMEOUT_SECONDS = 90.0

_FAMILY_LIST = " | ".join(family.value for family in MemoryTopicFamily)

_INSTRUCTIONS = (
    "你在把知识库工作区里的记忆候选合并成成型记忆。只做合并、去重与改写，"
    "不要新增候选里没有的事实，不要写入科学结论、页面正文、原始语料、隐藏推理或凭据。"
    "每个话题归入一个固定家族，同一家族内的条目合并到同一个 file_name。"
    "摘要的 User Profile 只写这个工作区里的协作口径（怎么维护知识库、要求什么输出、"
    "哪些操作必须先问），不写跨工作区的个人画像。"
    "只输出一个 JSON 对象："
    '{"topics": [{"topic_family": "...", "title": "...", "file_name": "kebab-case.md", '
    '"body": "..."}], "summary": {"profile": "...", "preferences": "...", '
    '"tips": "...", "index": "..."}}。'
    f"topic_family 只能取 {_FAMILY_LIST}；"
    "file_name 只用小写字母、数字与连字符，以 .md 结尾；"
    f"summary 总量必须小于 {MEMORY_SUMMARY_MAX_BYTES} 字节，index 用 `### <家族>` 分组。"
    "没有内容可写时 topics 返回空数组、summary 四段留空字符串。"
    "直接给结论，不要代码块、不要额外解释。"
)

_FILE_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}\.md$")


class MemoryMergeUnavailable(RuntimeError):
    """没有可用默认模型时跳过合并，候选保留待下次。"""


class MemoryMergeRejected(RuntimeError):
    """模型输出未通过确定性校验；本批候选标记 rejected。"""


def _truncate(text: str, limit: int) -> str:
    collapsed = " ".join(str(text).split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1] + "…"


class MemoryConsolidationService:
    """Merge pending candidates into topic files plus the injected summary."""

    def __init__(
        self,
        memory: WorkspaceMemoryStore,
        catalog: ModelCatalogService,
        *,
        completer: Callable[[str], str] | None = None,
    ) -> None:
        self.memory = memory
        self.catalog = catalog
        self._completer = completer
        self._log = logging.getLogger(__name__)

    # -- entry point -----------------------------------------------------

    def consolidate(self) -> list[MemoryEntry]:
        """Consume all pending candidates; returns the entries written this pass."""

        candidates = self.memory.list_candidates()
        if not candidates:
            return []
        prompt = self._build_prompt(candidates)
        raw = self._complete(prompt)
        try:
            payload = self._parse_payload(raw)
        except Exception as error:  # noqa: BLE001 - 输出不合规即整批拒绝
            self._log.warning("memory consolidation rejected: %s", error)
            for candidate in candidates:
                self.memory.mark_candidate(
                    candidate.memory_id, MemoryCandidateStatus.REJECTED
                )
            return []
        entries = self._apply(payload)
        for candidate in candidates:
            self.memory.mark_candidate(
                candidate.memory_id, MemoryCandidateStatus.MERGED
            )
        return entries

    # -- prompt ----------------------------------------------------------

    def _build_prompt(self, candidates: list[MemoryCandidate]) -> str:
        existing = [
            {
                "memory_id": entry.memory_id,
                "topic_family": entry.topic_family.value,
                "title": entry.title,
                "file_name": entry.file_name,
                "user_edited": entry.user_edited,
            }
            for entry in self.memory.list_entries()
        ]
        payload = {
            "existing_entries": existing,
            "existing_summary": self.memory.read_summary(),
            "existing_index": (
                self.memory.index_path().read_text(encoding="utf-8")
                if self.memory.index_path().is_file()
                else ""
            ),
            "candidates": [candidate.to_payload() for candidate in candidates],
        }
        return (
            _INSTRUCTIONS
            + "\n\n已有记忆（user_edited=true 的条目不要改写，只可追加新条目）：\n"
            + json.dumps(payload, ensure_ascii=False, indent=1)[:60_000]
        )

    def _complete(self, prompt: str) -> str:
        if self._completer is not None:
            return self._completer(prompt)
        spec = self.catalog.resolve()
        if spec is None:
            raise MemoryMergeUnavailable("no default model is configured")
        model = build_model_from_spec(
            spec,
            timeout_seconds=REQUEST_TIMEOUT_SECONDS,
            max_retries=0,
            purpose="structured",
        )
        try:
            response = model.invoke(prompt)
            text = getattr(response, "text", "") or ""
        finally:
            client = getattr(model, "root_client", None)
            if client is not None:
                client.close()
        return text

    # -- validation ------------------------------------------------------

    def _parse_payload(self, raw: str) -> dict[str, Any]:
        payload = _extract_json_object(raw)
        topics = payload.get("topics")
        if not isinstance(topics, list):
            raise MemoryMergeRejected("consolidation response carries no topics list")
        summary = payload.get("summary")
        if not isinstance(summary, dict):
            raise MemoryMergeRejected("consolidation response carries no summary")
        families = {family.value for family in MemoryTopicFamily}
        seen_files: set[str] = set()
        for topic in topics:
            if not isinstance(topic, dict):
                raise MemoryMergeRejected("topic entry is not an object")
            family = str(topic.get("topic_family") or "").strip()
            if family not in families:
                raise MemoryMergeRejected(f"topic family outside the enum: {family}")
            file_name = str(topic.get("file_name") or "").strip()
            if not _FILE_NAME.fullmatch(file_name):
                raise MemoryMergeRejected(f"invalid topic file name: {file_name}")
            if file_name in seen_files:
                raise MemoryMergeRejected(f"duplicate topic file name: {file_name}")
            seen_files.add(file_name)
            if not str(topic.get("title") or "").strip():
                raise MemoryMergeRejected("topic entry carries no title")
            if not str(topic.get("body") or "").strip():
                raise MemoryMergeRejected("topic entry carries no body")
        summary_body = self._render_summary(summary)
        validate_summary_body(summary_body)
        return {"topics": topics, "summary_body": summary_body}

    def _render_summary(self, summary: dict[str, Any]) -> str:
        return render_summary(
            profile=str(summary.get("profile") or ""),
            preferences=str(summary.get("preferences") or ""),
            tips=str(summary.get("tips") or ""),
            index=str(summary.get("index") or ""),
        )

    # -- apply -----------------------------------------------------------

    def _apply(self, payload: dict[str, Any]) -> list[MemoryEntry]:
        written: list[MemoryEntry] = []
        existing_by_file = {
            entry.file_name: entry for entry in self.memory.list_entries()
        }
        for topic in payload["topics"]:
            family = MemoryTopicFamily(str(topic["topic_family"]).strip())
            file_name = str(topic["file_name"]).strip()
            title = _truncate(str(topic["title"]), 120)
            body = str(topic["body"]).strip()
            existing = existing_by_file.get(file_name)
            if existing is not None and self._is_user_edited(existing):
                # 用户改过的条目保持原样：自动合并不得静默覆盖。
                continue
            memory_id = existing.memory_id if existing else f"mem_{uuid.uuid4().hex}"
            kind = existing.kind if existing else MemoryKind.LESSON
            entry = self.memory.upsert_entry(
                memory_id=memory_id,
                kind=kind,
                topic_family=family,
                title=title,
                file_name=file_name,
                derived_hash="",
                user_edited=False,
                auto_update=True,
            )
            derived = self.memory.write_entry_file(entry, body)
            entry = self.memory.upsert_entry(
                memory_id=memory_id,
                kind=kind,
                topic_family=family,
                title=title,
                file_name=file_name,
                derived_hash=derived,
                user_edited=False,
                auto_update=True,
            )
            written.append(entry)
        self.memory.write_summary(payload["summary_body"])
        self.memory.write_index(self._render_index(payload["summary_body"]))
        return written

    def _is_user_edited(self, entry: MemoryEntry) -> bool:
        """True when the file no longer matches the last automatic write."""

        if entry.user_edited or not entry.auto_update:
            return True
        return not self.memory.entry_body_matches(entry)

    @staticmethod
    def _render_index(summary_body: str) -> str:
        """MEMORY.md keeps the What's in Memory routing index for tool search."""

        lines = summary_body.splitlines()
        try:
            start = lines.index("## What's in Memory")
        except ValueError:
            return "# Memory index\n"
        index_lines = [line for line in lines[start + 1 :] if line.strip()]
        return "# Memory index\n\n" + "\n".join(index_lines) + "\n"


__all__ = [
    "MemoryConsolidationService",
    "MemoryMergeRejected",
    "MemoryMergeUnavailable",
]
