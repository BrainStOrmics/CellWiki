"""Local CellWiki daemon: ownership, discovery, lifecycle, and client helpers.

The daemon owns one workspace's ``AgentRuntimeManager`` and Product API. TUI and
future MCP clients connect through the loopback coordinates published in a
user-scoped discovery file; they never construct a second runtime owner.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import logging
import os
import secrets
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from filelock import FileLock, Timeout

from cellwiki.services.desktop import (
    ApplicationPaths,
    RedactingFormatter,
    backup_before_upgrade,
    recover_stale_runtime_files,
)
from cellwiki.services.environment import EnvironmentSettingsService
from cellwiki.services.workspace import ensure_workspace


DAEMON_API_VERSION = "cellwiki-daemon-v1"
DAEMON_SCHEMA_VERSION = 1
DISCOVERY_FILE_NAME = "daemon.json"
CONTROL_TOKEN_FILE_NAME = "control.token"
LOCK_FILE_NAME = "daemon.lock"
LAUNCH_LOG_FILE_NAME = "launch.log"
DAEMON_LOG_FILE_NAME = "daemon.log"
START_TIMEOUT_SECONDS = 90.0


class DaemonError(RuntimeError):
    """Base class for local daemon lifecycle errors."""


class DaemonAlreadyRunning(DaemonError):
    """Raised when a second daemon attempts to own the same workspace."""

    def __init__(self, coordinates: "DaemonCoordinates | None") -> None:
        self.coordinates = coordinates
        location = (
            f"pid {coordinates.pid} at http://127.0.0.1:{coordinates.port}"
            if coordinates is not None
            else "an existing process"
        )
        super().__init__(f"a CellWiki daemon is already running for this workspace: {location}")


class DaemonStartError(DaemonError):
    """Raised when a detached daemon does not become healthy in time."""


class DaemonVersionMismatch(DaemonError):
    """Raised when a live daemon does not match the client's package/API version."""

    def __init__(self, coordinates: "DaemonCoordinates") -> None:
        super().__init__(
            "the running CellWiki daemon was started by version "
            f"{coordinates.package_version} (API {coordinates.api_version}); "
            "run `cellwiki daemon restart` to restart it with the current version"
        )


@dataclass(frozen=True)
class DaemonCoordinates:
    """Non-secret connection metadata for one running daemon."""

    schema_version: int
    pid: int
    port: int
    workspace: str
    package_version: str
    api_version: str
    started_at: str
    log_path: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "pid": self.pid,
            "port": self.port,
            "workspace": self.workspace,
            "package_version": self.package_version,
            "api_version": self.api_version,
            "started_at": self.started_at,
            "log_path": self.log_path,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "DaemonCoordinates":
        return cls(
            schema_version=int(payload["schema_version"]),
            pid=int(payload["pid"]),
            port=int(payload["port"]),
            workspace=str(payload["workspace"]),
            package_version=str(payload["package_version"]),
            api_version=str(payload["api_version"]),
            started_at=str(payload["started_at"]),
            log_path=str(payload["log_path"]),
        )


def application_version() -> str:
    """Return installed package version, falling back to the VERSION file."""

    try:
        from importlib.metadata import version

        return version("cellwiki")
    except Exception:
        version_file = Path(__file__).resolve().parents[2] / "VERSION"
        return version_file.read_text(encoding="utf-8").strip() if version_file.exists() else "0.0.0"


def daemon_root() -> Path:
    """Return the base directory for daemon state across all workspaces."""

    override = os.getenv("CELLWIKI_DAEMON_DIR")
    if override:
        return Path(override).expanduser()
    runtime_dir = os.getenv("XDG_RUNTIME_DIR")
    if runtime_dir:
        return Path(runtime_dir) / "cellwiki" / "daemon"
    return Path.home() / ".cellwiki" / "daemon"


