# =============================================================================
# 配置模块 —— 路径、API 密钥和运行时设置的单一信源
# =============================================================================
# 通过 pydantic-settings 从环境变量和 .env 文件加载配置，
# 导出为模块级单例（settings），确保所有下游模块共享同一份已解析的环境视图。
# =============================================================================

"""Configuration for CellWiki - single source of truth for paths, API keys, and runtime settings.

Loaded from environment variables and .env via pydantic-settings, then exported as a
module-level singleton so all downstream modules share one resolved view of the environment.
"""

import logging

from cellwiki.services.logging_context import setup_structured_logging
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


# ---------------------------------------------------------------------------
# 日志初始化
# 在模块加载时调用，确保所有下游模块在首次使用日志时已有配置。
# 如果提供了无效的日志级别字符串，则回退到 INFO。
# ---------------------------------------------------------------------------
def setup_logging(level: str = "INFO"):
    """Configure logging for CellWiki with structured context support."""
    logging.basicConfig(
        # 如果传入的 level 字符串不是有效的日志常量，则回退到 INFO
        level=getattr(logging, level.upper(), logging.INFO),
        # 日志格式：时间 [级别] 模块名: 消息
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # Add structured logging with run correlation context
    setup_structured_logging(level)


# ---------------------------------------------------------------------------
# Settings —— 从环境变量 /.env 加载的全局配置
# 使用 pydantic-settings 自动读取环境变量，所有字段都有默认值。
# 导出为模块级单例（settings），确保所有模块共享同一份配置。
# ---------------------------------------------------------------------------
class Settings(BaseSettings):
    """CellWiki configuration loaded from environment / .env file."""

    # pydantic-settings 配置：从 .env 文件读取，UTF-8 编码
    # 注意：.env 是相对于执行工作目录解析的，不是包根目录
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # ---- OpenAI API 设置 ----
    openai_api_key: str = ""
    openai_base_url: str = ""
    # 默认使用非标准模型，用户可以通过环境变量覆盖
    # 兼容 Ollama、vLLM 等 OpenAI 兼容提供商
    openai_model: str = "qwen3.6-plus"
    # OpenAI 风格的 Base URL 无法说明服务端实现的是哪一种请求协议。
    # 显式配置可以避免 LangChain 根据模型名做出错误的自动切换。
    openai_api_protocol: str = "chat_completions"
    # 每个请求的超时时间，确保运行级取消和超时能在 HTTP 流停止时
    # 长论文结构化抽取的真实供应商尾延迟可超过 45 秒；默认 90 秒，
    # 同时保留 5-300 秒的显式配置范围。
    openai_request_timeout_seconds: float = Field(default=90.0, ge=5.0, le=300.0)

    # The desktop settings service persists the interface language in .env.
    # Keep it in the shared settings contract so that a saved UI preference
    # cannot make backend startup fail with an unexpected environment field.
    app_language: str = "zh-CN"

    # ---- 导入（Ingest）设置 ----
    # 每个分块的超时时间，防止传输超时被结构化输出重试循环放大
    ingest_chunk_timeout_seconds: float = Field(default=210.0, ge=15.0, le=900.0)
    # 最大重试次数，避免无限制重试耗尽 API 配额
    ingest_max_attempts: int = Field(default=3, ge=1, le=5)
    # 默认串行调用，避免长结构化请求在代理/Provider连接层互相影响；
    # 已验证支持并发的 Provider 仍可通过环境变量显式提高该值。
    ingest_max_concurrency: int = Field(default=1, ge=1, le=4)
    # 每次提取的最大输出 token 数，控制单次 LLM 调用的成本
    ingest_max_output_tokens: int = Field(default=5000, ge=500, le=20_000)

    # ---- 证据优先的 Ingest Agent 设置（Phase A/B）----
    # 提取通道：agent（整篇草稿 + 确定性护栏）或 chunked（原分块管线回退）。
    # prepare_ingest_change_set 未提供 agent_draft_run_id 时仍走 chunked 路径，
    # 因此该默认值不会改变既有调用行为。
    ingest_extraction_mode: str = "agent"
    ingest_agent_enabled: bool = True
    # 逐字接地未命中的证据回给 Agent 改写的最大轮次
    ingest_agent_max_grounding_passes: int = Field(default=2, ge=1, le=5)
    # 可选独立模型；为空则与协调器共用配置模型
    ingest_agent_model: str | None = None
    # 未落地实体占候选实体比例超过该阈值时，生成阻塞性审查项
    ingest_ungrounded_entity_ratio_limit: float = Field(default=0.10, ge=0.0, le=1.0)

    # ---- 实验性功能（Phase 7）- 默认关闭 ----
    # 在语义评估证明对基线有可衡量的改进之前保持 opt-in
    enable_agent_memory: bool = False       # 是否启用智能体长期记忆
    enable_external_research: bool = False  # 是否启用外部文献搜索
    # 单次记忆召回查询的 token 预算上限，防止单个智能体回合导致上下文无限增长
    memory_recall_token_budget: int = 800

    # ---- 日志级别 ----
    log_level: str = "INFO"

    # ---- 项目路径（相对项目根目录）----
    # 使用 __file__ 计算路径，确保无论以 wheel 安装还是源码运行都能工作
    # 不依赖固定工作目录或 PYTHONPATH
    project_root: Path = Path(__file__).parent.parent.parent
    data_dir: Path = project_root / "data"
    references_dir: Path = data_dir / "references"
    extraction_dir: Path = data_dir / "extraction"
    cell_ontology_dir: Path = data_dir / "cell_ontology"

    wiki_dir: Path = project_root / "wiki"
    wiki_cell_types_dir: Path = wiki_dir / "cell_types"

    # ---- 细胞本体论（Cell Ontology）----
    cell_ontology_url: str = "https://purl.obolibrary.org/obo/cl.obo"
    cell_ontology_file: Path = cell_ontology_dir / "cl.obo"


    # ---- Wiki 子目录 ----
    wiki_marker_genes_dir: Path = wiki_dir / "marker_genes"
    wiki_tissues_dir: Path = wiki_dir / "tissues"
    wiki_diseases_dir: Path = wiki_dir / "diseases"
    wiki_methods_dir: Path = wiki_dir / "methods"
    wiki_trajectories_dir: Path = wiki_dir / "trajectories"
    wiki_state_spaces_dir: Path = wiki_dir / "state_spaces"

# ---- 模块级单例 ----
# 所有下游模块导入此单例，配置在导入时解析一次而不是每次访问时构造。
# 这意味着导入后环境变量变更不会生效，需要重启。
settings = Settings()
setup_logging(settings.log_level)


def ensure_dirs():
    """Create all required directories if they don't exist.

    必须在启动时显式调用（例如在 CLI 入口点），而不是在导入时自动调用，
    这样简单的 --help 调用就不会创建文件系统状态。
    """
    # 遍历所有需要确保存在的目录
    for d in [
        settings.data_dir,
        settings.references_dir,
        settings.extraction_dir,
        settings.cell_ontology_dir,
        settings.wiki_dir,
        settings.wiki_cell_types_dir,
        settings.wiki_marker_genes_dir,
        settings.wiki_tissues_dir,
        settings.wiki_diseases_dir,
        settings.wiki_methods_dir,
        settings.wiki_trajectories_dir,
        settings.wiki_state_spaces_dir,
    ]:
        # exist_ok=True 使此操作幂等 —— 每次启动时调用是安全的
        d.mkdir(parents=True, exist_ok=True)
