# =============================================================================
# 智能体工具 —— 暴露给 CellWiki 智能体的领域级工具函数
# =============================================================================
# 本模块定义智能体可调用的各类工具，按功能分组：
#   - 只读工具（查询项目状态、搜索 Wiki、读取页面）
#   - 导入工具（准备提取变更集）
#   - 记忆工具（召回项目记忆、提交记忆候选）
#   - 研究工具（搜索外部来源）
#   - 提交工具（提交已审批的变更集）
# 每个工具函数通过 @tool 装饰器注册为 LangChain 可调用工具。
# =============================================================================

"""High-level domain tools exposed to the CellWiki agent."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from langchain.tools import ToolRuntime
from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from cellwiki.api.reader import WikiReader
from cellwiki.config import settings
from cellwiki.domain.contracts import (
    AgentAnswer,
    ApprovalPolicy,
    IngestStage,
    TaskStatus,
    WikiAgentContext,
)
from cellwiki.services.central_writer import CentralWriter
from cellwiki.services.changesets import ChangeSetRepository
from cellwiki.services.quality import inspect_projection
from cellwiki.services.ingest import IngestService
from cellwiki.services.revisions import IngestRevisionService
from cellwiki.services.linting import LintFixService
from cellwiki.services.sources import SourceRegistry
from cellwiki.services.attachments import AttachmentService
from cellwiki.services.tasks import TaskEventRepository
from cellwiki.domain.memory import MemoryCandidate, MemoryKind
from cellwiki.services.memory import MemoryStore
from cellwiki.services.research import ResearchService
from cellwiki.services.operations import current_agent_run_id
from cellwiki.services.pipeline import KnowledgePipelineHarness, PipelineBusyError
from cellwiki.domain.contracts import PipelineTaskType
from cellwiki.services.query import FormalQueryService


class FinalAnswerInput(BaseModel):
    """Compact model-facing input; grounding metadata is runtime-owned."""

    answer: str
    citations: list[dict[str, Any]] = Field(default_factory=list)
    confidence: str | int | float = "medium"
    missing_evidence: list[str] = Field(default_factory=list)
    knowledge_scope: str = "formal"
    knowledge_version: str | None = None


def _normalize_answer_confidence(value: Any) -> str:
    """Map loose provider confidence values onto the stable AgentAnswer enum."""

    if isinstance(value, bool):
        return "medium"
    if isinstance(value, int | float):
        if value >= 0.75:
            return "high"
        if value <= 0.35:
            return "low"
        return "medium"
    normalized = " ".join(str(value or "").strip().lower().split())
    if normalized in {"high", "medium", "low"}:
        return normalized
    try:
        return _normalize_answer_confidence(float(normalized))
    except ValueError:
        return "medium"


def _normalize_knowledge_scope(value: Any) -> str:
    """Keep operational answers out of the formal scientific citation gate."""

    normalized = " ".join(str(value or "").strip().lower().replace("_", "-").split())
    aliases = {
        "formal": "formal",
        "published": "formal",
        "wiki": "formal",
        "general": "general",
        "workflow": "general",
        "operation": "general",
        "operational": "general",
        "task": "general",
        "status": "general",
        "lint": "general",
        "quality": "general",
        "quality-check": "general",
        "project-quality": "general",
        "attachment": "attachment",
        "file": "attachment",
        "uploaded-file": "attachment",
        "unvalidated": "unvalidated",
        "candidate": "unvalidated",
    }
    return aliases.get(normalized, "general")


def build_final_answer_tool(project_root: Path) -> BaseTool:
    """Build the coordinator's validated, direct-return answer boundary."""

    query_service = FormalQueryService(Path(project_root).resolve())

    @tool("submit_agent_answer", args_schema=FinalAnswerInput, return_direct=True)
    def submit_agent_answer(
        answer: str,
        citations: list[dict[str, Any]] | None = None,
        confidence: str | int | float = "medium",
        missing_evidence: list[str] | None = None,
        knowledge_scope: str = "formal",
        knowledge_version: str | None = None,
    ) -> str:
        """Finish with a grounded answer, exact page citations, and evidence gaps."""
        # Providers sometimes echo display metadata from read tools (title/path/sections).
        # Keep the persisted contract narrow while tolerating that harmless boundary noise.
        citation_fields = {
            "page_id",
            "source_id",
            "locator",
            "evidence_id",
            "attachment_id",
            "original_name",
            "section_locator",
            "quote",
            "section",
            "type",
        }
        normalized_citations: list[dict[str, Any]] = []
        for citation in citations or []:
            normalized = {
                key: value for key, value in citation.items() if key in citation_fields
            }
            if normalized.get("attachment_id"):
                # Providers commonly call the attachment locator `locator`,
                # `quote`, or `section`; the domain contract uses one stable
                # field so page/section provenance is not lost in serialization.
                section_locator = (
                    normalized.get("section_locator")
                    or normalized.get("locator")
                    or normalized.get("quote")
                    or normalized.get("section")
                )
                if section_locator:
                    normalized["section_locator"] = str(section_locator)[:1_000]
                normalized.pop("quote", None)
                normalized.pop("section", None)
                normalized["type"] = "thread_attachment"
            elif normalized.get("page_id"):
                locator = (
                    normalized.get("locator")
                    or normalized.get("section_locator")
                    or normalized.get("quote")
                    or normalized.get("section")
                )
                normalized = {
                    key: value
                    for key, value in {
                        "page_id": normalized.get("page_id"),
                        "source_id": normalized.get("source_id"),
                        "locator": str(locator)[:1_000] if locator else None,
                        "evidence_id": normalized.get("evidence_id"),
                    }.items()
                    if value is not None
                }
            normalized_citations.append(normalized)
        candidate = AgentAnswer.model_validate(
            {
                "answer": answer,
                "citations": normalized_citations,
                "confidence": _normalize_answer_confidence(confidence),
                "missing_evidence": missing_evidence or [],
                "knowledge_scope": _normalize_knowledge_scope(knowledge_scope),
                "knowledge_version": knowledge_version,
            }
        )
        validated = query_service.validate_answer(candidate)
        return validated.model_dump_json()

    return submit_agent_answer


