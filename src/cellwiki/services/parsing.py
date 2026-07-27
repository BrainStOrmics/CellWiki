# =============================================================================
# 解析服务 —— 具有确定性缓存和两个具体适配器的页面感知源解析
# =============================================================================

"""Page-aware source parsing with deterministic cache and two concrete adapters."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Protocol

import pdfplumber

from cellwiki.domain.contracts import SourceRecord
from cellwiki.domain.documents import (
    DocumentBlock,
    DocumentBlockType,
    ParsedDocument,
    ParsedPage,
)


# ---------------------------------------------------------------------------
# UnsupportedSourceError —— 不支持的文件格式异常
# ---------------------------------------------------------------------------
class UnsupportedSourceError(ValueError):
    """Raised when no parser adapter owns a registered source extension."""


# ---------------------------------------------------------------------------
# SourceParser —— 解析器协议
# 解析器适配器必须保留源顺序和页面级定位器。
# 所有解析器输出 ParsedDocument，确保上层模块不依赖特定解析器实现。
# ---------------------------------------------------------------------------
class SourceParser(Protocol):
    """Parser seam; adapters must retain source order and page-level locators."""

    name: str                        # 解析器名称
    version: str                     # 解析器版本
    extensions: frozenset[str]       # 支持的文件扩展名集合
    configuration: dict              # 解析器配置

    def parse(self, source: SourceRecord) -> ParsedDocument: ...


# ---------------------------------------------------------------------------
# PlainTextParser —— 纯文本/Markdown 解析器
# 支持 .md 和 .txt 文件，使用换页符作为可选的分页标记。
# 将文本按行分割为 DocumentBlock，保留原始顺序。
# ---------------------------------------------------------------------------
class PlainTextParser:
    """Adapter for Markdown and text files, using form-feed as an optional page break."""

    name = "plain-text"
    version = "1"
    extensions = frozenset({".md", ".txt"})
    configuration = {"encoding": "utf-8", "page_break": "form-feed"}

    def parse(self, source: SourceRecord) -> ParsedDocument:
        path = Path(source.stored_path)
        raw = path.read_text(encoding="utf-8")
        page_texts = raw.split("\f")
        pages = [
            _page_from_text(page_number=index, text=text, markdown=path.suffix.lower() == ".md")
            for index, text in enumerate(page_texts, start=1)
        ]
        return _build_document(
            source=source,
            parser_name=self.name,
            parser_version=self.version,
            parser_config=self.configuration,
            pages=pages,
            metadata={"file_name": source.original_name},
        )


class PdfPlumberParser:
    """PDF adapter that deliberately preserves page numbers even when layout is imperfect."""

    name = "pdfplumber"
    version = "1"
    extensions = frozenset({".pdf"})
    configuration = {"x_tolerance": 2, "y_tolerance": 3}

    def parse(self, source: SourceRecord) -> ParsedDocument:
        pages: list[ParsedPage] = []
        warnings: list[str] = []
        with pdfplumber.open(source.stored_path) as pdf:
            metadata = {
                "file_name": source.original_name,
                "title": (pdf.metadata or {}).get("Title", ""),
                "author": (pdf.metadata or {}).get("Author", ""),
                "page_count": len(pdf.pages),
            }
            for index, page in enumerate(pdf.pages, start=1):
                text = page.extract_text(x_tolerance=2, y_tolerance=3) or ""
                if not text.strip():
                    warnings.append(f"page {index} contains no extractable text")
                    text = f"[No extractable text on page {index}]"
                parsed = _page_from_text(index, text, markdown=False)
                pages.append(
                    parsed.model_copy(
                        update={"width": float(page.width), "height": float(page.height)}
                    )
                )
        document = _build_document(
            source=source,
            parser_name=self.name,
            parser_version=self.version,
            parser_config=self.configuration,
            pages=pages,
            metadata=metadata,
        )
        return document.model_copy(update={"warnings": warnings})


class DocumentParsingService:
    """Deep parsing module: parser selection, deterministic cache, and rebuild live here."""

    def __init__(self, project_root: Path, parsers: list[SourceParser] | None = None):
        self.project_root = Path(project_root).resolve()
        self.cache_root = self.project_root / "data" / "runtime" / "parsing"
        self.parsers = parsers or [PdfPlumberParser(), PlainTextParser()]

    def parse(self, source: SourceRecord, *, force: bool = False) -> ParsedDocument:
        parser = self._parser_for(Path(source.stored_path).suffix.lower())
        cache_path = self._cache_path(source, parser)
        if cache_path.exists() and not force:
            cached = ParsedDocument.model_validate_json(cache_path.read_text(encoding="utf-8"))
            if cached.source_hash == source.content_hash:
                return cached

        document = parser.parse(source)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = cache_path.with_suffix(".json.tmp")
        temporary.write_text(document.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(cache_path)
        return document

    def _parser_for(self, extension: str) -> SourceParser:
        for parser in self.parsers:
            if extension in parser.extensions:
                return parser
        raise UnsupportedSourceError(f"unsupported source extension: {extension}")

    def _cache_path(self, source: SourceRecord, parser: SourceParser) -> Path:
        configuration = json.dumps(parser.configuration, sort_keys=True, ensure_ascii=False)
        material = f"{source.content_hash}\0{parser.name}\0{parser.version}\0{configuration}"
        key = hashlib.sha256(material.encode("utf-8")).hexdigest()[:20]
        return self.cache_root / source.source_id / f"{key}.json"


def _page_from_text(page_number: int, text: str, *, markdown: bool) -> ParsedPage:
    """Convert one page to source-ordered blocks while retaining the active heading."""

    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    segments = [segment.strip() for segment in re.split(r"\n\s*\n", normalized) if segment.strip()]
    if not segments and normalized:
        segments = [normalized]

    blocks: list[DocumentBlock] = []
    section = ""
    for order, segment in enumerate(segments):
        block_type = _block_type(segment, markdown=markdown)
        clean = re.sub(r"^#{1,6}\s+", "", segment).strip() if markdown else segment
        if block_type == DocumentBlockType.HEADING:
            section = clean
        digest = hashlib.sha256(clean.encode("utf-8")).hexdigest()[:10]
        blocks.append(
            DocumentBlock(
                block_id=f"block_{page_number:04d}_{order:04d}_{digest}",
                page_number=page_number,
                order=order,
                text=clean,
                block_type=block_type,
                section=section,
            )
        )
    if not blocks:
        blocks.append(
            DocumentBlock(
                block_id=f"block_{page_number:04d}_0000_empty",
                page_number=page_number,
                order=0,
                text=f"[Empty page {page_number}]",
                block_type=DocumentBlockType.OTHER,
            )
        )
    return ParsedPage(page_number=page_number, blocks=blocks)


def _block_type(text: str, *, markdown: bool) -> DocumentBlockType:
    first_line = text.splitlines()[0].strip()
    if markdown and re.match(r"^#{1,6}\s+", first_line):
        return DocumentBlockType.HEADING
    if first_line.startswith("|") and "|" in first_line[1:]:
        return DocumentBlockType.TABLE
    if first_line.startswith(("- ", "* ")):
        return DocumentBlockType.LIST
    if len(first_line) <= 100 and first_line.isupper() and len(first_line.split()) <= 12:
        return DocumentBlockType.HEADING
    return DocumentBlockType.PARAGRAPH


def _build_document(
    *,
    source: SourceRecord,
    parser_name: str,
    parser_version: str,
    parser_config: dict,
    pages: list[ParsedPage],
    metadata: dict,
) -> ParsedDocument:
    canonical = json.dumps(
        [page.model_dump(mode="json") for page in pages],
        sort_keys=True,
        ensure_ascii=False,
    )
    parse_hash = f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"
    return ParsedDocument(
        source_id=source.source_id,
        source_hash=source.content_hash,
        parser_name=parser_name,
        parser_version=parser_version,
        parser_config=parser_config,
        parse_hash=parse_hash,
        pages=pages,
        metadata=metadata,
    )
