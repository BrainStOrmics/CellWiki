# =============================================================================
# 桌面服务 —— 打包桌面应用的路径、备份、恢复和密钥感知日志
# =============================================================================

"""Packaged-desktop paths, backups, recovery, and secret-aware logging."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import os
import re
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path


# ---------------------------------------------------------------------------
# ApplicationPaths —— 桌面应用路径配置
# 定义打包桌面应用的所有标准目录：数据根目录、项目目录、运行时目录、
# 日志目录、缓存目录、备份目录和配置目录。
# 所有目录在创建时自动创建（mkdir parents=True）。
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ApplicationPaths:
    data_root: Path      # 数据根目录（用户数据存储位置）
    project_root: Path   # 项目根目录（包含 wiki、data 等）
    runtime_dir: Path    # 运行时目录（检查点、运行时状态）
    logs_dir: Path       # 日志目录
    cache_dir: Path      # 缓存目录
    backups_dir: Path    # 备份目录
    config_dir: Path     # 配置目录

    @classmethod
    def create(cls, data_root: Path, *, project_id: str = "default") -> "ApplicationPaths":
        root = Path(data_root).expanduser().resolve()
        paths = cls(
            data_root=root,
            project_root=root / "projects" / project_id,
            runtime_dir=root / "runtime",
            logs_dir=root / "logs",
            cache_dir=root / "cache",
            backups_dir=root / "backups",
            config_dir=root / "config",
        )
        # 自动创建所有目录
        for directory in (
            paths.project_root,
            paths.runtime_dir,
            paths.logs_dir,
            paths.cache_dir,
            paths.backups_dir,
            paths.config_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        # 运行时存储库使用项目相对路径，保持运行时数据库
        # in the requested top-level layout through an explicit directory junction
        # only when a release root is initialized; a normal directory remains portable.
        (paths.project_root / "data" / "runtime").mkdir(parents=True, exist_ok=True)
        return paths


class RedactingFormatter(logging.Formatter):
    """Remove authorization and provider secrets from messages and tracebacks."""

    def __init__(self, fmt: str, *, secrets: list[str] | None = None):
        super().__init__(fmt)
        self.secrets = [secret for secret in (secrets or []) if secret]

    def format(self, record: logging.LogRecord) -> str:
        return self._redact(super().format(record))

    def _redact(self, value: str) -> str:
        result = value
        for secret in self.secrets:
            result = result.replace(secret, "[REDACTED]")
        result = re.sub(
            r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;]+",
            r"\1[REDACTED]",
            result,
        )
        result = re.sub(
            r"(?i)(api[_-]?key\s*[:=]\s*)['\"]?[^\s,'\"]+",
            r"\1[REDACTED]",
            result,
        )
        return result


def configure_desktop_logging(paths: ApplicationPaths, *, secrets: list[str], level: str = "INFO") -> Path:
    """Write one bounded daily log file with configurable level and secret redaction."""

    log_path = paths.logs_dir / "cellwiki-sidecar.log"
    formatter = RedactingFormatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s", secrets=secrets
    )
    file_handler = RotatingFileHandler(
        log_path, maxBytes=5 * 1024 * 1024, backupCount=4, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.handlers.clear()
    root.addHandler(file_handler)
    return log_path


def recover_stale_runtime_files(paths: ApplicationPaths, *, minimum_age_minutes: int = 10) -> list[str]:
    """Remove abandoned temporary files only from runtime/cache, never truth sources."""

    cutoff = datetime.now(UTC) - timedelta(minutes=minimum_age_minutes)
    removed: list[str] = []
    for root in (paths.runtime_dir, paths.cache_dir, paths.project_root / "data" / "runtime"):
        if not root.exists():
            continue
        for path in root.rglob("*.tmp"):
            modified = datetime.fromtimestamp(path.stat().st_mtime, UTC)
            if modified <= cutoff:
                path.unlink(missing_ok=True)
                removed.append(str(path))
    return removed


def backup_before_upgrade(paths: ApplicationPaths, *, version: str) -> Path | None:
    """Back up configuration and SQLite state once before a new application version."""

    marker = paths.config_dir / "last_version"
    previous = marker.read_text(encoding="utf-8").strip() if marker.exists() else ""
    if not previous or previous == version:
        marker.write_text(version + "\n", encoding="utf-8")
        return None
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup = paths.backups_dir / f"upgrade-{previous}-to-{version}-{stamp}.zip"
    candidates = [
        paths.project_root / ".env",
        paths.project_root / "data" / "runtime" / "cellwiki.db",
        paths.project_root / "data" / "runtime" / "memory.sqlite",
        paths.config_dir,
    ]
    with zipfile.ZipFile(backup, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for candidate in candidates:
            if candidate.is_file():
                archive.write(candidate, candidate.relative_to(paths.data_root))
            elif candidate.is_dir():
                for path in candidate.rglob("*"):
                    if path.is_file() and path != backup:
                        archive.write(path, path.relative_to(paths.data_root))
    marker.write_text(version + "\n", encoding="utf-8")
    return backup


def default_data_root() -> Path:
    configured = os.getenv("CELLWIKI_DATA_DIR")
    if configured:
        return Path(configured)
    local = os.getenv("LOCALAPPDATA") or os.getenv("APPDATA")
    if local:
        return Path(local) / "CellWikiData"
    return Path.home() / ".cellwiki"