# ---------------------------------------------------------------------------
# 构建只读工具集
# 提供给智能体的四类只读操作：
# 1. get_project_status — 获取项目概览（页面数、来源数、待审批 ChangeSet 数）
# 2. search_wiki — 搜索已发布的 Wiki 页面
# 3. read_wiki_page — 读取单个页面内容（超过 20K 字符时截断）
# 4. get_change_set — 读取 ChangeSet 详情（用于审批前查看）
# 所有工具返回 JSON 字符串，确保智能体可以解析结果。
# ---------------------------------------------------------------------------
def build_read_tools(project_root: Path) -> list[BaseTool]:
    root = Path(project_root).resolve()
    reader = WikiReader(root)
    sources = SourceRegistry(root)
    changesets = ChangeSetRepository(root)
    pipeline = KnowledgePipelineHarness(root)
    query_service = FormalQueryService(root, reader=reader, pipeline=pipeline, changesets=changesets)

    # 获取项目状态：已发布页面数、注册来源数、待审批 ChangeSet 数
    @tool("get_project_status")
    def get_project_status() -> str:
        """Return counts for published pages, registered sources, and pending ChangeSets."""
        pending_dir = root / "data" / "runtime" / "changesets"
        policy_state = pipeline.approval_policy_status()
        result = {
            "project_id": "cellwiki",
            "page_count": len(reader.tree()),
            "source_count": len(sources.list_sources()),
            "change_set_count": len(list(pending_dir.glob("cs_*.json"))) if pending_dir.exists() else 0,
            "knowledge_version": pipeline.current_knowledge_version(),
            "approval_policy": policy_state["policy"],
            "approval_policy_valid": policy_state["valid"],
            "approval_policy_error": policy_state["error"],
            "active_pipeline_task": pipeline.active_task(),
        }
        return json.dumps(result, ensure_ascii=False)

    # 搜索 Wiki：返回页面 ID 和简短摘要
    @tool("search_wiki")
    def search_wiki(query: str, limit: int = 10) -> str:
        """Search published CellWiki pages and return page IDs with short snippets."""
        return query_service.search(query, limit).model_dump_json()

    # 读取页面：按领域页面 ID 读取，不接受文件路径
    # 超过 20K 字符时截断，避免超出 LLM 上下文窗口
    @tool("read_wiki_page")
    def read_wiki_page(page_id: str) -> str:
        """Read one published Wiki page by domain page ID; never accepts a file path."""
        try:
            page = query_service.read_page(page_id)
        except (KeyError, FileNotFoundError):
            # A guessed page ID is recoverable model input, not a runtime crash.
            return json.dumps(
                {"error": "page_not_found", "page_id": page_id},
                ensure_ascii=False,
            )
        if len(page.markdown) > 20_000:
            page = page.model_copy(update={"markdown": page.markdown[:20_000] + "\n...[truncated]"})
        return page.model_dump_json()

    @tool("list_change_sets")
    def list_change_sets(limit: int = 10) -> str:
        """List a bounded summary of recent ChangeSets without exposing local paths."""

        bounded_limit = max(1, min(limit, 20))
        summaries = [
            {
                "change_set_id": change_set.change_set_id,
                "run_id": change_set.run_id,
                "risk": change_set.risk.value,
                "reason": change_set.reason,
                "snapshot_id": change_set.snapshot_id,
                "created_at": change_set.created_at.isoformat(),
            }
            for change_set in changesets.list()[:bounded_limit]
        ]
        return json.dumps({"change_sets": summaries}, ensure_ascii=False)

    # 读取 ChangeSet：在要求用户审批前查看不可变的提议
    @tool("get_change_set")
    def get_change_set(change_set_id: str) -> str:
        """Read an immutable proposed ChangeSet before asking the user to approve it."""
        return changesets.get(change_set_id).model_dump_json()

    return [
        get_project_status,
        search_wiki,
        read_wiki_page,
        list_change_sets,
        get_change_set,
    ]


