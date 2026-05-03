"""PDF text extraction using pdfplumber."""

import pdfplumber


def extract_pdf_to_text(pdf_path: str) -> str:
    """Extract full text from a PDF, preserving page boundaries.

    Returns text with '--- Page N ---' separators between pages.
    """
    pages_text = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            pages_text.append(f"--- Page {i + 1} ---\n{text}")

    return "\n\n".join(pages_text)


def extract_pdf_metadata(pdf_path: str) -> dict:
    """Extract basic metadata from a PDF.

    Returns dict with title, authors (if available), and page count.
    """
    with pdfplumber.open(pdf_path) as pdf:
        meta = pdf.metadata or {}
        return {
            "title": meta.get("Title", ""),
            "page_count": len(pdf.pages),
        }
