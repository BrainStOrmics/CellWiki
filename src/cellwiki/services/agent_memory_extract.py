# =============================================================================
# 工作区记忆提取（ADR-0016 切片 2）
# =============================================================================
# run 进终态后写入持久化 memory_jobs：普通会话等待线程空闲窗口，显式
# remember/correct 信号走短窗口高优先级路径。后台 worker 到期后再次确认
# 线程空闲，再提取候选；进程重启后由 pending/expired job 恢复。提取输入取
# 终态转录 + 事件摘要 + tool-results 侧车。Agent 只产候选；候选落
# memory_candidates，不进 prompt。
# =============================================================================

"""Persistent job scheduling, idle-gated extraction and candidate persistence."""

from __future__ import annotations

import logging
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from cellwiki.adapters.openai_model import build_model_from_spec
from cellwiki.config import settings
from cellwiki.domain.memory import (
    MemoryCandidate,
    MemoryJob,
    MemoryKind,
    MemoryTopicFamily,
)
from cellwiki.domain.model_providers import ResolvedModelSpec
from cellwiki.domain.runs import AgentEventType, AgentRunStatus
from cellwiki.services.agent_memory import WorkspaceMemoryStore
from cellwiki.services.agent_memory_jobs import MemoryJobStore
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
TOOL_RESULT_MAX_FILES = 4
TOOL_RESULT_FILE_MAX_CHARS = 4_000
TOOL_RESULT_TOTAL_MAX_CHARS = 12_000
REQUEST_TIMEOUT_SECONDS = 60.0
JOB_LEASE_SECONDS = 120
JOB_RETRY_MAX = 5

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


class MemoryExtractionEmptyOutput(RuntimeError):
    """Provider returned no usable extraction text; retry the job later."""


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