def build_attachment_tools(project_root: Path) -> list[BaseTool]:
    """Build CellWiki-owned attachment tools; never expose generic file paths."""

    attachments = AttachmentService(Path(project_root).resolve())

    def runtime_scope(runtime: ToolRuntime) -> tuple[str | None, set[str]]:
        """Resolve the current thread without asking the model to invent IDs."""

        context = runtime.context
        if isinstance(context, WikiAgentContext):
            return context.thread_id, set(context.attachment_ids)
        if isinstance(context, dict):
            thread_id = context.get("thread_id")
            attachment_ids = context.get("attachment_ids", [])
            return (
                str(thread_id) if thread_id else None,
                {str(item) for item in attachment_ids if item},
            )
        return None, set()

    def missing_context() -> str:
        return json.dumps(
            {
                "error": "thread_context_missing",
                "message": "The current Agent thread context is unavailable; do not ask the user for thread_id.",
            },
            ensure_ascii=False,
        )

    def promotion_allowed(runtime: ToolRuntime) -> bool:
        context = runtime.context
        if isinstance(context, WikiAgentContext):
            return context.allow_attachment_promotion
        if isinstance(context, dict):
            return bool(context.get("allow_attachment_promotion", False))
        return False

    def promotion_not_allowed(attachment_id: str) -> str:
        return json.dumps(
            {
                "error": "attachment_promotion_not_allowed",
                "attachment_id": attachment_id,
                "message": (
                    "The current user request is attachment-grounded read-only. "
                    "Answer from the attachment tools; do not register sources or ingest unless the user explicitly asks for it."
                ),
            },
            ensure_ascii=False,
        )

    def attachment_payload(record: Any) -> dict[str, Any]:
        payload = record.model_dump(mode="json")
        payload.pop("stored_path", None)
        payload.pop("text_path", None)
        payload["text_available"] = bool(record.text_path)
        return payload

    def selected_records(thread_id: str, active_ids: set[str]) -> list[Any]:
        """Keep every attachment operation inside the run's explicit references."""

        return [
            record
            for record in attachments.list(thread_id)
            if record.attachment_id in active_ids
        ]

    def not_selected(thread_id: str, attachment_id: str) -> str:
        return json.dumps(
            {
                "error": "attachment_not_selected",
                "thread_id": thread_id,
                "attachment_id": attachment_id,
                "message": "The attachment is not referenced by the current Agent run.",
            },
            ensure_ascii=False,
        )

    @tool("list_thread_attachments")
    def list_thread_attachments(runtime: ToolRuntime) -> str:
        """List the files attached to the current Agent thread."""

        thread_id, active_ids = runtime_scope(runtime)
        if not thread_id:
            return missing_context()
        try:
            records = selected_records(thread_id, active_ids)
        except KeyError:
            return json.dumps({"error": "thread_not_found", "thread_id": thread_id}, ensure_ascii=False)
        return json.dumps(
            {"thread_id": thread_id, "attachments": [attachment_payload(record) for record in records]},
            ensure_ascii=False,
        )

    @tool("read_attachment_excerpt")
    def read_attachment_excerpt(
        runtime: ToolRuntime,
        attachment_id: str | None = None,
        start: int = 0,
        max_chars: int = 4000,
    ) -> str:
        """Read a bounded excerpt from a current-thread attachment."""

        thread_id, active_ids = runtime_scope(runtime)
        if not thread_id:
            return missing_context()
        try:
            records = selected_records(thread_id, active_ids)
        except KeyError:
            return json.dumps({"error": "thread_not_found", "thread_id": thread_id}, ensure_ascii=False)
        if attachment_id is None:
            if len(records) != 1:
                return json.dumps(
                    {
                        "error": "attachment_id_required",
                        "attachments": [attachment_payload(record) for record in records],
                    },
                    ensure_ascii=False,
                )
            attachment_id = records[0].attachment_id
        elif attachment_id not in active_ids:
            return not_selected(thread_id, attachment_id)
        try:
            record = attachments.get(thread_id, attachment_id)
            text = attachments.read_text(thread_id, attachment_id)
        except KeyError:
            return json.dumps(
                {"error": "attachment_not_found", "thread_id": thread_id, "attachment_id": attachment_id},
                ensure_ascii=False,
            )
        if not text:
            return json.dumps(
                {
                    "error": "attachment_text_unavailable",
                    "attachment_id": attachment_id,
                    "original_name": record.original_name,
                    "media_type": record.media_type,
                    "message": "No extractable text is available for this attachment.",
                },
                ensure_ascii=False,
            )
        bounded_start = max(0, min(start, len(text)))
        bounded_limit = max(1, min(max_chars, 12_000))
        excerpt = text[bounded_start : bounded_start + bounded_limit]
        return json.dumps(
            {
                "attachment_id": attachment_id,
                "original_name": record.original_name,
                "chunk_id": f"{attachment_id}:text:{bounded_start}",
                "excerpt": excerpt,
                "truncated": bounded_start + bounded_limit < len(text),
            },
            ensure_ascii=False,
        )

    @tool("search_attachment_text")
    def search_attachment_text(query: str, runtime: ToolRuntime) -> str:
        """Search extracted text across the current Agent thread's attachments."""

        thread_id, active_ids = runtime_scope(runtime)
        if not thread_id:
            return missing_context()
        try:
            matches = attachments.search_text(thread_id, query, attachment_ids=active_ids)
        except KeyError:
            return json.dumps({"error": "thread_not_found", "thread_id": thread_id}, ensure_ascii=False)
        return json.dumps({"thread_id": thread_id, "matches": matches}, ensure_ascii=False)

    @tool("register_attachment_as_source")
    def register_attachment_as_source(runtime: ToolRuntime, attachment_id: str) -> str:
        """Promote one current-thread attachment into the governed SourceRegistry."""

        thread_id, active_ids = runtime_scope(runtime)
        if not thread_id:
            return missing_context()
        if attachment_id not in active_ids:
            return not_selected(thread_id, attachment_id)
        if not promotion_allowed(runtime):
            return promotion_not_allowed(attachment_id)
        try:
            before = attachments.get(thread_id, attachment_id)
            already_promoted = before.promoted_source_id is not None
            source = attachments.promote_to_source(thread_id, attachment_id)
            after = attachments.get(thread_id, attachment_id)
        except KeyError:
            return json.dumps(
                {"error": "attachment_not_found", "thread_id": thread_id, "attachment_id": attachment_id},
                ensure_ascii=False,
            )
        return json.dumps(
            {
                "already_promoted": already_promoted,
                # Keep the canonical identifier flat so the next model turn
                # does not confuse it with the content hash nested in source.
                "source_id": source.source_id,
                "attachment": attachment_payload(after),
                "source": source.model_dump(mode="json"),
            },
            ensure_ascii=False,
        )

    return [
        list_thread_attachments,
        read_attachment_excerpt,
        search_attachment_text,
        register_attachment_as_source,
    ]