def workspace_state_dir(workspace: Path) -> Path:
    """Return the per-workspace daemon state directory."""

    resolved = Path(workspace).expanduser().resolve()
    digest = hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()[:16]
    return daemon_root() / digest


def _write_private_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    if os.name != "nt":
        temporary.chmod(0o600)
    os.replace(temporary, path)
    if os.name != "nt":
        path.chmod(0o600)


def write_coordinates(state_dir: Path, coordinates: DaemonCoordinates) -> None:
    _write_private_text(
        state_dir / DISCOVERY_FILE_NAME,
        json.dumps(coordinates.to_payload(), ensure_ascii=False, indent=2) + "\n",
    )


def read_coordinates(state_dir: Path) -> DaemonCoordinates | None:
    path = state_dir / DISCOVERY_FILE_NAME
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        coordinates = DaemonCoordinates.from_payload(payload)
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if coordinates.schema_version != DAEMON_SCHEMA_VERSION:
        return None
    return coordinates


def write_control_token(state_dir: Path, token: str) -> None:
    _write_private_text(state_dir / CONTROL_TOKEN_FILE_NAME, token + "\n")


def read_control_token(state_dir: Path) -> str | None:
    path = state_dir / CONTROL_TOKEN_FILE_NAME
    if not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def remove_state_files(state_dir: Path) -> None:
    for name in (DISCOVERY_FILE_NAME, CONTROL_TOKEN_FILE_NAME):
        (state_dir / name).unlink(missing_ok=True)


def pid_alive(pid: int) -> bool:
    """Return whether the process exists (best effort, cross-platform)."""

    if pid <= 0:
        return False
    if os.name == "nt":
        process_query_limited_information = 0x1000
        still_active = 259
        kernel32 = getattr(ctypes, "windll").kernel32
        handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return exit_code.value == still_active
            return False
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def check_health(coordinates: DaemonCoordinates, *, timeout: float = 0.5) -> bool:
    """Return whether the daemon's loopback health endpoint answers 200."""

    url = f"http://127.0.0.1:{coordinates.port}/health"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return int(response.status) == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _request_shutdown(coordinates: DaemonCoordinates, token: str, *, timeout: float = 5.0) -> bool:
    request = urllib.request.Request(
        f"http://127.0.0.1:{coordinates.port}/api/system/shutdown",
        method="POST",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout):
            return True
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _terminate_process(pid: int, *, force: bool) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return
    force_signal = getattr(signal, "SIGKILL", signal.SIGTERM)
    try:
        os.kill(pid, force_signal if force else signal.SIGTERM)
    except ProcessLookupError:
        return


def _ensure_compatible(coordinates: DaemonCoordinates) -> None:
    if coordinates.api_version != DAEMON_API_VERSION or coordinates.package_version != application_version():
        raise DaemonVersionMismatch(coordinates)


def _state_is_locked(state_dir: Path) -> bool:
    lock = FileLock(str(state_dir / LOCK_FILE_NAME))
    try:
        lock.acquire(timeout=0)
    except Timeout:
        return True
    else:
        lock.release()
        return False


def daemon_status(workspace: Path) -> dict[str, Any]:
    """Return a JSON-ready status snapshot for one workspace."""

    state_dir = workspace_state_dir(workspace)
    coordinates = read_coordinates(state_dir)
    if coordinates is None:
        return {
            "state": "absent",
            "workspace": str(Path(workspace).expanduser().resolve()),
            "state_dir": str(state_dir),
        }
    alive = pid_alive(coordinates.pid)
    healthy = alive and check_health(coordinates)
    if healthy:
        state = "running"
    elif alive:
        state = "unhealthy"
    else:
        state = "stale"
    return {
        "state": state,
        "workspace": coordinates.workspace,
        "state_dir": str(state_dir),
        "pid": coordinates.pid,
        "port": coordinates.port,
        "package_version": coordinates.package_version,
        "api_version": coordinates.api_version,
        "started_at": coordinates.started_at,
        "log_path": coordinates.log_path,
    }


