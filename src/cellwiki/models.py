# ruff: noqa: F811
# =============================================================================
# 数据模型 —— CellWiki 抽取、知识库和 Wiki 页面的 Pydantic 数据模型
# =============================================================================
# 这些模型构成了 LLM 抽取输出、知识库合并管线以及前端使用的最终 Wiki 页面
# 表示之间的模式层。每个类映射到导入到发布工作流中的一个阶段。
# 包含 v2.0 扩展实体模型（细胞类型、标记基因、组织、疾病、方法、轨迹等）。
# =============================================================================

"""Pydantic data models for CellWiki extraction, knowledge base, and wiki pages.

These models form the schema layer between LLM extraction output, the knowledge
base merge pipeline, and the final wiki page representations consumed by the
frontend. Each class maps to a stage in the ingest-to-publish workflow.
"""

from enum import Enum, IntEnum
from typing import Optional

from pydantic import BaseModel, Field

from cellwiki.domain.contracts import Claim


# ---- 标记物类型 ----
# 支持三种标记物类别：蛋白质水平（阳性/阴性）和 RNA 水平（转录本）
class MarkerType(str, Enum):
    """Supported marker categories: protein-level (positive/negative) and RNA-level (transcript)."""
    POSITIVE = "positive"      # 蛋白质水平阳性表达
    NEGATIVE = "negative"      # 蛋白质水平阴性表达
    TRANSCRIPT = "transcript"  # RNA 转录本水平


# ---- 标记物 ----
# 单个与细胞类型关联的基因标记物，含可选的证据分级
class Marker(BaseModel):
    """A single gene marker associated with a cell type, with optional evidence grading."""

    gene_symbol: str          # 基因符号，如 "CD4"
    marker_type: MarkerType   # 标记物类型（阳性/阴性/转录本）
    evidence: str = ""        # 证据描述
    # 定性强度分级（如 "high", "moderate", "low"），不是 p 值
    # 由 LLM 提取器根据论文措辞设定
    strength: str = ""


# ---- 功能特征 ----
# 归因于某细胞类型的一个功能角色或通路参与
# pathway 字段可选，因为并非所有功能都与特定通路相关
class FunctionalCharacteristic(BaseModel):
    """One functional role or pathway involvement attributed to a cell type."""

    description: str   # 功能描述
    # 通路字段可选，因为有些功能是通用描述（如"细胞因子分泌"）
    pathway: str = ""
    evidence: str = ""


# ---- 论文引用 ----
# 源论文的最小引用信息，用作各提取阶段之间的外键
class PaperReference(BaseModel):
    """Minimal reference to a source paper. Used as a foreign-key across extraction stages."""

    paper_id: str                        # 论文唯一标识
    title: str                           # 论文标题
    doi: str = ""                        # DOI 标识符
    year: int = 0                        # 发表年份
    local_path: str = ""                 # 本地缓存 PDF 路径，无本地副本时为空


# ---- 细胞类型提取结果 ----
# 从单篇论文中提取的一个细胞类型，包含名称、本体论 ID、标记物等
class CellTypeExtract(BaseModel):
    """One cell type extracted from a single paper."""

    name: str                    # 原始名称
    standard_name: str           # 标准化名称（用作合并键）
    # 细胞本体论 ID（CL:xxxxxx），可选，因为许多细胞类型没有 CL 条目
    cl_id: Optional[str] = None
    synonyms: list[str] = Field(default_factory=list)   # 同义词列表
    # 本体论层次结构中的父类型（如 "CD4+ T cell" -> "T cell"）
    parent_type: Optional[str] = None
    species: list[str] = Field(default_factory=list)     # 物种
    tissues: list[str] = Field(default_factory=list)      # 组织
    diseases: list[str] = Field(default_factory=list)     # 疾病
    markers: list[Marker] = Field(default_factory=list)   # 标记物
    functions: list[FunctionalCharacteristic] = Field(default_factory=list)  # 功能
    subpopulations: list[str] = Field(default_factory=list)  # 子群
    description: str = ""         # 描述
    paper_ref: PaperReference     # 来源论文引用


# ---- 提取结果 ----
# 从单篇论文中提取的所有细胞类型
class ExtractionResult(BaseModel):
    """All cell types extracted from a single paper."""

    paper: PaperReference
    cell_types: list[CellTypeExtract] = Field(default_factory=list)
    # LLM 输出的未归一化关系，为下游合并逻辑保留
    raw_relationships: list[dict] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    # 完整的源文档元数据（标题、摘要、章节），用于审计追溯
    source_document: dict = Field(default_factory=dict)


