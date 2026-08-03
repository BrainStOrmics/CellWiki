# =============================================================================
# 开发运行时 —— 支撑 `cellwiki dev` 命令的进程管理
# =============================================================================
# 负责启动和管理 CellWiki 开发所需的多个子进程：Product API（Uvicorn）、
# Agent Runtime（LangGraph）和 Desktop 前端（Tauri/Vite）。
# 自动检测端口占用、管理日志、优雅关闭子进程。
# =============================================================================

"""Owned-process development runtime behind the single ``cellwiki dev`` command."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import IO

from filelock import FileLock, Timeout


@dataclass(frozen=True)
class DevelopmentProcessSpec:
    name: str
    port: int
    command: tuple[str, ...]
    working_directory: Path


@dataclass
class OwnedProcess:
    spec: DevelopmentProcessSpec
    process: subprocess.Popen
    log_handle: IO[bytes]
    log_path: Path


def _terminate_process_tree(process: subprocess.Popen) -> None:
    """Stop an owned process and its Windows wrapper descendants."""

    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        process.terminate()

    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)


class DevelopmentRuntime:
    """Start and stop only the CellWiki development processes owned by this invocation."""

    def __init__(
        self,
        project_root: Path,
        *,
        include_agent: bool = True,
        include_desktop: bool = True,
        reuse_ports: bool = False,
    ):
        self.project_root = Path(project_root).resolve()
        self.include_agent = include_agent
        self.include_desktop = include_desktop
        self.reuse_ports = reuse_ports
        self.log_dir = self.project_root / "data" / "runtime" / "logs"
        self.owned: list[OwnedProcess] = []
        project_lock_path = self.project_root / "data" / "runtime" / "dev-runtime.lock"
        project_lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._project_lock = FileLock(str(project_lock_path), timeout=0)
        self._project_lock_acquired = False

    def specs(self) -> list[DevelopmentProcessSpec]:
        npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
        if self.include_desktop and not npm:
            raise RuntimeError("npm was not found; install Node.js before starting the desktop app")

        specs = [
            DevelopmentProcessSpec(
                name="product-api",
                port=8000,
                command=(
                    sys.executable,
                    "-X",
                    "utf8",
                    "-m",
                    "uvicorn",
                    "cellwiki.api.app:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "8000",
                ),
                working_directory=self.project_root,
            )
        ]
        if self.include_agent:
            specs.append(
                DevelopmentProcessSpec(
                    name="agent-runtime",
                    port=2024,
                    command=(
                        sys.executable,
                        "-X",
                        "utf8",
                        "-c",
                        "from langgraph_cli.cli import cli; cli()",
                        "dev",
                        "--config",
                        "langgraph.json",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        "2024",
                        "--no-browser",
                        "--no-reload",
                        "--allow-blocking",
                    ),
                    working_directory=self.project_root,
                )
            )
        if self.include_desktop:
            specs.append(
                DevelopmentProcessSpec(
                    name="desktop",
                    port=5173,
                    command=(npm or "npm", "run", "desktop:dev"),
                    working_directory=self.project_root / "frontend",
                )
            )
        return specs

    def run(self) -> None:
        """Start the runtime, report log paths, and block until interrupted or a child exits."""

        self._acquire_project_lock()
        try:
            self._validate_environment()
            for spec in self.specs():
                self._start(spec)
            self._watch()
        finally:
            try:
                self.stop()
            finally:
                self._release_project_lock()

    def _acquire_project_lock(self) -> None:
        try:
            self._project_lock.acquire()
        except Timeout as error:
            raise RuntimeError(
                "another CellWiki development runtime already owns this project"
            ) from error
        self._project_lock_acquired = True

    def _release_project_lock(self) -> None:
        if self._project_lock_acquired:
            self._project_lock.release()
            self._project_lock_acquired = False

    def _validate_environment(self) -> None:
        """Fail before spawning children when the repository-local toolchain is incomplete."""

        virtual_environment = self.project_root / ".venv"
        if not virtual_environment.is_dir():
            raise RuntimeError(".venv is missing; run `uv sync --extra dev` in the repository root")
        try:
            uses_project_python = Path(sys.executable).resolve().is_relative_to(
                virtual_environment.resolve()
            )
        except ValueError:
            uses_project_python = False
        if not uses_project_python:
            raise RuntimeError(
                "cellwiki dev must run from the repository .venv; use `uv run cellwiki dev`"
            )
        if self.include_desktop:
            if not shutil.which("npm.cmd" if os.name == "nt" else "npm"):
                raise RuntimeError("npm was not found; install Node.js before starting the desktop app")
            if not shutil.which("cargo.exe" if os.name == "nt" else "cargo"):
                raise RuntimeError("cargo was not found; install Rust before starting the Tauri app")
            if not (self.project_root / "frontend" / "node_modules").is_dir():
                raise RuntimeError("frontend/node_modules is missing; run `npm install` in frontend")
            if not (self.project_root / "frontend" / "src-tauri" / "tauri.conf.json").is_file():
                raise RuntimeError("frontend/src-tauri/tauri.conf.json is missing")

    def stop(self) -> None:
        """Stop owned children in reverse order; reused external services are untouched."""

        for owned in reversed(self.owned):
            if owned.process.poll() is None:
                _terminate_process_tree(owned.process)
            owned.log_handle.close()
        self.owned.clear()

    def _start(self, spec: DevelopmentProcessSpec) -> None:
        if _port_is_open(spec.port):
            if self.reuse_ports:
                print(f"[CellWiki] reusing explicitly approved port {spec.port} for {spec.name}")
                return
            raise RuntimeError(
                f"port {spec.port} is already in use; stop the existing process or pass --reuse-ports"
            )

        self.log_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        log_path = self.log_dir / f"dev-{timestamp}-{spec.name}.log"
        log_handle = log_path.open("ab", buffering=0)
        environment = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        process = subprocess.Popen(
            spec.command,
            cwd=spec.working_directory,
            env=environment,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
        )
        owned = OwnedProcess(spec, process, log_handle, log_path)
        self.owned.append(owned)
        print(f"[CellWiki] starting {spec.name} on {spec.port}; log: {log_path}")
        self._wait_until_ready(owned)

    def _wait_until_ready(self, owned: OwnedProcess) -> None:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if owned.process.poll() is not None:
                raise RuntimeError(
                    f"{owned.spec.name} exited during startup; inspect {owned.log_path}"
                )
            if _port_is_open(owned.spec.port):
                print(f"[CellWiki] {owned.spec.name} ready")
                return
            time.sleep(0.15)
        raise RuntimeError(f"{owned.spec.name} did not open port {owned.spec.port} within 30s")

    def _watch(self) -> None:
        if not self.owned:
            print("[CellWiki] all requested ports were reused; press Ctrl+C to stop watching")
        try:
            while True:
                for owned in self.owned:
                    code = owned.process.poll()
                    if code is not None:
                        raise RuntimeError(
                            f"{owned.spec.name} exited with code {code}; inspect {owned.log_path}"
                        )
                time.sleep(0.4)
        except KeyboardInterrupt:
            print("\n[CellWiki] stopping development runtime")


def _port_is_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
        connection.settimeout(0.15)
        return connection.connect_ex(("127.0.0.1", port)) == 0