def _ensure_utc(value: datetime) -> datetime:
    return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)


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
    """Own persistent memory jobs, idle eligibility and extraction.

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
        model_spec_for_run: Callable[[str], ResolvedModelSpec | None] | None = None,
        on_candidates: Callable[[], Any] | None = None,
        jobs: MemoryJobStore | None = None,
        debounce_minutes: int | None = None,
        min_idle_hours: int | None = None,
        max_age_days: int | None = None,
        max_threads_per_scan: int | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.project_root = Path(project_root)
        self.store = store
        self.memory = memory
        self.catalog = catalog
        self._completer = completer
        # 复用产生该 run 的模型；解析不到时才回落目录默认选择。
        self._model_spec_for_run = model_spec_for_run
        # 合并回调：候选落库后由 runtime 触发单写方 Phase 2；异常由调度线程兜底。
        self._on_candidates = on_candidates
        self.jobs = jobs or MemoryJobStore(store.path, self.project_root)
        self._debounce_minutes = (
            debounce_minutes
            if debounce_minutes is not None
            else settings.agent_memory_debounce_minutes
        )
        self._min_idle_hours = (
            min_idle_hours
            if min_idle_hours is not None
            else settings.agent_memory_min_idle_hours
        )
        self._max_age_days = (
            max_age_days
            if max_age_days is not None
            else settings.agent_memory_max_age_days
        )
        self._max_threads_per_scan = (
            max_threads_per_scan
            if max_threads_per_scan is not None
            else settings.agent_memory_max_threads_per_scan
        )
        self._now = now or (lambda: datetime.now(UTC))
        self._log = logging.getLogger(__name__)

    # -- terminal hook ---------------------------------------------------

    def notify_run_settled(self, run_id: str, thread_id: str, message: str) -> None:
        """Queue a settled run for background extraction.

        Explicit memory language is a fast path, not a hard gate. Ordinary
        terminal runs are queued only when automatic extraction is enabled.
        """

        if not settings.agent_memory_enabled or not settings.agent_memory_generate:
            return
        explicit = has_signal(message)
        if not explicit and not settings.agent_memory_auto_extract:
            return
        self.schedule(thread_id, run_id, explicit=explicit)

    def schedule(
        self,
        thread_id: str,
        run_id: str,
        *,
        explicit: bool = False,
    ) -> MemoryJob | None:
        """Create or refresh the persistent extraction job for one thread."""

        if not settings.agent_memory_enabled:
            return None
        now = self._now()
        delay = (
            timedelta(minutes=self._debounce_minutes)
            if explicit
            else timedelta(hours=self._min_idle_hours)
        )
        watermark = self._run_finished_at(run_id) or now.isoformat()
        return self.jobs.upsert_thread_job(
            thread_id=thread_id,
            available_at=now + delay,
            input_watermark=watermark,
            priority=1 if explicit else 0,
            payload={"run_id": run_id, "explicit": explicit},
        )

    def run_due_jobs(self, *, limit: int | None = None) -> int:
        """Claim and process one bounded batch of background memory jobs."""

        if not settings.agent_memory_enabled or not settings.agent_memory_generate:
            return 0
        now = self._now()
        claimed = self.jobs.claim_thread_jobs(
            now=now,
            worker_id=f"mem-extract-{uuid.uuid4().hex[:8]}",
            lease_seconds=JOB_LEASE_SECONDS,
            limit=min(
                limit or self._max_threads_per_scan,
                settings.agent_memory_extract_concurrency,
            ),
        )
        if not claimed:
            return 0
        workers = max(
            1,
            min(
                settings.agent_memory_extract_concurrency,
                len(claimed),
            ),
        )
        processed = 0
        with ThreadPoolExecutor(
            max_workers=workers,
            thread_name_prefix="cellwiki-memory-extract",
        ) as pool:
            futures = {
                pool.submit(self._process_job, job, now=now): job
                for job in claimed
            }
            for future in as_completed(futures):
                job = futures[future]
                try:
                    future.result()
                except Exception as error:  # noqa: BLE001 - 单 job 失败不影响其他 job
                    self._log.warning(
                        "memory extraction job failed for %s: %s",
                        job.thread_id,
                        error,
                    )
                    self.jobs.fail(
                        job.job_id,
                        error=str(error),
                        retry_at=now + self._retry_delay(job.retry_count),
                        max_retries=JOB_RETRY_MAX,
                    )
                processed += 1
        return processed

    def _process_job(self, job: MemoryJob, *, now: datetime) -> None:
        """Run one claimed thread extraction job with a fresh eligibility check."""

        if not settings.agent_memory_enabled or not settings.agent_memory_generate:
            return
        if not settings.agent_memory_auto_extract and job.priority == 0:
            self.jobs.reschedule(
                job.job_id,
                available_at=now + timedelta(days=1),
                error="automatic memory extraction is disabled",
            )
            return
        next_allowed = self._next_allowed_at(job, now=now)
        if next_allowed > now:
            self.jobs.reschedule(
                job.job_id,
                available_at=next_allowed,
                error="thread is not idle enough for memory extraction",
            )
            return
        run_ids = self._eligible_run_ids(
            job.thread_id,
            after_watermark=job.last_success_watermark,
            now=now,
        )
        watermark = (
            self._watermark_for_run_ids(run_ids)
            or job.input_watermark
            or now.isoformat()
        )
        if not run_ids:
            self.jobs.complete_without_output(job.job_id, watermark=watermark)
            return
        today = now.date().isoformat()
        if not self.memory.try_consume_extraction_slot(
            today, settings.agent_memory_daily_extractions
        ):
            self.jobs.reschedule(
                job.job_id,
                available_at=now + timedelta(minutes=10),
                error="daily memory extraction limit reached",
            )
            return
        created = self.extract(job.thread_id, run_ids, consume_slot=False)
        if created:
            self.jobs.complete_with_output(job.job_id, watermark=watermark)
            if self._on_candidates is not None:
                try:
                    self._on_candidates()
                except Exception:  # noqa: BLE001 - 提取成功不应被合并失败回滚
                    self._log.warning(
                        "memory consolidation failed after extraction; "
                        "candidates remain available for retry",
                        exc_info=True,
                    )
            return
        self.jobs.complete_without_output(job.job_id, watermark=watermark)

    def _next_allowed_at(self, job: MemoryJob, *, now: datetime) -> datetime:
        """Return when a thread may next be extracted."""

        if self._thread_has_active_run(job.thread_id):
            return now + timedelta(minutes=1)
        latest = self._latest_eligible_finished_at(job.thread_id)
        if latest is None:
            return now + timedelta(minutes=1)
        if job.priority > 0:
            return latest + timedelta(minutes=self._debounce_minutes)
        return latest + timedelta(hours=self._min_idle_hours)

    def _eligible_run_ids(
        self,
        thread_id: str,
        *,
        after_watermark: str,
        now: datetime,
    ) -> list[str]:
        """Return terminal run ids eligible for a bounded extraction pass."""

        cutoff = now - timedelta(days=self._max_age_days)
        runs = []
        try:
            for run in self.store.list_runs(thread_id=thread_id, limit=100):
                if run.finished_at is None:
                    continue
                if run.status in ACTIVE_RUN_STATUSES:
                    continue
                if run.status is AgentRunStatus.CANCELLED:
                    continue
                finished = _ensure_utc(run.finished_at)
                if finished < cutoff:
                    continue
                if after_watermark and finished.isoformat() <= after_watermark:
                    continue
                runs.append((finished, run.run_id))
        except Exception:  # noqa: BLE001 - 单线程读取失败按无候选处理
            return []
        runs.sort(key=lambda item: item[0])
        return [run_id for _finished, run_id in runs]

    def _latest_eligible_finished_at(self, thread_id: str) -> datetime | None:
        try:
            values = [
                _ensure_utc(run.finished_at)
                for run in self.store.list_runs(thread_id=thread_id, limit=100)
                if run.finished_at is not None
                and run.status not in ACTIVE_RUN_STATUSES
                and run.status is not AgentRunStatus.CANCELLED
            ]
        except Exception:  # noqa: BLE001
            return None
        return max(values, default=None)

    def _watermark_for_run_ids(self, run_ids: list[str]) -> str:
        values: list[datetime] = []
        for run_id in run_ids:
            try:
                run = self.store.get_run(run_id)
            except KeyError:
                continue
            if run.finished_at is not None:
                values.append(_ensure_utc(run.finished_at))
        return max(values).isoformat() if values else ""

    def _run_finished_at(self, run_id: str) -> str:
        try:
            run = self.store.get_run(run_id)
        except KeyError:
            return ""
        return (
            _ensure_utc(run.finished_at).isoformat()
            if run.finished_at is not None
            else ""
        )

    @staticmethod
    def _retry_delay(retry_count: int) -> timedelta:
        return timedelta(minutes=min(2**retry_count, 60))

    def _thread_has_active_run(self, thread_id: str) -> bool:
        try:
            runs = self.store.list_runs(thread_id=thread_id, limit=10)
        except Exception:  # noqa: BLE001 - 读不到就按空闲处理，由调用方兜底
            return False
        return any(run.status in ACTIVE_RUN_STATUSES for run in runs)

    # -- extraction ------------------------------------------------------

    def extract(
        self,
        thread_id: str,
        run_ids: list[str],
        *,
        consume_slot: bool = True,
    ) -> list[MemoryCandidate]:
        """Run one extraction pass over the settled runs; may return no candidates."""

        if not settings.agent_memory_enabled:
            return []
        if not run_ids:
            return []
        prompt = self._build_prompt(thread_id, run_ids)
        if not prompt.strip():
            return []
        today = datetime.now(UTC).date().isoformat()
        if consume_slot:
            if not self.memory.try_consume_extraction_slot(
                today, settings.agent_memory_daily_extractions
            ):
                self._log.info("memory extraction skipped: daily limit reached")
                return []
        raw = self._complete(prompt, run_ids[-1])
        if not raw.strip():
            raise MemoryExtractionEmptyOutput(
                "memory extraction returned empty output"
            )
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
        tool_results = self._tool_result_digest(run_id)
        if tool_results:
            lines.append("tool_results:\n" + tool_results)
        outline = self._event_outline(run_id)
        if outline:
            lines.append("activity:\n" + outline)
        return "\n".join(lines)

    def _tool_result_digest(self, run_id: str) -> str:
        """Read a bounded slice of this run's oversized tool-output sidecars."""

        sidecar_dir = (
            self.project_root
            / "data"
            / "runtime"
            / "tool-results"
            / run_id
        )
        if not sidecar_dir.is_dir():
            return ""
        lines: list[str] = []
        used = 0
        files = sorted(
            path
            for path in sidecar_dir.iterdir()
            if path.is_file() and path.suffix == ".txt"
        )
        for path in files[:TOOL_RESULT_MAX_FILES]:
            if used >= TOOL_RESULT_TOTAL_MAX_CHARS:
                break
            remaining = TOOL_RESULT_TOTAL_MAX_CHARS - used
            read_limit = min(TOOL_RESULT_FILE_MAX_CHARS, remaining)
            try:
                with path.open("r", encoding="utf-8", errors="replace") as handle:
                    text = handle.read(read_limit + 1)
            except OSError:
                continue
            excerpt = _truncate(
                text, min(TOOL_RESULT_FILE_MAX_CHARS, remaining)
            )
            if not excerpt:
                continue
            lines.append(f"- {path.name}: {excerpt}")
            used += len(excerpt)
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

    def _complete(self, prompt: str, run_id: str | None = None) -> str:
        if self._completer is not None:
            return self._completer(prompt)
        spec = self._spec_for_run(run_id) or self.catalog.resolve()
        if spec is None:
            raise MemoryNamingUnavailable("no model is available for memory extraction")
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

    def _spec_for_run(self, run_id: str | None) -> ResolvedModelSpec | None:
        if self._model_spec_for_run is None or not run_id:
            return None
        try:
            return self._model_spec_for_run(run_id)
        except Exception as error:  # noqa: BLE001 - 解析失败回落默认模型
            self._log.warning(
                "memory extraction could not resolve run model %s: %s", run_id, error
            )
            return None


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
    "MemoryExtractionEmptyOutput",
    "MemoryExtractionService",
    "MemoryNamingUnavailable",
    "TOOL_RESULT_FILE_MAX_CHARS",
    "TOOL_RESULT_MAX_FILES",
    "TOOL_RESULT_TOTAL_MAX_CHARS",
    "extract_candidates_from_json",
    "has_signal",
]