def ensure_daemon(workspace: Path, *, timeout: float = START_TIMEOUT_SECONDS) -> DaemonCoordinates:
    """Connect to the workspace daemon, starting a detached one when needed."""

    resolved = Path(workspace).expanduser().resolve()
    state_dir = workspace_state_dir(resolved)
    state_dir.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout

    existing = read_coordinates(state_dir)
    if existing is not None and pid_alive(existing.pid) and check_health(existing):
        _ensure_compatible(existing)
        return existing

    if existing is not None and _state_is_locked(state_dir):
        # Another client is starting (or restarting) the daemon; wait for it.
        while time.monotonic() < deadline:
            coordinates = read_coordinates(state_dir)
            if coordinates is not None and check_health(coordinates):
                _ensure_compatible(coordinates)
                return coordinates
            time.sleep(0.1)
        raise DaemonStartError("a CellWiki daemon is starting but did not become healthy in time")

    if existing is not None:
        lock = FileLock(str(state_dir / LOCK_FILE_NAME))
        try:
            lock.acquire(timeout=0)
        except Timeout:
            pass
        else:
            try:
                current = read_coordinates(state_dir)
                if current is None or not (pid_alive(current.pid) and check_health(current)):
                    remove_state_files(state_dir)
            finally:
                lock.release()

    launch_log = state_dir / LAUNCH_LOG_FILE_NAME
    command = [
        sys.executable,
        "-X",
        "utf8",
        "-m",
        "cellwiki.product_cli",
        "serve",
        "--workspace",
        str(resolved),
    ]
    environment = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    popen_options: dict[str, Any] = {
        "cwd": str(resolved),
        "env": environment,
        "stdin": subprocess.DEVNULL,
    }
    if os.name == "nt":
        popen_options["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
    else:
        popen_options["start_new_session"] = True
    with launch_log.open("ab", buffering=0) as log_handle:
        child = subprocess.Popen(command, stdout=log_handle, stderr=log_handle, **popen_options)

    while time.monotonic() < deadline:
        coordinates = read_coordinates(state_dir)
        if coordinates is not None and check_health(coordinates):
            _ensure_compatible(coordinates)
            return coordinates
        if child.poll() is not None:
            raise DaemonStartError(
                f"the CellWiki daemon exited during startup; inspect {launch_log}"
            )
        time.sleep(0.1)
    raise DaemonStartError(f"the CellWiki daemon did not become healthy; inspect {launch_log}")


def stop_daemon(workspace: Path, *, timeout: float = 15.0) -> bool:
    """Gracefully stop the workspace daemon; returns False when none is registered."""

    state_dir = workspace_state_dir(workspace)
    coordinates = read_coordinates(state_dir)
    if coordinates is None:
        return False
    token = read_control_token(state_dir)
    if token and pid_alive(coordinates.pid) and check_health(coordinates):
        _request_shutdown(coordinates, token)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not pid_alive(coordinates.pid):
            break
        time.sleep(0.1)
    else:
        _terminate_process(coordinates.pid, force=False)
        force_deadline = time.monotonic() + 5.0
        while time.monotonic() < force_deadline:
            if not pid_alive(coordinates.pid):
                break
            time.sleep(0.1)
        else:
            _terminate_process(coordinates.pid, force=True)
    remove_state_files(state_dir)
    return True


def restart_daemon(workspace: Path, *, timeout: float = START_TIMEOUT_SECONDS) -> DaemonCoordinates:
    """Stop any running workspace daemon, then start a fresh one."""

    stop_daemon(workspace)
    return ensure_daemon(workspace, timeout=timeout)


def _workspace_paths(workspace: Path) -> ApplicationPaths:
    runtime_dir = workspace / "data" / "runtime"
    paths = ApplicationPaths(
        data_root=workspace,
        project_root=workspace,
        runtime_dir=runtime_dir,
        logs_dir=runtime_dir / "logs",
        cache_dir=workspace / "cache",
        backups_dir=workspace / "data" / "backups",
        config_dir=runtime_dir / "config",
    )
    for directory in (
        paths.project_root,
        paths.runtime_dir,
        paths.logs_dir,
        paths.cache_dir,
        paths.backups_dir,
        paths.config_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)
    return paths


def _configure_daemon_logging(workspace: Path, *, secrets: list[str], level: str) -> Path:
    log_path = workspace / "data" / "runtime" / "logs" / DAEMON_LOG_FILE_NAME
    log_path.parent.mkdir(parents=True, exist_ok=True)
    formatter = RedactingFormatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        secrets=secrets,
    )
    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.handlers.clear()
    root.addHandler(file_handler)
    root.addHandler(stream_handler)
    return log_path


