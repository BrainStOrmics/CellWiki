# =============================================================================
# PDF 文本提取 —— 使用 pdfplumber 从 PDF 文件中提取文本和元数据
# =============================================================================
# pdfplumber 优先于 PyMuPDF 或 pdfminer，因为它能更好地保留阅读顺序，
# 并且对生物医学预印本中常见的格式异常的 PDF 处理更优雅。
# 调用者应自行捕获 pdfplumber.PDFSyntaxError 和 FileNotFoundError。
# =============================================================================

"""Extract text and metadata from PDF files using pdfplumber.

pdfplumber is preferred over PyMuPDF or pdfminer for this use case because it
preserves reading order and handles malformed PDFs (common in biomedical
preprints) more gracefully.  Callers should catch pdfplumber.PDFSyntaxError
and FileNotFoundError themselves since the right failure strategy depends on
the batch context (skip vs. abort).
"""

import pdfplumber


# ---------------------------------------------------------------------------
# 从 PDF 中提取全文文本，保留页面边界
# 返回的文本中每页之间用 '--- Page N ---' 分隔，
# 下游解析器可以在 "\n\n---" 处分割而不产生歧义。
# ---------------------------------------------------------------------------
def extract_pdf_to_text(pdf_path: str) -> str:
    """Extract full text from a PDF, preserving page boundaries.

    Returns text with '--- Page N ---' separators between pages.
    """
    pages_text = []
    # 使用 pdfplumber 打开 PDF 文件
    with pdfplumber.open(pdf_path) as pdf:
        # 遍历每一页
        for i, page in enumerate(pdf.pages):
            # extract_text() 对空白页或纯扫描页返回 None，
            # 因此用 or "" 转为空字符串，保持页面分隔符出现在输出中
            text = page.extract_text() or ""
            # 添加页面分隔标记，方便下游按页分割
            pages_text.append(f"--- Page {i + 1} ---\n{text}")

    # 页之间用双换行分隔，这样下游解析器可以在 "\n\n---" 处分割，
    # 而不会产生歧义（页面内容本身永远不会以 "---" 开头）
    return "\n\n".join(pages_text)


# ---------------------------------------------------------------------------
# 提取 PDF 基本元数据（标题和页数）
# 故意省略作者提取，因为实际 PDF 元数据中的 "Author" 通常是管道用户名
# 而不是真名，可靠的作者解析需要在标题页上使用 NLP 处理。
# ---------------------------------------------------------------------------
def extract_pdf_metadata(pdf_path: str) -> dict:
    """Extract basic metadata from a PDF.

    Returns dict with title and page count.  Author extraction is deliberately
    omitted because real-world PDF metadata for "Author" is often a pipeline
    username rather than a person's name, and reliable author parsing requires
    NLP over the title page instead.
    """
    with pdfplumber.open(pdf_path) as pdf:
        # pdfplumber.metadata 在 PDF 没有元数据流时为 None
        meta = pdf.metadata or {}
        return {
            "title": meta.get("Title", ""),
            "page_count": len(pdf.pages),
        }