# ---------------------------------------------------------------------------
# 构建导入工具集
# prepare_ingest_change_set — 分析一个已注册来源并持久化提取 ChangeSet，
# 但不发布它。取消权限来自持久化运行时上下文，而非模型提供的任务标识符。
# ---------------------------------------------------------------------------
def _resolve_registered_source_id(sources: SourceRegistry, value: str) -> str:
    """Resolve a Source ID and tolerate model-copied content-hash aliases."""

    requested = value.strip()
    try:
        sources.get(requested)
        return requested
    except KeyError:
        pass

    hash_value = requested.removeprefix("src_").removeprefix("sha256:")
    for source in sources.list_sources():
        content_hash = source.content_hash.removeprefix("sha256:")
        if hash_value == content_hash:
            return source.source_id
    raise KeyError(requested)


def build_ingest_tools(project_root: Path) -> list[BaseTool]:
    root = Path(project_root).resolve()
    ingest = IngestService(root)
    sources = SourceRegistry(root)
    revisions = IngestRevisionService(root, ingest=ingest)
    pipeline = KnowledgePipelineHarness(root)

    @tool("prepare_ingest_change_set")
    def prepare_ingest_change_set(source_id: str, run_id: str = "") -> str:
        """Analyze one registered source and persist a proposed extraction ChangeSet without publishing it."""
        requested_source_id = source_id
        try:
            source_id = _resolve_registered_source_id(sources, source_id)
        except KeyError:
            return json.dumps(
                {
                    "error": "source_not_found",
                    "source_id": requested_source_id,
                    "message": (
                        "Use the canonical source.source_id returned by "
                        "register_attachment_as_source; content_hash is not a Source ID."
                    ),
                },
                ensure_ascii=False,
            )
        effective_run_id = run_id.strip() or current_agent_run_id() or f"ingest_{uuid.uuid4().hex}"
        change_set = ingest.prepare_change_set(
            source_id,
            effective_run_id,
            # 取消权限来自持久化运行时上下文，而非模型提供的任务标识符
            cancellation_id=current_agent_run_id() or effective_run_id,
        )
        policy = pipeline.approval_policy()
        snapshot_id = getattr(change_set, "snapshot_id", None)
        snapshot = (
            pipeline.get_snapshot(snapshot_id).model_dump(mode="json")
            if snapshot_id
            else None
        )
        return json.dumps(
            {
                "source_id": source_id,
                "change_set": json.loads(change_set.model_dump_json()),
                "snapshot": snapshot,
                "run_id": effective_run_id,
                "approval_policy": policy.value,
                "requires_human_review": policy is not ApprovalPolicy.AUTO_ALL,
            },
            ensure_ascii=False,
        )

    @tool("request_ingest_revision")
    def request_ingest_revision(
        change_set_id: str,
        comments: list[str],
        reviewer: str = "default-reviewer",
        run_id: str = "",
    ) -> str:
        """Record review feedback and prepare a new same-source ingest ChangeSet."""

        revision = revisions.request_revision(
            change_set_id,
            reviewer=reviewer,
            comments=comments,
        )
        effective_run_id = run_id.strip() or current_agent_run_id() or f"revision_{uuid.uuid4().hex}"
        change_set = revisions.prepare_revision(
            revision.revision_id,
            run_id=effective_run_id,
            cancellation_id=current_agent_run_id() or effective_run_id,
        )
        policy = pipeline.approval_policy()
        snapshot_id = getattr(change_set, "snapshot_id", None)
        snapshot = (
            pipeline.get_snapshot(snapshot_id).model_dump(mode="json")
            if snapshot_id
            else None
        )
        return json.dumps(
            {
                "revision": revisions.get(revision.revision_id).model_dump(mode="json"),
                "change_set": change_set.model_dump(mode="json"),
                "snapshot": snapshot,
                "run_id": effective_run_id,
                "approval_policy": policy.value,
                "requires_human_review": policy is not ApprovalPolicy.AUTO_ALL,
            },
            ensure_ascii=False,
        )

    return [prepare_ingest_change_set, request_ingest_revision]


