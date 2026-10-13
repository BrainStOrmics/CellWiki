"""Textual terminal client for the local CellWiki daemon."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Callable, Literal

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    RichLog,
    Static,
    TextArea,
)

from cellwiki.tui.client import CellWikiClientError, DaemonClient


TERMINAL_STATUSES = {"succeeded", "failed", "cancelled", "unfinished", "rejected"}
POLL_INTERVAL_SECONDS = 0.25


class QuestionScreen(ModalScreen[str | None]):
    """Answer one ``ask_user_question`` prompt."""

    BINDINGS = [Binding("escape", "cancel", "Skip")]

    def __init__(self, question: dict[str, Any]) -> None:
        super().__init__()
        self._question = question

    def compose(self) -> ComposeResult:
        yield Label("CellWiki needs your decision", classes="modal-title")
        yield Static(str(self._question.get("question") or ""), id="question-text")
        with Vertical(id="question-options"):
            for index, option in enumerate(self._question.get("options") or []):
                label = str(option.get("label") or "").strip()
                if not label:
                    continue
                description = str(option.get("description") or "").strip()
                text = f"{label}: {description}" if description else label
                variant: Literal["default", "primary"] = (
                    "primary" if option.get("recommended") else "default"
                )
                yield Button(text, id=f"option-{index}", variant=variant)
        yield Input(placeholder="Type an answer and press Enter", id="free-text")
        yield Button("Skip (leave the run unfinished)", id="skip")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id == "skip":
            self.dismiss(None)
            return
        if button_id.startswith("option-"):
            index = int(button_id.split("-", 1)[1])
            options = self._question.get("options") or []
            if 0 <= index < len(options):
                self.dismiss(str(options[index].get("label") or ""))

    def on_input_submitted(self, event: Input.Submitted) -> None:
        value = event.value.strip()
        if value:
            self.dismiss(value)

    def action_cancel(self) -> None:
        self.dismiss(None)


class DiffScreen(ModalScreen[str | None]):
    """Review one pending diff and return accept, reject, or cancel."""

    BINDINGS = [
        Binding("a", "accept", "Accept"),
        Binding("r", "reject", "Reject"),
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, diff_id: str, patch: str) -> None:
        super().__init__()
        self._diff_id = diff_id
        self._patch = patch

    def compose(self) -> ComposeResult:
        yield Label(f"Pending diff {self._diff_id}", classes="modal-title")
        yield TextArea(self._patch, read_only=True, id="patch")
        with Horizontal(id="diff-actions"):
            yield Button("Accept", id="accept", variant="success")
            yield Button("Reject", id="reject", variant="error")
            yield Button("Cancel", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id)

    def action_accept(self) -> None:
        self.dismiss("accept")

    def action_reject(self) -> None:
        self.dismiss("reject")

    def action_cancel(self) -> None:
        self.dismiss(None)


class CellWikiTui(App[None]):
    """Conversation-first terminal client for one workspace daemon."""

    CSS = """
    #body { height: 1fr; }
    #threads { width: 34; border: solid $panel; }
    #conversation { width: 1fr; }
    #transcript { height: 1fr; }
    #live { min-height: 1; padding: 0 1; }
    #composer { dock: bottom; }
    #status { height: 1; padding: 0 1; color: $text-muted; }
    .modal-title { text-style: bold; padding: 1; }
    #question-text { padding: 0 1 1 1; }
    #question-options { height: auto; }
    #patch { height: 1fr; }
    #diff-actions { height: auto; }
    """

    BINDINGS = [
        Binding("ctrl+n", "new_thread", "New conversation"),
        Binding("ctrl+q", "quit_app", "Quit"),
    ]

    def __init__(
        self,
        workspace: Path,
        *,
        client_factory: Callable[[Path], Any] = DaemonClient.connect,
    ) -> None:
        super().__init__()
        self.workspace = Path(workspace).expanduser().resolve()
        self._client_factory = client_factory
        self.client: Any | None = None
        self.thread_id: str | None = None
        self.active_run_id: str | None = None
        self._thread_ids: list[str] = []
        self._event_cursor = 0
        self._answer_buffer = ""
        self._reviewed_diffs: set[str] = set()
        self.connected = False

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="body"):
            yield ListView(id="threads")
            with Vertical(id="conversation"):
                yield RichLog(id="transcript", markup=False, wrap=True)
                yield Static("", id="live", markup=False)
        yield Input(placeholder="Type a message and press Enter", id="composer")
        yield Static("Connecting to the CellWiki daemon...", id="status", markup=False)
        yield Footer()

    def on_mount(self) -> None:
        self.connect_daemon()

    @work(exclusive=True, group="connection")
    async def connect_daemon(self) -> None:
        try:
            self.client = await asyncio.to_thread(self._client_factory, self.workspace)
            self._set_status(f"Connected to {getattr(self.client, 'base_url', 'daemon')}")
            await self._load_threads()
            self.query_one("#composer", Input).focus()
            self.connected = True
        except Exception as error:  # noqa: BLE001 - startup must surface any failure
            self._set_status(f"Failed to connect: {error}")
            self.notify(str(error), severity="error", timeout=8)

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        message = event.value.strip()
        if not message or self.active_run_id is not None:
            return
        event.input.value = ""
        self.send_message(message)

    @work(exclusive=True, group="conversation")
    async def send_message(self, message: str) -> None:
        try:
            client = self._require_client()
            if self.thread_id is None:
                self.thread_id = await asyncio.to_thread(client.create_thread)
                await self._load_threads()
            transcript = self.query_one("#transcript", RichLog)
            transcript.write(f"You: {message}")
            run = await asyncio.to_thread(client.start_run, self.thread_id, message)
            await self._drive_run(str(run["run_id"]))
        except CellWikiClientError as error:
            self._set_status(str(error))
            self.notify(str(error), severity="error", timeout=8)

    async def _drive_run(self, run_id: str) -> None:
        client = self._require_client()
        self.active_run_id = run_id
        self._event_cursor = 0
        self._answer_buffer = ""
        self._reviewed_diffs = set()
        live = self.query_one("#live", Static)
        live.update("")
        status = "unknown"
        try:
            while True:
                run = await asyncio.to_thread(client.get_run, run_id)
                events = await asyncio.to_thread(
                    client.list_events, run_id, self._event_cursor
                )
                for event in events:
                    self._event_cursor = max(
                        self._event_cursor, int(event.get("sequence") or 0)
                    )
                    self._render_event(event, live)
                status = str(run.get("status") or "unknown")
                if status == "waiting_confirmation":
                    question = await asyncio.to_thread(client.get_question, run_id)
                    if question is not None:
                        answer = await self.push_screen_wait(QuestionScreen(question))
                        if answer is None:
                            await asyncio.to_thread(
                                client.answer_question, run_id, None, True
                            )
                        else:
                            await asyncio.to_thread(
                                client.answer_question, run_id, answer
                            )
                diff_id = run.get("pending_diff_id")
                if status == "waiting_approval" and diff_id:
                    diff_id = str(diff_id)
                    if diff_id not in self._reviewed_diffs:
                        self._reviewed_diffs.add(diff_id)
                        await self._review_diff(diff_id)
                if status in TERMINAL_STATUSES:
                    break
                await asyncio.sleep(POLL_INTERVAL_SECONDS)
        except CellWikiClientError as error:
            self._set_status(str(error))
            self.notify(str(error), severity="error", timeout=8)
        finally:
            if self._answer_buffer:
                self.query_one("#transcript", RichLog).write(
                    f"CellWiki: {self._answer_buffer}"
                )
            live.update("")
            self.active_run_id = None
            self._set_status(f"run {run_id}: {status}")
            if self.client is not None:
                try:
                    await self._load_threads()
                except CellWikiClientError:
                    pass

    async def _review_diff(self, diff_id: str) -> None:
        client = self._require_client()
        patch = await asyncio.to_thread(client.pending_diff_patch, diff_id)
        decision = await self.push_screen_wait(DiffScreen(diff_id, patch))
        if decision == "accept":
            await asyncio.to_thread(client.accept_pending_diff, diff_id)
            self._set_status(f"accepted {diff_id}")
        elif decision == "reject":
            await asyncio.to_thread(client.reject_pending_diff, diff_id)
            self._set_status(f"rejected {diff_id}")
        else:
            self._set_status(f"pending diff left undecided: {diff_id}")

    def _render_event(self, event: dict[str, Any], live: Static) -> None:
        event_type = str(event.get("type") or "")
        message = str(event.get("message") or "")
        data = event.get("data") or {}
        transcript = self.query_one("#transcript", RichLog)
        if event_type == "message_delta":
            self._answer_buffer += message
            live.update(self._answer_buffer)
        elif event_type == "final_response":
            if message:
                self._answer_buffer = message
            live.update(self._answer_buffer)
        elif event_type == "tool_started":
            transcript.write(f"[tool] {data.get('tool_name') or '?'} started")
        elif event_type == "tool_completed":
            transcript.write(f"[tool] {data.get('tool_name') or '?'} completed")
        elif event_type == "error":
            transcript.write(f"[error] {message}")

    async def _load_threads(self) -> None:
        client = self._require_client()
        threads = await asyncio.to_thread(client.list_threads)
        self._thread_ids = [
            str(thread.get("thread_id")) for thread in threads if thread.get("thread_id")
        ]
        view = self.query_one("#threads", ListView)
        view.clear()
        for thread in threads:
            title = str(thread.get("title") or thread.get("thread_id") or "Conversation")
            view.append(ListItem(Label(title)))
        if self._thread_ids:
            self.thread_id = self._thread_ids[0]
            view.index = 0
            await self._load_messages()
        else:
            self.query_one("#transcript", RichLog).clear()

    async def _load_messages(self) -> None:
        if self.thread_id is None:
            return
        client = self._require_client()
        messages = await asyncio.to_thread(client.list_messages, self.thread_id)
        transcript = self.query_one("#transcript", RichLog)
        transcript.clear()
        for message in messages[-80:]:
            role = message.get("role")
            content = str(message.get("content") or "")
            if role == "user" and content:
                transcript.write(f"You: {content}")
            elif role == "assistant" and content:
                transcript.write(f"CellWiki: {content}")

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        index = event.index
        if index is not None and 0 <= index < len(self._thread_ids):
            self.thread_id = self._thread_ids[index]
            await self._load_messages()

    def action_new_thread(self) -> None:
        if self.active_run_id is not None:
            self.notify("A run is active; wait for it to finish.", severity="warning")
            return
        self.thread_id = None
        self.query_one("#transcript", RichLog).clear()
        self.query_one("#live", Static).update("")
        self._set_status("New conversation")

    def action_quit_app(self) -> None:
        self.exit()

    def _require_client(self) -> Any:
        if self.client is None:
            raise CellWikiClientError("not connected to the CellWiki daemon")
        return self.client

    def _set_status(self, text: str) -> None:
        self.query_one("#status", Static).update(text)


def run_tui(workspace: Path) -> None:
    """Run the terminal client for one workspace."""

    CellWikiTui(workspace).run()
