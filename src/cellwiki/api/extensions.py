# =============================================================================
# 扩展路由 —— 发现、受控记忆、外部研究和语义审查的产品 API 路由
# =============================================================================
# 本模块提供独立的功能路由，避免主应用组装文件过于臃肿。
# 包含：知识图谱查询、记忆管理（召回/写入/冲突解决）、
# 外部研究搜索、L2 语义审查等端点。
# =============================================================================

"""Product routes for discovery, governed memory, research, and semantic review."""

from __future__ import annotations

from pathlib import Path
import uuid

from fastapi import APIRouter, Header, HTTPException, Query, status
from pydantic import BaseModel, Field

from cellwiki.domain.discovery import GraphNodeType, SearchDocumentType
from cellwiki.domain.memory import MemoryCandidate, MemoryKind
from cellwiki.services.discovery import DiscoveryIndex
from cellwiki.services.memory import MemoryStore
from cellwiki.services.research import ResearchService
from cellwiki.services.semantic_lint import SemanticLintService
from cellwiki.domain.contracts import PipelineTaskType
from cellwiki.services.pipeline import KnowledgePipelineHarness, PipelineBusyError


# ===========================================================================
# 请求/响应模型
# ===========================================================================

# 记忆召回请求
class MemoryRecallRequest(BaseModel):
    project_id: str = Field(default="cellwiki", max_length=128)
    query: str = Field(min_length=1, max_length=4000)
    kinds: list[MemoryKind] = Field(default_factory=list)
    limit: int = Field(default=6, ge=1, le=50)
    token_budget: int = Field(default=800, ge=32, le=8000)

# 记忆冲突解决请求
class MemoryConflictRequest(BaseModel):
    activate: bool  # True=激活，False=停用

# 外部研究搜索请求
class ResearchRequest(BaseModel):
    project_id: str = Field(default="cellwiki", max_length=128)
    query: str = Field(min_length=1, max_length=1000)
    limit: int = Field(default=5, ge=1, le=20)


