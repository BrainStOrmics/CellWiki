# =============================================================================
# FastAPI 产品 API —— CellWiki 桌面应用的 HTTP 接口层
# =============================================================================
# 提供完整的 REST API 端点，包括：系统管理、项目树浏览、页面查询、
# 全文搜索、来源管理、智能体运行管理、变更集审批、质量检查等。
# 是桌面端前端与后端服务之间的主要通信桥梁。
# =============================================================================

"""FastAPI Product API for the visual CellWiki application."""

from __future__ import annotations

import asyncio
import os
import re
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, File, Header, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from cellwiki.config import settings
from cellwiki.api.reader import WikiReader
from cellwiki.api.errors import create_error_router
from cellwiki.api.runs import create_runs_router
from cellwiki.api.retention import create_retention_router
from cellwiki.api.extensions import create_extension_router, search_discovery
from cellwiki.api.security import DesktopTokenMiddleware
from cellwiki.domain.discovery import SearchDocumentType
from cellwiki.domain.contracts import (
    ApprovalDecision,
    ApprovalPolicy,
    ChangeSet,
    IngestStage,
    TaskStatus,
    WikiAgentContext,
)
from cellwiki.domain.runs import AgentRun, AgentRunStatus, RunBudget
from cellwiki.services.agent_runtime import (
    AgentRuntimeBusyError,
    AgentRuntimeManager,
    is_retryable_run,
)
from cellwiki.services.approvals import ApprovalConflictError, ApprovalRepository
from cellwiki.services.batch_approvals import AdminBatchApprovalService
from cellwiki.services.attachments import AttachmentService
from cellwiki.services.central_writer import CentralWriter, VersionConflictError
from cellwiki.services.changesets import ChangeSetDeleteBlockedError, ChangeSetNotFoundError, ChangeSetRepository
from cellwiki.services.environment import EnvironmentSettingsService
from cellwiki.services.diffing import ChangeSetDiffService
from cellwiki.services.linting import LintFixService
from cellwiki.services.parsing import DocumentParsingService
from cellwiki.services.quality import inspect_projection
from cellwiki.services.sources import SourceDeleteBlockedError, SourceRegistry
from cellwiki.services.tasks import TaskEventRepository
from cellwiki.services.pipeline import KnowledgePipelineHarness
from cellwiki.services.query import FormalQueryService
from cellwiki.services.revisions import (
    IngestRevisionConflictError,
    IngestRevisionNotFoundError,
    IngestRevisionService,
)


# ===========================================================================
# 请求/响应模型 —— 定义所有 API 端点的输入输出格式
# ===========================================================================

# ---- 变更集审批决策请求 ----
class ChangeSetDecisionRequest(BaseModel):
    """Explicit local-desktop decision; the caller cannot supply write operations."""
    approved: bool                           # 是否批准
    reason: str = Field(default="", max_length=1000)  # 审批理由


class ApprovalPolicyRequest(BaseModel):
    """Project-level policy for ChangeSet approval."""

    policy: ApprovalPolicy

# ---- 设置更新请求 ----
class SettingsUpdateRequest(BaseModel):
    """Editable provider settings; a blank key preserves the stored secret."""
    openai_base_url: str = Field(default="", max_length=2000)
    openai_model: str = Field(min_length=1, max_length=300)
    openai_api_protocol: str | None = Field(default=None, max_length=40)
    openai_api_key: str | None = Field(default=None, max_length=4000)  # None表示不修改
    clear_openai_api_key: bool = False        # 是否清除 API 密钥
    log_level: str = Field(default="INFO", max_length=20)
    app_language: str = Field(default="zh-CN", max_length=10)
    enable_agent_memory: bool = False
    enable_external_research: bool = False
    memory_recall_token_budget: int = Field(default=800, ge=128, le=4000)

# ---- 设置测试请求（仅用于连接测试，不持久化）----
class SettingsTestRequest(BaseModel):
    """A transient provider draft used only for a bounded connection test."""
    openai_base_url: str = Field(default="", max_length=2000)
    openai_model: str = Field(min_length=1, max_length=300)
    openai_api_protocol: str | None = Field(default=None, max_length=40)
    openai_api_key: str | None = Field(default=None, max_length=4000)

# ---- Lint 修复请求 ----
class LintFixRequest(BaseModel):
    finding_ids: list[str] = Field(min_length=1, max_length=100)  # 要修复的 finding
    run_id: str = Field(min_length=1, max_length=128)
    max_iterations: int = Field(default=3, ge=1, le=10)          # 最大迭代次数

# ---- 回滚请求 ----
class IngestRevisionRequest(BaseModel):
    """Reviewer feedback that starts a same-source ingest revision."""

    reviewer: str = Field(default="default-reviewer", min_length=1, max_length=200)
    comments: list[str] = Field(min_length=1, max_length=20)


class RollbackRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)            # 回滚原因


# ---- 管理员批量审批 ----
class AdminBatchApprovalRequest(BaseModel):
    """Approve and commit several ChangeSets under one auditable admin batch."""
    change_set_ids: list[str] = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=1000)
    decided_by: str = Field(default="admin-user", max_length=128)
    role: str = Field(default="admin", max_length=64)

# ---- 智能体运行请求 ----
class AgentRunRequest(BaseModel):
    """Natural-language Product API input; routing stays inside the Agent."""

    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=100_000)
    thread_id: str | None = Field(default=None, max_length=128)   # 对话线程 ID
    project_id: str = Field(default="cellwiki", max_length=128)
    source_id: str | None = Field(default=None, max_length=256)
    page_id: str | None = Field(default=None, max_length=256)
    attachment_ids: list[str] = Field(default_factory=list, max_length=50)
    selected_text: str | None = Field(default=None, max_length=4000)  # 用户选中的文本
    budget: RunBudget = Field(default_factory=RunBudget)           # 运行预算

# ---- 智能体恢复请求 ----
class AgentResumeRequest(BaseModel):
    decision: str = Field(pattern="^(approve|reject)$")  # 审批或拒绝


# ===========================================================================
# create_app —— 创建 FastAPI 应用实例
# 组装所有路由、中间件和服务依赖，返回配置好的 FastAPI 应用。
# 支持两种运行模式：开发模式（空 token）和打包模式（Tauri 侧车注入 token）。
# 智能体运行时延迟加载：仅在首次使用智能体端点时创建。
# ===========================================================================
def create_app(
    project_root: Path | None = None,
    *,
    agent_runtime: AgentRuntimeManager | None = None,
    local_token: str | None = None,
    shutdown_callback: Callable[[], None] | None = None,
) -> FastAPI:
    # 解析项目根目录
    root = Path(project_root or settings.project_root).resolve()
    # 初始化所有服务依赖
    reader = WikiReader(root)                    # Wiki 页面读取器
    sources = SourceRegistry(root)               # 来源注册
    attachments = AttachmentService(root, source_registry=sources)
    changesets = ChangeSetRepository(root)       # 变更集仓库
    approvals = ApprovalRepository(root)         # 审批仓库
    writer = CentralWriter(root, repository=changesets)  # 中央写入器
    tasks = TaskEventRepository(root)            # 任务事件
    environment = EnvironmentSettingsService(root)  # 环境设置
    differ = ChangeSetDiffService(root)          # 变更差异对比
    lint_fixes = LintFixService(root)            # Lint 修复
    pipeline = KnowledgePipelineHarness(root)    # 全库快照、互斥和审批策略
    query_service = FormalQueryService(root, reader=reader, pipeline=pipeline, changesets=changesets)
    revisions = IngestRevisionService(root)
    parsing = DocumentParsingService(root)       # 文档解析
    # 智能体运行时（延迟加载）
    runtime = agent_runtime
    runtime_lock = threading.Lock()
    owns_runtime = agent_runtime is None         # 是否拥有运行时（用于关闭）

    # 延迟创建智能体运行时，仅在首次使用智能体端点时加载
    def get_agent_runtime() -> AgentRuntimeManager:
        """Create the model-bearing runtime only when an Agent endpoint is first used."""
        nonlocal runtime
        if runtime is not None:
            return runtime
        with runtime_lock:
            if runtime is None:
                try:
                    runtime = AgentRuntimeManager(root)
                except AgentRuntimeBusyError as error:
                    raise HTTPException(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        detail=str(error),
                    ) from None
        return runtime

    # 创建 FastAPI 应用
    app = FastAPI(title="CellWiki Product API", version="0.1.0")
    # 空 token 表示开发模式，打包桌面构建始终通过侧车环境注入随机 token
    app.add_middleware(
        DesktopTokenMiddleware,
        token=local_token if local_token is not None else os.getenv("CELLWIKI_DESKTOP_TOKEN", ""),
    )
    # CORS 配置：允许前端开发服务器和 Tauri 桌面端访问
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:5173",       # Vite 开发服务器
            "http://localhost:5173",
            "http://127.0.0.1:15173",      # Isolated Playwright workbench
            "http://tauri.localhost",        # Tauri 桌面端
            "tauri://localhost",
        ],
        # Vite and Playwright may select a free local port; keep the dynamic
        # rule restricted to loopback hosts instead of allowing arbitrary origins.
        allow_origin_regex=r"^https?://(?:127\.0\.0\.1|localhost):\d+$",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ==================== 健康检查 ====================
    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    # ==================== 系统管理 ====================
    @app.get("/api/system/info")
    def system_info() -> dict[str, str | bool]:
        """Expose non-secret runtime diagnostics for the desktop recovery view."""
        paths = getattr(app.state, "application_paths", None)
        return {
            "status": "ok",
            "packaged": bool(local_token or os.getenv("CELLWIKI_DESKTOP_TOKEN")),
            "project_root": str(root),
            "logs_dir": str(paths.logs_dir) if paths is not None else str(root / "logs"),
        }

    @app.post("/api/system/shutdown", status_code=status.HTTP_202_ACCEPTED)
    def shutdown() -> dict[str, str]:
        """Request a graceful uvicorn stop after in-flight atomic requests finish."""
        if shutdown_callback is None:
            raise HTTPException(status_code=409, detail="runtime shutdown is managed externally")
        if runtime is not None:
            # 在 uvicorn 开始生命周期拆除前，让模型承载工具先观察到关闭信号
            # 否则阻塞的提供商请求可能会变成孤儿进程
            runtime.request_shutdown()
        shutdown_callback()
        return {"status": "stopping"}

    # ==================== 项目与页面 ====================
    @app.get("/api/projects/{project_id}/tree")
    def project_tree(project_id: str) -> list[dict]:
        if project_id != "cellwiki":
            raise HTTPException(status_code=404, detail="project not found")
        return reader.tree()

    @app.get("/api/pages/{page_id}")
    def page(page_id: str) -> dict:
        try:
            return reader.read_page(page_id)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="page not found") from None

    @app.get("/api/search")
    def search(
        q: str = Query(min_length=1),
        type: list[SearchDocumentType] = Query(default=[]),
        limit: int = Query(default=20, ge=1, le=100),
    ) -> list[dict]:
        return search_discovery(root, q, types=type, limit=limit)

    @app.get("/api/query")
    def formal_query(
        q: str = Query(min_length=1, max_length=4000),
        limit: int = Query(default=20, ge=1, le=100),
    ) -> dict:
        """Return the default formal-only knowledge query contract."""
        return query_service.search(q, limit).model_dump(mode="json")

    # ==================== 来源管理 ====================
    @app.post("/api/sources", status_code=status.HTTP_201_CREATED)
    async def register_source(file: UploadFile = File(...)) -> dict:
        """上传并注册一个新来源文件"""
        filename = Path(file.filename or "upload.bin").name
        upload_dir = root / "data" / "runtime" / "uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            # 先写入临时文件，再注册到 SourceRegistry
            with tempfile.NamedTemporaryFile(
                dir=upload_dir, prefix="upload_", suffix=".tmp", delete=False
            ) as temporary:
                temporary_path = Path(temporary.name)
                while chunk := await file.read(1024 * 1024):
                    temporary.write(chunk)
            record = sources.register(
                temporary_path,
                source_type="paper",
                original_name=filename,
            )
            return record.model_dump(mode="json")
        finally:
            # 清理临时文件
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    @app.get("/api/sources")
    def list_sources() -> list[dict]:
        return [record.model_dump(mode="json") for record in sources.list_sources()]

    @app.get("/api/sources/{source_id}/file")
    def source_file(source_id: str) -> FileResponse:
        """Serve the immutable registered copy so evidence cards can open an exact PDF page."""
        try:
            source = sources.get(source_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="source not found") from None
        path = Path(source.stored_path)
        # 根据文件扩展名选择 MIME 类型
        media_type = {
            ".pdf": "application/pdf",
            ".md": "text/markdown; charset=utf-8",
            ".txt": "text/plain; charset=utf-8",
        }.get(path.suffix.lower(), "application/octet-stream")
        return FileResponse(
            path,
            media_type=media_type,
            filename=source.original_name,
            content_disposition_type="inline",  # 浏览器内联显示
        )

    @app.get("/api/sources/{source_id}/evidence/{block_id}")
    def source_evidence_block(source_id: str, block_id: str) -> dict:
        """Resolve a stable block locator back to parser text for audit and UI fallback."""
        try:
            document = parsing.parse(sources.get(source_id))
            block = document.block(block_id)
        except (KeyError, ValueError):
            raise HTTPException(status_code=404, detail="evidence block not found") from None
        return block.model_dump(mode="json")

    # ==================== Source 删除 ====================
    @app.delete("/api/sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_source(source_id: str) -> Response:
        """Delete a registered source and derived caches after all referencing ChangeSets are gone."""
        try:
            sources.delete(source_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="source not found") from None
        except SourceDeleteBlockedError as error:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "source is in use",
                    "detail": error.detail,
                    "blocking_change_set_ids": error.blocking_change_set_ids,
                    "active_run_ids": error.active_run_ids,
                },
            ) from None
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    # ==================== 设置管理 ====================
    @app.get("/api/settings")
    def get_settings() -> dict:
        """Expose non-secret desktop settings and whether a provider key exists."""
        return environment.public_settings()

    # ==================== 知识 Pipeline 管理 ====================
    @app.get("/api/pipeline/status")
    def pipeline_status() -> dict:
        """Return the whole-project pipeline state without exposing lock paths."""
        policy_state = pipeline.approval_policy_status()
        return {
            "project_id": "cellwiki",
            "knowledge_version": pipeline.current_knowledge_version(),
            "approval_policy": policy_state["policy"],
            "approval_policy_valid": policy_state["valid"],
            "approval_policy_source": policy_state["source"],
            "approval_policy_error": policy_state["error"],
            "default_reviewer": "default-reviewer",
            "active_task": pipeline.active_task(),
        }

    @app.post("/api/pipeline/approval-policy")
    def update_approval_policy(request: ApprovalPolicyRequest) -> dict:
        """Set the project approval policy used by all future ChangeSet writes."""
        policy = pipeline.set_approval_policy(request.policy)
        return {
            "project_id": "cellwiki",
            "approval_policy": policy.value,
            "default_reviewer": "default-reviewer",
        }

    @app.post("/api/settings")
    def update_settings(request: SettingsUpdateRequest) -> dict:
        """Persist provider settings; the Agent graph reloads them on desktop restart."""
        try:
            changed = environment.update(**request.model_dump())
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from None
        return {
            **environment.public_settings(),
            "restart_required": changed,  # 某些变更需要重启才能生效
        }

    @app.post("/api/settings/test")
    def test_settings(request: SettingsTestRequest) -> dict:
        """Test a draft against the provider without writing it to disk."""
        try:
            return environment.test_connection(**request.model_dump())
        except (ValueError, RuntimeError) as error:
            return {"ok": False, "message": str(error)}

    # ==================== 智能体运行管理 ====================
    @app.post("/api/agent/threads", status_code=status.HTTP_201_CREATED)
    def create_agent_thread() -> dict[str, str]:
        """Allocate a durable conversation identity without creating framework state yet."""
        return {"thread_id": f"thread_{uuid.uuid4().hex}"}

    @app.get("/api/agent/threads/{thread_id}/messages")
    def list_agent_thread_messages(thread_id: str) -> list[dict]:
        """Return the complete persisted transcript for one conversation."""
        return get_agent_runtime().store.list_messages(thread_id)

    @app.post("/api/agent/threads/{thread_id}/attachments", status_code=status.HTTP_201_CREATED)
    async def upload_agent_thread_attachments(
        thread_id: str,
        files: list[UploadFile] = File(...),
    ) -> list[dict]:
        """Upload temporary Agent attachments scoped to one conversation thread."""
        upload_dir = root / "data" / "runtime" / "uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)
        records = []
        for upload in files:
            filename = Path(upload.filename or "attachment.bin").name
            temporary_path: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    dir=upload_dir, prefix="agent_attachment_", suffix=".tmp", delete=False
                ) as temporary:
                    temporary_path = Path(temporary.name)
                    while chunk := await upload.read(1024 * 1024):
                        temporary.write(chunk)
                record = attachments.create(
                    thread_id,
                    temporary_path,
                    original_name=filename,
                    media_type=upload.content_type,
                )
                records.append(_attachment_payload(record))
            except KeyError:
                raise HTTPException(status_code=404, detail="agent thread not found") from None
            finally:
                if temporary_path is not None:
                    temporary_path.unlink(missing_ok=True)
        return records

    @app.get("/api/agent/threads/{thread_id}/attachments")
    def list_agent_thread_attachments(thread_id: str) -> list[dict]:
        """Return temporary Agent attachments for one conversation thread."""
        try:
            return [_attachment_payload(record) for record in attachments.list(thread_id)]
        except KeyError:
            raise HTTPException(status_code=404, detail="agent thread not found") from None

    @app.delete("/api/agent/threads/{thread_id}/attachments/{attachment_id}")
    def delete_agent_thread_attachment(thread_id: str, attachment_id: str) -> dict[str, object]:
        """Remove a pending upload; sent message attachments are immutable."""
        if attachment_id in set(get_agent_runtime().store.list_thread_attachment_ids(thread_id)):
            raise HTTPException(
                status_code=409,
                detail="sent agent attachments cannot be deleted from conversation history",
            )
        try:
            deleted = attachments.delete(thread_id, attachment_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="agent attachment not found") from None
        return {
            "thread_id": thread_id,
            "attachment_id": deleted.attachment_id,
            "deleted": True,
        }

    @app.delete("/api/agent/threads/{thread_id}")
    def delete_agent_thread(thread_id: str) -> dict[str, int | str]:
        """Permanently delete a conversation and its LangGraph checkpoint."""
        try:
            deleted_runs = get_agent_runtime().delete_thread(thread_id)
            deleted_attachments = attachments.delete_thread(thread_id)
            return {
                "thread_id": thread_id,
                "deleted_runs": deleted_runs,
                "deleted_attachments": deleted_attachments,
            }
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from None
        except KeyError:
            raise HTTPException(status_code=404, detail="agent thread not found") from None

    @app.post("/api/agent/runs", status_code=status.HTTP_202_ACCEPTED)
    def start_agent_run(request: AgentRunRequest) -> dict:
        """启动一个新的智能体运行"""
        thread_id = request.thread_id or f"thread_{uuid.uuid4().hex}"
        if request.attachment_ids:
            try:
                available_attachment_ids = {
                    record.attachment_id for record in attachments.list(thread_id)
                }
            except KeyError:
                raise HTTPException(status_code=422, detail="invalid agent thread or attachment") from None
            invalid_attachment_ids = [
                attachment_id
                for attachment_id in request.attachment_ids
                if attachment_id not in available_attachment_ids
            ]
            if invalid_attachment_ids:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "attachment_ids do not belong to the requested agent thread: "
                        + ", ".join(invalid_attachment_ids)
                    ),
                )
        context = WikiAgentContext(
            project_id=request.project_id,
            source_id=request.source_id,
            page_id=request.page_id,
            selected_text=request.selected_text,
            thread_id=thread_id,
            attachment_ids=request.attachment_ids,
        )
        try:
            runtime = get_agent_runtime()
            run = runtime.start(
                thread_id=thread_id,
                message=request.message,
                context=context,
                budget=request.budget,
            )
            return _agent_run_payload(run)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from None

    @app.get("/api/agent/runs")
    def list_agent_runs(
        thread_id: str | None = None,
        limit: int = Query(default=50, ge=1, le=500),
    ) -> list[dict]:
        """列出智能体运行记录"""
        runs = get_agent_runtime().store.list_runs(thread_id=thread_id, limit=limit)
        return [_agent_run_payload(run) for run in runs]

    @app.get("/api/agent/runs/{run_id}")
    def get_agent_run(run_id: str) -> dict:
        """获取单个智能体运行详情"""
        try:
            return _agent_run_payload(get_agent_runtime().store.get_run(run_id))
        except KeyError:
            raise HTTPException(status_code=404, detail="agent run not found") from None

    @app.get("/api/agent/runs/{run_id}/events")
    def get_agent_events(
        run_id: str,
        after: int = Query(default=0, ge=0),
    ) -> list[dict]:
        """获取智能体运行的事件流（after 参数用于轮询）"""
        try:
            events = get_agent_runtime().store.list_events(run_id, after=after)
            return [event.model_dump(mode="json") for event in events]
        except KeyError:
            raise HTTPException(status_code=404, detail="agent run not found") from None

    @app.get("/api/agent/runs/{run_id}/stream")
    async def stream_agent_events(
        run_id: str,
        request: Request,
        after: int = Query(default=0, ge=0),
    ) -> StreamingResponse:
        """SSE 流式推送智能体运行事件"""
        manager = get_agent_runtime()
        try:
            manager.store.get_run(run_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="agent run not found") from None

        async def event_stream():
            cursor = after
            last_keepalive = time.monotonic()
            # 终态集合：到达这些状态后关闭 SSE 连接
            terminal = {
                AgentRunStatus.WAITING_CONFIRMATION,
                AgentRunStatus.WAITING_APPROVAL,  # 等待审批是静默的：关闭订阅让 UI 启用审查控件
                AgentRunStatus.SUCCEEDED,
                AgentRunStatus.REJECTED,
                AgentRunStatus.FAILED,
                AgentRunStatus.CANCELLED,
            }
            while True:
                events = manager.store.list_events(run_id, after=cursor)
                for event in events:
                    cursor = event.sequence
                    # 命名 SSE 事件让桌面端更新状态、消息、工具和审查
                    # 而无需检查框架私有的流对象
                    yield (
                        f"id: {event.sequence}\n"
                        f"event: {event.type.value}\n"
                        f"data: {event.model_dump_json()}\n\n"
                    )
                run = manager.store.get_run(run_id)
                if run.status in terminal and not events:
                    break
                if await request.is_disconnected():
                    break
                # 每 10 秒发送心跳保持连接
                if time.monotonic() - last_keepalive >= 10:
                    yield ": keep-alive\n\n"
                    last_keepalive = time.monotonic()
                await asyncio.sleep(0.2)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/agent/runs/{run_id}/resume", status_code=status.HTTP_202_ACCEPTED)
    def resume_agent_run(run_id: str, request: AgentResumeRequest) -> dict:
        """恢复等待审批的智能体运行（批准或拒绝）"""
        try:
            return _agent_run_payload(
                get_agent_runtime().resume(run_id, decision=request.decision)
            )
        except KeyError:
            raise HTTPException(status_code=404, detail="agent run not found") from None
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from None

    @app.get("/api/agent/runs/{run_id}/diagnostics")
    def get_agent_diagnostics(run_id: str) -> dict:
        """Return redacted run telemetry without prompts, reasoning, or credentials."""

        try:
            runtime = get_agent_runtime()
            run = runtime.store.get_run(run_id)
            spans = runtime.store.list_spans(run_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="agent run not found") from None
        return {
            "run_id": run.run_id,
            "thread_id": run.thread_id,
            "status": run.status.value,
            "task_kind": run.task_kind,
            "model": run.model_name,
            "model_role": run.model_role,
            "error_type": run.error_type.value if run.error_type else None,
            "error_message": _redact_diagnostic_error(run.error_message),
            "usage": run.usage.model_dump(mode="json"),
            "spans": [span.model_dump(mode="json") for span in spans],
        }
    @app.post("/api/agent/runs/{run_id}/cancel", status_code=status.HTTP_202_ACCEPTED)
    def cancel_agent_run(run_id: str) -> dict:
        """取消正在运行的智能体"""
        try:
            return _agent_run_payload(get_agent_runtime().cancel(run_id))
        except KeyError:
            raise HTTPException(status_code=404, detail="agent run not found") from None
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from None

    @app.post("/api/agent/runs/{run_id}/retry", status_code=status.HTTP_202_ACCEPTED)
    def retry_agent_run(run_id: str) -> dict:
        """重试失败的智能体运行"""
        try:
            return _agent_run_payload(get_agent_runtime().retry(run_id))
        except KeyError:
            raise HTTPException(status_code=404, detail="agent run not found") from None
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from None

    # ==================== 变更集管理 ====================
    @app.get("/api/changesets")
    def list_change_sets(source_id: str | None = None) -> list[dict]:
        """Return review-ready proposals, newest first, without exposing local paths."""
        return [
            _review_payload(change_set, approvals, writer, differ)
            for change_set in changesets.list(target_id=source_id)
        ]

    @app.get("/api/changesets/{change_set_id}")
    def get_change_set(change_set_id: str) -> dict:
        try:
            return changesets.get(change_set_id).model_dump(mode="json")
        except ChangeSetNotFoundError:
            raise HTTPException(status_code=404, detail="change set not found") from None

    @app.get("/api/changesets/{change_set_id}/review")
    def review_change_set(change_set_id: str) -> dict:
        """获取 ChangeSet 的完整审查视图（含差异预览）"""
        try:
            return _review_payload(changesets.get(change_set_id), approvals, writer, differ)
        except ChangeSetNotFoundError:
            raise HTTPException(status_code=404, detail="change set not found") from None

    @app.post("/api/changesets/{change_set_id}/rebase")
    def rebase_change_set(change_set_id: str) -> dict:
        """Check a stale proposal and return a new proposal or explicit conflicts."""
        try:
            result = changesets.rebase(change_set_id)
            payload = result.model_dump(mode="json")
            if result.rebased_change_set_id is not None:
                payload["change_set"] = changesets.get(result.rebased_change_set_id).model_dump(mode="json")
            return payload
        except ChangeSetNotFoundError:
            raise HTTPException(status_code=404, detail="change set not found") from None
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from None

    @app.get("/api/tasks")
    def list_tasks(source_id: str | None = None) -> list[dict]:
        """Return persisted ingest-run summaries for desktop history views."""
        return tasks.list_runs(source_id=source_id)

    @app.get("/api/tasks/{run_id}")
    def task_timeline(run_id: str) -> dict:
        """Return an append-only timeline; an unstarted valid run has no events yet."""
        try:
            events = tasks.list_events(run_id)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from None
        return {
            "run_id": run_id,
            "events": [event.model_dump(mode="json") for event in events],
        }

    @app.post("/api/changesets/{change_set_id}/revision", status_code=status.HTTP_201_CREATED)
    def request_ingest_revision(
        change_set_id: str,
        request: IngestRevisionRequest,
    ) -> dict:
        """Persist review comments for a new same-source ingest proposal."""

        try:
            revision = revisions.request_revision(
                change_set_id,
                reviewer=request.reviewer,
                comments=request.comments,
            )
            return {
                "revision": revision.model_dump(mode="json"),
                "parent_change_set_id": change_set_id,
                "next_action": "prepare_ingest_revision",
            }
        except ChangeSetNotFoundError:
            raise HTTPException(status_code=404, detail="change set not found") from None
        except (IngestRevisionConflictError, IngestRevisionNotFoundError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from None
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from None

    @app.post("/api/changesets/{change_set_id}/decision")
    def decide_change_set(change_set_id: str, request: ChangeSetDecisionRequest) -> dict:
        """Record human intent and commit only an already persisted immutable ChangeSet."""
        try:
            change_set = changesets.get(change_set_id)
            source_id = change_set.operations[0].target_id
            # ``auto_all`` is the default for unattended commits. An explicit
            # decision from the review surface is stronger than that default,
            # so the user can still reject or approve a visible proposal.
            requested_decision = ApprovalDecision(
                approved=request.approved,
                decided_by="desktop-user",
                reason=request.reason,
            )
            decision = approvals.save(change_set_id, requested_decision)
            if decision.approved:
                # 审批通过：记录提交开始 → 执行提交 → 质量检查 → 标记完成
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
                    writer.commit(change_set_id, approval=decision)
                except Exception as error:
                    # CentralWriter 在此错误可见之前保证回滚
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
                # 提交后运行质量检查
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
                tasks.record(
                    run_id=change_set.run_id,
                    source_id=source_id,
                    stage=IngestStage.PUBLISH,
                    status=TaskStatus.COMMITTED,
                    message="ChangeSet was published and verified.",
                    progress=100,
                    change_set_id=change_set_id,
                )
            else:
                # 审批拒绝
                tasks.record(
                    run_id=change_set.run_id,
                    source_id=source_id,
                    stage=IngestStage.HUMAN_REVIEW,
                    status=TaskStatus.REJECTED,
                    message="ChangeSet was rejected; formal Wiki data was not changed.",
                    progress=100,
                    change_set_id=change_set_id,
                )
            return _review_payload(change_set, approvals, writer, differ)
        except ChangeSetNotFoundError:
            raise HTTPException(status_code=404, detail="change set not found") from None
        except (ApprovalConflictError, VersionConflictError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from None
        except (ValueError, RuntimeError) as error:
            # CentralWriter 在此错误到达边界之前已回滚
            raise HTTPException(status_code=422, detail=str(error)) from None

    # ==================== 管理员批量审批 ====================
    @app.post("/api/admin/approvals/batch")
    def batch_approve_change_sets(request: AdminBatchApprovalRequest) -> dict:
        """Approve and commit multiple ChangeSets in one auditable admin batch."""
        try:
            return AdminBatchApprovalService(root).approve_batch(
                request.change_set_ids,
                decided_by=request.decided_by,
                reason=request.reason,
                role=request.role,
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from None

    # ==================== 质量检查 ====================
    @app.get("/api/quality")
    def quality_report() -> dict:
        return inspect_projection(root)

    @app.post("/api/internal/quality/fixes", status_code=status.HTTP_201_CREATED)
    def propose_quality_fixes(
        request: LintFixRequest,
        internal_compatibility: str | None = Header(default=None, alias="X-CellWiki-Internal"),
    ) -> dict:
        """Create a low-risk ChangeSet for deterministic findings; never apply it here."""
        if internal_compatibility != "1":
            raise HTTPException(status_code=404, detail="internal compatibility route")
        try:
            change_set = lint_fixes.propose(
                request.finding_ids,
                run_id=request.run_id,
                max_iterations=request.max_iterations,
            )
            if pipeline.approval_for(
                change_set.change_set_id,
                reviewer="default-reviewer",
            ).approved:
                source_id = change_set.operations[0].target_id
                tasks.record(
                    run_id=change_set.run_id,
                    source_id=source_id,
                    stage=IngestStage.PUBLISH,
                    status=TaskStatus.COMMITTING,
                    message="Publishing the auto-approved Lint ChangeSet.",
                    progress=82,
                    change_set_id=change_set.change_set_id,
                )
                writer.commit(change_set.change_set_id, approval=None)
                report = inspect_projection(root)
                tasks.record(
                    run_id=change_set.run_id,
                    source_id=source_id,
                    stage=IngestStage.LINT,
                    status=TaskStatus.COMMITTING,
                    message="Projection lint completed.",
                    progress=96,
                    change_set_id=change_set.change_set_id,
                    detail={"quality_status": report["status"], "issue_count": report["issue_count"]},
                )
                tasks.record(
                    run_id=change_set.run_id,
                    source_id=source_id,
                    stage=IngestStage.PUBLISH,
                    status=TaskStatus.COMMITTED,
                    message="Auto-approved Lint ChangeSet was published and verified.",
                    progress=100,
                    change_set_id=change_set.change_set_id,
                )
            return _review_payload(change_set, approvals, writer, differ)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from None
        except (ValueError, RuntimeError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from None

    # ==================== 回滚 ====================
    @app.post("/api/changesets/{change_set_id}/rollback")
    def rollback_change_set(change_set_id: str, request: RollbackRequest) -> dict:
        """Restore the committed snapshot while keeping the original audit records immutable."""
        try:
            writer.rollback(
                change_set_id,
                decided_by="desktop-user",
                reason=request.reason,
            )
            return _review_payload(changesets.get(change_set_id), approvals, writer, differ)
        except (KeyError, ChangeSetNotFoundError) as error:
            raise HTTPException(status_code=404, detail=str(error)) from None
        except (ValueError, RuntimeError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from None

    # ==================== ChangeSet 删除 ====================
    @app.delete("/api/changesets/{change_set_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_change_set(change_set_id: str) -> Response:
        """Delete a terminal proposal and its audit artifacts; committed ChangeSets must be rolled back first."""
        try:
            changesets.delete(change_set_id)
        except ChangeSetNotFoundError:
            raise HTTPException(status_code=404, detail="change set not found") from None
        except ChangeSetDeleteBlockedError as error:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "change set is in use",
                    "blocking": error.blocking,
                    "detail": error.detail,
                    "run_ids": error.run_ids,
                },
            ) from None
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    # 关闭时清理智能体运行时
    def close_agent_runtime() -> None:
        # 注入的运行时属于测试/应用所有，只关闭延迟加载的默认运行时
        if owns_runtime and runtime is not None:
            runtime.close()

    app.router.add_event_handler("shutdown", close_agent_runtime)

    # 功能路由保持独立，不扩展主应用组装
    # Register error reporting router
    app.include_router(create_error_router(root))
    
    # Register unified runs query router
    app.include_router(create_runs_router(root))
    
    # Register retention management router
    app.include_router(create_retention_router(root))
    
    app.include_router(create_extension_router(root))
    return app


# ===========================================================================
# 辅助函数
# ===========================================================================

# 构建审查负载：从不可变的 ChangeSet 构建紧凑的人工审查模型
def _review_payload(
    change_set: ChangeSet,
    approvals: ApprovalRepository,
    writer: CentralWriter,
    differ: ChangeSetDiffService,
) -> dict:
    """Build a compact human review model from the immutable domain proposal."""
    decision = approvals.get(change_set.change_set_id)
    commit = writer.get_commit(change_set.change_set_id)
    rollback = writer.get_rollback(change_set.change_set_id)
    # 确定审查状态（优先级：回滚 > 已提交 > 已拒绝 > 已批准 > 待审查）
    if rollback is not None:
        review_status = "rolled_back"
    elif commit is not None:
        review_status = "committed"
    elif decision is not None and not decision.approved:
        review_status = "rejected"
    elif decision is not None:
        review_status = "approved"
    else:
        review_status = "awaiting_review"

    return {
        "change_set": change_set.model_dump(mode="json"),
        "status": review_status,
        "decision": decision.model_dump(mode="json") if decision is not None else None,
        "commit": commit.model_dump(mode="json") if commit is not None else None,
        "rollback": rollback.model_dump(mode="json") if rollback is not None else None,
        "preview": differ.preview(change_set),  # 差异预览
    }


# 构建智能体运行负载：移除内部字段，添加 UI 辅助标记
def _agent_run_payload(run: AgentRun) -> dict:
    payload = run.model_dump(mode="json")
    # 用户提示在队列运行恢复时保持持久化，但不是桌面控制面的 DTO 的一部分
    payload.pop("input_message", None)
    payload["error_message"] = _redact_diagnostic_error(run.error_message)
    # 添加 UI 辅助标记
    payload["retryable"] = is_retryable_run(run)    # 是否可重试
    payload["cancellable"] = run.status in {        # 是否可取消
        AgentRunStatus.QUEUED,
        AgentRunStatus.RUNNING,
        AgentRunStatus.WAITING_CONFIRMATION,
        AgentRunStatus.WAITING_APPROVAL,
    }
    return payload


def _attachment_payload(record) -> dict:
    payload = record.model_dump(mode="json")
    payload.pop("stored_path", None)
    payload.pop("text_path", None)
    return payload


def _redact_diagnostic_error(message: str | None) -> str | None:
    if message is None:
        return None
    redacted = re.sub(r"(?i)bearer\s+[^\s,;]+", "Bearer [REDACTED]", message)
    if settings.openai_api_key:
        redacted = redacted.replace(settings.openai_api_key, "[REDACTED]")
    return redacted[:1000]


# 默认导出
app = create_app()
