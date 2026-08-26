# =============================================================================
# Wiki 读取器 —— 产品 API 和查询智能体使用的只读投影查询
# =============================================================================
# WikiReader 提供对已发布 Wiki 页面的只读访问，包括页面读取、目录树
# 获取和全文搜索功能。所有操作均基于文件系统上的 Markdown 文件，
# 不涉及任何数据库或网络调用。
# =============================================================================

"""Read-only projection queries used by the Product API and Query Agent."""

from __future__ import annotations

import re
from pathlib import Path

import yaml


# 页面 ID 格式验证：字母数字开头，允许下划线和连字符，最长 128 字符
_PAGE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")

# ---------------------------------------------------------------------------
# WikiReader —— Wiki 页面读取器
# 提供对已发布 Wiki 页面的只读访问，包括页面读取、目录树和全文搜索。
# 所有操作基于文件系统上的 Markdown 文件，不涉及数据库或网络调用。
# 页面 ID 使用正则验证，防止路径遍历攻击。
# 搜索使用简单的子串匹配，返回匹配页面和摘要片段。
# ---------------------------------------------------------------------------
class WikiReader:
    def __init__(self, project_root: Path):
        self.project_root = Path(project_root).resolve()
        # Wiki 页面分布在 wiki/ 下的任意子目录（cell_types/、diseases/、marker_genes/ 等）
        self.wiki_dir = self.project_root / "wiki"

    # 返回 wiki/ 下全部 Markdown 页面的稳定排序路径（递归扫描子目录）
    def _iter_pages(self) -> list[Path]:
        if not self.wiki_dir.is_dir():
            return []
        return sorted(self.wiki_dir.rglob("*.md"))

    # 读取单个页面，返回前端元数据和 Markdown 内容
    def read_page(self, page_id: str) -> dict:
        path = self._page_path(page_id)
        if not path.exists():
            raise FileNotFoundError(page_id)
        raw = path.read_text(encoding="utf-8")
        frontmatter, markdown = self._split_frontmatter(raw)
        return {
            "page_id": page_id,
            "path": path.relative_to(self.project_root).as_posix(),
            "frontmatter": frontmatter,
            "markdown": markdown,
        }

    # 返回页面目录树（页面 ID、标题、路径）；page_id 同名时按稳定排序保留第一个
    def tree(self) -> list[dict]:
        result = []
        seen: set[str] = set()
        for path in self._iter_pages():
            page_id = path.stem
            if page_id in seen:
                continue
            seen.add(page_id)
            page = self.read_page(page_id)
            result.append(
                {
                    "page_id": page_id,
                    "title": page["frontmatter"].get("display_name") or page_id,
                    "path": page["path"],
                }
            )
        return result

    # 全文搜索：在页面内容中查找查询字符串
    # 返回匹配页面列表，按匹配次数排序，包含上下文摘要
    def search(self, query: str, limit: int = 20) -> list[dict]:
        query = query.strip().lower()
        if not query:
            return []
        matches: list[dict[str, str | int]] = []
        for path in self._iter_pages():
            raw = path.read_text(encoding="utf-8")
            haystack = raw.lower()
            if query not in haystack:
                continue
            # 提取匹配位置周围的上下文作为摘要
            index = haystack.index(query)
            start = max(0, index - 120)       # 前 120 字符
            end = min(len(raw), index + len(query) + 180)  # 后 180 字符
            matches.append(
                {
                    "page_id": path.stem,
                    "score": haystack.count(query),   # 匹配次数作为分数
                    "snippet": raw[start:end].replace("\n", " ").strip(),
                }
            )
        # 按分数降序排列，取前 limit 个
        return sorted(
            matches,
            key=lambda item: (-int(item["score"]), str(item["page_id"])),
        )[:limit]

    # 验证页面 ID 并返回安全的文件路径
    # 防止路径遍历攻击：验证 ID 格式并检查路径是否在 wiki/ 下
    def _page_path(self, page_id: str) -> Path:
        if not _PAGE_ID.fullmatch(page_id):
            raise FileNotFoundError(page_id)
        for path in self._iter_pages():
            if path.stem != page_id:
                continue
            resolved = path.resolve()
            # 安全检查：确保解析后的路径仍在 wiki/ 下
            if self.wiki_dir.resolve() not in resolved.parents:
                continue
            return resolved
        raise FileNotFoundError(page_id)

    # 解析 YAML 前端元数据
    @staticmethod
    def _split_frontmatter(raw: str) -> tuple[dict, str]:
        if not raw.startswith("---"):
            return {}, raw
        parts = raw.split("---", 2)
        if len(parts) != 3:
            return {}, raw
        return yaml.safe_load(parts[1]) or {}, parts[2].lstrip("\r\n")
