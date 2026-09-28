# =============================================================================
# 工作区记忆提取（ADR-0016 切片 2）
# =============================================================================
# run 进终态后：信号门先判定这次是否值得记录（查询、状态检查与普通问答直接
# no-op），有信号则按线程起去抖窗口；窗口到期且线程空闲时提取一次，把窗口内的
# 多轮合并成一次候选提取。提取复用当前 coordinator 模型，输入取终态转录 +
# 事件摘要 + tool-results 侧车，避开随后发生的工具输出预览化与冷点剪枝。
# Agent 只产候选；候选落 memory_candidates，不进 prompt。
# =============================================================================

"""Signal gate, debounced extraction and candidate persistence for memory."""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from cellwiki.adapters.openai_model import build_model_from_spec
from cellwiki.config import settings
from cellwiki.domain.memory import (
    MemoryCandidate,
    MemoryKind,
    MemoryTopicFamily,
)
from cellwiki.domain.runs import AgentEventType
from cellwiki.services.agent_memory import WorkspaceMemoryStore
from cellwiki.services.environment import _extract_json_object
from cellwiki.services.model_catalog import ModelCatalogService
from cellwiki.services.runtime_store import ACTIVE_RUN_STATUSES, RuntimeStore

# 信号词表：只在用户消息里匹配，避免把 Agent 自己的措辞当信号。
_SIGNAL_MARKERS: tuple[str, ...] = (
    "记住",
    "以后都",
    "以后不要",
    "不要再",
    "下次",
    "更正",
    "纠正",
    "不是这样",
    "偏好",
    "习惯",
    "remember",
    "forget",
    "from now on",
    "don't do that",
    "prefer",
    "always",
    "never",
    "correction",
)
# 明确的"不需要记忆"信号：纯查询与状态检查。
_NO_SIGNAL_MARKERS: tuple[str, ...] = (
    "这条写了什么",
    "这个页面写了什么",
    "lint 结果",
    "状态怎么样",
    "what does this page say",
    "show me the lint",
)

DIGEST_MAX_CHARS = 24_000
MAX_CANDIDATES_PER_RUN = 5
TITLE_MAX_CHARS = 120
BODY_MAX_CHARS = 2_000
MAX_SOURCE_REFS = 20
REQUEST_TIMEOUT_SECONDS = 60.0

_EXTRACT_INSTRUCTIONS = (
    "你在把一个已完成的知识库工作 run 提炼成工作区级记忆候选。"
    "只记录可复用的协作经验：用户的偏好、工作区约定、跑通的做法、决策理由及其来源指针。"
    "不要记录科学结论、页面正文、原始语料、整段对话、隐藏推理或凭据。"
    "没有值得记录的内容时返回空数组。"
    "只输出一个 JSON 对象："
    '{"candidates": [{"kind": "...", "topic_family": "...", "title": "...", "body": "...", "source_refs": ["..."]}]}。'
    f"kind 取 preference | convention | lesson | decision_pointer；"
    f"topic_family 取 {' | '.join(family.value for family in MemoryTopicFamily)}；"
    f"title 不超过 {TITLE_MAX_CHARS} 字，body 不超过 {BODY_MAX_CHARS} 字，"
    "source_refs 是这次 run 里可核查的句柄（文件路径、run_id、commit、页面 id）。"
    "直接给结论，不要代码块、不要额外解释。"
)


class MemoryExtractionDisabled(RuntimeError):
    """记忆总开关关闭时不做任何提取。"""


class MemoryNamingUnavailable(RuntimeError):
    """没有可用默认模型时跳过提取，不影响 run 终态。"""


def has_signal(message: str | None) -> bool:
    """信号门：这次 run 是否可能留下值得复用的记忆。

    纯查询与状态检查优先短路；其余按关键词表匹配。宁缺勿滥——漏记由后续
    重复出现补上，错记会污染记忆。
    """

    text = (message or "").strip()
    if not text:
        return False
    lowered = text.lower()
    if any(marker in lowered for marker in _NO_SIGNAL_MARKERS):
        return False
    return any(marker in lowered for marker in _SIGNAL_MARKERS)


def _truncate(text: str, limit: int) -> str:
    collapsed = " ".join(str(text).split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1] + "…"


