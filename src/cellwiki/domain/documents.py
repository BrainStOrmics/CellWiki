# =============================================================================
# 文档合约 —— 解析器、导入、证据引用和 UI 适配器共享的文档模型
# =============================================================================
# 定义从源文档解析到结构化表示（DocumentBlock → ParsedPage → ParsedDocument）
# 的完整数据管道，以及后续分块处理（DocumentChunk）的稳定合约。
# 所有解析器后端必须输出此模型，确保上层模块不依赖特定解析器实现。
# =============================================================================

"""Stable document contracts shared by parsers, ingest, evidence, and UI adapters."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import Field, field_validator

from cellwiki.domain.contracts import ContractModel


# ---- 文档块类型 ----
# 源文档解析后的块类型分类，不强制绑定特定解析器后端
class DocumentBlockType(str, Enum):
    """Block categories retained from source parsing without forcing one parser backend."""

    HEADING = "heading"       # 标题
    PARAGRAPH = "paragraph"   # 段落
    TABLE = "table"           # 表格
    FIGURE = "figure"         # 图片
    CAPTION = "caption"       # 图注/表注
    LIST = "list"             # 列表
    OTHER = "other"           # 其他


# ---- 文档块 ----
# 源文档的最小可解析单元，包含块 ID、页码、顺序、文本内容等
# 验证：文本不能为空
class DocumentBlock(ContractModel):
    block_id: str                             # 块唯一标识
    page_number: int = Field(ge=1)            # 所在页码
    order: int = Field(ge=0)                  # 块内顺序（从 0 开始）
    text: str                                  # 文本内容
    block_type: DocumentBlockType = DocumentBlockType.PARAGRAPH  # 块类型
    section: str = ""                          # 所属章节
    metadata: dict[str, Any] = Field(default_factory=dict)  # 附加元数据

    # 验证：块文本不能为空
    @field_validator("text")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("document blocks cannot be empty")
        return normalized


# ---- 解析页面 ----
# 解析后的页面，包含页面内的所有块
class ParsedPage(ContractModel):
    page_number: int = Field(ge=1)                       # 页码
    blocks: list[DocumentBlock] = Field(default_factory=list)  # 页面内的块列表
    width: float | None = None                           # 页面宽度（PDF 物理尺寸）
    height: float | None = None                          # 页面高度

    # 验证：所有块必须属于当前页面，并按 order 排序
    @field_validator("blocks")
    @classmethod
    def require_matching_page_numbers(cls, value: list[DocumentBlock], info):
        page_number = info.data.get("page_number")
        if page_number is not None and any(block.page_number != page_number for block in value):
            raise ValueError("every block must belong to its containing page")
        return sorted(value, key=lambda block: block.order)


# ---- 解析文档 ----
# 解析器适配器生成的可重建、页面感知的文档表示。
# 包含来源信息、解析器信息、页面列表和警告。
# 提供 all_blocks() 和 block() 方法用于上层模块访问。
class ParsedDocument(ContractModel):
    """Rebuildable, page-aware representation produced by a source parser adapter."""

    source_id: str                                  # 来源 ID
    source_hash: str                                # 来源文件哈希
    parser_name: str                                # 使用的解析器名称
    parser_version: str                             # 解析器版本
    parser_config: dict[str, Any] = Field(default_factory=dict)  # 解析器配置
    parse_hash: str                                 # 解析结果的哈希
    pages: list[ParsedPage]                         # 页面列表
    metadata: dict[str, Any] = Field(default_factory=dict)  # 附加元数据
    warnings: list[str] = Field(default_factory=list)  # 解析警告
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))  # 创建时间

    # 验证：页面必须有序且页码唯一
    @field_validator("pages")
    @classmethod
    def require_ordered_unique_pages(cls, value: list[ParsedPage]) -> list[ParsedPage]:
        if not value:
            raise ValueError("a parsed document must contain at least one page")
        ordered = sorted(value, key=lambda page: page.page_number)
        numbers = [page.page_number for page in ordered]
        if len(numbers) != len(set(numbers)):
            raise ValueError("parsed page numbers must be unique")
        return ordered

    # 返回所有块（按源顺序），分块和证据使用相同的接口
    def all_blocks(self) -> list[DocumentBlock]:
        """Return source-order blocks through the same interface used by chunking and evidence."""
        return [block for page in self.pages for block in page.blocks]

    # 按 block_id 查找块
    def block(self, block_id: str) -> DocumentBlock:
        for block in self.all_blocks():
            if block.block_id == block_id:
                return block
        raise KeyError(block_id)


# ---- 文档块 ----
# 稳定的提取单元，保留声明证据所需的每个源定位器。
# 基于来源内容生成稳定的 chunk_id（SHA256 哈希），
# 确保相同内容的分块产生相同的 ID。
class DocumentChunk(ContractModel):
    """A stable extraction unit retaining every source locator needed for claim evidence."""

    chunk_id: str                              # 分块 ID（内容寻址）
    source_id: str                             # 来源 ID
    page_start: int = Field(ge=1)              # 起始页码
    page_end: int = Field(ge=1)                # 结束页码
    section: str = ""                          # 章节
    block_ids: list[str]                       # 包含的块 ID 列表
    text: str                                  # 合并后的文本
    token_estimate: int = Field(ge=1)          # 估算的 token 数

    # 验证：结束页码不能小于起始页码
    @field_validator("page_end")
    @classmethod
    def require_valid_page_range(cls, value: int, info) -> int:
        start = info.data.get("page_start")
        if start is not None and value < start:
            raise ValueError("page_end cannot precede page_start")
        return value

    # 生成稳定的分块 ID（基于内容哈希）
    @classmethod
    def stable_id(cls, source_id: str, block_ids: list[str], text: str) -> str:
        digest = hashlib.sha256(
            f"{source_id}\0{'|'.join(block_ids)}\0{text}".encode("utf-8")
        ).hexdigest()[:20]
        return f"chunk_{digest}"
