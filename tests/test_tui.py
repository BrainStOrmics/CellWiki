"""Textual client flows against a scripted daemon client."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Callable

from textual.pilot import Pilot
from textual.widgets import Button, Input

from cellwiki.tui.app import CellWikiTui, DiffScreen, QuestionScreen


class FakeClient:
    """Scripted daemon client covering the Product API surface used by the TUI."""

    base_url = "http://127.0.0.1:9"

    def __init__(
        self,
        runs: list[dict[str, Any]],
        *,
        events: dict[str, list[dict[str, Any]]] | None = None,
        question: dict[str, Any] | None = None,
    ) -> None:
        self._runs = list(runs)
        self._current = dict(self._runs[0])
        self._events = events or {}
        self._question = question
        self.threads: list[dict[str, Any]] = [
            {"thread_id": "thread_1", "title": "First"}
        ]
        self.messages: dict[str, list[dict[str, Any]]] = {
            "thread_1": [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "hi"},
            ]
        }
        self.started: list[tuple[str, str]] = []
        self.answers: list[tuple[Any, bool]] = []
        self.accepted: list[str] = []
        self.rejected: list[str] = []
        self.created_threads = 0

    def list_threads(self) -> list[dict[str, Any]]:
        return list(self.threads)

    def create_thread(self) -> str:
        self.created_threads += 1
        self.threads.insert(0, {"thread_id": "thread_new", "title": "New"})
        return "thread_new"

    def list_messages(self, thread_id: str) -> list[dict[str, Any]]:
        return list(self.messages.get(thread_id, []))

    def start_run(self, thread_id: str, message: str) -> dict[str, Any]:
        self.started.append((thread_id, message))
        return {"run_id": "run_1", "status": "running"}

    def get_run(self, run_id: str) -> dict[str, Any]:
        if self._runs:
            self._current = dict(self._runs.pop(0))
        return dict(self._current)

    def list_events(self, run_id: str, after: int = 0) -> list[dict[str, Any]]:
        return [
            event
            for event in self._events.get(run_id, [])
            if int(event.get("sequence") or 0) > after
        ]

    def get_question(self, run_id: str) -> dict[str, Any] | None:
        return dict(self._question) if self._question is not None else None

    def answer_question(
        self,
        run_id: str,
        answers: Any,
        *,
        timed_out: bool = False,
    ) -> dict[str, Any]:
        self.answers.append((answers, timed_out))
        self._question = None
        return {"run_id": run_id}

    def pending_diff_patch(self, diff_id: str) -> str:
        return "diff --git a/wiki/x.md b/wiki/x.md\n"

    def accept_pending_diff(self, diff_id: str) -> dict[str, Any]:
        self.accepted.append(diff_id)
        return {"diff_id": diff_id}

    def reject_pending_diff(self, diff_id: str) -> dict[str, Any]:
        self.rejected.append(diff_id)
        return {"diff_id": diff_id}

    def cancel_run(self, run_id: str) -> dict[str, Any]:
        return {"run_id": run_id}


async def _wait_for(
    pilot: Pilot[Any],
    predicate: Callable[[], bool],
    *,
    timeout: float = 8.0,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        await pilot.pause(0.05)
    raise AssertionError("timed out waiting for the TUI condition")


def test_tui_streams_answer_and_sends_message(tmp_path: Path) -> None:
    fake = FakeClient(
        [
            {"run_id": "run_1", "status": "running", "answer": "", "pending_diff_id": None},
            {"run_id": "run_1", "status": "succeeded", "answer": "Answer", "pending_diff_id": None},
        ],
        events={
            "run_1": [
                {"sequence": 1, "type": "message_delta", "message": "Answer", "data": {}}
            ]
        },
    )

    async def scenario() -> None:
        app = CellWikiTui(tmp_path, client_factory=lambda workspace: fake)
        async with app.run_test(size=(100, 30)) as pilot:
            await _wait_for(pilot, lambda: app.connected)
            composer = app.query_one("#composer", Input)
            composer.value = "What is FOXP3?"
            composer.focus()
            await pilot.pause(0.05)
            await pilot.press("enter")
            await _wait_for(
                pilot,
                lambda: app.active_run_id is None and bool(fake.started),
            )
            assert fake.started[0][1] == "What is FOXP3?"
            assert app._answer_buffer == "Answer"

    asyncio.run(scenario())


def test_tui_answers_question_gate(tmp_path: Path) -> None:
    fake = FakeClient(
        [
            {
                "run_id": "run_1",
                "status": "waiting_confirmation",
                "answer": "",
                "pending_diff_id": None,
            },
            {
                "run_id": "run_1",
                "status": "succeeded",
                "answer": "done",
                "pending_diff_id": None,
            },
        ],
        question={
            "question": "Proceed?",
            "options": [{"label": "Yes", "recommended": True}],
            "required": True,
        },
    )

    async def scenario() -> None:
        app = CellWikiTui(tmp_path, client_factory=lambda workspace: fake)
        async with app.run_test(size=(100, 30)) as pilot:
            await _wait_for(pilot, lambda: app.connected)
            composer = app.query_one("#composer", Input)
            composer.value = "go"
            composer.focus()
            await pilot.pause(0.05)
            await pilot.press("enter")
            await _wait_for(pilot, lambda: isinstance(app.screen, QuestionScreen))
            app.screen.query_one("#option-0", Button).press()
            await _wait_for(pilot, lambda: app.active_run_id is None and bool(fake.answers))
            assert fake.answers == [("Yes", False)]

    asyncio.run(scenario())


def test_tui_accepts_pending_diff(tmp_path: Path) -> None:
    fake = FakeClient(
        [
            {
                "run_id": "run_1",
                "status": "waiting_approval",
                "answer": "",
                "pending_diff_id": "diff_1",
            },
            {
                "run_id": "run_1",
                "status": "succeeded",
                "answer": "",
                "pending_diff_id": None,
            },
        ]
    )

    async def scenario() -> None:
        app = CellWikiTui(tmp_path, client_factory=lambda workspace: fake)
        async with app.run_test(size=(100, 30)) as pilot:
            await _wait_for(pilot, lambda: app.connected)
            composer = app.query_one("#composer", Input)
            composer.value = "edit a page"
            composer.focus()
            await pilot.pause(0.05)
            await pilot.press("enter")
            await _wait_for(pilot, lambda: isinstance(app.screen, DiffScreen))
            app.screen.query_one("#accept", Button).press()
            await _wait_for(pilot, lambda: app.active_run_id is None and bool(fake.accepted))
            assert fake.accepted == ["diff_1"]

    asyncio.run(scenario())
