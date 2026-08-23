# =============================================================================
# LangGraph State 定义 —— CellWiki 所有子图的状态模型
# =============================================================================
# 本模块定义所有 LangGraph 子图使用的 State 类型。
# 状态定义于 MASTER_PLAN.md 第 4 节。
# 使用 TypedDict 定义状态结构，LangGraph 通过 reducer 函数管理状态更新。
# 所有子图共享 WikiState 作为全局知识状态的基础。
# =============================================================================

"""LangGraph State definitions for CellWiki.

This module defines all State models used across LangGraph subgraphs.
States are defined in MASTER_PLAN.md Section 4.
"""

from typing_extensions import TypedDict


# ============================================================================
# Reducer 函数 —— 定义 LangGraph 状态更新策略
# ============================================================================

# 合并两个字典（b 覆盖 a 中同名字段）
def merge_dict(a: dict, b: dict) -> dict:
    """Merge two dicts, b overwrites a."""
    return {**a, **b}


# 追加两个列表（返回新列表 a + b）
def append_list(a: list, b: list) -> list:
    """Append lists."""
    return a + b


# ============================================================================
# WikiState —— 全局 Wiki 知识状态
# 所有子图都可以读写此状态，包含实体存储、索引、图谱和元数据
# ============================================================================

class WikiState(TypedDict):
    """Global CellWiki knowledge state. All subgraphs read/write this."""

    # ---- 实体存储 ----
    cell_types: dict          # 细胞类型字典
    marker_genes: dict        # 标记基因字典
    tissues: dict             # 组织字典
    diseases: dict            # 疾病字典
    methods: dict             # 实验方法字典
    trajectories: dict        # 分化轨迹字典

    # ---- 索引和日志 ----
    index: dict               # 搜索索引
    log_entries: list         # 日志条目
    contradictions: list      # 矛盾记录

    # ---- 知识图谱 ----
    graph_nodes: list         # 图节点列表
    graph_edges: list         # 图边列表

    # ---- 元数据 ----
    source_registry: dict     # 来源注册表
    statistics: dict          # 统计信息


# ============================================================================
# IngestState —— 导入操作状态
# 单次导入操作的完整状态，从输入到输出
# ============================================================================

class IngestState(TypedDict):
    """State for a single ingest operation."""

    # ---- 输入 ----
    source_path: str                        # 来源文件路径
    source_type: str                        # 来源类型："paper", "dataset", "note"
    paper_text: str                         # 论文全文文本

    # ---- 步骤 1: 分析 ----
    analysis: dict                          # IngestAnalysis 分析结果

    # ---- 上下文 ----
    existing_pages: dict                    # 已有页面内容（page_id -> markdown）

    # ---- 审查 ----
    review_items: list                      # 需要审查的项
    approved: bool                          # 是否已批准
    review_notes: str                       # 审查备注

    # ---- 步骤 2: 生成 ----
    generation_plan: dict                   # 页面生成计划
    updated_pages: list                     # 已更新的页面列表
    new_pages: list                         # 新创建的页面列表

    # ---- 状态 ----
    status: str                             # 当前状态：initialized|analyzing|reviewing|generating|linting|done|aborted
    errors: list                            # 错误列表


# ============================================================================
# QueryState —— 查询操作状态
# 一次查询的完整状态，从问题到答案
# ============================================================================

class QueryState(TypedDict):
    """State for a single query operation."""

    question: str                           # 用户问题
    max_context_tokens: int                 # 最大上下文 token 数

    identified_entities: list               # 识别出的实体
    initial_matches: list                   # 初始匹配结果
    expanded_matches: list                  # 扩展匹配结果
    selected_pages: list                    # 选中的页面
    used_tokens: int                        # 已使用的 token 数
    budget_exceeded: bool                   # 是否超出预算

    answer: str                             # 最终回答
    citations: list                         # 引用列表
    confidence: str                         # 置信度

    status: str                             # 当前状态
    needs_research: bool                    # 是否需要外部研究


# ============================================================================
# LintState —— Lint 操作状态
# 质量检查的完整状态，从扫描到修复
# ============================================================================

class LintState(TypedDict):
    """State for a lint operation."""

    issues: list                            # 发现的问题列表
    auto_fixable: list                      # 可自动修复的问题
    manual_review: list                     # 需要人工审查的问题
    fixes_applied: list                     # 已应用的修复
    remaining_issues: list                  # 剩余问题
    iteration: int                          # 当前迭代次数
    max_iterations: int                     # 最大迭代次数
    status: str                             # 当前状态


# ============================================================================
# ResearchState —— 研究操作状态
# 深度研究的完整状态，从知识缺口到研究发现
# ============================================================================

class ResearchState(TypedDict):
    """State for a deep research operation."""

    gap: dict                               # 知识缺口描述
    search_queries: list                    # 搜索查询列表
    search_results: list                    # 搜索结果列表
    synthesized_findings: str               # 综合发现
    proposed_updates: list                  # 建议的更新
    confidence: str                         # 置信度
    iteration: int                          # 当前迭代次数
    max_iterations: int                     # 最大迭代次数
    status: str                             # 当前状态


# ============================================================================
# OrchestratorState —— 编排器状态
# 顶层编排器的状态，负责路由到子图
# ============================================================================

class OrchestratorState(TypedDict):
    """State for the orchestrator."""

    command: str                            # 命令类型："ingest", "query", "lint", "research"
    command_args: dict                      # 命令参数
    result: dict                            # 执行结果