# ---- 证据等级 ----
# 声明和注释的证据等级，从强到弱
# Compatibility exports for the original CLI and graph Modules. New product
# code imports these contracts from ``cellwiki.domain.extraction`` directly.
from cellwiki.domain.extraction import (  # noqa: E402,F401
    CellTypeExtract as CellTypeExtract,
    ExtractionResult as ExtractionResult,
    FunctionalCharacteristic as FunctionalCharacteristic,
    Marker as Marker,
    MarkerType as MarkerType,
    PaperReference as PaperReference,
)


class EvidenceTier(IntEnum):
    """Evidence tier for claims and annotations."""
    TIER_1 = 1  # 直接实验验证（KO、功能实验、空间共定位）
    TIER_2 = 2  # 多组学一致性（RNA + 蛋白质 + 表观遗传学一致）
    TIER_3 = 3  # 单组学 + 多篇独立论文（>=3 篇）
    TIER_4 = 4  # 单篇论文报告
    TIER_5 = 5  # LLM 推断 / 假设 / 未验证


# ---- 标记基因（Wiki 页面模型）----
# 包含表达谱、特异性评分、阴性证据、共表达、多组学等丰富字段
class MarkerGene(BaseModel):
    """A marker gene page in the wiki."""

    gene_symbol: str
    gene_name: str = ""
    gene_id_ensembl: str = ""      # Ensembl 基因 ID
    gene_id_ncbi: str = ""         # NCBI 基因 ID
    chromosome: str = ""           # 染色体位置
    protein_name: str = ""         # 蛋白质名称
    cell_types_expressed: list[str] = Field(default_factory=list)  # 表达的细胞类型
    specificity: str = ""          # 特异性，如 "T cell lineage"
    evidence_tier: EvidenceTier = EvidenceTier.TIER_5   # 证据等级
    source_count: int = 0          # 来源论文数量
    last_updated: str = ""         # 最后更新时间
    # 评估分数
    specificity_score: str = ""    # 特异性评分
    sensitivity_score: str = ""    # 敏感性评分
    stability_score: str = ""      # 稳定性评分
    detectability_score: str = ""  # 可检测性评分
    # 阴性证据
    negative_evidence: list[dict] = Field(default_factory=list)
    # [{"cell_type": "B cell", "evidence": "Not detected", "sources": ["paper1"]}]
    # 共表达
    co_expression: list[dict] = Field(default_factory=list)
    # [{"gene": "CD25", "cell_type": "Treg", "correlation": 0.85}]
    # 多组学
    epigenetic_features: str = ""  # 表观遗传学特征
    protein_data: str = ""         # 蛋白质数据
    references: list[dict] = Field(default_factory=list)  # 引用
    sources: list[str] = Field(default_factory=list)       # 来源


# ---- 组织（Wiki 页面模型）----
class Tissue(BaseModel):
    """A tissue/organ page in the wiki."""

    name: str
    display_name: str = ""
    uberon_id: str = ""            # UBERON 本体论 ID
    description: str = ""
    cell_types_found: dict[str, str] = Field(default_factory=dict)
    # key: cell_type_id, value: 丰度（"high"/"moderate"/"low"/"rare"）
    source_count: int = 0
    last_updated: str = ""
    references: list[dict] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)


# ---- 疾病（Wiki 页面模型）----
class Disease(BaseModel):
    """A disease association page in the wiki."""

    name: str
    display_name: str = ""
    category: str = ""             # 如 "cancer", "autoimmune", "infectious"
    mondo_id: str = ""             # MONDO 本体论 ID
    description: str = ""
    associated_cell_types: dict[str, str] = Field(default_factory=dict)
    # key: cell_type_id, value: 角色（"increased", "decreased", "altered"）
    associated_genes: list[str] = Field(default_factory=list)
    source_count: int = 0
    last_updated: str = ""
    references: list[dict] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)


# ---- 实验方法（Wiki 页面模型）----
class Method(BaseModel):
    """An experimental method page in the wiki."""

    name: str
    display_name: str = ""
    description: str = ""
    # 功能分类，不是字符串枚举——类别是自由格式的
    # （如 "transcriptomics", "proteomics"），可能随时间扩展
    category: str = ""
    applicable_scenarios: list[str] = Field(default_factory=list)  # 适用场景
    limitations: list[str] = Field(default_factory=list)            # 局限性
    source_count: int = 0
    last_updated: str = ""
    references: list[dict] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)


# ---- 轨迹状态 ----
# 分化/状态转换轨迹中的一个单一状态
class TrajectoryState(BaseModel):
    """A single state within a trajectory."""

    name: str
    cell_type_id: str = ""
    key_markers: list[str] = Field(default_factory=list)  # 关键标记物
    function: str = ""              # 功能描述
    # 定性增殖率，非测量值
    proliferation: str = ""         # "high"/"moderate"/"low"/"none"
    # 该状态的免疫检查点阻断（ICB）反应预测
    icb_responsive: str = ""        # "yes"/"partial"/"limited"/"no"
    # 驱动该状态的转录因子和其他调控因子
    key_regulators: list[dict] = Field(default_factory=list)
    # [{"tf": "TCF7", "role": "stemness maintenance"}]