def apply_workspace_environment(
    runtime_values: dict[str, str],
    *,
    workspace: Path,
) -> None:
    """Apply workspace settings while explicit process environment wins.

    The decided precedence is environment > workspace `.env` > user config, so
    an explicitly exported provider key must not be replaced by an empty
    workspace default.
    """

    for key, value in runtime_values.items():
        if key == "PROJECT_ROOT":
            continue
        if os.environ.get(key):
            continue
        os.environ[key] = value
    os.environ["PROJECT_ROOT"] = str(workspace)


def run_daemon(workspace: Path, *, log_level: str | None = None) -> None:
    """Run the blocking daemon process for one workspace."""

    resolved = Path(workspace).expanduser().resolve()
    ensure_workspace(resolved)
    os.chdir(resolved)
    os.environ["PROJECT_ROOT"] = str(resolved)

    state_dir = workspace_state_dir(resolved)
    state_dir.mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(state_dir / LOCK_FILE_NAME))
    try:
        lock.acquire(timeout=0)
    except Timeout:
        raise DaemonAlreadyRunning(read_coordinates(state_dir)) from None

    token = secrets.token_urlsafe(32)
    write_control_token(state_dir, token)
    try:
        settings_service = EnvironmentSettingsService(resolved, prefer_system_store=False)
        apply_workspace_environment(
            settings_service.runtime_environment(),
            workspace=resolved,
        )
        effective_level = str(
            log_level or settings_service.public_settings().get("log_level") or "INFO"
        )
        log_path = _configure_daemon_logging(
            resolved,
            secrets=[token, os.getenv("OPENAI_API_KEY", "")],
            level=effective_level,
        )
        paths = _workspace_paths(resolved)
        recover_stale_runtime_files(paths)
        backup_before_upgrade(paths, version=application_version())
        from cellwiki.services.migrations import upgrade_runtime_database

        upgrade_runtime_database(resolved / "data" / "runtime" / "cellwiki.db")

        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        port = int(listener.getsockname()[1])
        coordinates = DaemonCoordinates(
            schema_version=DAEMON_SCHEMA_VERSION,
            pid=os.getpid(),
            port=port,
            workspace=str(resolved),
            package_version=application_version(),
            api_version=DAEMON_API_VERSION,
            started_at=datetime.now(UTC).isoformat(),
            log_path=str(log_path),
        )
        write_coordinates(state_dir, coordinates)

        import uvicorn

        from cellwiki.api.app import create_app

        holder: dict[str, Any] = {}

        def request_shutdown() -> None:
            server = holder.get("server")
            if server is not None:
                server.should_exit = True

        app = create_app(
            project_root=resolved,
            env_root=resolved,
            local_token=token,
            shutdown_callback=request_shutdown,
        )
        server = uvicorn.Server(
            uvicorn.Config(app, log_level="info", access_log=False)
        )
        holder["server"] = server
        try:
            server.run(sockets=[listener])
        finally:
            listener.close()
    finally:
        remove_state_files(state_dir)
        lock.release()
