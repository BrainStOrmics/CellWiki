# =============================================================================
# 搜索与知识图谱投影 —— 面向可重建的全文搜索和图结构查询
# =============================================================================
# 定义搜索引擎索引状态、知识图谱节点/边类型，以及搜索结果的统一数据模型。
# 这些模型支撑了 CellWiki 的全文搜索功能和实体关系可视化。
# =============================================================================

"""Stable contracts for rebuildable full-text search and knowledge graph projections."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import Field

from cellwiki.domain.contracts import ContractModel


# ---- 搜索文档类型 ----
# 搜索引擎索引的文档类型分类
class SearchDocumentType(str, Enum):
    PAGE = "page"          # Wiki 页面
    ENTITY = "entity"      # 实体（细胞类型等）
    SOURCE = "source"      # 来源文档
    CLAIM = "claim"        # 科学声明
    EVIDENCE = "evidence"  # 证据引用
    LINT = "lint"          # Lint 发现项


# ---- 搜索结果 ----
# 搜索引擎返回的单个结果项
class SearchResult(ContractModel):
    document_id: str                # 文档 ID
    type: SearchDocumentType        # 文档类型
    title: str                      # 标题
    snippet: str                    # 摘要片段
    score: float                    # 相关性分数
    page_id: str | None = None      # 关联页面 ID
    source_id: str | None = None    # 关联来源 ID
    locator: str | None = None      # 定位器
    metadata: dict[str, Any] = Field(default_factory=dict)  # 附加元数据


# ---- 搜索索引状态 ----
# 搜索引擎的当前状态信息
class SearchIndexStatus(ContractModel):
    schema_version: int              # 模式版本号
    content_version: str             # 内容版本
    document_count: int              # 文档总数
    node_count: int                  # 图谱节点数
    edge_count: int                  # 图谱边数
    rebuilt: bool = False            # 是否已重建


# ---- 图谱节点类型 ----
class GraphNodeType(str, Enum):
    CELL_TYPE = "cell_type"   # 细胞类型
    MARKER = "marker"         # 标记物
    TISSUE = "tissue"         # 组织
    SPECIES = "species"       # 物种
    SOURCE = "source"         # 来源
    CLAIM = "claim"           # 声明


# ---- 图谱边类型 ----
# 定义实体之间的关系类型
class GraphEdgeType(str, Enum):
    EXPRESSES = "expresses"               # 表达关系
    DOES_NOT_EXPRESS = "does_not_express" # 不表达
    LOCATED_IN = "located_in"             # 位于
    SUPPORTED_BY = "supported_by"         # 受支持
    CONTRADICTS = "contradicts"           # 矛盾
    RELATED_TO = "related_to"             # 相关


# ---- 图谱节点 ----
class GraphNode(ContractModel):
    node_id: str                     # 节点唯一标识
    type: GraphNodeType              # 节点类型
    label: str                       # 显示标签
    page_id: str | None = None       # 关联 Wiki 页面 ID
    source_id: str | None = None     # 关联来源 ID
    metadata: dict[str, Any] = Field(default_factory=dict)  # 附加元数据


# ---- 图谱边 ----
class GraphEdge(ContractModel):
    edge_id: str                     # 边唯一标识
    type: GraphEdgeType              # 关系类型
    source: str                      # 源节点 ID
    target: str                      # 目标节点 ID
    claim_id: str | None = None      # 支持此关系的声明 ID
    source_id: str | None = None     # 来源 ID
    confidence: str = "medium"        # 关系置信度
    evidence_count: int = Field(default=0, ge=0)  # 证据数量
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---- 知识图谱 ----
# 完整的知识图谱结构，包含节点列表和边列表
class KnowledgeGraph(ContractModel):
    nodes: list[GraphNode]            # 节点列表
    edges: list[GraphEdge]            # 边列表
    scope: str = "global"             # 查询范围
    truncated: bool = False           # 结果是否被截断