def build_lint_tools(project_root: Path) -> list[BaseTool]:
    """Build read-first Lint tools that share the governed Pipeline Harness."""

    root = Path(project_root).resolve()
    lint = LintFixService(root)
    research = ResearchService(root)
    pipeline = KnowledgePipelineHarness(root)

    def pipeline_busy_payload(run_id: str) -> str:
        """Keep a concurrent Pipeline request visible without failing the Agent run."""

        return json.dumps(
            {
                "status": "pipeline_busy",
                "run_id": run_id,
                "active_task": pipeline.active_task(),
                "message": (
                    "Another CellWiki knowledge pipeline task owns the project lease; "
                    "do not start a second ingest or lint task."
                ),
            },
            ensure_ascii=False,
        )

    @tool("run_broad_lint")
    def run_broad_lint(
        external_query: str = "",
        limit: int = 5,
        run_id: str = "",
    ) -> str:
        """Run local quality lint and optionally refresh external research candidates."""

        effective_run_id = run_id.strip() or current_agent_run_id() or f"lint_{uuid.uuid4().hex}"
        normalized_query = " ".join(external_query.split())
        try:
            with pipeline.acquire(task_type=PipelineTaskType.LINT, run_id=effective_run_id) as lease:
                local_report = lint.inspect()
                snapshot = lease.snapshot.model_dump(mode="json")
                external_refresh = None
                if normalized_query:
                    external_refresh = research.refresh(
                        normalized_query,
                        project_id="cellwiki",
                        limit=max(1, min(limit, 20)),
                        run_id=effective_run_id,
                        lease=lease,
                    ).model_dump(mode="json")
        except PipelineBusyError:
            return pipeline_busy_payload(effective_run_id)

        return json.dumps(
            {
                "mode": "broad",
                "run_id": effective_run_id,
                "snapshot": snapshot,
                "local_quality": local_report,
                "external_refresh": external_refresh,
                "policy": (
                    "external_results_are_candidate_only"
                    if external_refresh is not None
                    else "external_refresh_not_requested"
                ),
            },
            ensure_ascii=False,
        )

    @tool("inspect_knowledge_quality")
    def inspect_knowledge_quality() -> str:
        """Inspect the complete formal Wiki state and return findings with its snapshot."""

        run_id = current_agent_run_id() or "lint_query"
        try:
            with pipeline.acquire(task_type=PipelineTaskType.LINT, run_id=run_id) as lease:
                report = lint.inspect()
                return json.dumps(
                    {
                        "snapshot": lease.snapshot.model_dump(mode="json"),
                        "report": report,
                    },
                    ensure_ascii=False,
                )
        except PipelineBusyError:
            return pipeline_busy_payload(run_id)

    @tool("propose_lint_fix")
    def propose_lint_fix(finding_ids: list[str], run_id: str = "") -> str:
        """Create a reviewable Lint ChangeSet; never apply the repair directly."""

        effective_run_id = run_id.strip() or current_agent_run_id() or f"lint_{uuid.uuid4().hex}"
        change_set = lint.propose(finding_ids, run_id=effective_run_id)
        policy = pipeline.approval_policy()
        snapshot_id = getattr(change_set, "snapshot_id", None)
        snapshot = (
            pipeline.get_snapshot(snapshot_id).model_dump(mode="json")
            if snapshot_id
            else None
        )
        return json.dumps(
            {
                "change_set": change_set.model_dump(mode="json"),
                "snapshot": snapshot,
                "run_id": effective_run_id,
                "approval_policy": policy.value,
                "requires_human_review": policy is not ApprovalPolicy.AUTO_ALL,
            },
            ensure_ascii=False,
        )

    return [run_broad_lint, inspect_knowledge_quality, propose_lint_fix]