def _valid_family(value: Any) -> MemoryTopicFamily | None:
    raw = str(value or "").strip()
    for family in MemoryTopicFamily:
        if family.value == raw:
            return family
    return None


def _valid_kind(value: Any) -> MemoryKind | None:
    raw = str(value or "").strip()
    for kind in MemoryKind:
        if kind.value == raw:
            return kind
    return None


class MemoryExtractionService:
    """Own the signal gate, the per-thread debounce window and extraction.

    ``completer`` 是测试注入点：传入 ``prompt -> str`` 即可完全离线驱动提取；
    生产走供应商目录的默认模型一次性结构化调用。提取失败只记日志，不影响 run。
    """

    def __init__(
        self,
        project_root: Path,
        store: RuntimeStore,
        memory: WorkspaceMemoryStore,
        catalog: ModelCatalogService,
        *,
        completer: Callable[[str], str] | None = None,
        on_candidates: Callable[[], Any] | None = None,
        debounce_minutes: int | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.project_root = Path(project_root)
        self.store = store
        self.memory = memory
        self.catalog = catalog
        self._completer = completer
        # 合并回调：候选落库后由 runtime 触发单写方 Phase 2；异常由调度线程兜底。
        self._on_candidates = on_candidates
        self._debounce_minutes = (
            debounce_minutes
            if debounce_minutes is not None
            else settings.agent_memory_debounce_minutes
        )
        self._sleep = sleep
        self._lock = threading.Lock()
        self._pending_at: dict[str, float] = {}
        self._pending_runs: dict[str, list[str]] = defaultdict(list)
        self._log = logging.getLogger(__name__)

    # -- terminal hook ---------------------------------------------------

    def notify_run_settled(self, run_id: str, thread_id: str, message: str) -> None:
        """Called once per settled run; decides whether to schedule extraction."""

        if not settings.agent_memory_enabled or not settings.agent_memory_generate:
            return
        if not has_signal(message):
            return
        self.schedule(thread_id, run_id)

    def schedule(self, thread_id: str, run_id: str) -> None:
        """Start (or restart) the debounce window for one thread."""

        if not settings.agent_memory_enabled:
            return
        with self._lock:
            self._pending_at[thread_id] = time.monotonic()
            runs = self._pending_runs[thread_id]
            if run_id not in runs:
                runs.append(run_id)
        worker = threading.Thread(
            target=self._debounced_extract,
            args=(thread_id,),
            name=f"memory-extract-{thread_id[:8]}",
            daemon=True,
        )
        worker.start()

    def _debounced_extract(self, thread_id: str) -> None:
        """Wait out the window, then extract once if the thread stayed idle."""

        while True:
            started = self._pending_at.get(thread_id)
            if started is None:
                return
            remaining = self._debounce_minutes * 60 - (time.monotonic() - started)
            if remaining <= 0:
                break
            self._sleep(min(remaining, 30.0))
        if self._thread_has_active_run(thread_id):
            # 线程又忙起来了：把窗口交给下一次终态触发。
            return
        with self._lock:
            run_ids = list(self._pending_runs.pop(thread_id, []))
            self._pending_at.pop(thread_id, None)
        try:
            created = self.extract(thread_id, run_ids)
            if created and self._on_candidates is not None:
                self._on_candidates()
        except Exception as error:  # noqa: BLE001 - 提取失败不影响任何 run
            self._log.warning("memory extraction failed for %s: %s", thread_id, error)

    def _thread_has_active_run(self, thread_id: str) -> bool:
        try:
            runs = self.store.list_runs(thread_id=thread_id, limit=10)
        except Exception:  # noqa: BLE001 - 读不到就按空闲处理，由调用方兜底
            return False
        return any(run.status in ACTIVE_RUN_STATUSES for run in runs)

    # -- extraction ------------------------------------------------------

    def extract(self, thread_id: str, run_ids: list[str]) -> list[MemoryCandidate]:
        """Run one extraction pass over the settled runs; may return no candidates."""

        if not settings.agent_memory_enabled:
            return []
        if not run_ids:
            return []
        prompt = self._build_prompt(thread_id, run_ids)
        if not prompt.strip():
            return []
        today = datetime.now(UTC).date().isoformat()
        if not self.memory.try_consume_extraction_slot(
            today, settings.agent_memory_daily_extractions
        ):
            self._log.info("memory extraction skipped: daily limit reached")
            return []
        raw = self._complete(prompt)
        if not raw.strip():
            return []
        return self._parse_candidates(raw, thread_id, run_ids)

    def _parse_candidates(
        self, raw: str, thread_id: str, run_ids: list[str]
    ) -> list[MemoryCandidate]:
        try:
            payload = _extract_json_object(raw)
        except Exception:  # noqa: BLE001 - 模型输出不是 JSON 时按无候选处理
            self._log.warning("memory extraction returned unparsable output")
            return []
        raw_candidates = payload.get("candidates")
        if not isinstance(raw_candidates, list):
            return []
        created: list[MemoryCandidate] = []
        for item in raw_candidates[:MAX_CANDIDATES_PER_RUN]:
            if not isinstance(item, dict):
                continue
            kind = _valid_kind(item.get("kind"))
            family = _valid_family(item.get("topic_family"))
            title = _truncate(str(item.get("title") or ""), TITLE_MAX_CHARS)
            body = _truncate(str(item.get("body") or ""), BODY_MAX_CHARS)
            if kind is None or family is None or not title or not body:
                continue
            refs = [
                _truncate(str(ref), 200)
                for ref in (item.get("source_refs") or [])
                if str(ref).strip()
            ][:MAX_SOURCE_REFS]
            created.append(
                self.memory.add_candidate(
                    kind=kind,
                    topic_family=family,
                    title=title,
                    body=body,
                    origin_run_id=run_ids[-1],
                    origin_thread_id=thread_id,
                    source_refs=refs,
                )
            )
        return created

    def _build_prompt(self, thread_id: str, run_ids: list[str]) -> str:
        parts = [_EXTRACT_INSTRUCTIONS]
        for run_id in run_ids:
            digest = self._run_digest(run_id)
            if digest:
                parts.append(digest)
        prompt = "\n\n".join(parts)
        return prompt[:DIGEST_MAX_CHARS]

    def _run_digest(self, run_id: str) -> str:
        """Bounded view of one settled run: message, answer text, event outline."""

        try:
            run = self.store.get_run(run_id)
        except KeyError:
            return ""
        lines = [
            f"## run {run_id}",
            f"status: {run.status.value}",
            f"user: {_truncate(run.input_message or '', 600)}",
        ]
        answer = self._assistant_text(thread_id=run.thread_id, run_id=run_id)
        if answer:
            lines.append("assistant: " + _truncate(answer, 1_200))
        outline = self._event_outline(run_id)
        if outline:
            lines.append("activity:\n" + outline)
        return "\n".join(lines)

    def _assistant_text(self, *, thread_id: str, run_id: str) -> str:
        try:
            records = self.store.list_model_messages(thread_id)
        except Exception:  # noqa: BLE001 - 输入缺一块不影响其余部分
            return ""
        texts = [
            str((record.get("content") or {}).get("text") or "")
            for record in records
            if record.get("run_id") == run_id and record.get("kind") == "assistant"
        ]
        return "\n".join(text for text in texts if text)

    def _event_outline(self, run_id: str) -> str:
        try:
            events = self.store.list_events(run_id)
        except Exception:  # noqa: BLE001
            return ""
        lines: list[str] = []
        for event in events:
            if event.type not in {
                AgentEventType.TOOL_COMPLETED,
                AgentEventType.RUN_STATUS,
            }:
                continue
            summary = _truncate(str(event.message or ""), 160)
            if not summary:
                continue
            lines.append(f"- {event.type.value}: {summary}")
            if len(lines) >= 30:
                break
        return "\n".join(lines)

    def _complete(self, prompt: str) -> str:
        if self._completer is not None:
            return self._completer(prompt)
        spec = self.catalog.resolve()
        if spec is None:
            raise MemoryNamingUnavailable("no default model is configured")
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


def extract_candidates_from_json(raw: str) -> list[dict[str, Any]]:
    """Test helper: parse a model response into candidate dicts."""

    payload = _extract_json_object(raw)
    items = payload.get("candidates")
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


__all__ = [
    "DIGEST_MAX_CHARS",
    "MemoryExtractionDisabled",
    "MemoryExtractionService",
    "MemoryNamingUnavailable",
    "extract_candidates_from_json",
    "has_signal",
]
