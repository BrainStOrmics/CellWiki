# =============================================================================
# 分块服务 —— 保留页面和块定位器的章节感知分块
# =============================================================================

"""Section-aware chunking that retains page and block locators for evidence validation."""

from __future__ import annotations

import re

from cellwiki.domain.documents import DocumentBlock, DocumentChunk, ParsedDocument


# ---------------------------------------------------------------------------
# 将解析后的文档分块
# 将源文档的块（blocks）按字符数限制分组为多个 DocumentChunk。
# 过大的块会被分割为有界文本片段，但保留原始块 ID。
# 这样证据引用可以解析到不可变的源块和页面，
# 而模型请求不会继承无界解析器块。
# 分块策略：在达到字符限制或章节变更时刷新当前块，
# 并保留重叠文本以保持上下文连续性。
# ---------------------------------------------------------------------------
def chunk_document(
    document: ParsedDocument,
    *,
    max_characters: int = 18_000,
    overlap_characters: int = 1_200,
) -> list[DocumentChunk]:
    """Group source blocks into bounded chunks without losing source identity.

    Oversized blocks are exposed as bounded text fragments that retain the original
    block ID. Evidence therefore resolves to the immutable source block and page,
    while model requests never inherit an unbounded parser block.
    """

    # 验证参数范围
    if max_characters < 500:
        raise ValueError("max_characters must be at least 500")
    if overlap_characters < 0 or overlap_characters >= max_characters:
        raise ValueError("overlap_characters must be non-negative and smaller than max_characters")

    chunks: list[DocumentChunk] = []
    current: list[DocumentBlock] = []  # 当前正在构建的块
    current_size = 0                    # 当前块的总字符数

    # 刷新当前块到 chunks 列表，并计算重叠部分
    def flush() -> list[DocumentBlock]:
        nonlocal current, current_size
        if not current:
            return []
        # 将当前块列表转换为 DocumentChunk
        chunks.append(_make_chunk(document.source_id, current))
        # 计算重叠部分：从当前块末尾开始反向收集块
        # 直到达到 overlap_characters 限制
        overlap: list[DocumentBlock] = []
        overlap_size = 0
        for block in reversed(current):
            candidate = len(block.text) + 2
            if overlap and overlap_size + candidate > overlap_characters:
                break
            if candidate > overlap_characters:
                break
            overlap.insert(0, block)
            overlap_size += candidate
        # 将当前块替换为重叠部分，实现上下文连续性
        current = overlap
        current_size = overlap_size
        return overlap

    # 遍历所有源块
    for source_block in document.all_blocks():
        # 将过大的块分割为有界片段
        for block in _bounded_block_fragments(source_block, max_characters):
            block_size = len(block.text) + 2
            # 检测章节是否变更
            section_changed = bool(
                current
                and block.section
                and current[-1].section
                and block.section != current[-1].section
            )
            # 达到字符限制或章节变更时刷新
            if current and (current_size + block_size > max_characters or section_changed):
                flush()
            if current and current_size + block_size > max_characters:
                # 重叠是可选上下文。丢弃它而不是让下一个模型请求
                # 超过硬块边界
                current = []
                current_size = 0
            current.append(block)
            current_size += block_size
    flush()
    return chunks


# 从块列表创建 DocumentChunk
def _make_chunk(source_id: str, blocks: list[DocumentBlock]) -> DocumentChunk:
    text = "\n\n".join(block.text for block in blocks)
    # 使用 dict.fromkeys 保持顺序的同时去重块 ID
    block_ids = list(dict.fromkeys(block.block_id for block in blocks))
    sections = [block.section for block in blocks if block.section]
    # 使用最后一个非空章节作为块的章节标识
    return DocumentChunk(
        chunk_id=DocumentChunk.stable_id(source_id, block_ids, text),
        source_id=source_id,
        page_start=min(block.page_number for block in blocks),
        page_end=max(block.page_number for block in blocks),
        section=sections[-1] if sections else "",
        block_ids=block_ids,
        text=text,
        # 估算 token 数：按词和标点计数（粗略估计）
        token_estimate=max(1, len(re.findall(r"\b\w+\b|[^\s\w]", text))),
    )


# 将过大的块分割为有界文本片段，同时保留源定位器标识
# 使用自然边界（段落、句子、短语）进行分割，确保分割点合理
def _bounded_block_fragments(
    block: DocumentBlock,
    max_characters: int,
) -> list[DocumentBlock]:
    """Split model-facing text while preserving the source locator identity."""

    remaining = block.text.strip()
    fragments: list[DocumentBlock] = []
    # 最小分割边界：至少 max_characters 的一半
    minimum_boundary = max(1, max_characters // 2)
    while len(remaining) > max_characters:
        # 按优先级尝试不同的分割点：段落 > 句子 > 短语 > 逗号 > 空格
        candidates = [
            remaining.rfind(marker, minimum_boundary, max_characters + 1) + len(marker)
            for marker in ("\n\n", "\n", ". ", "; ", ", ", " ")
        ]
        # 选择最佳分割点，如果没有找到合适的分割点则强制在 max_characters 处分割
        split_at = max((candidate for candidate in candidates if candidate > 0), default=max_characters)
        fragment = remaining[:split_at].strip()
        if not fragment:
            fragment = remaining[:max_characters]
            split_at = max_characters
        fragments.append(block.model_copy(update={"text": fragment}))
        remaining = remaining[split_at:].strip()
    if remaining:
        fragments.append(block.model_copy(update={"text": remaining}))
    return fragments