# ---------------------------------------------------------------------------
# 构建记忆工具集
# 两个工具：
# 1. recall_project_memory — 召回项目范围的任务结果
# 2. propose_memory_candidate — 提交仅包含结果的记忆候选
# 记忆是受控的：只包含任务结果，不包含科学证据。
# 限制：limit 范围 1-10，token_budget 由配置决定。
# ---------------------------------------------------------------------------
def build_memory_tools(project_root: Path, project_id: str = "cellwiki") -> tuple[BaseTool, BaseTool]:
    """Build bounded recall and candidate-only write tools for governed memory."""

    memory = MemoryStore(Path(project_root).resolve())

    # 召回记忆：查询项目范围的历史任务结果
    @tool("recall_project_memory")
    def recall_project_memory(query: str, limit: int = 6) -> str:
        """Recall project-scoped outcomes; memory is context only and never citation evidence."""

        records, recall = memory.recall(
            project_id,
            query,
            limit=max(1, min(limit, 10)),                      # 限制召回数量
            token_budget=settings.memory_recall_token_budget,   # 限制 token 消耗
        )
        return json.dumps(
            {
                "recall": recall.model_dump(mode="json"),
                "records": [record.model_dump(mode="json") for record in records],
                # 明确声明记忆不是科学证据
                "policy": "memory_is_not_scientific_evidence",
            },
            ensure_ascii=False,
        )

    # 提交记忆候选：用于确定性验证和去重
    @tool("propose_memory_candidate")
    def propose_memory_candidate(
        content: str,
        kind: str = "episode",
        key: str = "",
        confidence: float = 0.7,
        tags: list[str] | None = None,
        expires_in_days: int | None = None,
    ) -> str:
        """Submit an outcome-only MemoryCandidate for deterministic validation and deduplication."""

        memory_kind = MemoryKind(kind)
        # 稳定记忆必须有确定性键，用于去重
        if memory_kind == MemoryKind.STABLE and not key.strip():
            raise ValueError("stable memory candidates require a deterministic key")
        # 计算过期时间，限制范围 1-3650 天
        expires_at = (
            datetime.now(UTC) + timedelta(days=max(1, min(expires_in_days, 3650)))
            if expires_in_days is not None
            else None
        )
        # 构建记忆候选，使用 UUID 生成唯一 ID
        candidate = MemoryCandidate(
            candidate_id=f"candidate_{uuid.uuid4().hex}",
            project_id=project_id,
            kind=memory_kind,
            content=content,
            key=key.strip() or None,
            confidence=confidence,
            tags=(tags or [])[:20],  # 最多 20 个标签
            expires_at=expires_at,
        )
        # 提交到记忆存储进行验证和去重
        record = memory.admit(candidate)
        return record.model_dump_json()

    return recall_project_memory, propose_memory_candidate


