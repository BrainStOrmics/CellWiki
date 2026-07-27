# =============================================================================
# 桌面运行时测试 —— 验证应用数据、迁移、备份和编辑功能
# =============================================================================

"""Release-runtime tests for application data, migration, backup, and redaction."""

from __future__ import annotations

import logging
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage

from cellwiki.services.desktop import (
    ApplicationPaths,
    RedactingFormatter,
    backup_before_upgrade,
)
from cellwiki.services.migrations import upgrade_runtime_database
from cellwiki.services.environment import EnvironmentSettingsService


def test_application_layout_and_upgrade_backup_preserve_project_data(tmp_path: Path):
    paths = ApplicationPaths.create(tmp_path / "CellWikiData")
    database = paths.project_root / "data" / "runtime" / "cellwiki.db"
    database.write_bytes(b"database-v1")
    config = paths.project_root / ".env"
    config.write_text("OPENAI_API_KEY=secret\n", encoding="utf-8")

    assert backup_before_upgrade(paths, version="1.0.0") is None
    backup = backup_before_upgrade(paths, version="2.0.0")

    assert backup is not None and backup.is_file()
    assert database.read_bytes() == b"database-v1"
    assert config.read_text(encoding="utf-8") == "OPENAI_API_KEY=secret\n"
    assert all(
        directory.is_dir()
        for directory in (
            paths.project_root,
            paths.runtime_dir,
            paths.logs_dir,
            paths.cache_dir,
            paths.backups_dir,
            paths.config_dir,
        )
    )


def test_redacting_formatter_removes_tokens_keys_and_authorization():
    formatter = RedactingFormatter("%(message)s", secrets=["launch-secret", "provider-key"])
    record = logging.LogRecord(
        name="cellwiki",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="Authorization: Bearer launch-secret api_key=provider-key",
        args=(),
        exc_info=None,
    )

    rendered = formatter.format(record)

    assert "launch-secret" not in rendered
    assert "provider-key" not in rendered
    assert rendered.count("[REDACTED]") >= 2


def test_alembic_migrates_fresh_and_stamps_phase3_database(tmp_path: Path):
    fresh = tmp_path / "fresh.db"
    upgrade_runtime_database(fresh)
    with sqlite3.connect(fresh) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        version = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    assert {"agent_runs", "agent_events", "alembic_version"} <= tables
    assert version == "0001_agent_runtime"

    legacy = tmp_path / "legacy.db"
    with sqlite3.connect(legacy) as connection:
        connection.executescript(
            """
            CREATE TABLE agent_runs(run_id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE agent_events(run_id TEXT NOT NULL, sequence INTEGER NOT NULL, event_id TEXT NOT NULL UNIQUE, payload TEXT NOT NULL, PRIMARY KEY(run_id, sequence));
            INSERT INTO agent_runs VALUES ('run_existing', 'thread_existing', 'succeeded', '{}', 'now');
            """
        )
    upgrade_runtime_database(legacy)
    with sqlite3.connect(legacy) as connection:
        assert connection.execute("SELECT run_id FROM agent_runs").fetchone()[0] == "run_existing"
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0001_agent_runtime"


def test_packaged_settings_prefer_system_credential_store(tmp_path: Path):
    class FakeCredentialStore:
        value: str | None = None

        def get(self):
            return self.value

        def set(self, value: str):
            self.value = value
            return True

        def delete(self):
            self.value = None
            return True

    vault = FakeCredentialStore()
    settings = EnvironmentSettingsService(
        tmp_path, secret_store=vault, prefer_system_store=True
    )

    settings.update(
        openai_base_url="https://provider.example/v1",
        openai_model="model-1",
        openai_api_key="vault-secret",
        clear_openai_api_key=False,
        log_level="INFO",
        app_language="zh-CN",
    )

    assert vault.value == "vault-secret"
    assert "vault-secret" not in (tmp_path / ".env").read_text(encoding="utf-8")
    assert settings.public_settings()["secret_storage"] == "system"


def test_provider_test_uses_selected_protocol_and_closes_temporary_client(tmp_path: Path):
    (tmp_path / ".env").write_text("OPENAI_API_KEY=test-secret\n", encoding="utf-8")
    model = MagicMock()
    model.invoke.return_value = AIMessage(content='{"status":"CELLWIKI_OK"}')
    service = EnvironmentSettingsService(tmp_path)

    with patch(
        "cellwiki.adapters.openai_model.build_openai_chat_model",
        return_value=model,
    ) as build_model:
        result = service.test_connection(
            openai_base_url="https://provider.example/v1",
            openai_model="provider-model",
            openai_api_key=None,
            openai_api_protocol="responses",
        )

    assert result["protocol"] == "responses"
    assert result["structured_output"] is True
    assert build_model.call_args.kwargs["purpose"] == "structured"
    model.root_client.close.assert_called_once_with()


def test_packaged_sidecar_loads_project_environment_before_global_settings(tmp_path: Path):
    """The settings UI project must win over a stale launcher working directory."""

    launcher = tmp_path / "launcher"
    project = tmp_path / "desktop-project"
    launcher.mkdir()
    project.mkdir()
    (launcher / ".env").write_text(
        "OPENAI_BASE_URL=https://stale.example/v1\nOPENAI_MODEL=stale-model\n",
        encoding="utf-8",
    )
    (project / ".env").write_text(
        "OPENAI_BASE_URL=https://project.example/v1\nOPENAI_MODEL=project-model\n",
        encoding="utf-8",
    )
    script = f"""
import json
from pathlib import Path
from cellwiki.sidecar import _configure_project_environment

_configure_project_environment(Path({str(project)!r}), prefer_system_store=False)
from cellwiki.config import settings
print(json.dumps({{
    'base_url': settings.openai_base_url,
    'model': settings.openai_model,
}}))
"""
    environment = os.environ.copy()
    environment.pop("OPENAI_BASE_URL", None)
    environment.pop("OPENAI_MODEL", None)
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=launcher,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=True,
    )

    assert json.loads(result.stdout) == {
        "base_url": "https://project.example/v1",
        "model": "project-model",
    }


def test_configure_desktop_logging_respects_level_parameter(tmp_path: Path):
    """Verify that configure_desktop_logging uses the provided level parameter."""
    import logging
    from cellwiki.services.desktop import ApplicationPaths, configure_desktop_logging
    
    paths = ApplicationPaths.create(tmp_path / "CellWikiData")
    
    # Test with DEBUG level
    log_path = configure_desktop_logging(paths, secrets=["test-secret"], level="DEBUG")
    root_logger = logging.getLogger()
    assert root_logger.level == logging.DEBUG
    assert log_path.exists()
    
    # Test with WARNING level
    configure_desktop_logging(paths, secrets=["test-secret"], level="WARNING")
    assert root_logger.level == logging.WARNING
    
    # Test with invalid level (should fall back to INFO)
    configure_desktop_logging(paths, secrets=["test-secret"], level="INVALID")
    assert root_logger.level == logging.INFO