# ---- 轨迹（Wiki 页面模型）----
class Trajectory(BaseModel):
    """A differentiation/state transition trajectory page."""

    name: str
    display_name: str = ""
    description: str = ""
    start_state: str = ""                        # 起始状态（cell_type_id）
    end_state: str = ""                          # 终止状态（cell_type_id）
    intermediate_states: list[str] = Field(default_factory=list)  # 中间状态
    states: list[TrajectoryState] = Field(default_factory=list)   # 所有状态
    key_regulators: list[dict] = Field(default_factory=list)      # 关键调控因子
    therapeutic_interventions: list[str] = Field(default_factory=list)  # 治疗干预
    context: list[str] = Field(default_factory=list)  # 如 ["chronic_infection", "cancer"]
    species: list[str] = Field(default_factory=list)
    evidence_tier: EvidenceTier = EvidenceTier.TIER_5
    source_count: int = 0
    last_updated: str = ""
    references: list[dict] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)


# ---- 导入分析结果 ----
# 导入链步骤 1 的结构化分析输出
class IngestAnalysis(BaseModel):
    """Structured analysis output from Step 1 of the ingest chain."""

    entities: list[dict] = Field(default_factory=list)
    # [{"type": "cell_type", "name": "...", "standard_name": "...", "markers": [...]}]
    relationships: list[dict] = Field(default_factory=list)
    # [{"source": "...", "relation": "...", "target": "..."}]
    contradictions: list[dict] = Field(default_factory=list)
    # [{"entity": "...", "description": "..."}]
    existing_pages_touched: list[str] = Field(default_factory=list)  # 触及的现有页面
    new_pages_needed: list[str] = Field(default_factory=list)        # 需要的新页面
    # LLM 评估的置信度，非统计测量
    confidence: str = "medium"  # "high"/"medium"/"low"
    uncertainties: list[str] = Field(default_factory=list)  # 不确定性


# ---- Wiki 细胞类型（合并后的规范表示）----
# 合并多篇论文数据后的细胞类型规范表示
class WikiCellType(BaseModel):
    """Merged, canonical representation of one cell type in the wiki."""

    standard_name: str
    display_name: str = ""
    cl_id: Optional[str] = None
    aliases: set[str] = Field(default_factory=set)
    parent_type: Optional[str] = None
    description: str = ""
    markers: dict[str, list[dict]] = Field(default_factory=dict)     # gene_symbol -> [marker entries]
    functions: dict[str, list[dict]] = Field(default_factory=dict)   # description -> [function entries]
    contexts: dict[str, dict] = Field(default_factory=dict)           # species -> {tissues, diseases}
    subpopulations: set[str] = Field(default_factory=set)
    references: list[dict] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    # 已知冲突被保留而非静默解决，如 "CD44: positive vs negative"
    # 合并管线在此记录分歧供人工审查
    conflicts: list[str] = Field(default_factory=list)

    # === CellWiki v2.0 扩展字段 ===
    identity: str = ""              # 谱系身份（如 "T_cell"）
    state: str = ""                 # 当前状态（如 "exhausted", "naive"）
    context: dict = Field(default_factory=dict)
    # {tissue, disease, species, spatial_zone, timepoint}
    temporal_stability: str = ""    # 时间稳定性："stable"/"transient"/"oscillating"
    evidence_tier: EvidenceTier = EvidenceTier.TIER_5
    # 阴性标记物（不表达的基因）用于排除门控
    # 与 MarkerType.NEGATIVE 不同，后者是蛋白质水平的阴性发现
    negative_markers: list[dict] = Field(default_factory=list)
    multi_omics_features: dict = Field(default_factory=dict)
    # {epigenetic: "...", proteomic: "...", spatial: "..."}
    open_questions: list[str] = Field(default_factory=list)  # 开放问题


# ============================================================
# CellWiki v2.0 — Extended Entity Models
# CellWiki v2.0 扩展实体模型
# ============================================================


# ---- 导入结果 ----
# 导入链步骤 2 的输出
class IngestResult(BaseModel):
    """Output from Step 2 of the ingest chain."""

    updated_pages: list[str] = Field(default_factory=list)   # 已更新的页面
    new_pages: list[str] = Field(default_factory=list)       # 新创建的页面
    review_items: list[dict] = Field(default_factory=list)   # 需要审查的项目
    log_entry: dict = Field(default_factory=dict)            # 日志条目
