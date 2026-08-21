# =============================================================================
# 来源注册服务 —— 本地 CellWiki 项目的内容寻址来源注册
# =============================================================================

"""Content-addressed source registration for local CellWiki projects."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path

from filelock import FileLock

from cellwiki.domain.contracts import SourceRecord, SourceStatus, TaskStatus


# ---------------------------------------------------------------------------
# SourceDeleteBlockedError —— 来源删除被阻止异常
# 当派生提案或活跃运行仍依赖该来源时抛出
# ---------------------------------------------------------------------------
class SourceDeleteBlockedError(RuntimeError):
    """Raised when a source cannot be deleted while derived proposals or live runs depend on it."""

    def __init__(self, detail: str, blocking_change_set_ids: list[str], active_run_ids: list[str]):
        super().__init__(detail)
        self.detail = detail
        self.blocking_change_set_ids = blocking_change_set_ids
        self.active_run_ids = active_run_ids


# ---------------------------------------------------------------------------
# SourceRegistry —— 来源注册服务
# 本地 CellWiki 项目的内容寻址来源注册。
# 每个来源通过 SHA256 哈希生成唯一 ID，实现内容寻址和去重。
# 注册时将源文件复制到受管的数据目录，确保原始文件不会被意外修改。
# 存储结构：
#   - data/sources/<source_id>/<original_name> — 受管副本
#   - data/runtime/sources/<source_id>.json — 注册记录
# ---------------------------------------------------------------------------
class SourceRegistry:
    def __init__(self, project_root: Path):
        self.project_root = Path(project_root)
        self.sources_dir = self.project_root / "data" / "sources"           # 源文件存储目录
        self.records_dir = self.project_root / "data" / "runtime" / "sources"  # 注册记录目录

    # 注册一个来源文件，返回 SourceRecord
    def register(
        self,
        source_path: Path,
        source_type: str,
        original_name: str | None = None,
    ) -> SourceRecord:
        source_path = Path(source_path).resolve()
        if not source_path.is_file():
            raise FileNotFoundError(source_path)

        # 计算文件哈希，用于内容寻址和去重
        digest = self._sha256(source_path)
        source_id = f"src_{digest[:20]}"
        record_path = self.records_dir / f"{source_id}.json"
        # 如果已注册，直接返回现有记录
        if record_path.exists():
            return SourceRecord.model_validate_json(record_path.read_text(encoding="utf-8"))

        # 安全地复制文件到受管目录
        safe_name = Path(original_name or source_path.name).name
        destination = self.sources_dir / source_id / safe_name
        destination.parent.mkdir(parents=True, exist_ok=True)
        self.records_dir.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        shutil.copy2(source_path, temporary)
        temporary.replace(destination)

        record = SourceRecord(
            source_id=source_id,
            source_type=source_type,
            original_name=safe_name,
            stored_path=str(destination.resolve()),
            content_hash=f"sha256:{digest}",
        )
        temporary_record = record_path.with_suffix(".json.tmp")
        temporary_record.write_text(record.model_dump_json(indent=2), encoding="utf-8")
        temporary_record.replace(record_path)
        return record

    # 硬删除一个已注册来源及其派生缓存：先落 tombstone，再级联删除
    def delete(self, source_id: str) -> None:
        """Hard-delete a registered source and its derived caches after a tombstone.

        Deletion is blocked while any ChangeSet references the source (delete the
        proposals first) or while a live ingest run is still using it, so evidence
        resolution and in-flight tasks never dangle.
        """
        if not re.fullmatch(r"src_[a-f0-9]{20}", source_id):
            raise KeyError(source_id)
        record_path = self.records_dir / f"{source_id}.json"
        if not record_path.exists():
            raise KeyError(source_id)

        lock_path = self.records_dir / ".sources.delete.lock"
        with FileLock(str(lock_path)):
            if not record_path.exists():
                raise KeyError(source_id)
            referencing = self._referencing_change_sets(source_id)
            if referencing:
                raise SourceDeleteBlockedError(
                    detail="Delete the ChangeSets referencing this source first.",
                    blocking_change_set_ids=[
                        change_set.change_set_id for change_set in referencing
                    ],
                    active_run_ids=[],
                )
            active_run_ids = self._active_run_ids(source_id)
            if active_run_ids:
                raise SourceDeleteBlockedError(
                    detail="A live ingest run is still using this source.",
                    blocking_change_set_ids=[],
                    active_run_ids=active_run_ids,
                )
            self._write_tombstone(
                {
                    "source_id": source_id,
                    "deleted_at": datetime.now(UTC).isoformat(),
                }
            )
            # 级联删除：受管源文件目录 + 注册记录 + 解析/提取缓存
            source_dir = self.sources_dir / source_id
            if source_dir.exists():
                shutil.rmtree(source_dir)
            record_path.unlink(missing_ok=True)
            for cache_name in ("parsing", "extraction_cache"):
                cache_dir = self.project_root / "data" / "runtime" / cache_name / source_id
                if cache_dir.exists():
                    shutil.rmtree(cache_dir)

    # 找出仍引用该来源的 ChangeSet（任何状态都阻止删除）
    def _referencing_change_sets(self, source_id: str):
        from cellwiki.services.changesets import ChangeSetRepository

        return ChangeSetRepository(self.project_root).list(target_id=source_id)

    # 找出仍在使用该来源的活跃 ingest 运行。
    # 只把真正在跑（RUNNING/COMMITTING）的运行视为活跃；账本停在
    # AWAITING_REVIEW 只代表提案曾等待审核，不代表运行还活着——已结束的
    # 历史运行不应永久阻止来源删除（提案本身由 _referencing_change_sets 兜底）。
    def _active_run_ids(self, source_id: str) -> list[str]:
        from cellwiki.services.tasks import TaskEventRepository

        active = {
            TaskStatus.RUNNING.value,
            TaskStatus.COMMITTING.value,
        }
        return [
            run["run_id"]
            for run in TaskEventRepository(self.project_root).list_runs(source_id=source_id)
            if run["status"] in active
        ]

    # 先落审计 tombstone，再物理删除，文件名带时间戳避免内容寻址复用冲突
    def _write_tombstone(self, payload: dict) -> None:
        deleted_dir = self.project_root / "data" / "runtime" / "deleted"
        deleted_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
        path = deleted_dir / f"{payload['source_id']}.deleted.{timestamp}.json"
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(path)

    def get(self, source_id: str) -> SourceRecord:
        if not re.fullmatch(r"src_[a-f0-9]{20}", source_id):
            raise KeyError(source_id)
        path = self.records_dir / f"{source_id}.json"
        if not path.exists():
            raise KeyError(source_id)
        return SourceRecord.model_validate_json(path.read_text(encoding="utf-8"))

    def list_sources(self) -> list[SourceRecord]:
        if not self.records_dir.exists():
            return []
        return [
            SourceRecord.model_validate_json(path.read_text(encoding="utf-8"))
            for path in sorted(self.records_dir.glob("src_*.json"))
        ]

    def update_status(self, source_id: str, status: SourceStatus) -> SourceRecord:
        """Update runtime metadata without changing the content-addressed source file."""
        record = self.get(source_id)
        updated = record.model_copy(
            update={
                "status": status,
                "error_reason": None
                if status != SourceStatus.FAILED
                else record.error_reason,
            }
        )
        return self._write_record(updated)

    def update_parse_metadata(
        self,
        source_id: str,
        *,
        parser_name: str,
        parser_version: str,
        parse_hash: str,
        text_hash: str,
        metadata: dict | None = None,
    ) -> SourceRecord:
        """Record rebuild metadata while preserving the content-addressed source identity."""

        record = self.get(source_id)
        updated = record.model_copy(
            update={
                "parser_name": parser_name,
                "parser_version": parser_version,
                "parse_hash": parse_hash,
                "text_hash": text_hash,
                "metadata": {**record.metadata, **(metadata or {})},
                "error_reason": None,
            }
        )
        return self._write_record(updated)

    def mark_failed(self, source_id: str, reason: str) -> SourceRecord:
        """Persist a bounded failure reason so the desktop can distinguish retryable sources."""

        record = self.get(source_id)
        return self._write_record(
            record.model_copy(
                update={"status": SourceStatus.FAILED, "error_reason": reason[:1000]}
            )
        )

    def update_metadata(self, source_id: str, metadata: dict) -> SourceRecord:
        """Merge derived paper identity without changing content-addressed source identity."""

        record = self.get(source_id)
        return self._write_record(
            record.model_copy(update={"metadata": {**record.metadata, **metadata}})
        )

    def find_paper_candidates(
        self,
        source_id: str,
        *,
        doi: str = "",
        title: str = "",
        year: int = 0,
    ) -> list[tuple[str, str]]:
        """Find likely alternate files of one paper while preserving both source IDs."""

        normalized_doi = doi.strip().lower().removeprefix("https://doi.org/")
        normalized_title = _normalize_title(title)
        matches: list[tuple[str, str]] = []
        for candidate in self.list_sources():
            if candidate.source_id == source_id:
                continue
            identity = candidate.metadata.get("paper_identity", {})
            candidate_doi = str(identity.get("doi", "")).strip().lower().removeprefix("https://doi.org/")
            candidate_title = _normalize_title(str(identity.get("title", "")))
            candidate_year = int(identity.get("year", 0) or 0)
            if normalized_doi and candidate_doi == normalized_doi:
                matches.append((candidate.source_id, "matching DOI"))
            elif (
                normalized_title
                and candidate_title == normalized_title
                and (not year or not candidate_year or year == candidate_year)
            ):
                matches.append((candidate.source_id, "matching normalized title and year"))
        return matches

    def _write_record(self, record: SourceRecord) -> SourceRecord:
        path = self.records_dir / f"{record.source_id}.json"
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(record.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(path)
        return record

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()


def _normalize_title(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