# ---------------------------------------------------------------------------
# 构建提交工具
# commit_change_set — 在运行时获得明确用户审批后提交不可变的 ChangeSet。
# 流程：
# 1. 记录"正在提交"状态
# 2. 调用 CentralWriter 执行提交
# 3. 运行投影质量检查
# 4. 记录"已提交"状态
# 如果提交失败，CentralWriter 保证回滚，记录失败状态并重新抛出异常。
# ---------------------------------------------------------------------------
def build_rebase_tool(project_root: Path) -> BaseTool:
    """Return an explicit current/rebased/conflict result for one proposal."""

    changesets = ChangeSetRepository(Path(project_root).resolve())

    @tool("rebase_change_set")
    def rebase_change_set(change_set_id: str) -> str:
        """Rebase a stale ChangeSet or report overlapping targets without mutating the original."""

        result = changesets.rebase(change_set_id)
        payload = result.model_dump(mode="json")
        if result.rebased_change_set_id is not None:
            payload["change_set"] = changesets.get(result.rebased_change_set_id).model_dump(mode="json")
        return json.dumps(payload, ensure_ascii=False)

    return rebase_change_set


def build_commit_tool(project_root: Path) -> BaseTool:
    root = Path(project_root).resolve()
    writer = CentralWriter(root)
    changesets = ChangeSetRepository(root)
    tasks = TaskEventRepository(root)

    @tool("commit_change_set")
    def commit_change_set(change_set_id: str) -> str:
        """Commit an immutable ChangeSet after the runtime has obtained explicit user approval."""
        # 获取 ChangeSet 并提取来源 ID
        change_set = changesets.get(change_set_id)
        source_id = change_set.operations[0].target_id
        # 1. 记录"正在提交"状态
        tasks.record(
            run_id=change_set.run_id,
            source_id=source_id,
            stage=IngestStage.PUBLISH,
            status=TaskStatus.COMMITTING,
            message="Publishing the approved ChangeSet.",
            progress=82,
            change_set_id=change_set_id,
        )
        try:
            # 2. 执行提交
            # The model cannot manufacture an approval. CentralWriter derives
            # policy approval or consumes the persisted desktop decision.
            result = writer.commit(change_set_id, None)
            # 3. 运行投影质量检查
            report = inspect_projection(root)
            tasks.record(
                run_id=change_set.run_id,
                source_id=source_id,
                stage=IngestStage.LINT,
                status=TaskStatus.COMMITTING,
                message="Projection lint completed.",
                progress=96,
                change_set_id=change_set_id,
                detail={
                    "quality_status": report["status"],
                    "issue_count": report["issue_count"],
                },
            )
            # 4. 记录"已提交"状态
            tasks.record(
                run_id=change_set.run_id,
                source_id=source_id,
                stage=IngestStage.PUBLISH,
                status=TaskStatus.COMMITTED,
                message="ChangeSet was published and verified.",
                progress=100,
                change_set_id=change_set_id,
            )
            return result.model_dump_json()
        except Exception as error:
            # 提交失败：CentralWriter 已回滚投影，记录失败状态
            tasks.record(
                run_id=change_set.run_id,
                source_id=source_id,
                stage=IngestStage.PUBLISH,
                status=TaskStatus.FAILED,
                message="Publish failed; CentralWriter rolled back the projection.",
                progress=82,
                change_set_id=change_set_id,
                detail={"error": str(error)},
            )
            raise

    return commit_change_set
