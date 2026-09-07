# =============================================================================
# FastAPI 产品 API —— CellWiki 桌面应用的 HTTP 接口层（工作区版）
# =============================================================================
# 提供工作区版产品 API：系统管理、设置、项目树浏览、Markdown 页面读取、
# 智能体线程与运行管理、事件流。旧治理端点（来源、变更集、审批、任务、
# 搜索/查询、扩展）已随阶段 1 的删除清单移除；阶段 2 会加入工作区
# 目录浏览 API 与待确认 diff 审批端点。
# =============================================================================

"""FastAPI Product API for the workspace-based CellWiki application."""

from __future__ import annotations

import asyncio
import json
import os
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Callable

from fastapi import (
    FastAPI,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from cellwiki.config import settings
from cellwiki.api.reader import WikiReader
from cellwiki.api.errors import create_error_router
from cellwiki.api.retention import create_retention_router
from cellwiki.api.security import DesktopTokenMiddleware
from cellwiki.domain.contracts import WikiAgentContext
from cellwiki.domain.runs import (
    AgentEvent,
    AgentEventType,
    AgentRun,
    AgentRunStatus,
    RunBudget,
)
from cellwiki.services.attachment_store import (
    AttachmentFileStore,
    MAX_ATTACHMENTS_PER_UPLOAD,
)
from cellwiki.services.agent_runtime import (
    AgentRuntimeBusyError,
    AgentRuntimeManager,
    InvalidRunTransitionError,
    AgentRunInProgressError,
    is_retryable_run,
)
from cellwiki.services.checkpoints import CheckpointMissingError, checkpoint_file_bytes
from cellwiki.services.environment import EnvironmentSettingsService
from cellwiki.services.path_guard import PathGuardError, validate_workspace_path
from cellwiki.services.runtime_store import RuntimeStore, ThreadDeletionBlockedError


# 决策 4（2026-09-07 修订）：checkpoint 缺失是**永久性**拒绝——载体里没有该 run 的
# 图状态，「继续」不可能成功，正确的出路是 retry（清状态 + 从有界 transcript 重放）。
# 而同一个端点的门禁冲突 409 是**可重试**拒绝。两者 HTTP 状态相同、消息都是英文，
# 前端只能靠这个稳定码区分：否则要么把死结的「继续」按钮还回来，要么在门禁冲突时
# 误摘按钮。码是契约，消息文案不是。
CHECKPOINT_MISSING_CODE = "checkpoint_missing"


# ===========================================================================
# 请求/响应模型 —— 定义所有 API 端点的输入输出格式
# ===========================================================================

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


# ---- 设置测试请求（仅用于连接测试，不持久化）----
class SettingsTestRequest(BaseModel):
    """A transient provider draft used only for a bounded connection test."""

    openai_base_url: str = Field(default="", max_length=2000)
    openai_model: str = Field(min_length=1, max_length=300)
    openai_api_protocol: str | None = Field(default=None, max_length=40)
    openai_api_key: str | None = Field(default=None, max_length=4000)


# ---- 智能体运行请求 ----
class AnswerQuestionRequest(BaseModel):
    """ask_user_question 5+1 回复：string | array + 超时标记。"""

    answers: str | list[str] | None = None
    timed_out: bool = False


class WorkspaceEditRequest(BaseModel):
    """APP 受控编辑：md/txt 内容保存（走合成 run + pending diff 审批）。"""
    path: str = Field(min_length=1, max_length=4096)
    content: str = Field(max_length=400_000)

class WorkspaceSelectRequest(BaseModel):
    """请求切换工作区根目录（写入 PROJECT_ROOT，重启后生效）。"""

    path: str = Field(min_length=1, max_length=4096)


class AgentRunRequest(BaseModel):
    """Natural-language Product API input; routing stays inside the Agent."""

    message: str = Field(min_length=1, max_length=100_000)
    thread_id: str | None = Field(default=None, max_length=128)   # 对话线程 ID
    project_id: str = Field(default="cellwiki", max_length=128)
    source_id: str | None = Field(default=None, max_length=256)
    page_id: str | None = Field(default=None, max_length=256)
    selected_text: str | None = Field(default=None, max_length=4000)  # 用户选中的文本
    attachment_ids: list[str] = Field(default_factory=list)       # 线程附件（临时 Agent 上下文）
    # ADR-0010 决策 7：幂等提交键。重试同一次提交（网络抖动/重复点击）带上同一个
    # request_id，服务端命中既有 run 并原样返回；省略则每次提交都新建 run。
    request_id: str | None = Field(default=None, max_length=128)
    # 省略即 None -> 运行时回退 settings（AGENT_MAX_TOOL_STEPS / AGENT_RUN_MAX_SECONDS）。
    # 曾写成 default_factory=RunBudget，把 100/7200 硬编码进 API 边界，配置覆盖成为死路径。
    budget: RunBudget | None = None                               # 运行预算


# ===========================================================================
# create_app —— 创建 FastAPI 应用实例
# 组装所有路由、中间件和服务依赖，返回配置好的 FastAPI 应用。
# 智能体运行时延迟加载：仅在首次使用智能体端点时创建。
# ===========================================================================
def create_app(
    project_root: Path | None = None,
    *,
    env_root: Path | None = None,
    agent_runtime: AgentRuntimeManager | None = None,
    local_token: str | None = None,
    shutdown_callback: Callable[[], None] | None = None,
) -> FastAPI:
    # 解析项目根目录
    root = Path(project_root or settings.workspace_root).resolve()
    # 初始化服务依赖
    reader = WikiReader(root)                    # Wiki Markdown 页面读取器
    # .env 定位：显式传入 project_root（测试/嵌入方）时跟随该根，生产默认固定应用根
    resolved_env_root = Path(env_root or (project_root if project_root is not None else settings.project_root)).resolve()
    environment = EnvironmentSettingsService(resolved_env_root)
    # 智能体运行时（延迟加载）
    runtime = agent_runtime
    runtime_lock = threading.Lock()
    owns_runtime = agent_runtime is None         # 是否拥有运行时（用于关闭）
    attachment_files = AttachmentFileStore(root)  # 线程附件文件存储

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
        allow_origin_regex=r"^https?://(?:127\.0\.0\.1|localhost):\d+$",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ==================== 健康检查 ====================
    @app.get("/health")
    def health_legacy() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    # ==================== 系统管理 ====================
    @app.get("/api/system/info")
    def system_info() -> dict[str, str | bool]:
        """Expose non-secret runtime diagnostics for the desktop recovery view."""
        paths = getattr(app.state, "application_paths", None)
        logs_dir = (
            str(paths.logs_dir)
            if paths is not None and getattr(paths, "logs_dir", None)
            else str(root / "logs")
        )
        return {
            "status": "ok",
            "packaged": bool(local_token or os.getenv("CELLWIKI_DESKTOP_TOKEN")),
            "project_root": str(root),
            "logs_dir": logs_dir,
        }

    @app.post("/api/system/shutdown", status_code=status.HTTP_202_ACCEPTED)
    def shutdown() -> dict[str, str]:
        """Request a graceful uvicorn stop after in-flight atomic requests finish."""
        if shutdown_callback is None:
            raise HTTPException(status_code=409, detail="runtime shutdown is managed externally")
        if runtime is not None:
            runtime.close()
        shutdown_callback()
        return {"status": "stopping"}

    # ==================== 设置管理 ====================
    @app.get("/api/settings")
    def get_settings() -> dict:
        """Expose non-secret desktop settings and whether a provider key exists."""
        return environment.public_settings()

    @app.post("/api/settings")
    def update_settings(request: SettingsUpdateRequest) -> dict:
        """Persist provider settings; the Agent graph reloads them on desktop restart."""
        try:
            changed = environment.update(**request.model_dump())
        except AgentRuntimeBusyError as error:
            raise HTTPException(status_code=409, detail=str(error)) from None
        except AgentRuntimeBusyError as error:
            raise HTTPException(status_code=409, detail=str(error)) from None
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
    # ==================== 项目与页面（工作区浏览）====================
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
        q: str = Query(default="", min_length=0, max_length=200),
        limit: int = Query(default=40, ge=1, le=100),
    ) -> list[dict]:
        """Bounded full-text search over workspace wiki pages (no index, gitignored)."""
        title_by_page = {item["page_id"]: item["title"] for item in reader.tree()}
        results = []
        for hit in reader.search(q, limit=limit):
            page_id = str(hit["page_id"])
            results.append(
                {
                    "document_id": page_id,
                    "type": "page",
                    "title": title_by_page.get(page_id, page_id),
                    "snippet": str(hit["snippet"]),
                    "score": int(hit["score"]),
                    "page_id": page_id,
                    "source_id": None,
                    "locator": None,
                }
            )
        return results

    # ==================== 工作区管理 ====================
    @app.get("/api/workspace")
    def get_workspace() -> dict:
        """返回当前工作区根目录与初始化状态。"""
        return {
            "path": str(root),
            "git_ready": (root / ".git").exists(),
            "wiki_page_count": len(reader.tree()),
        }

    @app.post("/api/workspace/select")
    def select_workspace(request: WorkspaceSelectRequest) -> dict:
        """校验并持久化一个新的工作区根目录（重启后生效）。"""
        from cellwiki.services.workspace import ensure_workspace, WorkspaceNotInitializedError

        raw = request.path.strip()
        if not raw or "\x00" in raw:
            raise HTTPException(
                status_code=422,
                detail="workspace path is required and must not contain NUL bytes",
            )
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            raise HTTPException(status_code=422, detail="workspace path must be absolute")
        try:
            resolved = candidate.resolve()
        except OSError as error:
            raise HTTPException(status_code=422, detail=f"cannot resolve workspace path: {error}") from None
        if resolved == root:
            return {"path": str(root), "status": "unchanged", "requires_restart": False}
        try:
            ensure_workspace(resolved)
        except (WorkspaceNotInitializedError, OSError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from None
        environment.set_workspace_path(str(resolved))
        return {"path": str(resolved), "status": "saved", "requires_restart": True}

    # ---- 工作区文件浏览器（Obsidian 式文件树 / 只读 / 受控编辑）----
    _workflow_tree_excludes = frozenset({".git", "data", "node_modules", ".venv", "build"})
    _viewable_suffixes = frozenset({".md", ".txt", ".pdf", ".json", ".mmd", ".dot", ".yml", ".yaml"})

    def _resolve_workspace_file(path: str) -> Path:
        """Validate a readable workspace file; raise HTTPException on violation."""
        try:
            target = validate_workspace_path(root, path)
        except PathGuardError as error:
            raise HTTPException(status_code=422, detail=str(error)) from None
        if not target.is_file():
            raise HTTPException(status_code=404, detail="file not found")
        if ".git" in target.parts or "data" in target.parts:
            raise HTTPException(status_code=403, detail="runtime and git files are not readable")
        if target.name.endswith(".staging") or target.name.startswith("."):
            raise HTTPException(status_code=403, detail="hidden or staging files are not readable")
        if target.suffix.lower() not in _viewable_suffixes:
            raise HTTPException(status_code=422, detail="unsupported file type")
        return target

    @app.get("/api/workspace/tree")
    def workspace_tree() -> list[dict]:
        """Return a flat workspace file tree (wiki/, raw/, root md, schema.md)."""
        entries: list[dict] = []
        include_dirs = {"wiki", "raw"}
        for candidate in sorted(root.iterdir(), key=lambda item: item.name.lower()):
            if candidate.name in _workflow_tree_excludes or candidate.name.startswith("."):
                continue
            if candidate.is_dir():
                if candidate.name not in include_dirs:
                    continue
                entries.append(
                    {"name": candidate.name, "path": candidate.name, "kind": "dir", "type": "dir", "size": None}
                )
                for child in sorted(candidate.rglob("*"), key=lambda item: (not item.is_dir(), item.name.lower())):
                    if ".git" in child.parts or child.name.endswith(".staging"):
                        continue
                    rel = child.relative_to(root).as_posix()
                    if child.is_dir():
                        entries.append({"name": child.name, "path": rel, "kind": "dir", "type": "dir", "size": None})
                    else:
                        suffix = child.suffix.lower().lstrip(".")
                        ftype = suffix if suffix in {"md", "txt", "pdf"} else "binary"
                        entries.append(
                            {"name": child.name, "path": rel, "kind": "file", "type": ftype, "size": child.stat().st_size}
                        )
            elif candidate.is_file() and candidate.suffix.lower() in {".md"}:
                entries.append(
                    {"name": candidate.name, "path": candidate.name, "kind": "file", "type": "md", "size": candidate.stat().st_size}
                )
        return entries

    @app.get("/api/workspace/file")
    def workspace_file(path: str = Query(min_length=1, max_length=4096)) -> Response:
        """Serve one workspace file read-only (PDF binary for inline preview)."""
        target = _resolve_workspace_file(path)
        data = target.read_bytes()
        suffix = target.suffix.lower()
        if suffix == ".pdf":
            return Response(content=data, media_type="application/pdf")
        if suffix in {".md", ".txt", ".json", ".mmd", ".dot", ".yml", ".yaml"}:
            return Response(content=data.decode("utf-8", errors="replace"), media_type="text/plain; charset=utf-8")
        return Response(content=data, media_type="application/octet-stream")

    @app.post("/api/workspace/edit")
    def workspace_edit(request: WorkspaceEditRequest) -> dict:
        """Stage a controlled md/txt edit: synthetic run + git commit + pending diff."""
        try:
            run = get_agent_runtime().propose_workspace_edit(request.path, request.content)
            return {"run_id": run.run_id, "status": run.status.value, "pending_diff_id": run.pending_diff_id}
        except AgentRunInProgressError as error:
            raise HTTPException(status_code=409, detail=str(error)) from None
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from None

    @app.post("/api/workspace/raw/scan")
    def scan_raw_sources_endpoint() -> dict:
        """登记用户直接放进 raw/ 的预置源（产品侧动作，不产生 git 变更）。

        返回新增/更新/跳过/待提取四类计数；幂等，可安全重复调用。
        """
        from cellwiki.services.promotion import scan_raw_sources

        try:
            return scan_raw_sources(root)
        except OSError as error:
            raise HTTPException(status_code=500, detail=f"raw scan failed: {error}") from None

    # ==================== 智能体线程管理 ====================
    @app.post("/api/agent/threads", status_code=status.HTTP_201_CREATED)
    def create_agent_thread() -> dict[str, str]:
        """Allocate a durable conversation identity without creating framework state yet."""
        thread_id = f"thread_{uuid.uuid4().hex}"
        get_agent_runtime().store.create_thread(thread_id)
        return {"thread_id": thread_id}

    @app.get("/api/agent/threads")
    def list_agent_threads(limit: int = Query(default=50, ge=1, le=500)) -> list[dict]:
        """列出会话登记条目（含尚未产生 run 的新会话），按最近活动排序。"""
        return get_agent_runtime().store.list_threads(limit=limit)

    @app.post("/api/agent/threads/{thread_id}/attachments", status_code=status.HTTP_201_CREATED)
    def upload_thread_attachments(thread_id: str, files: list[UploadFile] = File(...)) -> list[dict]:
        """将上传文件作为该线程的临时 Agent 上下文保存（不登记 Source、不 ingest）。"""
        if not files:
            raise HTTPException(status_code=422, detail="no files provided")
        if len(files) > MAX_ATTACHMENTS_PER_UPLOAD:
            raise HTTPException(
                status_code=422,
                detail=f"at most {MAX_ATTACHMENTS_PER_UPLOAD} files per upload",
            )
        store = get_agent_runtime().store
        if not store.thread_exists(thread_id):
            raise HTTPException(status_code=404, detail="thread not found")
        records = []
        for uploaded in files:
            try:
                attachment = attachment_files.store_upload(
                    thread_id,
                    original_name=uploaded.filename or "file",
                    media_type=uploaded.content_type or "application/octet-stream",
                    stream=uploaded.file,
                )
            except ValueError as error:
                raise HTTPException(status_code=422, detail=str(error)) from None
            store.save_attachment(attachment)
            records.append(attachment.to_payload())
        return records

    @app.get("/api/agent/threads/{thread_id}/attachments")
    def list_thread_attachments(thread_id: str) -> list[dict]:
        """Return the temporary attachments owned by one thread (newest first)."""
        return get_agent_runtime().store.list_attachments(thread_id)

    @app.delete("/api/agent/threads/{thread_id}/attachments/{attachment_id}")
    def delete_thread_attachment(thread_id: str, attachment_id: str) -> dict[str, bool]:
        """Remove one composer attachment before it is sent with a message.

        已随某个 run 发出的附件不可撤回：409 让前端区分"已发送"与通用失败，
        而不是把 run 记录里的引用变成悬空 ID。
        """
        store = get_agent_runtime().store
        if not store.thread_exists(thread_id):
            raise HTTPException(status_code=404, detail="thread not found")
        if store.get_attachment(thread_id, attachment_id) is None:
            raise HTTPException(status_code=404, detail="attachment not found")
        if store.attachment_was_sent(thread_id, attachment_id):
            raise HTTPException(
                status_code=409,
                detail=f"attachment {attachment_id} was already sent with a message",
            )
        store.delete_attachment(thread_id, attachment_id)
        attachment_files.delete_attachment(thread_id, attachment_id)
        return {"deleted": True}

    @app.get("/api/agent/threads/{thread_id}/messages")
    def list_agent_thread_messages(thread_id: str) -> list[dict]:
        """Return the complete persisted transcript for one conversation."""
        return get_agent_runtime().store.list_messages(thread_id)

    @app.delete("/api/agent/threads/{thread_id}")
    def delete_agent_thread(thread_id: str) -> dict[str, int | str]:
        """Permanently delete a conversation and its LangGraph checkpoint."""
        try:
            deleted_runs = get_agent_runtime().delete_thread(thread_id)
            attachment_files.delete_thread(thread_id)
            return {
                "thread_id": thread_id,
                "deleted_runs": deleted_runs,
            }
        except ThreadDeletionBlockedError as error:
            raise HTTPException(status_code=409, detail=str(error)) from None
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from None

    # ==================== 智能体运行管理 ====================
    @app.post("/api/agent/runs", status_code=status.HTTP_202_ACCEPTED)
    def start_agent_run(request: AgentRunRequest) -> dict:
        """启动一个新的智能体运行"""
        thread_id = request.thread_id or f"thread_{uuid.uuid4().hex}"
        get_agent_runtime().store.create_thread(thread_id)
        context = WikiAgentContext(
            project_id=request.project_id,
            source_id=request.source_id,
            page_id=request.page_id,
            selected_text=request.selected_text,
            thread_id=thread_id,
        )
        try:
            runtime = get_agent_runtime()
            owned = {record["attachment_id"] for record in runtime.store.list_attachments(thread_id)}
            unknown = [aid for aid in request.attachment_ids if aid not in owned]
            if unknown:
                raise ValueError(f"attachment(s) do not belong to thread {thread_id}: {unknown[:5]}")
            run, replayed = runtime.start_idempotent(
                thread_id=thread_id,
                message=request.message,
                context=context,
                budget=request.budget,
                attachment_ids=request.attachment_ids,
                request_id=request.request_id,
            )
            payload = _agent_run_payload(run, store=runtime.store)
            if replayed:
                # 决策 7：幂等命中不排队第二个 run，仍是 202，只多一个可辨识标记。
                payload["replayed"] = True
            return payload
        except AgentRuntimeBusyError as error:
            raise HTTPException(status_code=409, detail=str(error)) from None
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from None

    @app.get("/api/agent/runs")
    def list_agent_runs(
        thread_id: str | None = None,
        limit: int = Query(default=50, ge=1, le=500),
    ) -> list[dict]:
        """列出智能体运行记录"""
        runs = get_agent_runtime().store.list_runs(thread_id=thread_id, limit=limit)
        return [
            _agent_run_payload(run, store=get_agent_runtime().store) for run in runs
        ]

    @app.get("/api/agent/runs/{run_id}")
    def get_agent_run(run_id: str) -> dict:
        """获取单个智能体运行详情"""
        try:
            _runtime = get_agent_runtime()
            return _agent_run_payload(
                _runtime.store.get_run(run_id), store=_runtime.store
            )
        except KeyError:
            raise HTTPException(status_code=404, detail="agent run not found") from None

    @app.get("/api/agent/runs/{run_id}/question")
    def get_run_question(run_id: str) -> dict:
        """返回 run 当前挂起问题（5+1：question + 最多 5 个选项 + 自由文本）。"""
        question = get_agent_runtime().store.get_open_question(run_id)
        if question is None:
            raise HTTPException(status_code=404, detail="no open question")
        return question

    @app.post("/api/agent/runs/{run_id}/question")
    def answer_run_question(run_id: str, body: AnswerQuestionRequest) -> dict:
        """登记答案、把 run 转回 RUNNING 后**立即返回**；续跑段在运行时执行器上跑，
        进度走该 run 的 ``/stream`` SSE。answers 为 string | array；timed_out=true
        按超时收尾。"""
        runtime = get_agent_runtime()
        try:
            run_payload = runtime.answer_question(
                run_id, body.answers, timed_out=body.timed_out
            )
        except KeyError:
            raise HTTPException(status_code=404, detail="run not found")
        except InvalidRunTransitionError:
            raise HTTPException(status_code=409, detail="run is not waiting for a question")
        except CheckpointMissingError as error:
            # 决策 4（2026-09-07 修订）：载体里也没有该 run 的图状态，明确失败而不是在
            # 空图上静默重放。带稳定码，前端据此不再把用户留在一条走不通的路上。
            raise HTTPException(
                status_code=409,
                detail={"code": CHECKPOINT_MISSING_CODE, "message": str(error)},
            ) from None
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error))
        return _agent_run_payload(
            AgentRun.model_validate(run_payload), runtime.store
        )

    @app.get("/api/agent/runs/{run_id}/events")
    def get_agent_events(
        run_id: str,
        after: int = Query(default=0, ge=0),
    ) -> list[dict]:
        """获取智能体运行的事件流（after 参数用于轮询）"""
        try:
            events = get_agent_runtime().store.list_events(run_id, after=after)
            return [_redacted_event_payload(event) for event in events]
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
                AgentRunStatus.SUCCEEDED,
                AgentRunStatus.FAILED,
                AgentRunStatus.CANCELLED,
                # 暂停（预算/超时/重启恢复）也是运行终点：SSE 结束，前端可继续/恢复
                AgentRunStatus.UNFINISHED,
            }
            while True:
                events = manager.store.list_events(run_id, after=cursor)
                for event in events:
                    cursor = event.sequence
                    # 与 /events 同一份脱敏。ensure_ascii=False + 紧凑分隔符让线上字节
                    # 与原先的 model_dump_json() 一致：中文按 UTF-8 原样发出，不转义。
                    payload = json.dumps(
                        _redacted_event_payload(event),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                    yield (
                        f"id: {event.sequence}\n"
                        f"event: {event.type.value}\n"
                        f"data: {payload}\n\n"
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

    @app.post("/api/agent/runs/{run_id}/cancel", status_code=status.HTTP_202_ACCEPTED)
    def cancel_agent_run(run_id: str) -> dict:
        """取消正在运行的智能体"""
        try:
            _runtime = get_agent_runtime()
            return _agent_run_payload(_runtime.cancel(run_id), store=_runtime.store)
        except KeyError:
            raise HTTPException(status_code=404, detail="agent run not found") from None
        except InvalidRunTransitionError as error:
            raise HTTPException(status_code=409, detail=str(error)) from None
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from None

    @app.post("/api/agent/runs/{run_id}/retry", status_code=status.HTTP_202_ACCEPTED)
    def retry_agent_run(run_id: str) -> dict:
        """重试失败的智能体运行"""
        try:
            _runtime = get_agent_runtime()
            return _agent_run_payload(_runtime.retry(run_id), store=_runtime.store)
        except KeyError:
            raise HTTPException(status_code=404, detail="agent run not found") from None
        # 两个异常都继承 RuntimeError（不是 ValueError）：漏掉它们，门禁冲突就是 500。
        except InvalidRunTransitionError as error:
            raise HTTPException(status_code=409, detail=str(error)) from None
        except AgentRunInProgressError as error:
            raise HTTPException(status_code=409, detail=str(error)) from None
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from None

    @app.post("/api/agent/runs/{run_id}/resume", status_code=status.HTTP_202_ACCEPTED)
    def resume_agent_run(run_id: str) -> dict:
        """继续/恢复未完成的智能体运行（从 checkpoint 推进）"""
        try:
            _runtime = get_agent_runtime()
            return _agent_run_payload(_runtime.resume(run_id), store=_runtime.store)
        except KeyError:
            raise HTTPException(status_code=404, detail="agent run not found") from None
        except InvalidRunTransitionError as error:
            raise HTTPException(status_code=409, detail=str(error)) from None
        except CheckpointMissingError as error:
            # 决策 4（2026-09-07 修订）：载体复核后仍没有该 run 的图状态，明确失败而不是
            # 在空图上静默重放。带稳定码让前端把「继续」换成「重试」——retry 清状态后从
            # 有界 transcript 重放，用的正是后端持久化的 input_message，是这条唯一走得通的
            # 恢复路径；而 UNFINISHED 仍占着串行门禁，所以单纯让用户"重发消息"是死路。
            raise HTTPException(
                status_code=409,
                detail={"code": CHECKPOINT_MISSING_CODE, "message": str(error)},
            ) from None
        except AgentRunInProgressError as error:
            raise HTTPException(status_code=409, detail=str(error)) from None
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from None

    @app.get("/api/pending-diffs")
    def list_pending_diffs(run_id: str | None = None) -> dict:
        """列出待确认/已确认的运行 diff（可按 run_id 过滤）"""
        diffs = get_agent_runtime().store.list_pending_diffs(run_id=run_id)
        return {"pending_diffs": [diff.model_dump() for diff in diffs]}

    @app.get("/api/pending-diffs/{diff_id}")
    def get_pending_diff(diff_id: str) -> dict:
        try:
            return get_agent_runtime().store.get_pending_diff(diff_id).model_dump()
        except KeyError:
            raise HTTPException(status_code=404, detail="pending diff not found") from None

    @app.get("/api/pending-diffs/{diff_id}/patch")
    def get_pending_diff_patch(diff_id: str) -> dict:
        """返回待确认 diff 的统一补丁文本（侧边栏 diff 查看）。"""
        try:
            patch = get_agent_runtime().pending_diff_patch(diff_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="pending diff not found") from None
        return {"diff_id": diff_id, "patch": patch}

    @app.post("/api/pending-diffs/{diff_id}/accept", status_code=status.HTTP_200_OK)
    def accept_pending_diff(diff_id: str) -> dict:
        """接受运行 diff：commit 保留，审计生效"""
        try:
            return get_agent_runtime().accept_pending_diff(diff_id).model_dump()
        except KeyError:
            raise HTTPException(status_code=404, detail="pending diff not found") from None
        except Exception as error:
            raise HTTPException(status_code=409, detail=str(error)) from None

    @app.post("/api/pending-diffs/{diff_id}/reject", status_code=status.HTTP_200_OK)
    def reject_pending_diff(diff_id: str) -> dict:
        """拒绝运行 diff：逐个 revert 该 run 的 commit"""
        try:
            return get_agent_runtime().reject_pending_diff(diff_id).model_dump()
        except KeyError:
            raise HTTPException(status_code=404, detail="pending diff not found") from None
        except Exception as error:
            raise HTTPException(status_code=409, detail=str(error)) from None

    @app.post("/api/pending-diffs/{diff_id}/reopen", status_code=status.HTTP_200_OK)
    def reopen_pending_diff(diff_id: str) -> dict:
        """重新打开当前未判定单元（幂等）；已判定单元不可回退 -> 409。"""
        try:
            return get_agent_runtime().reopen_pending_diff(diff_id).model_dump()
        except KeyError:
            raise HTTPException(status_code=404, detail="pending diff not found") from None
        except InvalidRunTransitionError as error:
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
            "thread_summary": runtime.store.thread_usage_summary(run.thread_id),
            # 决策 12：载体不设 TTL/体积上限，膨胀只由删会话治理，所以把体积报出来，
            # 后续才能按实测数据重新评估要不要加上限。
            "checkpoint": {
                "id": run.checkpoint_id,
                "backend": settings.agent_checkpointer,
                "file_bytes": checkpoint_file_bytes(runtime.project_root),
            },
        }

    # 关闭时清理智能体运行时
    def close_agent_runtime() -> None:
        # 注入的运行时属于测试/应用所有，只关闭延迟加载的默认运行时
        if owns_runtime and runtime is not None:
            runtime.close()

    app.router.add_event_handler("shutdown", close_agent_runtime)

    # 功能路由保持独立，不扩展主应用组装
    app.include_router(create_error_router(root))
    app.include_router(create_retention_router(root))
    return app


# ===========================================================================
# 辅助函数
# ===========================================================================

def _agent_run_payload(run: AgentRun, store: RuntimeStore | None = None) -> dict:
    payload = run.model_dump(mode="json")
    if store is not None:
        assistants = [
            m for m in store.list_messages(run.thread_id) if m["role"] == "assistant"
        ]
        payload["answer"] = (assistants[-1]["content"] if assistants else "") or ""
    # 用户提示在队列运行恢复时保持持久化，但不是桌面控制面的 DTO 的一部分
    payload.pop("input_message", None)
    payload["error_message"] = _redact_diagnostic_error(run.error_message)
    # 添加 UI 辅助标记
    payload["retryable"] = is_retryable_run(run)    # 是否可重试
    payload["cancellable"] = run.status in {        # 是否可取消
        AgentRunStatus.QUEUED,
        AgentRunStatus.RUNNING,
        AgentRunStatus.RETRYING,
        AgentRunStatus.UNFINISHED,
    }
    payload["resumable"] = run.status == AgentRunStatus.UNFINISHED  # 是否可继续/恢复
    return payload


def _redacted_event_payload(event: AgentEvent) -> dict:
    """事件出口的统一脱敏：ERROR 的 message 与终态 RUN_STATUS 的 error_message。

    这两处原样携带 provider 的报错文本，而它可能把 ``Authorization: Bearer …`` 或
    API key 一起带回来（实测交接问题 E：前端直接看到 ``Error code: 500 - {...}``）。
    读侧脱敏而不是写侧：既覆盖已经落库的历史行，又让运行库保留完整原文供调试——与
    diagnostics 现有的读侧脱敏一致。

    只作用于这两类事件：``_redact_diagnostic_error`` 还会截断到 1000 字，套到
    MESSAGE_DELTA / REASONING_DELTA 上会把用户可见的正文悄悄截短。
    """
    payload = event.model_dump(mode="json")
    if event.type == AgentEventType.ERROR:
        payload["message"] = _redact_diagnostic_error(event.message)
    elif event.type == AgentEventType.RUN_STATUS:
        data = payload.get("data")
        if isinstance(data, dict) and data.get("error_message"):
            data["error_message"] = _redact_diagnostic_error(
                str(data["error_message"])
            )
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
