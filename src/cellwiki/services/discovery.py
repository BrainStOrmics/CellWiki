# =============================================================================
# 发现服务 —— 基于 CellWiki 真实信源的可重建 SQLite FTS5 和图投影
# =============================================================================

# ---------------------------------------------------------------------------
# DiscoveryIndex —— 发现索引服务
# 基于 CellWiki 真实信源的可重建 SQLite FTS5 全文搜索和知识图谱投影。
# 维护两个主要索引：
# - FTS5 全文搜索索引：用于快速搜索页面和实体
# - 知识图谱投影：用于实体关系查询和可视化
# 索引可以随时重建（rebuild），确保与真实数据源保持一致。
# 支持按类型过滤、焦点实体查询和限制返回数量。
# ---------------------------------------------------------------------------

"""Rebuildable SQLite FTS5 and graph projections over CellWiki truth sources."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator

from cellwiki.api.reader import WikiReader
from cellwiki.domain.discovery import (
    GraphEdge,
    GraphEdgeType,
    GraphNode,
    GraphNodeType,
    KnowledgeGraph,
    SearchDocumentType,
    SearchIndexStatus,
    SearchResult,
)
from cellwiki.services.quality import inspect_projection
from cellwiki.services.sources import SourceRegistry


INDEX_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class _Document:
    document_id: str
    type: SearchDocumentType
    title: str
    content: str
    page_id: str | None = None
    source_id: str | None = None
    locator: str | None = None
    metadata: dict[str, Any] | None = None


class DiscoveryIndex:
    """One deep Interface for full-text and graph discovery.

    The SQLite file contains only derived data. Callers can delete it and invoke
    ``rebuild`` without changing SourceRecords, extraction, curation, or Wiki files.
    """

    def __init__(self, project_root: Path):
        self.project_root = Path(project_root).resolve()
        self.db_path = self.project_root / "data" / "runtime" / "discovery.sqlite"

    def status(self) -> SearchIndexStatus:
        if not self.db_path.exists():
            return SearchIndexStatus(
                schema_version=INDEX_SCHEMA_VERSION,
                content_version="",
                document_count=0,
                node_count=0,
                edge_count=0,
            )
        with self._connect() as connection:
            return self._status(connection)

    def refresh(self, *, force: bool = False) -> SearchIndexStatus:
        """Rebuild only when truth-source fingerprints change."""

        content_version = self._content_version()
        if not force and self.db_path.exists():
            with self._connect() as connection:
                current = self._metadata(connection, "content_version")
                schema = self._metadata(connection, "schema_version")
                if current == content_version and schema == str(INDEX_SCHEMA_VERSION):
                    return self._status(connection)
        return self.rebuild(content_version=content_version)

    def rebuild(self, *, content_version: str | None = None) -> SearchIndexStatus:
        """Atomically replace all derived documents, nodes, and edges."""

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        documents, nodes, edges = self._collect()
        with self._connect() as connection:
            self._create_schema(connection)
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute("DELETE FROM search_documents_fts")
                connection.execute("DELETE FROM search_documents")
                connection.execute("DELETE FROM graph_edges")
                connection.execute("DELETE FROM graph_nodes")
                for document in documents:
                    cursor = connection.execute(
                        """
                        INSERT INTO search_documents(
                            document_id, type, title, content, page_id, source_id, locator, metadata_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            document.document_id,
                            document.type.value,
                            document.title,
                            document.content,
                            document.page_id,
                            document.source_id,
                            document.locator,
                            json.dumps(document.metadata or {}, ensure_ascii=False, sort_keys=True),
                        ),
                    )
                    connection.execute(
                        "INSERT INTO search_documents_fts(rowid, title, content) VALUES (?, ?, ?)",
                        (cursor.lastrowid, document.title, document.content),
                    )
                connection.executemany(
                    """
                    INSERT INTO graph_nodes(node_id, type, label, page_id, source_id, metadata_json)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            node.node_id,
                            node.type.value,
                            node.label,
                            node.page_id,
                            node.source_id,
                            json.dumps(node.metadata, ensure_ascii=False, sort_keys=True),
                        )
                        for node in nodes.values()
                    ],
                )
                connection.executemany(
                    """
                    INSERT INTO graph_edges(
                        edge_id, type, source_node, target_node, claim_id, source_id,
                        confidence, evidence_count, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            edge.edge_id,
                            edge.type.value,
                            edge.source,
                            edge.target,
                            edge.claim_id,
                            edge.source_id,
                            edge.confidence,
                            edge.evidence_count,
                            json.dumps(edge.metadata, ensure_ascii=False, sort_keys=True),
                        )
                        for edge in edges.values()
                    ],
                )
                self._set_metadata(connection, "schema_version", str(INDEX_SCHEMA_VERSION))
                self._set_metadata(
                    connection, "content_version", content_version or self._content_version()
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            return self._status(connection).model_copy(update={"rebuilt": True})

    def search(
        self,
        query: str,
        *,
        types: Iterable[SearchDocumentType] | None = None,
        limit: int = 20,
    ) -> list[SearchResult]:
        self.refresh()
        terms = [term for term in query.strip().split() if term]
        if not terms:
            return []
        fts_query = " AND ".join(f'"{term.replace(chr(34), chr(34) * 2)}"' for term in terms)
        requested = [item.value for item in (types or [])]
        where = "AND d.type IN ({})".format(",".join("?" for _ in requested)) if requested else ""
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT d.*, bm25(search_documents_fts, 5.0, 1.0) AS rank,
                       snippet(search_documents_fts, 1, '<mark>', '</mark>', ' … ', 28) AS snippet
                FROM search_documents_fts
                JOIN search_documents d ON d.id = search_documents_fts.rowid
                WHERE search_documents_fts MATCH ? {where}
                ORDER BY rank, d.title
                LIMIT ?
                """,
                [fts_query, *requested, max(1, min(limit, 100))],
            ).fetchall()
        return [
            SearchResult(
                document_id=row["document_id"],
                type=SearchDocumentType(row["type"]),
                title=row["title"],
                snippet=row["snippet"] or row["content"][:240],
                # FTS5 bm25 returns lower values for better matches; expose a positive score.
                score=round(1.0 / (1.0 + abs(float(row["rank"]))), 6),
                page_id=row["page_id"],
                source_id=row["source_id"],
                locator=row["locator"],
                metadata=json.loads(row["metadata_json"]),
            )
            for row in rows
        ]

    def graph(
        self,
        *,
        focus: str | None = None,
        node_types: Iterable[GraphNodeType] | None = None,
        source_id: str | None = None,
        limit: int = 400,
    ) -> KnowledgeGraph:
        self.refresh()
        requested_types = {item.value for item in (node_types or [])}
        with self._connect() as connection:
            node_rows = connection.execute("SELECT * FROM graph_nodes ORDER BY type, label").fetchall()
            edge_rows = connection.execute("SELECT * FROM graph_edges ORDER BY type, edge_id").fetchall()

        nodes = {row["node_id"]: self._node_from_row(row) for row in node_rows}
        edges = [self._edge_from_row(row) for row in edge_rows]
        if focus:
            # A local subgraph includes the focus node and its one-hop neighbours. This
            # protects the desktop renderer from loading an unbounded global graph.
            incident = [edge for edge in edges if focus in {edge.source, edge.target}]
            visible = {focus}
            for edge in incident:
                visible.update((edge.source, edge.target))
            edges = incident
            nodes = {node_id: node for node_id, node in nodes.items() if node_id in visible}
        if source_id:
            edges = [edge for edge in edges if edge.source_id == source_id]
            visible = {endpoint for edge in edges for endpoint in (edge.source, edge.target)}
            nodes = {node_id: node for node_id, node in nodes.items() if node_id in visible}
        requested_node_ids: set[str] = set()
        if requested_types:
            requested_node_ids = {
                node_id for node_id, node in nodes.items() if node.type.value in requested_types
            }
            # A type filter selects focal nodes, not a disconnected induced graph. Keep
            # incident edges and their adjacent provenance nodes so selecting "cell type"
            # still shows markers, claims and sources that explain each result.
            edges = [
                edge
                for edge in edges
                if edge.source in requested_node_ids or edge.target in requested_node_ids
            ]
            visible = {endpoint for edge in edges for endpoint in (edge.source, edge.target)}
            visible.update(requested_node_ids)
            nodes = {node_id: node for node_id, node in nodes.items() if node_id in visible}

        bounded_edges = edges[: max(1, min(limit, 2000))]
        visible = {endpoint for edge in bounded_edges for endpoint in (edge.source, edge.target)}
        if focus:
            visible.add(focus)
        visible.update(requested_node_ids)
        bounded_nodes = [node for node_id, node in nodes.items() if node_id in visible]
        return KnowledgeGraph(
            nodes=bounded_nodes,
            edges=bounded_edges,
            scope=focus or "global",
            truncated=len(edges) > len(bounded_edges),
        )

    def delete_index(self) -> None:
        """Delete only the disposable projection, never project truth sources."""

        self.db_path.unlink(missing_ok=True)

    def _collect(self) -> tuple[list[_Document], dict[str, GraphNode], dict[str, GraphEdge]]:
        documents: dict[str, _Document] = {}
        nodes: dict[str, GraphNode] = {}
        edges: dict[str, GraphEdge] = {}
        reader = WikiReader(self.project_root)
        registry = SourceRegistry(self.project_root)

        for page in reader.tree():
            detail = reader.read_page(page["page_id"])
            title = str(page.get("title") or page["page_id"])
            documents[f"page:{page['page_id']}"] = _Document(
                document_id=f"page:{page['page_id']}",
                type=SearchDocumentType.PAGE,
                title=title,
                content=detail["markdown"],
                page_id=page["page_id"],
                locator=detail["path"],
                metadata={"frontmatter": detail["frontmatter"]},
            )

        for source in registry.list_sources():
            identity = source.metadata.get("paper_identity", {})
            title = str(identity.get("title") or source.original_name)
            documents[f"source:{source.source_id}"] = _Document(
                document_id=f"source:{source.source_id}",
                type=SearchDocumentType.SOURCE,
                title=title,
                content=" ".join(
                    str(value)
                    for value in (
                        source.original_name,
                        identity.get("doi", ""),
                        identity.get("year", ""),
                        source.parser_name or "",
                    )
                ),
                source_id=source.source_id,
                locator=source.original_name,
                metadata={"status": source.status.value, **source.metadata},
            )
            nodes[f"source:{source.source_id}"] = GraphNode(
                node_id=f"source:{source.source_id}",
                type=GraphNodeType.SOURCE,
                label=title,
                source_id=source.source_id,
            )

        extraction_dir = self.project_root / "data" / "extraction"
        for path in sorted(extraction_dir.glob("*.json")) if extraction_dir.exists() else []:
            try:
                extraction = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            self._collect_extraction(extraction, documents, nodes, edges)

        quality = inspect_projection(self.project_root)
        for finding in quality.get("findings", []):
            finding_id = str(finding.get("finding_id", ""))
            if not finding_id:
                continue
            documents[f"lint:{finding_id}"] = _Document(
                document_id=f"lint:{finding_id}",
                type=SearchDocumentType.LINT,
                title=str(finding.get("category") or "Lint finding"),
                content=str(finding.get("message") or ""),
                page_id=str(finding.get("target_id") or "") or None,
                locator=str(finding.get("locator") or ""),
                metadata=finding,
            )
        return list(documents.values()), nodes, edges

    def _collect_extraction(
        self,
        extraction: dict[str, Any],
        documents: dict[str, _Document],
        nodes: dict[str, GraphNode],
        edges: dict[str, GraphEdge],
    ) -> None:
        paper = extraction.get("paper") or {}
        default_source_id = str(paper.get("paper_id") or "") or None
        for cell in extraction.get("cell_types") or []:
            page_id = str(cell.get("standard_name") or cell.get("name") or "").strip()
            if not page_id:
                continue
            node_id = f"cell_type:{page_id}"
            label = str(cell.get("name") or page_id)
            nodes[node_id] = GraphNode(
                node_id=node_id,
                type=GraphNodeType.CELL_TYPE,
                label=label,
                page_id=page_id,
                source_id=default_source_id,
            )
            documents[f"entity:{page_id}"] = _Document(
                document_id=f"entity:{page_id}",
                type=SearchDocumentType.ENTITY,
                title=label,
                content=json.dumps(cell, ensure_ascii=False),
                page_id=page_id,
                source_id=default_source_id,
                metadata={"entity_type": "cell_type"},
            )

        claims = extraction.get("claims") or []
        for claim in claims:
            claim_id = str(claim.get("claim_id") or "").strip()
            if not claim_id:
                continue
            subject = str(claim.get("subject") or "").strip()
            predicate = str(claim.get("predicate") or "related_to").strip()
            obj = str(claim.get("object") or "").strip()
            evidence = claim.get("evidence") or []
            source_id = str((evidence[0] if evidence else {}).get("source_id") or default_source_id or "") or None
            page_id = subject
            content = f"{subject} {predicate} {obj}"
            documents[f"claim:{claim_id}"] = _Document(
                document_id=f"claim:{claim_id}",
                type=SearchDocumentType.CLAIM,
                title=content,
                content=" ".join([content, json.dumps(claim.get("qualifiers") or {}, ensure_ascii=False)]),
                page_id=page_id or None,
                source_id=source_id,
                locator=claim_id,
                metadata={"confidence": claim.get("confidence", "medium")},
            )
            claim_node_id = f"claim:{claim_id}"
            nodes[claim_node_id] = GraphNode(
                node_id=claim_node_id,
                type=GraphNodeType.CLAIM,
                label=content,
                page_id=page_id or None,
                source_id=source_id,
            )
            subject_node = f"cell_type:{subject}"
            if subject_node not in nodes and subject:
                nodes[subject_node] = GraphNode(
                    node_id=subject_node,
                    type=GraphNodeType.CELL_TYPE,
                    label=subject,
                    page_id=subject,
                )
            relation = self._relation(predicate)
            target_id, target_type = self._target_node(predicate, obj)
            if target_id and target_id not in nodes:
                nodes[target_id] = GraphNode(node_id=target_id, type=target_type, label=obj)
            if subject and target_id:
                edge = GraphEdge(
                    edge_id=self._edge_id(subject_node, relation.value, target_id, claim_id),
                    type=relation,
                    source=subject_node,
                    target=target_id,
                    claim_id=claim_id,
                    source_id=source_id,
                    confidence=str(claim.get("confidence") or "medium"),
                    evidence_count=len(evidence),
                )
                edges[edge.edge_id] = edge
            if source_id:
                source_node = f"source:{source_id}"
                if source_node not in nodes:
                    nodes[source_node] = GraphNode(
                        node_id=source_node,
                        type=GraphNodeType.SOURCE,
                        label=source_id,
                        source_id=source_id,
                    )
                support = GraphEdge(
                    edge_id=self._edge_id(claim_node_id, "supported_by", source_node, claim_id),
                    type=GraphEdgeType.SUPPORTED_BY,
                    source=claim_node_id,
                    target=source_node,
                    claim_id=claim_id,
                    source_id=source_id,
                    confidence=str(claim.get("confidence") or "medium"),
                    evidence_count=len(evidence),
                )
                edges[support.edge_id] = support
            for item in evidence:
                evidence_id = str(item.get("evidence_id") or "").strip()
                if not evidence_id:
                    continue
                locator = str(item.get("locator") or item.get("block_id") or "")
                documents[f"evidence:{evidence_id}"] = _Document(
                    document_id=f"evidence:{evidence_id}",
                    type=SearchDocumentType.EVIDENCE,
                    title=f"Evidence for {content}",
                    content=str(item.get("excerpt") or ""),
                    page_id=page_id or None,
                    source_id=str(item.get("source_id") or source_id or "") or None,
                    locator=locator,
                    metadata={
                        "page_start": item.get("page_start"),
                        "page_end": item.get("page_end"),
                        "section": item.get("section", ""),
                        "claim_id": claim_id,
                    },
                )

    def _content_version(self) -> str:
        digest = hashlib.sha256()
        roots = [
            self.project_root / "wiki",
            self.project_root / "data" / "extraction",
            self.project_root / "data" / "runtime" / "sources",
        ]
        for root in roots:
            if not root.exists():
                continue
            for path in sorted(item for item in root.rglob("*") if item.is_file()):
                relative = path.relative_to(self.project_root).as_posix()
                stat = path.stat()
                digest.update(f"{relative}\0{stat.st_size}\0{stat.st_mtime_ns}\0".encode())
        return f"sha256:{digest.hexdigest()}"

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path, timeout=30)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA foreign_keys=ON")
            self._create_schema(connection)
            yield connection
        finally:
            # sqlite3's own context manager commits or rolls back but does not close;
            # explicit closure is required before Windows can replace/delete an index.
            connection.close()

    @staticmethod
    def _create_schema(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS index_metadata(
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS search_documents(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id TEXT NOT NULL UNIQUE,
                type TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                page_id TEXT,
                source_id TEXT,
                locator TEXT,
                metadata_json TEXT NOT NULL
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS search_documents_fts USING fts5(
                title, content, tokenize='unicode61 remove_diacritics 2'
            );
            CREATE TABLE IF NOT EXISTS graph_nodes(
                node_id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                label TEXT NOT NULL,
                page_id TEXT,
                source_id TEXT,
                metadata_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS graph_edges(
                edge_id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                source_node TEXT NOT NULL,
                target_node TEXT NOT NULL,
                claim_id TEXT,
                source_id TEXT,
                confidence TEXT NOT NULL,
                evidence_count INTEGER NOT NULL,
                metadata_json TEXT NOT NULL,
                FOREIGN KEY(source_node) REFERENCES graph_nodes(node_id),
                FOREIGN KEY(target_node) REFERENCES graph_nodes(node_id)
            );
            CREATE INDEX IF NOT EXISTS idx_graph_edge_source ON graph_edges(source_node);
            CREATE INDEX IF NOT EXISTS idx_graph_edge_target ON graph_edges(target_node);
            CREATE INDEX IF NOT EXISTS idx_search_document_type ON search_documents(type);
            """
        )

    def _status(self, connection: sqlite3.Connection) -> SearchIndexStatus:
        def count(table: str) -> int:
            return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

        return SearchIndexStatus(
            schema_version=int(self._metadata(connection, "schema_version") or INDEX_SCHEMA_VERSION),
            content_version=self._metadata(connection, "content_version") or "",
            document_count=count("search_documents"),
            node_count=count("graph_nodes"),
            edge_count=count("graph_edges"),
        )

    @staticmethod
    def _metadata(connection: sqlite3.Connection, key: str) -> str | None:
        row = connection.execute("SELECT value FROM index_metadata WHERE key = ?", (key,)).fetchone()
        return str(row[0]) if row else None

    @staticmethod
    def _set_metadata(connection: sqlite3.Connection, key: str, value: str) -> None:
        connection.execute(
            "INSERT INTO index_metadata(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    @staticmethod
    def _relation(predicate: str) -> GraphEdgeType:
        return {
            "expresses": GraphEdgeType.EXPRESSES,
            "does_not_express": GraphEdgeType.DOES_NOT_EXPRESS,
            "located_in": GraphEdgeType.LOCATED_IN,
        }.get(predicate, GraphEdgeType.RELATED_TO)

    @staticmethod
    def _target_node(predicate: str, value: str) -> tuple[str | None, GraphNodeType]:
        if not value:
            return None, GraphNodeType.CLAIM
        if predicate in {"expresses", "does_not_express"}:
            return f"marker:{value}", GraphNodeType.MARKER
        if predicate == "located_in":
            return f"tissue:{value}", GraphNodeType.TISSUE
        if predicate in {"species", "observed_in_species"}:
            return f"species:{value}", GraphNodeType.SPECIES
        return f"claim_value:{hashlib.sha256(value.encode()).hexdigest()[:16]}", GraphNodeType.CLAIM

    @staticmethod
    def _edge_id(source: str, relation: str, target: str, claim_id: str) -> str:
        material = f"{source}\0{relation}\0{target}\0{claim_id}"
        return f"edge_{hashlib.sha256(material.encode()).hexdigest()[:20]}"

    @staticmethod
    def _node_from_row(row: sqlite3.Row) -> GraphNode:
        return GraphNode(
            node_id=row["node_id"],
            type=GraphNodeType(row["type"]),
            label=row["label"],
            page_id=row["page_id"],
            source_id=row["source_id"],
            metadata=json.loads(row["metadata_json"]),
        )

    @staticmethod
    def _edge_from_row(row: sqlite3.Row) -> GraphEdge:
        return GraphEdge(
            edge_id=row["edge_id"],
            type=GraphEdgeType(row["type"]),
            source=row["source_node"],
            target=row["target_node"],
            claim_id=row["claim_id"],
            source_id=row["source_id"],
            confidence=row["confidence"],
            evidence_count=row["evidence_count"],
            metadata=json.loads(row["metadata_json"]),
        )
