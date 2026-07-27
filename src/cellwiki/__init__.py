# =============================================================================
# CellWiki —— 基于文献构建的单细胞生物学知识库
# =============================================================================
# 本包提供从科研文献中提取、整理和查询单细胞生物学知识的完整管线。
# 它结合了 LLM 实体抽取、引用感知的知识图谱构建以及结构化查询 API，
# 支持可复现的、文献规模的细胞生物学研究。
#
# 核心组件：
#   - domain/models: 细胞、基因、标记物、组织、疾病等核心数据模型
#   - services/ingest: 文档导入、解析和实体抽取管线
#   - services/research: 跨多数据源的文献检索与发现
#   - api: 知识库的结构化查询端点
#   - agent: 基于 LLM 驱动的智能体接口，支持交互式探索
#   - evaluation: 抽取准确性的基准测试与质量指标
# =============================================================================

"""CellWiki - Single-cell biology knowledge base built from literature.

This package provides a complete pipeline for extracting, curating, and querying
single-cell biology knowledge from scientific literature. It combines LLM-based
entity extraction, citation-aware graph construction, and a structured query API
to support reproducible literature-scale cell biology research.

Key components:
  - domain/models: core data model for cells, genes, markers, tissues, and diseases
  - services/ingest: document ingestion, parsing, and entity extraction pipeline
  - services/research: literature search and discovery across multiple sources
  - api: structured query endpoints for the knowledge base
  - agent: LLM-driven agentic interface for interactive exploration
  - evaluation: benchmarking and quality metrics for extraction accuracy
"""
