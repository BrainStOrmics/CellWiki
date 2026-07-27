"""Exercise the built sidecar's health, token boundary, write path, and shutdown."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _available_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _request(url: str, *, method: str = "GET", token: str = "", body: dict | None = None) -> int:
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


def _default_binary() -> Path:
    candidates = sorted((ROOT / "frontend" / "src-tauri" / "binaries").glob("cellwiki-sidecar-*.exe"))
    if len(candidates) != 1:
        raise SystemExit(f"expected one built Windows sidecar, found {len(candidates)}")
    return candidates[0]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path)
    args = parser.parse_args()
    binary = (args.binary or _default_binary()).resolve()
    if not binary.is_file():
        raise SystemExit(f"sidecar binary not found: {binary}")

    port = _available_port()
    token = secrets.token_urlsafe(36)
    with tempfile.TemporaryDirectory(prefix="cellwiki_sidecar_smoke_") as data_dir:
        environment = {
            **os.environ,
            "CELLWIKI_PORT": str(port),
            "CELLWIKI_DESKTOP_TOKEN": token,
            "CELLWIKI_DATA_DIR": data_dir,
            "CELLWIKI_PACKAGED": "1",
        }
        process = subprocess.Popen(
            [str(binary)],
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        origin = f"http://127.0.0.1:{port}"
        try:
            deadline = time.monotonic() + 25
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError(f"sidecar exited before health check: {process.returncode}")
                try:
                    if _request(f"{origin}/health") == 200:
                        break
                except OSError:
                    pass
                time.sleep(0.15)
            else:
                raise TimeoutError("sidecar health endpoint did not become ready")

            unauthorized = _request(
                f"{origin}/api/memories",
                method="POST",
                body={
                    "candidate_id": "unauthorized",
                    "project_id": "cellwiki",
                    "kind": "episode",
                    "content": "must not be written",
                },
            )
            authorized = _request(
                f"{origin}/api/memories",
                method="POST",
                token=token,
                body={
                    "candidate_id": "sidecar_smoke",
                    "project_id": "cellwiki",
                    "kind": "episode",
                    "content": "observable packaged sidecar smoke outcome",
                },
            )
            shutdown = _request(
                f"{origin}/api/system/shutdown",
                method="POST",
                token=token,
            )
            process.wait(timeout=10)
            report = {
                "binary": str(binary),
                "health": 200,
                "unauthorized_write": unauthorized,
                "authorized_write": authorized,
                "shutdown": shutdown,
                "exit_code": process.returncode,
            }
            print(json.dumps(report, indent=2))
            if (unauthorized, authorized, shutdown, process.returncode) != (401, 201, 202, 0):
                raise SystemExit("packaged sidecar smoke failed")
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)


if __name__ == "__main__":
    main()
