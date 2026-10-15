"""Line-oriented terminal client for the local CellWiki daemon.

Completed output is printed to the terminal's main screen (native scrollback)
and a single prompt stays at the bottom, aligned with Claude Code's interaction
model: streaming output above, inline numbered gates, slash commands, Esc to
interrupt, and Enter to queue a message while a run is active.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import CompleteEvent, Completer, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.history import FileHistory, InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
from prompt_toolkit.patch_stdout import patch_stdout
from rich.console import Console
from rich.text import Text

from cellwiki.services.local_daemon import DaemonVersionMismatch, restart_daemon
from cellwiki.tui import renderer
from cellwiki.tui.client import CellWikiClientError, DaemonClient


ESCAPE = "\x1b"
CTRL_C = "\x03"
CTRL_D = "\x04"
POLL_INTERVAL_SECONDS = 0.5
RECONNECT_ATTEMPTS = 5
RUN_ID_PATTERN = re.compile(r"run_[A-Za-z0-9_]+")

COMMANDS = (
    "/help",
    "/new",
    "/resume",
    "/clear",
    "/status",
    "/continue",
    "/retry",
    "/diff",
    "/quit",
)


@dataclass
class Gate:
    """One inline user decision the run is waiting on."""

    kind: Literal["diff", "question"]
    run_id: str
    diff_id: str | None = None
    question: dict[str, Any] | None = None


class CommandCompleter(Completer):
    """Complete slash commands while the buffer starts with '/'."""

    def get_completions(
        self,
        document: Document,
        complete_event: CompleteEvent,
    ) -> Iterator[Completion]:
        text = document.text_before_cursor
        if not text.startswith("/") or " " in text:
            return
        for command in COMMANDS:
            if command.startswith(text):
                yield Completion(command, start_position=-len(text))


class CellWikiTui:
    """Conversation-first terminal client for one workspace daemon."""

    def __init__(
        self,
        workspace: Path,
        *,
        client_factory: Callable[[Path], Any] = DaemonClient.connect,
        console: Console | None = None,
    ) -> None:
        self.workspace = Path(workspace).expanduser().resolve()
        self._client_factory = client_factory
        self.console = console or Console()
        self._console_injected = console is not None
        self.client: Any = None
        self.connected = False
        self.thread_id: str | None = None
        self.thread_title = ""
        self.active_run_id: str | None = None
        self.last_run_id: str | None = None
        self.run_status = "idle"
        self.model_label = "unknown"
        self.context_label = ""
        self.usage_label = ""
        self.pending_diff_id: str | None = None
        self.gate: Gate | None = None
        self.queue: list[str] = []
        self.run_task: asyncio.Task[None] | None = None
        self._session: PromptSession[str] | None = None
        self._exiting = False
        self._stream_mode = "sse"
        self._answer_buffer = ""
        self._streamed_answer = False
        self._reasoning_open = False
        self._print_lock = asyncio.Lock()

    # ------------------------------------------------------------- lifecycle

    async def connect(self) -> None:
        """Resolve the daemon, load the latest thread, and read status labels."""

        self.client = await asyncio.to_thread(self._client_factory, self.workspace)
        self.connected = True
        threads = await asyncio.to_thread(self.client.list_threads)
        if threads:
            latest = threads[0]
            self.thread_id = str(latest.get("thread_id") or "") or None
            self.thread_title = str(latest.get("title") or "")
        await self._refresh_model()
        await self._refresh_context()

    async def run(self) -> None:
        """Run the prompt loop until the user quits."""

        with patch_stdout():
            if not self._console_injected:
                self.console = Console()
            self._session = self._build_session()
            if not await self._connect_with_restart_prompt():
                return
            await self._emit_welcome()
            while not self._exiting:
                try:
                    text = await self._session.prompt_async(
                        message=self._prompt_message
                    )
                except (EOFError, KeyboardInterrupt):
                    break
                await self.submit(text)

    async def _connect_with_restart_prompt(self) -> bool:
        try:
            await self.connect()
            return True
        except DaemonVersionMismatch as error:
            await self._emit(Text(str(error), style="yellow"))
            answer = await self._prompt_line("Restart the daemon now? [y/N] ")
            if answer.strip().lower() not in {"y", "yes"}:
                await self._emit(
                    Text("TUI cannot connect to an outdated daemon.", style="red")
                )
                return False
            await asyncio.to_thread(restart_daemon, self.workspace)
            await self.connect()
            return True
        except Exception as error:  # noqa: BLE001 - startup must surface any failure
            await self._emit(Text(str(error), style="red"))
            return False

    def _build_session(self) -> PromptSession[str]:
        history: FileHistory | InMemoryHistory
        try:
            history_path = Path.home() / ".cellwiki" / "tui_history"
            history_path.parent.mkdir(parents=True, exist_ok=True)
            history = FileHistory(str(history_path))
        except OSError:
            history = InMemoryHistory()
        return PromptSession(
            history=history,
            completer=CommandCompleter(),
            complete_while_typing=True,
            key_bindings=self._build_key_bindings(),
            bottom_toolbar=self._toolbar,
            multiline=True,
            prompt_continuation=lambda width, line_number, is_soft_wrap: "... ",
        )

    def _build_key_bindings(self) -> KeyBindings:
        bindings = KeyBindings()

        @bindings.add("escape")
        def _escape(event: KeyPressEvent) -> None:
            event.app.exit(result=ESCAPE)

        @bindings.add("c-c")
        def _ctrl_c(event: KeyPressEvent) -> None:
            event.app.exit(result=CTRL_C)

        @bindings.add("c-d")
        def _ctrl_d(event: KeyPressEvent) -> None:
            buffer = event.current_buffer
            if buffer.text:
                buffer.delete()
            else:
                event.app.exit(result=CTRL_D)

        @bindings.add("enter")
        def _enter(event: KeyPressEvent) -> None:
            buffer = event.current_buffer
            if buffer.text.endswith("\\") and not buffer.text.endswith("\\\\"):
                buffer.delete_before_cursor(count=1)
                buffer.insert_text("\n")
            else:
                buffer.validate_and_handle()

        @bindings.add("c-j")
        def _newline(event: KeyPressEvent) -> None:
            event.current_buffer.insert_text("\n")

        @bindings.add("up")
        def _up(event: KeyPressEvent) -> None:
            buffer = event.current_buffer
            if not buffer.text and self.queue:
                buffer.text = self.withdraw_queued() or ""
                buffer.cursor_position = len(buffer.text)
            else:
                buffer.auto_up()

        return bindings

    def _prompt_message(self) -> FormattedText:
        if self.gate is not None:
            if self.gate.kind == "diff":
                return FormattedText(
                    [("class:prompt", "approval (1/2/3, esc later)> ")]
                )
            return FormattedText([("class:prompt", "answer (esc skip)> ")])
        if self._run_active():
            return FormattedText([("class:prompt", "(running - enter queues)> ")])
        return FormattedText([("class:prompt", "> ")])

    def _toolbar(self) -> FormattedText:
        parts = ["cellwiki", f"model {self.model_label}"]
        if self.thread_title:
            parts.append(self.thread_title)
        parts.append(f"run {self.run_status}")
        if self.context_label:
            parts.append(self.context_label)
        if self.usage_label:
            parts.append(self.usage_label)
        if self.pending_diff_id and self.gate is None:
            parts.append(f"diff {self.pending_diff_id} (/diff)")
        if self.queue:
            parts.append(f"queued {len(self.queue)}")
        return FormattedText([("class:bottom-toolbar", "  ".join(parts))])

    # -------------------------------------------------------------- dispatch

    async def submit(self, text: str) -> None:
        """Handle one submitted line from the prompt (or a scripted test)."""

        raw = text or ""
        if raw == ESCAPE:
            await self._handle_escape()
            return
        if raw in {CTRL_C, CTRL_D}:
            if raw == CTRL_C and self._run_active():
                await self._handle_escape()
            else:
                self._exiting = True
            return
        message = raw.strip()
        if not message:
            return
        if self.gate is not None:
            await self._handle_gate_input(message)
            return
        if message.startswith("/"):
            await self._handle_command(message)
            return
        if self._run_active():
            self.queue.append(message)
            await self._emit(
                Text(f"queued ({len(self.queue)}): {message}", style="dim")
            )
            return
        await self._start_message(message)

    def withdraw_queued(self) -> str | None:
        """Pop the last queued message (bound to Up in the prompt)."""

        if not self.queue:
            return None
        return self.queue.pop()

    def _run_active(self) -> bool:
        if self.active_run_id is not None:
            return True
        return self.run_task is not None and not self.run_task.done()

    async def wait_idle(self, timeout: float = 10.0) -> bool:
        """Wait until no run, queue, or driver task is active (test helper)."""

        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            task = self.run_task
            busy = (
                (task is not None and not task.done())
                or self.active_run_id is not None
                or bool(self.queue)
            )
            if not busy:
                return True
            if loop.time() >= deadline:
                return False
            await asyncio.sleep(0.01)

    # ------------------------------------------------------------------ runs

    async def _start_message(self, message: str) -> None:
        if self.client is None:
            await self._emit(Text("not connected to the CellWiki daemon", style="red"))
            return
        if self.thread_id is None:
            self.thread_id = await asyncio.to_thread(self.client.create_thread)
            await self._load_thread_title()
        await self._emit(Text(f"> {message}", style="bold"))
        try:
            run = await asyncio.to_thread(
                self.client.start_run, self.thread_id, message
            )
        except CellWikiClientError as error:
            await self._emit(Text(str(error), style="red"))
            if error.status_code == 409:
                match = RUN_ID_PATTERN.search(str(error))
                if match:
                    await self._emit(
                        Text(
                            f"active run {match.group(0)} - /status to inspect",
                            style="yellow",
                        )
                    )
            return
        run_id = str(run.get("run_id") or "")
        if not run_id:
            await self._emit(Text("daemon returned a run without an id", style="red"))
            return
        self.last_run_id = run_id
        self.run_task = asyncio.create_task(self._drive_run(run_id))

    async def _load_thread_title(self) -> None:
        if self.client is None:
            return
        threads = await asyncio.to_thread(self.client.list_threads)
        for thread in threads:
            if str(thread.get("thread_id") or "") == self.thread_id:
                self.thread_title = str(thread.get("title") or "")
                return

    async def _drive_run(self, run_id: str) -> None:
        self.active_run_id = run_id
        self.run_status = "running"
        cursor = 0
        try:
            while True:
                if self._stream_mode == "sse":
                    outcome = await self._drive_sse(run_id, cursor)
                    if outcome == "gate":
                        return
                    cursor = outcome
                else:
                    outcome = await self._drive_poll(run_id, cursor)
                    if outcome == "gate":
                        return
                    cursor = outcome
                run = await asyncio.to_thread(self.client.get_run, run_id)
                if await self._maybe_open_gate_from_run(run):
                    return
                status = str(run.get("status") or "unknown")
                if status in renderer.TERMINAL_STATUSES:
                    await self._complete_run(run)
                    return
                await asyncio.sleep(0.25)
        except CellWikiClientError as error:
            await self._emit(
                Text(f"run {run_id} connection error: {error}", style="red")
            )
            self.run_status = "disconnected"
        except Exception as error:  # noqa: BLE001 - a broken driver must not kill TUI
            await self._emit(Text(f"unexpected TUI error: {error}", style="red"))
            self.run_status = "error"

    async def _drive_sse(self, run_id: str, cursor: int) -> int | Literal["gate"]:
        try:
            async for event in self.client.stream_events(run_id, after=cursor):
                cursor = max(cursor, int(event.get("sequence") or 0))
                await self._render_event(event)
                if await self._maybe_open_gate_from_event(event, run_id):
                    return "gate"
        except CellWikiClientError as error:
            if error.status_code == 404:
                raise
            await self._emit(
                Text(f"stream lost: {error}; reconnecting...", style="yellow")
            )
            if not await self._reconnect():
                self._stream_mode = "poll"
                await self._emit(
                    Text("SSE unavailable; falling back to polling", style="dim")
                )
        return cursor

    async def _drive_poll(self, run_id: str, cursor: int) -> int | Literal["gate"]:
        try:
            run = await asyncio.to_thread(self.client.get_run, run_id)
            events = await asyncio.to_thread(self.client.list_events, run_id, cursor)
        except CellWikiClientError as error:
            await self._emit(
                Text(f"poll failed: {error}; reconnecting...", style="yellow")
            )
            if not await self._reconnect():
                raise
            return cursor
        for event in events:
            cursor = max(cursor, int(event.get("sequence") or 0))
            await self._render_event(event)
            if await self._maybe_open_gate_from_event(event, run_id):
                return "gate"
        if str(run.get("status") or "") not in renderer.TERMINAL_STATUSES:
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
        return cursor

    async def _reconnect(self) -> bool:
        last_error: Exception | None = None
        for attempt in range(RECONNECT_ATTEMPTS):
            await asyncio.sleep(min(0.5 * (2**attempt), 4.0))
            try:
                self.client = await asyncio.to_thread(
                    self._client_factory, self.workspace
                )
                self.connected = True
                await self._emit(Text("reconnected", style="green"))
                return True
            except Exception as error:  # noqa: BLE001 - bounded reconnect loop
                last_error = error
        await self._emit(Text(f"reconnect failed: {last_error}", style="red"))
        return False

    async def _maybe_open_gate_from_event(
        self,
        event: dict[str, Any],
        run_id: str,
    ) -> bool:
        event_type = str(event.get("type") or "")
        data = event.get("data") or {}
        status = str(data.get("status") or "")
        if event_type == "task_confirmation_required" or (
            event_type == "run_status" and status == "waiting_confirmation"
        ):
            question = await asyncio.to_thread(self.client.get_question, run_id)
            if question:
                await self._open_question_gate(run_id, question)
                return True
        if event_type == "run_status" and status == "waiting_approval":
            run = await asyncio.to_thread(self.client.get_run, run_id)
            if run.get("pending_diff_id"):
                await self._open_diff_gate(run)
                return True
        if event_type in {"review_required", "changeset_ready"}:
            run = await asyncio.to_thread(self.client.get_run, run_id)
            if run.get("pending_diff_id"):
                await self._open_diff_gate(run)
                return True
        return False

    async def _maybe_open_gate_from_run(self, run: dict[str, Any]) -> bool:
        status = str(run.get("status") or "")
        run_id = str(run.get("run_id") or "")
        if status == "waiting_confirmation":
            question = await asyncio.to_thread(self.client.get_question, run_id)
            if question:
                await self._open_question_gate(run_id, question)
                return True
        if status == "waiting_approval" and run.get("pending_diff_id"):
            await self._open_diff_gate(run)
            return True
        return False

    async def _open_question_gate(
        self,
        run_id: str,
        question: dict[str, Any],
    ) -> None:
        self.run_status = "waiting_confirmation"
        for line in renderer.question_lines(question):
            await self._emit(line)
        self.gate = Gate("question", run_id, question=question)

    async def _open_diff_gate(self, run: dict[str, Any]) -> None:
        run_id = str(run.get("run_id") or "")
        diff_id = str(run.get("pending_diff_id") or "")
        patch = await asyncio.to_thread(self.client.pending_diff_patch, diff_id)
        self.pending_diff_id = diff_id
        self.run_status = "waiting_approval"
        for line in renderer.approval_lines(diff_id, patch):
            await self._emit(line)
        self.gate = Gate("diff", run_id, diff_id=diff_id)

    async def _complete_run(self, run: dict[str, Any]) -> None:
        self.active_run_id = None
        self.gate = None
        self.run_status = str(run.get("status") or "unknown")
        self.pending_diff_id = run.get("pending_diff_id") or None
        await self._emit(renderer.run_summary(run))
        await self._refresh_context()
        self.usage_label = ""
        if self.queue:
            message = self.queue.pop(0)
            await self._start_message(message)

    # ----------------------------------------------------------------- gates

    async def _handle_gate_input(self, text: str) -> None:
        gate = self.gate
        if gate is None:
            return
        if gate.kind == "diff":
            if text == "1":
                await self._resolve_diff(gate, accept=True)
            elif text == "2":
                await self._resolve_diff(gate, accept=False)
            elif text == "3":
                patch = await asyncio.to_thread(
                    self.client.pending_diff_patch, gate.diff_id or ""
                )
                for line in renderer.full_diff_lines(patch):
                    await self._emit(line)
                await self._emit(
                    Text("1 accept - 2 reject - Esc later", style="bold")
                )
            else:
                await self._emit(
                    Text(
                        "choose 1 accept, 2 reject, 3 view diff, or Esc later",
                        style="dim",
                    )
                )
            return
        question = gate.question or {}
        answer = self._question_answer(question, text)
        try:
            await asyncio.to_thread(
                self.client.answer_question, gate.run_id, answer
            )
        except CellWikiClientError as error:
            await self._emit(Text(str(error), style="red"))
        self.gate = None
        self._restart_driver(gate.run_id)

    @staticmethod
    def _question_answer(question: dict[str, Any], text: str) -> str:
        options = question.get("options") or []
        if text.isdigit():
            index = int(text) - 1
            if 0 <= index < len(options):
                label = str(options[index].get("label") or "").strip()
                if label:
                    return label
        return text

    async def _resolve_diff(self, gate: Gate, *, accept: bool) -> None:
        diff_id = gate.diff_id or ""
        try:
            if accept:
                await asyncio.to_thread(self.client.accept_pending_diff, diff_id)
                await self._emit(Text(f"accepted {diff_id}", style="green"))
            else:
                await asyncio.to_thread(self.client.reject_pending_diff, diff_id)
                await self._emit(Text(f"rejected {diff_id}", style="yellow"))
        except CellWikiClientError as error:
            await self._emit(Text(str(error), style="red"))
        self.gate = None
        self.pending_diff_id = None
        self._restart_driver(gate.run_id)

    def _restart_driver(self, run_id: str) -> None:
        self.run_task = asyncio.create_task(self._drive_run(run_id))

    async def _handle_escape(self) -> None:
        if self.gate is not None:
            gate = self.gate
            if gate.kind == "diff":
                self.gate = None
                await self._emit(
                    Text("approval deferred - /diff to review", style="yellow")
                )
                return
            try:
                await asyncio.to_thread(
                    self.client.answer_question,
                    gate.run_id,
                    None,
                    timed_out=True,
                )
            except CellWikiClientError as error:
                await self._emit(Text(str(error), style="red"))
            self.gate = None
            self._restart_driver(gate.run_id)
            return
        if self.active_run_id is not None:
            run_id = self.active_run_id
            try:
                await asyncio.to_thread(self.client.cancel_run, run_id)
                await self._emit(Text(f"interrupting {run_id}...", style="yellow"))
            except CellWikiClientError as error:
                await self._emit(Text(str(error), style="red"))

    # -------------------------------------------------------------- commands

    async def _handle_command(self, text: str) -> None:
        command, _, argument = text.partition(" ")
        command = command.strip()
        argument = argument.strip()
        if command == "/help":
            await self._print_help()
        elif command == "/quit":
            self._exiting = True
            await self._emit(Text("bye - the daemon keeps running", style="dim"))
        elif command == "/new":
            if self._run_active():
                await self._emit(
                    Text(
                        "a run is active; finish or interrupt it first",
                        style="yellow",
                    )
                )
            else:
                self.thread_id = None
                self.thread_title = ""
                self.context_label = ""
                await self._emit(Text("new conversation", style="dim"))
        elif command == "/resume":
            await self._resume_session(argument)
        elif command == "/clear":
            self.console.clear()
        elif command == "/status":
            await self._print_status()
        elif command == "/continue":
            await self._recover_run(resume=True)
        elif command == "/retry":
            await self._recover_run(resume=False)
        elif command == "/diff":
            if self.pending_diff_id:
                run = {
                    "run_id": self.active_run_id or self.last_run_id,
                    "pending_diff_id": self.pending_diff_id,
                }
                await self._open_diff_gate(run)
            else:
                await self._emit(Text("no pending diff", style="dim"))
        else:
            await self._emit(
                Text(f"unknown command: {command}; /help for the list", style="yellow")
            )

    async def _resume_session(self, argument: str) -> None:
        if self._run_active():
            await self._emit(
                Text("a run is active; finish or interrupt it first", style="yellow")
            )
            return
        threads = await asyncio.to_thread(self.client.list_threads)
        if not threads:
            await self._emit(Text("no conversations in this workspace", style="dim"))
            return
        for line in renderer.thread_lines(threads):
            await self._emit(line)
        choice = argument or await self._prompt_line("select session #> ")
        choice = choice.strip()
        if not choice:
            return
        try:
            index = int(choice) - 1
        except ValueError:
            await self._emit(Text("expected a session number", style="yellow"))
            return
        if not 0 <= index < len(threads):
            await self._emit(Text("session number out of range", style="yellow"))
            return
        thread = threads[index]
        self.thread_id = str(thread.get("thread_id") or "") or None
        self.thread_title = str(thread.get("title") or "")
        if self.thread_id:
            messages = await asyncio.to_thread(
                self.client.list_messages, self.thread_id
            )
            for line in renderer.message_lines(messages):
                await self._emit(line)
        await self._refresh_context()

    async def _recover_run(self, *, resume: bool) -> None:
        run_id = self.last_run_id
        if not run_id:
            await self._emit(Text("no run to recover", style="dim"))
            return
        if self._run_active():
            await self._emit(Text("a run is already active", style="yellow"))
            return
        try:
            run = await asyncio.to_thread(self.client.get_run, run_id)
        except CellWikiClientError as error:
            await self._emit(Text(str(error), style="red"))
            return
        status = str(run.get("status") or "")
        if resume and status == "unfinished":
            await asyncio.to_thread(self.client.resume_run, run_id)
            await self._emit(Text(f"resuming {run_id}", style="green"))
            self._restart_driver(run_id)
            return
        if not resume and run.get("retryable"):
            await asyncio.to_thread(self.client.retry_run, run_id)
            await self._emit(Text(f"retrying {run_id}", style="green"))
            self._restart_driver(run_id)
            return
        action = "resume" if resume else "retry"
        await self._emit(
            Text(f"run {run_id} is {status}; nothing to {action}", style="dim")
        )

    async def _print_status(self) -> None:
        await self._refresh_run_status()
        await self._refresh_context()
        lines = [
            Text(f"workspace: {self.workspace}"),
            Text(f"thread: {self.thread_title or self.thread_id or '(new)'}"),
            Text(f"model: {self.model_label}"),
            Text(
                f"run: {self.run_status}"
                + (f" ({self.active_run_id})" if self.active_run_id else "")
            ),
        ]
        if self.context_label:
            lines.append(Text(f"context: {self.context_label}"))
        if self.pending_diff_id:
            lines.append(Text(f"pending diff: {self.pending_diff_id} (/diff)"))
        for line in lines:
            await self._emit(line)

    async def _print_help(self) -> None:
        for line in (
            "/help            show this help",
            "/new             start a new conversation",
            "/resume [#]      list and switch conversations",
            "/clear           clear the screen (scrollback is kept)",
            "/status          workspace, model, run and context status",
            "/continue        resume an unfinished run",
            "/retry           retry a failed run",
            "/diff            reopen the pending diff approval",
            "/quit            leave the TUI (the daemon keeps running)",
            "Esc              interrupt the active run / defer a decision",
            "Enter            send; while a run is active, queue the message",
        ):
            await self._emit(Text(line))

    # -------------------------------------------------------------- refresh

    async def _refresh_model(self) -> None:
        try:
            catalog = await asyncio.to_thread(self.client.list_model_providers)
        except CellWikiClientError:
            return
        self.model_label = renderer.model_label(catalog)

    async def _refresh_context(self) -> None:
        if self.thread_id is None or self.client is None:
            self.context_label = ""
            return
        try:
            payload = await asyncio.to_thread(
                self.client.context_usage, self.thread_id
            )
        except CellWikiClientError:
            self.context_label = ""
            return
        self.context_label = renderer.context_label(payload)

    async def _refresh_run_status(self) -> None:
        run_id = self.active_run_id or self.last_run_id
        if not run_id or self.client is None:
            return
        try:
            run = await asyncio.to_thread(self.client.get_run, run_id)
        except CellWikiClientError:
            return
        self.run_status = str(run.get("status") or self.run_status)

    # -------------------------------------------------------------- render

    async def _render_event(self, event: dict[str, Any]) -> None:
        event_type = str(event.get("type") or "")
        message = str(event.get("message") or "")
        if event_type == "message_delta":
            if message:
                self._answer_buffer += message
                self._streamed_answer = True
                await self._write_chunk(message)
            return
        if event_type == "reasoning_delta":
            if message:
                if not self._reasoning_open:
                    await self._write_chunk("\u273b ", style="dim")
                    self._reasoning_open = True
                await self._write_chunk(message, style="dim")
            return
        if event_type == "final_response":
            await self._finish_answer(message)
            return
        if self._reasoning_open:
            await self._write_chunk("\n")
            self._reasoning_open = False
        if event_type == "usage_updated":
            self.usage_label = renderer.usage_label(event) or self.usage_label
            return
        line = renderer.event_line(event)
        if line is not None:
            await self._emit(line)

    async def _write_chunk(self, text: str, *, style: str | None = None) -> None:
        async with self._print_lock:
            self.console.print(Text(text, style=style) if style else Text(text), end="")

    async def _finish_answer(self, message: str) -> None:
        if message and not self._streamed_answer:
            self._answer_buffer = message
            await self._write_chunk(message)
        elif (
            message
            and self._answer_buffer != message
            and message.startswith(self._answer_buffer)
        ):
            remainder = message[len(self._answer_buffer) :]
            if remainder:
                await self._write_chunk(remainder)
                self._answer_buffer = message
        if self._answer_buffer or self._streamed_answer:
            await self._write_chunk("\n")
        self._answer_buffer = ""
        self._streamed_answer = False

    async def _emit(self, renderable: Text | str) -> None:
        async with self._print_lock:
            self.console.print(renderable)

    async def _emit_welcome(self) -> None:
        title = self.thread_title or self.thread_id or "(new conversation)"
        await self._emit(Text(f"CellWiki - {self.workspace.name}", style="bold"))
        await self._emit(
            Text(
                f"model {self.model_label} - thread {title} - /help for commands",
                style="dim",
            )
        )

    async def _prompt_line(self, message: str) -> str:
        if self._session is None:
            return ""
        return await self._session.prompt_async(message=message)


def run_tui(workspace: Path) -> None:
    """Run the terminal client for one workspace."""

    asyncio.run(CellWikiTui(workspace).run())
