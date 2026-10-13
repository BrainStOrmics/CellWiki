"""HTTP client for the local CellWiki daemon."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from cellwiki.services.local_daemon import (
    ensure_daemon,
    read_control_token,
    workspace_state_dir,
)


DEFAULT_TIMEOUT_SECONDS = 60.0


class CellWikiClientError(RuntimeError):
    """Raised when a daemon request fails or the daemon is unreachable."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass
class DaemonClient:
    """Minimal Product API client for the terminal surface."""

    base_url: str
    token: str

    @classmethod
    def connect(cls, workspace: Path) -> "DaemonClient":
        coordinates = ensure_daemon(workspace)
        token = read_control_token(workspace_state_dir(workspace))
        if not token:
            raise CellWikiClientError("the CellWiki daemon control token is missing")
        return cls(base_url=f"http://127.0.0.1:{coordinates.port}", token=token)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def _send(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            return httpx.request(
                method,
                f"{self.base_url}{path}",
                headers=self._headers(),
                timeout=DEFAULT_TIMEOUT_SECONDS,
                **kwargs,
            )
        except httpx.HTTPError as error:
            raise CellWikiClientError(f"CellWiki daemon is unreachable: {error}") from error

    def _json(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self._send(method, path, **kwargs)
        if response.status_code >= 400:
            raise CellWikiClientError(
                _error_message(response),
                status_code=response.status_code,
            )
        try:
            return response.json()
        except ValueError as error:
            raise CellWikiClientError(f"daemon returned invalid JSON for {path}") from error

    def list_threads(self) -> list[dict[str, Any]]:
        return list(self._json("GET", "/api/agent/threads"))

    def create_thread(self) -> str:
        payload = self._json("POST", "/api/agent/threads")
        return str(payload["thread_id"])

    def list_messages(self, thread_id: str) -> list[dict[str, Any]]:
        return list(self._json("GET", f"/api/agent/threads/{thread_id}/messages"))

    def start_run(self, thread_id: str, message: str) -> dict[str, Any]:
        payload = {
            "thread_id": thread_id,
            "message": message,
            "request_id": f"tui_{uuid.uuid4().hex}",
        }
        return dict(self._json("POST", "/api/agent/runs", json=payload))

    def get_run(self, run_id: str) -> dict[str, Any]:
        return dict(self._json("GET", f"/api/agent/runs/{run_id}"))

    def list_events(self, run_id: str, after: int = 0) -> list[dict[str, Any]]:
        return list(
            self._json(
                "GET",
                f"/api/agent/runs/{run_id}/events",
                params={"after": after},
            )
        )

    def get_question(self, run_id: str) -> dict[str, Any] | None:
        response = self._send("GET", f"/api/agent/runs/{run_id}/question")
        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            raise CellWikiClientError(
                _error_message(response),
                status_code=response.status_code,
            )
        return dict(response.json())

    def answer_question(
        self,
        run_id: str,
        answers: str | list[str] | None,
        *,
        timed_out: bool = False,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = (
            {"timed_out": True} if timed_out else {"answers": answers}
        )
        return dict(
            self._json("POST", f"/api/agent/runs/{run_id}/question", json=payload)
        )

    def list_pending_diffs(self) -> list[dict[str, Any]]:
        return list(self._json("GET", "/api/pending-diffs"))

    def pending_diff_patch(self, diff_id: str) -> str:
        response = self._send("GET", f"/api/pending-diffs/{diff_id}/patch")
        if response.status_code >= 400:
            raise CellWikiClientError(
                _error_message(response),
                status_code=response.status_code,
            )
        return response.text

    def accept_pending_diff(self, diff_id: str) -> dict[str, Any]:
        return dict(self._json("POST", f"/api/pending-diffs/{diff_id}/accept"))

    def reject_pending_diff(self, diff_id: str) -> dict[str, Any]:
        return dict(self._json("POST", f"/api/pending-diffs/{diff_id}/reject"))

    def cancel_run(self, run_id: str) -> dict[str, Any]:
        return dict(self._json("POST", f"/api/agent/runs/{run_id}/cancel"))


def _error_message(response: httpx.Response) -> str:
    detail: str
    try:
        payload = response.json()
        detail = str(payload.get("detail", payload))
    except ValueError:
        detail = response.text.strip() or response.reason_phrase
    return f"daemon request failed ({response.status_code}): {detail}"
