# =============================================================================
# 审批单元与会话的命名 —— 展示性元数据（LLM 标题 + 确定性兜底）
# =============================================================================
# 自动接受策略落地后，评审从"发布时逐个读 diff"变成"事后在历史列表里翻"，
# 列表可读性因此成为主路径。命名只写 PendingDiff.data 与 agent_threads.title：
# 不参与判定、不进 run 事件流、不计入 run 预算与用量。任何失败都只落
# data.unit_title_error 与服务日志，确定性回退标题照常可读、门禁不受影响。
# =============================================================================

"""Readable names for approval units and conversations (LLM title + fallbacks)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from cellwiki.adapters.openai_model import build_model_from_spec
from cellwiki.domain.pending_diff import PendingDiff
from cellwiki.services.environment import _extract_json_object
from cellwiki.services.git_executor import GitCommandError, GitExecutor
from cellwiki.services.model_catalog import ModelCatalogService
from cellwiki.services.runtime_store import ACTIVE_RUN_STATUSES, RuntimeStore

TITLE_MAX_CHARS = 30
# 回退标题放宽：它是确定性文本（提交 subject 本身就是干净的一行），
# 显示端有 CSS 省略；按 30 字硬切反而丢信息。
FALLBACK_TITLE_MAX_CHARS = 120
SUMMARY_MAX_CHARS = 200
ERROR_MAX_CHARS = 200
PROMPT_MAX_CHARS = 8000
PATCH_EXCERPT_MAX_CHARS = 4000
COMMIT_LIMIT = 20
FILE_LIMIT = 50
ANSWER_EXCERPT_MAX_CHARS = 1200
# 上限压到 20 秒：命名是展示性元数据，进程关闭时不为它多等（见 runtime.close）。
REQUEST_TIMEOUT_SECONDS = 20.0

# run 收口（ADR-0007 决策 14）以这个前缀代为提交，它描述不了内容本身。
_AUTO_VERSION_PREFIX = "wip(agent):"

_INSTRUCTIONS = (
    "你在为知识库的一次变更起名，方便人以后在列表里认出来。"
    '只输出一个 JSON 对象：{"title": "...", "summary": "..."}。'
    f"title 不超过 {TITLE_MAX_CHARS} 个字符，summary 不超过 {SUMMARY_MAX_CHARS} 个字符，"
    "都用中文，直接给结论，不要代码块、不要额外解释。"
)


class NamingUnavailableError(RuntimeError):
    """没有可用的默认模型（供应商目录为空或未设默认）时抛出。"""


def _truncate(text: str, limit: int) -> str:
    collapsed = " ".join(str(text).split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1] + "…"


def _parse_title_payload(raw: str) -> tuple[str, str]:
    """Extract ``{title, summary}`` from model output; tolerate fences and prose."""
    payload = _extract_json_object(raw)
    title = _truncate(payload.get("title") or "", TITLE_MAX_CHARS)
    if not title:
        raise ValueError("naming response carries no title")
    return title, _truncate(payload.get("summary") or "", SUMMARY_MAX_CHARS)


class UnitNamingService:
    """Names approval units and conversations; never blocks the approval gate.

    ``completer`` 是测试注入点：传入一个 ``prompt -> str`` 的可调用对象即可
    完全离线地驱动命名；生产走供应商目录的默认模型一次性结构化调用。
    """

    def __init__(
        self,
        project_root: Path,
        store: RuntimeStore,
        catalog: ModelCatalogService,
        *,
        completer: Callable[[str], str] | None = None,
    ) -> None:
        self.project_root = Path(project_root)
        self.store = store
        self.catalog = catalog
        self._completer = completer
        self._log = logging.getLogger(__name__)

    # ---- 审批单元 ----

    def fallback_title(self, diff: PendingDiff) -> str:
        """确定性回退标题，发布时物化进 ``data.unit_title_fallback``。

        链：最新 commit subject（跳过自动版本化提交）→ 会话标题 →
        "变更 N 文件 +X/−Y" → ``run_id``。物化而不是渲染时计算：提交 subject
        要读 git，列表渲染不能每个单元打一次 git。
        """
        subject = self._commit_subjects(diff, limit=1)
        if subject and not subject[0].startswith(_AUTO_VERSION_PREFIX):
            return _truncate(subject[0], FALLBACK_TITLE_MAX_CHARS)
        title = self._thread_title(diff.thread_id)
        if title:
            return _truncate(title, FALLBACK_TITLE_MAX_CHARS)
        if diff.files:
            return f"变更 {len(diff.files)} 文件 +{diff.insertions}/−{diff.deletions}"
        return diff.run_id

    def name_pending_diff(self, diff_id: str, *, source: str = "publish") -> None:
        """Name one unit; failures land in ``data.unit_title_error`` and the log."""
        try:
            diff = self.store.get_pending_diff(diff_id)
        except KeyError:
            return
        try:
            raw, model_label = self._complete(self._unit_prompt(diff))
            title, summary = _parse_title_payload(raw)
        except Exception as error:  # noqa: BLE001 - 命名失败不得向上传播
            self._record_failure(diff, error)
            return
        self._record_title(
            diff,
            title=title,
            summary=summary,
            source=source,
            model_label=model_label,
        )

    def _unit_prompt(self, diff: PendingDiff) -> str:
        parts = [_INSTRUCTIONS, f"用户请求：{self._run_message(diff.run_id) or '（未记录）'}"]
        subjects = self._commit_subjects(diff, limit=COMMIT_LIMIT)
        if subjects:
            parts.append("提交信息：\n" + "\n".join(f"- {item}" for item in subjects))
        if diff.files:
            listing = "\n".join(f"- {path}" for path in diff.files[:FILE_LIMIT])
            parts.append(
                f"变更文件（{len(diff.files)} 个，+{diff.insertions}/−{diff.deletions}）：\n"
                + listing
            )
        excerpt = self._patch_excerpt(diff)
        if excerpt:
            parts.append("补丁节选（尾部可能被截断）：\n" + excerpt)
        return "\n\n".join(parts)[:PROMPT_MAX_CHARS]

    def _record_title(
        self,
        diff: PendingDiff,
        *,
        title: str,
        summary: str,
        source: str,
        model_label: str,
    ) -> None:
        payload: dict[str, Any] = {
            "unit_title": title,
            "unit_title_source": source,
            "unit_title_model": model_label,
            "unit_title_at": datetime.now(UTC).isoformat(),
            "unit_title_error": None,
        }
        if summary:
            payload["unit_summary"] = summary
        try:
            # 只并 data：判定字段不动（模型调用期间单元可能已被接受）。
            self.store.patch_pending_diff_data(diff.diff_id, payload)
        except Exception as error:  # noqa: BLE001 - 写库失败只记日志，不回抛
            self._log.warning("unit naming write failed for %s: %s", diff.diff_id, error)

    def _record_failure(self, diff: PendingDiff, error: Exception) -> None:
        self._log.warning("unit naming failed for %s: %s", diff.diff_id, error)
        try:
            self.store.patch_pending_diff_data(
                diff.diff_id,
                {"unit_title_error": _truncate(str(error), ERROR_MAX_CHARS)},
            )
        except Exception as write_error:  # noqa: BLE001 - 兜底同样只记日志
            self._log.warning(
                "unit naming error write failed for %s: %s", diff.diff_id, write_error
            )

    # ---- 会话 ----

    def name_thread_once(self, thread_id: str) -> None:
        """Name a conversation once, after its first settled run.

        幂等：只对 ``title_source == "derived"`` 的会话动作，成功后写 ``"llm"``
        就不再调用。失败只记日志——会话标题没有错误字段，回退标题（确定性
        派生）本来就是可用的。
        """
        state = self.store.get_thread_title_state(thread_id)
        if state is None or state[1] != "derived":
            return
        runs = self.store.list_runs(thread_id=thread_id, limit=20)
        settled = [run for run in runs if run.status not in ACTIVE_RUN_STATUSES]
        if not settled:
            return
        first = min(settled, key=lambda run: run.created_at)
        try:
            raw, _ = self._complete(self._thread_prompt(thread_id, first.run_id))
            title, _summary = _parse_title_payload(raw)
        except Exception as error:  # noqa: BLE001 - 会话命名失败只记日志
            self._log.warning("thread naming failed for %s: %s", thread_id, error)
            return
        try:
            self.store.set_thread_title(thread_id, title, source="llm")
        except Exception as error:  # noqa: BLE001
            self._log.warning("thread naming write failed for %s: %s", thread_id, error)

    def _thread_prompt(self, thread_id: str, run_id: str) -> str:
        parts = [
            _INSTRUCTIONS,
            f"用户的第一条请求：{self._run_message(run_id) or '（未记录）'}",
        ]
        answer = self._run_answer_excerpt(thread_id, run_id)
        if answer:
            parts.append("这次回答的节选：\n" + answer)
        return "\n\n".join(parts)[:PROMPT_MAX_CHARS]

    def _run_answer_excerpt(self, thread_id: str, run_id: str) -> str:
        try:
            messages = self.store.list_messages(thread_id)
        except Exception:  # noqa: BLE001 - 命名输入缺一块不影响成败
            return ""
        for message in messages:
            if message.get("run_id") == run_id and message.get("role") == "assistant":
                return _truncate(message.get("content") or "", ANSWER_EXCERPT_MAX_CHARS)
        return ""

    # ---- 内部：模型调用与读取 ----

    def _complete(self, prompt: str) -> tuple[str, str]:
        """Return ``(raw model output, "<provider>/<model>" label)``."""
        if self._completer is not None:
            return self._completer(prompt), "injected"
        spec = self.catalog.resolve()
        if spec is None:
            raise NamingUnavailableError("no default model is configured")
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
            # 与设置页探针同例：一次性调用自己持有的 HTTP 池必须立刻释放。
            client = getattr(model, "root_client", None)
            if client is not None:
                client.close()
        if not text.strip():
            raise ValueError("naming response is empty")
        return text, f"{spec.provider_id}/{spec.model_id}"

    def _run_message(self, run_id: str) -> str:
        try:
            return self.store.get_run(run_id).input_message
        except KeyError:
            return ""

    def _thread_title(self, thread_id: str) -> str | None:
        state = self.store.get_thread_title_state(thread_id)
        return state[0] if state else None

    def _commit_subjects(self, diff: PendingDiff, *, limit: int) -> list[str]:
        if not diff.commits:
            return []
        try:
            return GitExecutor(self.project_root).commit_subjects(
                diff.commits[:limit]
            )
        except (GitCommandError, OSError, ValueError):
            return []

    def _patch_excerpt(self, diff: PendingDiff) -> str:
        """与待审面板同一范围（`pending_diff_patch`）的有界节选。"""
        refs = frozenset({"HEAD"})
        if diff.snapshot_commit is not None:
            refs = frozenset({diff.snapshot_commit, "HEAD"})
        try:
            reviewer = GitExecutor(
                self.project_root, max_output_bytes=PATCH_EXCERPT_MAX_CHARS * 4
            )
            patch = reviewer.diff_between(diff.snapshot_commit, enabled_refs=refs).patch
        except (GitCommandError, OSError, ValueError):
            return ""
        return patch[:PATCH_EXCERPT_MAX_CHARS]
