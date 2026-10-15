"""Line-oriented TUI flows against a scripted daemon client."""

from __future__ import annotations

import asyncio
import io
from pathlib import Path
from typing import Any

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import CompleteEvent
from prompt_toolkit.document import Document
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput
from rich.console import Console

from cellwiki.tui import renderer
from cellwiki.tui.app import ESCAPE, CellWikiTui, CommandCompleter
from cellwiki.tui.client import CellWikiClientError


class FakeClient:
    """Scripted daemon client covering the Product API surface used by the TUI."""

    base_url = "http://127.0.0.1:9"

    def __init__(
        self,
        runs: list[dict[str, Any]],
        *,
        events: dict[str, list[dict[str, Any]]] | None = None,
        question: dict[str, Any] | None = None,
        patch: str = "",
        fail_stream_once: bool = False,
        threads: list[dict[str, Any]] | None = None,
    ) -> None:
        self._runs = [dict(run) for run in runs]
        self._current = dict(self._runs[0])
        self._events = events or {}
        self._question = question
        self.patch = patch or (
            "diff --git a/wiki/x.md b/wiki/x.md\n"
            "--- a/wiki/x.md\n"
            "+++ b/wiki/x.md\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "+new\n"
        )
        self.fail_stream_once = fail_stream_once
        self.threads = threads or [
            {
                "thread_id": "thread_1",
                "title": "First",
                "latest_status": "succeeded",
                "updated_at": "2026-10-15T10:00:00",
            }
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
        self.cancelled: list[str] = []
        self.retried: list[str] = []
        self.resumed: list[str] = []
        self.stream_calls = 0
        self.created_threads = 0

    def list_threads(self) -> list[dict[str, Any]]:
        return [dict(thread) for thread in self.threads]

    def create_thread(self) -> str:
        self.created_threads += 1
        self.threads.insert(
            0,
            {
                "thread_id": "thread_new",
                "title": "New",
                "latest_status": "no runs",
                "updated_at": "2026-10-15T10:00:00",
            },
        )
        return "thread_new"

    def list_messages(self, thread_id: str) -> list[dict[str, Any]]:
        return list(self.messages.get(thread_id, []))

    def start_run(self, thread_id: str, message: str) -> dict[str, Any]:
        self.started.append((thread_id, message))
        return {"run_id": f"run_{len(self.started)}", "status": "running"}

    def get_run(self, run_id: str) -> dict[str, Any]:
        if self._runs:
            self._current = dict(self._runs.pop(0))
        return dict(self._current)

    def list_events(self, run_id: str, after: int = 0) -> list[dict[str, Any]]:
        return [
            dict(event)
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
        return self.patch

    def accept_pending_diff(self, diff_id: str) -> dict[str, Any]:
        self.accepted.append(diff_id)
        return {"diff_id": diff_id}

    def reject_pending_diff(self, diff_id: str) -> dict[str, Any]:
        self.rejected.append(diff_id)
        return {"diff_id": diff_id}

    def cancel_run(self, run_id: str) -> dict[str, Any]:
        self.cancelled.append(run_id)
        return {"run_id": run_id}

    def retry_run(self, run_id: str) -> dict[str, Any]:
        self.retried.append(run_id)
        return {"run_id": run_id}

    def resume_run(self, run_id: str) -> dict[str, Any]:
        self.resumed.append(run_id)
        return {"run_id": run_id}

    def list_model_providers(self) -> dict[str, Any]:
        return {
            "default_selection": {"provider_id": "openai", "model_id": "gpt-5"},
            "providers": [],
        }

    def context_usage(self, thread_id: str) -> dict[str, Any]:
        return {"thread_id": thread_id, "used_tokens": 12000}

    async def stream_events(self, run_id: str, after: int = 0) -> Any:
        self.stream_calls += 1
        if self.fail_stream_once and self.stream_calls == 1:
            raise CellWikiClientError("daemon unreachable")
        for event in self._events.get(run_id, []):
            if int(event.get("sequence") or 0) > after:
                yield dict(event)


def _console() -> tuple[Console, io.StringIO]:
    buffer = io.StringIO()
    return Console(file=buffer, force_terminal=False, width=100), buffer


async def _wait_for(predicate: Any, timeout: float = 5.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("timed out waiting for the TUI condition")


def test_tui_streams_answer_into_scrollback(tmp_path: Path) -> None:
    fake = FakeClient(
        [
            {"run_id": "run_1", "status": "running", "pending_diff_id": None},
            {
                "run_id": "run_1",
                "status": "succeeded",
                "pending_diff_id": None,
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "elapsed_seconds": 1.2,
                },
            },
        ],
        events={
            "run_1": [
                {
                    "sequence": 1,
                    "type": "message_delta",
                    "message": "FOXP3 ",
                    "data": {},
                },
                {
                    "sequence": 2,
                    "type": "message_delta",
                    "message": "is a marker.",
                    "data": {},
                },
                {
                    "sequence": 3,
                    "type": "final_response",
                    "message": "FOXP3 is a marker.",
                    "data": {},
                },
                {
                    "sequence": 4,
                    "type": "run_status",
                    "message": "Run succeeded.",
                    "data": {"status": "succeeded"},
                },
            ]
        },
    )
    console, buffer = _console()

    async def scenario() -> None:
        app = CellWikiTui(
            tmp_path, client_factory=lambda workspace: fake, console=console
        )
        await app.connect()
        await app.submit("What is FOXP3?")
        assert await app.wait_idle(5.0)
        assert app.run_status == "succeeded"
        assert app.model_label == "openai/gpt-5"
        assert app.context_label == "ctx 12k"
        toolbar = "".join(piece for _, piece in app._toolbar())
        assert "model openai/gpt-5" in toolbar
        assert "ctx 12k" in toolbar

    asyncio.run(scenario())
    text = buffer.getvalue()
    assert "FOXP3 is a marker." in text
    assert "run run_1: succeeded" in text
    assert fake.started == [("thread_1", "What is FOXP3?")]


def test_tui_question_gate_answers_inline(tmp_path: Path) -> None:
    fake = FakeClient(
        [
            {
                "run_id": "run_1",
                "status": "waiting_confirmation",
                "pending_diff_id": None,
            },
            {"run_id": "run_1", "status": "succeeded", "pending_diff_id": None},
        ],
        events={
            "run_1": [
                {
                    "sequence": 1,
                    "type": "task_confirmation_required",
                    "message": "Proceed?",
                    "data": {},
                }
            ]
        },
        question={
            "question": "Proceed?",
            "options": [{"label": "Yes", "recommended": True}, {"label": "No"}],
            "required": True,
        },
    )
    console, buffer = _console()

    async def scenario() -> None:
        app = CellWikiTui(
            tmp_path, client_factory=lambda workspace: fake, console=console
        )
        await app.connect()
        await app.submit("go")
        await _wait_for(lambda: app.gate is not None)
        assert app.gate is not None and app.gate.kind == "question"
        await app.submit("1")
        assert await app.wait_idle(5.0)

    asyncio.run(scenario())
    assert fake.answers == [("Yes", False)]
    assert "CellWiki needs your decision" in buffer.getvalue()


def test_tui_question_gate_escape_skips(tmp_path: Path) -> None:
    fake = FakeClient(
        [
            {
                "run_id": "run_1",
                "status": "waiting_confirmation",
                "pending_diff_id": None,
            },
            {"run_id": "run_1", "status": "unfinished", "pending_diff_id": None},
        ],
        events={
            "run_1": [
                {
                    "sequence": 1,
                    "type": "task_confirmation_required",
                    "message": "Proceed?",
                    "data": {},
                }
            ]
        },
        question={
            "question": "Proceed?",
            "options": [{"label": "Yes", "recommended": True}],
            "required": True,
        },
    )
    console, _ = _console()

    async def scenario() -> None:
        app = CellWikiTui(
            tmp_path, client_factory=lambda workspace: fake, console=console
        )
        await app.connect()
        await app.submit("go")
        await _wait_for(lambda: app.gate is not None)
        await app.submit(ESCAPE)
        assert await app.wait_idle(5.0)

    asyncio.run(scenario())
    assert fake.answers == [(None, True)]


def test_tui_diff_gate_defers_and_reopens(tmp_path: Path) -> None:
    fake = FakeClient(
        [
            {
                "run_id": "run_1",
                "status": "waiting_approval",
                "pending_diff_id": "diff_1",
            },
            {"run_id": "run_1", "status": "succeeded", "pending_diff_id": None},
        ],
        events={
            "run_1": [
                {
                    "sequence": 1,
                    "type": "run_status",
                    "message": "Waiting approval.",
                    "data": {"status": "waiting_approval"},
                }
            ]
        },
    )
    console, buffer = _console()

    async def scenario() -> None:
        app = CellWikiTui(
            tmp_path, client_factory=lambda workspace: fake, console=console
        )
        await app.connect()
        await app.submit("edit a page")
        await _wait_for(
            lambda: app.gate is not None and app.gate.kind == "diff"
        )
        await app.submit("3")
        assert app.gate is not None
        await app.submit(ESCAPE)
        assert app.gate is None
        assert app.pending_diff_id == "diff_1"
        assert app.run_task is not None and app.run_task.done()
        assert fake.accepted == [] and fake.rejected == []
        await app.submit("note for later")
        assert app.queue == ["note for later"]
        assert "queued (1): note for later" in buffer.getvalue()
        assert app.withdraw_queued() == "note for later"
        await app.submit("/diff")
        await _wait_for(lambda: app.gate is not None)
        await app.submit("1")
        assert await app.wait_idle(5.0)

    asyncio.run(scenario())
    assert fake.accepted == ["diff_1"]
    text = buffer.getvalue()
    assert "Pending diff diff_1" in text
    assert "approval deferred" in text
    assert "accepted diff_1" in text


def test_tui_queues_while_running_and_sends_next(tmp_path: Path) -> None:
    fake = FakeClient(
        [
            {"run_id": "run_1", "status": "running", "pending_diff_id": None},
            {"run_id": "run_1", "status": "succeeded", "pending_diff_id": None},
            {"run_id": "run_2", "status": "running", "pending_diff_id": None},
            {"run_id": "run_2", "status": "succeeded", "pending_diff_id": None},
        ],
        events={"run_1": [], "run_2": []},
    )
    console, buffer = _console()

    async def scenario() -> None:
        app = CellWikiTui(
            tmp_path, client_factory=lambda workspace: fake, console=console
        )
        await app.connect()
        await app.submit("first")
        await app.submit("second")
        assert app.queue == ["second"]
        assert await app.wait_idle(5.0)

    asyncio.run(scenario())
    assert fake.started == [("thread_1", "first"), ("thread_1", "second")]
    assert "queued (1): second" in buffer.getvalue()


def test_tui_withdraw_queued_message(tmp_path: Path) -> None:
    fake = FakeClient(
        [{"run_id": "run_1", "status": "succeeded", "pending_diff_id": None}]
    )
    console, _ = _console()
    app = CellWikiTui(
        tmp_path, client_factory=lambda workspace: fake, console=console
    )
    app.queue = ["first", "second"]
    assert app.withdraw_queued() == "second"
    assert app.queue == ["first"]


def test_tui_escape_pauses_run_and_continue_resumes(tmp_path: Path) -> None:
    fake = FakeClient(
        [
            {"run_id": "run_1", "status": "running", "pending_diff_id": None},
            {"run_id": "run_1", "status": "unfinished", "pending_diff_id": None},
        ],
        events={"run_1": []},
    )
    console, _ = _console()

    async def scenario() -> None:
        app = CellWikiTui(
            tmp_path, client_factory=lambda workspace: fake, console=console
        )
        await app.connect()
        await app.submit("long task")
        await _wait_for(lambda: app.active_run_id == "run_1")
        await app.submit(ESCAPE)
        assert fake.cancelled == ["run_1"]
        assert await app.wait_idle(5.0)
        assert app.run_status == "unfinished"
        await app.submit("/continue")
        assert await app.wait_idle(5.0)

    asyncio.run(scenario())
    assert fake.resumed == ["run_1"]


def test_tui_reconnects_after_stream_failure(tmp_path: Path) -> None:
    fake = FakeClient(
        [
            {"run_id": "run_1", "status": "running", "pending_diff_id": None},
            {"run_id": "run_1", "status": "succeeded", "pending_diff_id": None},
        ],
        events={
            "run_1": [
                {
                    "sequence": 1,
                    "type": "message_delta",
                    "message": "ok",
                    "data": {},
                }
            ]
        },
        fail_stream_once=True,
    )
    console, buffer = _console()

    async def scenario() -> None:
        app = CellWikiTui(
            tmp_path, client_factory=lambda workspace: fake, console=console
        )
        await app.connect()
        await app.submit("hello")
        assert await app.wait_idle(10.0)

    asyncio.run(scenario())
    assert fake.stream_calls >= 2
    assert "reconnected" in buffer.getvalue()


def test_tui_busy_409_shows_active_run(tmp_path: Path) -> None:
    class BusyClient(FakeClient):
        def start_run(self, thread_id: str, message: str) -> dict[str, Any]:
            raise CellWikiClientError(
                "daemon request failed (409): another agent run is active: "
                "run_busy",
                status_code=409,
            )

    fake = BusyClient(
        [{"run_id": "run_busy", "status": "running", "pending_diff_id": None}]
    )
    console, buffer = _console()

    async def scenario() -> None:
        app = CellWikiTui(
            tmp_path, client_factory=lambda workspace: fake, console=console
        )
        await app.connect()
        await app.submit("hello")

    asyncio.run(scenario())
    assert "run_busy" in buffer.getvalue()


def test_tui_resume_switches_thread(tmp_path: Path) -> None:
    threads = [
        {
            "thread_id": "thread_1",
            "title": "First",
            "latest_status": "succeeded",
            "updated_at": "2026-10-15T10:00:00",
        },
        {
            "thread_id": "thread_2",
            "title": "Second",
            "latest_status": "unfinished",
            "updated_at": "2026-10-14T09:00:00",
        },
    ]
    fake = FakeClient(
        [{"run_id": "run_1", "status": "succeeded", "pending_diff_id": None}],
        threads=threads,
    )
    fake.messages["thread_2"] = [
        {"role": "assistant", "content": "second thread answer"}
    ]
    console, buffer = _console()

    async def scenario() -> None:
        app = CellWikiTui(
            tmp_path, client_factory=lambda workspace: fake, console=console
        )
        await app.connect()
        await app.submit("/resume 2")
        assert app.thread_id == "thread_2"

    asyncio.run(scenario())
    assert "second thread answer" in buffer.getvalue()


def test_renderer_tool_and_status_labels() -> None:
    started = renderer.event_line(
        {
            "type": "tool_started",
            "message": "read_file \u00b7 wiki/x.md",
            "data": {"tool_name": "read_file"},
        }
    )
    assert started is not None and "read_file" in started.plain
    completed = renderer.event_line(
        {"type": "tool_completed", "message": "read wiki/x.md", "data": {}}
    )
    assert completed is not None and "read wiki/x.md" in completed.plain
    assert (
        renderer.model_label(
            {"default_selection": {"provider_id": "openai", "model_id": "gpt-5"}}
        )
        == "openai/gpt-5"
    )
    assert renderer.model_label(None) == "legacy .env"
    assert renderer.context_label({"used_tokens": 12000}) == "ctx 12k"
    assert renderer.context_label({}) == ""


def test_renderer_approval_lines_include_patch_and_options() -> None:
    patch = (
        "diff --git a/wiki/x.md b/wiki/x.md\n"
        "--- a/wiki/x.md\n"
        "+++ b/wiki/x.md\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
    )
    lines = renderer.approval_lines("diff_1", patch)
    plain = "\n".join(line.plain for line in lines)
    assert "diff_1" in plain
    assert "wiki/x.md" in plain
    assert "+new" in plain
    assert "1 accept" in plain


def test_tui_retry_recovers_failed_run(tmp_path: Path) -> None:
    fake = FakeClient(
        [
            {
                "run_id": "run_1",
                "status": "failed",
                "pending_diff_id": None,
                "retryable": True,
            },
            {
                "run_id": "run_1",
                "status": "failed",
                "pending_diff_id": None,
                "retryable": True,
            },
        ],
        events={"run_1": []},
    )
    console, _ = _console()

    async def scenario() -> None:
        app = CellWikiTui(
            tmp_path, client_factory=lambda workspace: fake, console=console
        )
        await app.connect()
        await app.submit("hello")
        assert await app.wait_idle(5.0)
        assert app.run_status == "failed"
        await app.submit("/retry")
        assert await app.wait_idle(5.0)

    asyncio.run(scenario())
    assert fake.retried == ["run_1"]


def test_tui_version_mismatch_prompts_restart(
    tmp_path: Path, monkeypatch: Any
) -> None:
    from cellwiki.services.local_daemon import (
        DaemonCoordinates,
        DaemonVersionMismatch,
    )

    coordinates = DaemonCoordinates(
        schema_version=1,
        pid=1,
        port=1,
        workspace=str(tmp_path),
        package_version="0.0.1",
        api_version="old",
        started_at="2026-10-15T00:00:00+00:00",
        log_path="launch.log",
    )
    fake = FakeClient(
        [{"run_id": "run_1", "status": "succeeded", "pending_diff_id": None}]
    )
    attempts: list[int] = []

    def factory(workspace: Path) -> FakeClient:
        attempts.append(1)
        if len(attempts) == 1:
            raise DaemonVersionMismatch(coordinates)
        return fake

    restarts: list[Path] = []
    monkeypatch.setattr(
        "cellwiki.tui.app.restart_daemon",
        lambda workspace: restarts.append(workspace),
    )
    console, _ = _console()

    async def scenario() -> None:
        app = CellWikiTui(tmp_path, client_factory=factory, console=console)

        async def confirm(message: str) -> str:
            return "y"

        monkeypatch.setattr(app, "_prompt_line", confirm)
        assert await app._connect_with_restart_prompt()
        assert app.connected

    asyncio.run(scenario())
    assert len(attempts) == 2
    assert restarts == [tmp_path.resolve()]


def test_tui_command_completion_and_multiline_binding(tmp_path: Path) -> None:
    fake = FakeClient(
        [{"run_id": "run_1", "status": "succeeded", "pending_diff_id": None}]
    )
    console, _ = _console()
    app = CellWikiTui(
        tmp_path, client_factory=lambda workspace: fake, console=console
    )
    completions = list(
        CommandCompleter().get_completions(Document("/re", 3), CompleteEvent())
    )
    assert {completion.text for completion in completions} == {"/resume", "/retry"}

    async def scenario() -> None:
        with create_pipe_input() as pipe:
            session: PromptSession[str] = PromptSession(
                input=pipe,
                output=DummyOutput(),
                key_bindings=app._build_key_bindings(),
                multiline=True,
            )
            pipe.send_text("line1\\\r")
            pipe.send_text("line2\r")
            result = await session.prompt_async()
            assert result == "line1\nline2"

    asyncio.run(scenario())
