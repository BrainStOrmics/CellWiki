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
    # 每次整篇 Agent 草稿定稿的最大输出 token 数（上限 64K）
    ingest_max_output_tokens: int = Field(default=12000, ge=500, le=65_536)

    # ---- 证据优先的 Ingest Agent 设置（Phase A/B）----
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

    # ---- 工作区版 Agent 运行时设置（阶段 4/5）----
    # 单次 run 的最大工具步数（阶段 4 使用）；超限进入 unfinished 状态
    agent_max_tool_steps: int = Field(default=100, ge=1, le=500)
    # 单次 run 的墙钟超时（秒），防止模型调用卡死
    agent_run_max_seconds: int = Field(default=7200, ge=60, le=86_400)
    # 会话上下文上限（token）；阶段 5 的分层 prompt 按 512K/80%/32K 压缩
    agent_context_max_tokens: int = Field(default=512_000, ge=8_000, le=2_000_000)
    agent_context_auto_compact_ratio: float = Field(default=0.8, ge=0.5, le=0.95)
    agent_context_retained_tokens: int = Field(default=32_768, ge=4_000, le=200_000)
    # ---- 附件感知与读取预算（附件驱动导入）----
    agent_attachment_preview_chars: int = Field(default=2000, ge=0, le=20_000)
    agent_attachment_read_budget_chars: int = Field(default=400_000, ge=0, le=20_000_000)  # 0 = 不限制

    # ---- 日志级别 ----
    log_level: str = "INFO"

    # ---- 项目路径（应用根与工作区根分离）----
    # 应用根 = 代码仓库根：由 __file__ 固定推断，不依赖工作目录；env alias
    # 指向不会出现的变量名，因此不会被 .env 的 PROJECT_ROOT 覆盖。
    project_root: Path = Field(
        default_factory=lambda: Path(__file__).resolve().parent.parent.parent,
        validation_alias="CELLWIKI_APP_ROOT",
    )
    # 工作区根 = 用户选择的知识库目录：Settings UI 持久化到 .env 的
    # PROJECT_ROOT；未选择时回退到应用根（单目录工作流）。
    workspace_root: Path = Field(
        default_factory=lambda: Path(__file__).resolve().parent.parent.parent,
        validation_alias="PROJECT_ROOT",
    )

    # ---- 细胞本体论（Cell Ontology）----
    cell_ontology_url: str = "https://purl.obolibrary.org/obo/cl.obo"

    # ---- 知识库派生路径（基于工作区根，动态计算）----
    @property
    def data_dir(self) -> Path:
        return self.workspace_root / "data"

    @property
    def references_dir(self) -> Path:
        return self.data_dir / "references"

    @property
    def extraction_dir(self) -> Path:
        return self.data_dir / "extraction"

    @property
    def cell_ontology_dir(self) -> Path:
        return self.data_dir / "cell_ontology"

    @property
    def cell_ontology_file(self) -> Path:
        return self.cell_ontology_dir / "cl.obo"

    @property
    def wiki_dir(self) -> Path:
        return self.workspace_root / "wiki"

    @property
    def wiki_cell_types_dir(self) -> Path:
        return self.wiki_dir / "cell_types"

    @property
    def wiki_marker_genes_dir(self) -> Path:
        return self.wiki_dir / "marker_genes"

    @property
    def wiki_tissues_dir(self) -> Path:
        return self.wiki_dir / "tissues"

    @property
    def wiki_diseases_dir(self) -> Path:
        return self.wiki_dir / "diseases"

    @property
    def wiki_methods_dir(self) -> Path:
        return self.wiki_dir / "methods"

    @property
    def wiki_trajectories_dir(self) -> Path:
        return self.wiki_dir / "trajectories"

    @property
    def wiki_state_spaces_dir(self) -> Path:
        return self.wiki_dir / "state_spaces"

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