# ===========================================================================
# create_extension_router —— 创建扩展功能路由
# 将发现、记忆、研究和语义审查等功能路由到独立的路由器，
# 保持主应用组装文件（api/app.py）简洁。
# 路由前缀为 /api，包括：
# - /discovery/* — 知识图谱搜索索引
# - /graph — 实体关系图查询
# - /memories/* — 智能体记忆管理
# - /research/* — 外部研究搜索
# - /lint/l2 — 语义审查
# ===========================================================================
def create_extension_router(project_root: Path) -> APIRouter:
    """Create feature routes while keeping the main application assembly shallow."""

    root = Path(project_root).resolve()
    # 初始化服务
    discovery = DiscoveryIndex(root)          # 发现索引
    memories = MemoryStore(root)              # 记忆存储
    semantic_lint = SemanticLintService(root)  # 语义 Lint
    pipeline = KnowledgePipelineHarness(root)
    router = APIRouter(prefix="/api")

    # ---- 发现索引 ----
    @router.get("/discovery/status")
    def discovery_status() -> dict:
        """获取发现索引状态"""
        return discovery.status().model_dump(mode="json")

    @router.post("/discovery/rebuild")
    def rebuild_discovery() -> dict:
        """重建发现索引"""
        return discovery.rebuild().model_dump(mode="json")

    # ---- 知识图谱 ----
    @router.get("/graph")
    def graph(
        focus: str | None = None,
        node_type: list[GraphNodeType] = Query(default=[]),
        source_id: str | None = None,
        limit: int = Query(default=400, ge=1, le=2000),
    ) -> dict:
        """查询知识图谱，支持焦点实体、节点类型过滤和来源过滤"""
        return discovery.graph(
            focus=focus,
            node_types=node_type,
            source_id=source_id,
            limit=limit,
        ).model_dump(mode="json")

    # ---- 记忆管理 ----
    # 列出记忆记录
    @router.get("/memories")
    def list_memories(
        project_id: str = "cellwiki",
        kind: MemoryKind | None = None,
        include_inactive: bool = False,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict]:
        return [
            item.model_dump(mode="json")
            for item in memories.list(
                project_id, kind=kind, include_inactive=include_inactive, limit=limit
            )
        ]

    # 提交记忆
    @router.post("/memories", status_code=status.HTTP_201_CREATED)
    def admit_memory(candidate: MemoryCandidate) -> dict:
        return memories.admit(candidate).model_dump(mode="json")

    # 召回记忆
    @router.post("/memories/recall")
    def recall_memory(request: MemoryRecallRequest) -> dict:
        records, recall = memories.recall(
            request.project_id,
            request.query,
            kinds=request.kinds,
            limit=request.limit,
            token_budget=request.token_budget,
        )
        return {
            "memories": [record.model_dump(mode="json") for record in records],
            "recall": recall.model_dump(mode="json"),
        }

    # 重建记忆索引
    @router.post("/memories/rebuild-index")
    def rebuild_memory_index() -> dict[str, int]:
        return {"indexed": memories.rebuild_index()}

    # 解决记忆冲突
    @router.post("/memories/{memory_id}/resolve")
    def resolve_memory(memory_id: str, request: MemoryConflictRequest, project_id: str = "cellwiki") -> dict:
        try:
            return memories.resolve_conflict(
                project_id, memory_id, activate=request.activate
            ).model_dump(mode="json")
        except KeyError:
            raise HTTPException(status_code=404, detail="memory not found") from None
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from None

    # 删除记忆
    @router.delete("/memories/{memory_id}")
    def delete_memory(memory_id: str, project_id: str = "cellwiki") -> dict:
        try:
            return memories.delete(project_id, memory_id).model_dump(mode="json")
        except KeyError:
            raise HTTPException(status_code=404, detail="memory not found") from None

    # ---- 外部研究 ----
    # 列出研究候选
    @router.get("/research/candidates")
    def research_candidates(project_id: str = "cellwiki") -> list[dict]:
        return [
            item.model_dump(mode="json")
            for item in ResearchService(root).list_candidates(project_id)
        ]

    # 搜索外部研究
    @router.get("/research/runs")
    def research_runs(project_id: str = "cellwiki") -> list[dict]:
        return [
            item.model_dump(mode="json")
            for item in ResearchService(root).list_refresh_runs(project_id)
        ]

    @router.post("/internal/research/refresh", status_code=status.HTTP_202_ACCEPTED)
    def research_refresh(
        request: ResearchRequest,
        internal_compatibility: str | None = Header(default=None, alias="X-CellWiki-Internal"),
    ) -> dict:
        """Run broad external lint research against one pipeline snapshot."""
        if internal_compatibility != "1":
            raise HTTPException(status_code=404, detail="internal compatibility route")
        try:
            return ResearchService(root).refresh(
                request.query,
                project_id=request.project_id,
                limit=request.limit,
            ).model_dump(mode="json")
        except PipelineBusyError as error:
            raise HTTPException(status_code=409, detail=str(error)) from None
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from None
        except Exception as error:
            raise HTTPException(status_code=503, detail=str(error)[:500]) from None

    @router.post("/internal/research/search", status_code=status.HTTP_202_ACCEPTED)
    def research(
        request: ResearchRequest,
        internal_compatibility: str | None = Header(default=None, alias="X-CellWiki-Internal"),
    ) -> list[dict]:
        if internal_compatibility != "1":
            raise HTTPException(status_code=404, detail="internal compatibility route")
        try:
            return [
                item.model_dump(mode="json")
                for item in ResearchService(root).search_and_register(
                    request.query, project_id=request.project_id, limit=request.limit
                )
            ]
        except (ValueError, RuntimeError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from None
        except Exception as error:
            # 网络/提供商失败仍可重试，但不会成为正式变更
            raise HTTPException(status_code=503, detail=str(error)[:500]) from None

    # ---- 语义审查（L2）----
    @router.get("/lint/l2")
    def l2_findings() -> list[dict]:
        """获取 L2 语义审查发现项"""
        with pipeline.acquire(
            task_type=PipelineTaskType.LINT,
            run_id=f"lint_l2_{uuid.uuid4().hex}",
        ):
            return [item.model_dump(mode="json") for item in semantic_lint.inspect()]

    @router.post("/internal/lint/l2/review")
    def l2_review_items(
        internal_compatibility: str | None = Header(default=None, alias="X-CellWiki-Internal"),
    ) -> list[dict]:
        """运行 L2 审查并返回审查项"""
        if internal_compatibility != "1":
            raise HTTPException(status_code=404, detail="internal compatibility route")
        with pipeline.acquire(
            task_type=PipelineTaskType.LINT,
            run_id=f"lint_l2_{uuid.uuid4().hex}",
        ):
            semantic_lint.inspect(persist_reviews=True)
            return [item.model_dump(mode="json") for item in semantic_lint.review_items()]

    return router


# 搜索适配器（为已有的 /api/search 路由保留）
def search_discovery(
    project_root: Path,
    query: str,
    *,
    types: list[SearchDocumentType] | None = None,
    limit: int = 20,
) -> list[dict]:
    """Small adapter retained for the existing `/api/search` route."""
    return [
        item.model_dump(mode="json")
        for item in DiscoveryIndex(project_root).search(query, types=types, limit=limit)
    ]
