# =============================================================================
# 侧车入口 —— 打包为 Tauri 侧车的独立 Product API 入口点
# =============================================================================
# 侧车模式让桌面应用在环回端口上启动私有 Python HTTP 服务器，
# 通过共享密钥 token 进行通信。这使 Python 运行时与 Tauri 进程隔离，
# 避免了在 Electron 风格 shell 中嵌入完整 Python 解释器。
# =============================================================================

"""Standalone Product API entrypoint packaged as the Tauri sidecar.

The sidecar pattern lets the desktop app launch a private Python HTTP server
on a loopback port, communicating via a shared secret token. This isolates the
Python runtime from the Tauri process and avoids embedding a full Python
interpreter in the Electron-style shell.
"""

from __future__ import annotations

import os
from pathlib import Path

import uvicorn

from cellwiki.services.desktop import (
    ApplicationPaths,
    backup_before_upgrade,
    configure_desktop_logging,
    default_data_root,
    recover_stale_runtime_files,
)
from cellwiki.services.environment import EnvironmentSettingsService
from cellwiki.services.migrations import upgrade_runtime_database


def application_version() -> str:
    """Return installed package version, falling back to a VERSION file for bundled installs."""
    try:
        from importlib.metadata import version

        return version("cellwiki")
    except Exception:
        # Fallback for bundled installs that lack proper package metadata.
        version_file = Path(__file__).resolve().parents[2] / "VERSION"
        return version_file.read_text(encoding="utf-8").strip() if version_file.exists() else "0.0.0"


def _configure_project_environment(
    project_root: Path,
    *,
    prefer_system_store: bool = True,
) -> None:
    """Make desktop settings authoritative before importing global Agent config.

    Pydantic otherwise resolves `.env` relative to the launcher's working
    directory. A release executable started from a repository could therefore use
    an unrelated development provider even though the Settings UI showed the
    project-scoped value.
    """

    runtime = EnvironmentSettingsService(
        project_root,
        prefer_system_store=prefer_system_store,
    ).runtime_environment()
    os.environ.update(runtime)


def main() -> None:
    """Boot the sidecar: validate env, prepare paths, then serve the Product API on a loopback port."""
    token = os.getenv("CELLWIKI_DESKTOP_TOKEN", "")
    if not token:
        # Shared secret prevents the loopback API from being accessible to
        # arbitrary processes on the same machine.
        raise SystemExit("CELLWIKI_DESKTOP_TOKEN is required for packaged sidecar mode")
    port = int(os.getenv("CELLWIKI_PORT", "0"))
    if not 1 <= port <= 65535:
        raise SystemExit("CELLWIKI_PORT must be an allocated loopback port")

    paths = ApplicationPaths.create(default_data_root())
    _configure_project_environment(paths.project_root)
    # Read log level from desktop settings before configuring logging
    settings_service = EnvironmentSettingsService(paths.project_root)
    log_level = settings_service.public_settings().get("log_level", "INFO")
    configure_desktop_logging(paths, secrets=[token, os.getenv("OPENAI_API_KEY", "")], level=log_level)
    recover_stale_runtime_files(paths)  # Clean up files left behind by a previous crash.
    backup_before_upgrade(paths, version=application_version())
    runtime_db = paths.project_root / "data" / "runtime" / "cellwiki.db"
    upgrade_runtime_database(runtime_db)

    # Dict as mutable container so request_shutdown can reference the
    # uvicorn.Server before it is assigned (Python closure captures by name).
    holder: dict[str, uvicorn.Server] = {}

    def request_shutdown() -> None:
        server = holder.get("server")
        if server is not None:
            server.should_exit = True

    # Defer import until after project-scoped provider values and the system
    # credential have been injected; cellwiki.config owns a process-global
    # Settings object that reads env vars at import time.
    from cellwiki.api.app import create_app

    app = create_app(
        local_token=token,
        shutdown_callback=request_shutdown,
    )  # root 默认为 settings.workspace_root（已选工作区）
    app.state.application_paths = paths
    config = uvicorn.Config(
        app,
        host="127.0.0.1",  # Loopback only — never expose the sidecar to the network.
        port=port,
        log_level="info",
        access_log=False,  # Logging is handled by configure_desktop_logging.
    )
    server = uvicorn.Server(config)
    holder["server"] = server  # Makes server accessible to request_shutdown.
    server.run()


if __name__ == "__main__":
    main()
