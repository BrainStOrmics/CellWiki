import { DaemonClient, DaemonRequestError } from "./api/client";
import type {
  AgentEvent,
  AgentRun,
  ContextUsage,
  MessageRecord,
  ModelCatalog,
  PendingQuestion,
  ThreadRecord,
} from "./api/types";
import { parseCommand } from "./commands";
import {
  DaemonVersionMismatch,
  ensureDaemon,
  readControlToken,
  restartDaemon,
  workspaceStateDir,
} from "./daemon/discovery";
import { listWorkspaceFiles } from "./workspace/files";

export interface ClientLike {
  listThreads(): Promise<ThreadRecord[]>;
  createThread(): Promise<string>;
  listMessages(threadId: string): Promise<MessageRecord[]>;
  startRun(
    threadId: string,
    message: string,
    requestId: string,
  ): Promise<AgentRun>;
  getRun(runId: string): Promise<AgentRun>;
  listEvents(runId: string, after?: number): Promise<AgentEvent[]>;
  getQuestion(runId: string): Promise<PendingQuestion | null>;
  answerQuestion(
    runId: string,
    answers: string | string[] | null,
    timedOut?: boolean,
  ): Promise<AgentRun>;
  cancelRun(runId: string): Promise<AgentRun>;
  retryRun(runId: string): Promise<AgentRun>;
  resumeRun(runId: string): Promise<AgentRun>;
  pendingDiffPatch(diffId: string): Promise<string>;
  acceptPendingDiff(diffId: string): Promise<unknown>;
  rejectPendingDiff(diffId: string): Promise<unknown>;
  listModelProviders(): Promise<ModelCatalog>;
  contextUsage(threadId: string): Promise<ContextUsage>;
  streamEvents(
    runId: string,
    after?: number,
    signal?: AbortSignal,
  ): AsyncGenerator<AgentEvent>;
}

export interface ToolState {
  id: string;
  name: string;
  summary: string;
  status: "running" | "completed" | "failed";
  result?: string;
}

export type Gate =
  | { kind: "diff"; runId: string; diffId: string; patch: string }
  | { kind: "question"; runId: string; question: PendingQuestion };

export type Tone =
  | "user"
  | "assistant"
  | "tool"
  | "error"
  | "dim"
  | "success"
  | "warning";

export interface TranscriptLine {
  id: number;
  text: string;
  tone?: Tone;
}

export interface TuiState {
  workspace: string;
  connected: boolean;
  connecting: boolean;
  modelLabel: string;
  threadId: string | null;
  threadTitle: string;
  threads: ThreadRecord[];
  runId: string | null;
  lastRunId: string | null;
  runStatus: string;
  cursor: number;
  streaming: string;
  reasoning: string;
  tools: ToolState[];
  toolHistory: ToolState[];
  verbose: boolean;
  gate: Gate | null;
  pendingDiffId: string | null;
  queue: string[];
  transcript: TranscriptLine[];
  contextLabel: string;
  usageLabel: string;
  error: string | null;
  versionMismatch: DaemonVersionMismatch | null;
  exitRequested: boolean;
}

export interface ControllerOptions {
  clientFactory?: () => Promise<ClientLike>;
  restart?: () => Promise<void>;
  sleep?: (ms: number) => Promise<void>;
}

const TERMINAL_STATUSES = new Set([
  "succeeded",
  "failed",
  "cancelled",
  "unfinished",
  "rejected",
]);
const RECONNECT_ATTEMPTS = 5;

export class TuiController {
  readonly workspace: string;
  state: TuiState;

  private client: ClientLike | null = null;
  private readonly listeners = new Set<() => void>();
  private readonly options: ControllerOptions;
  private readonly sleep: (ms: number) => Promise<void>;
  private runTask: Promise<void> | null = null;
  private driverRunning = false;
  private streamMode: "sse" | "poll" = "sse";
  private nextLineId = 1;
  private abortController: AbortController | null = null;
  private fileCache: string[] | null = null;

  constructor(workspace: string, options: ControllerOptions = {}) {
    this.workspace = workspace;
    this.options = options;
    this.sleep =
      options.sleep ?? ((ms) => new Promise((resolve) => setTimeout(resolve, ms)));
    this.state = {
      workspace,
      connected: false,
      connecting: false,
      modelLabel: "unknown",
      threadId: null,
      threadTitle: "",
      threads: [],
      runId: null,
      lastRunId: null,
      runStatus: "idle",
      cursor: 0,
      streaming: "",
      reasoning: "",
      tools: [],
      toolHistory: [],
      verbose: false,
      gate: null,
      pendingDiffId: null,
      queue: [],
      transcript: [],
      contextLabel: "",
      usageLabel: "",
      error: null,
      versionMismatch: null,
      exitRequested: false,
    };
  }

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  getSnapshot = (): TuiState => this.state;

  async connect(): Promise<void> {
    this.update({ connecting: true, error: null });
    try {
      this.client = await this.createClient();
      const threads = await this.client.listThreads();
      const latest = threads[0] ?? null;
      this.update({
        connected: true,
        connecting: false,
        threads,
        threadId: latest?.thread_id ?? null,
        threadTitle: latest?.title ?? "",
        versionMismatch: null,
      });
      await this.refreshModel();
      await this.refreshContext();
    } catch (error) {
      if (error instanceof DaemonVersionMismatch) {
        this.update({ connecting: false, versionMismatch: error });
        return;
      }
      this.update({
        connecting: false,
        connected: false,
        error: error instanceof Error ? error.message : String(error),
      });
    }
  }

  async restart(): Promise<void> {
    this.update({ connecting: true, error: null });
    try {
      if (this.options.restart) {
        await this.options.restart();
      } else {
        await restartDaemon(this.workspace);
      }
      this.update({ versionMismatch: null });
      await this.connect();
    } catch (error) {
      this.update({
        connecting: false,
        error: error instanceof Error ? error.message : String(error),
      });
    }
  }

  async submit(raw: string): Promise<void> {
    const text = raw.trim();
    if (!text) {
      return;
    }
    if (this.state.gate) {
      await this.handleGateInput(text);
      return;
    }
    if (text.startsWith("/")) {
      await this.handleCommand(text);
      return;
    }
    if (this.runActive()) {
      this.update({ queue: [...this.state.queue, text] });
      return;
    }
    await this.startMessage(text);
  }

  withdrawQueued(): string | null {
    const queue = [...this.state.queue];
    const message = queue.pop() ?? null;
    this.update({ queue });
    return message;
  }

  toggleVerbose(): void {
    this.update({ verbose: !this.state.verbose });
  }

  mentionCandidates(query: string): string[] {
    this.fileCache ??= listWorkspaceFiles(this.workspace);
    const normalized = query.toLowerCase();
    return this.fileCache
      .filter((file) => file.toLowerCase().includes(normalized))
      .slice(0, 8);
  }

  async escape(): Promise<void> {
    const gate = this.state.gate;
    if (gate) {
      if (gate.kind === "diff") {
        this.update({ gate: null });
        this.commit("approval deferred - /diff to review", "warning");
        return;
      }
      try {
        await this.requireClient().answerQuestion(gate.runId, null, true);
      } catch (error) {
        this.reportError(error);
      }
      this.update({ gate: null });
      this.startDriver(gate.runId);
      return;
    }
    if (this.state.runId) {
      try {
        await this.requireClient().cancelRun(this.state.runId);
        this.commit(`interrupting ${this.state.runId}...`, "warning");
      } catch (error) {
        this.reportError(error);
      }
    }
  }

  requestExit(): void {
    this.update({ exitRequested: true });
  }

  async waitIdle(timeoutMs = 10_000): Promise<boolean> {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      const busy = this.driverRunning || this.state.queue.length > 0;
      if (!busy) {
        return true;
      }
      await this.sleep(10);
    }
    return false;
  }

  private async createClient(): Promise<ClientLike> {
    if (this.options.clientFactory) {
      return this.options.clientFactory();
    }
    const coordinates = await ensureDaemon(this.workspace);
    const token = readControlToken(workspaceStateDir(coordinates.workspace));
    if (!token) {
      throw new Error("the CellWiki daemon control token is missing");
    }
    return new DaemonClient(`http://127.0.0.1:${coordinates.port}`, token);
  }

  private requireClient(): ClientLike {
    if (!this.client) {
      throw new Error("not connected to the CellWiki daemon");
    }
    return this.client;
  }

  private runActive(): boolean {
    return this.state.runId !== null;
  }

  private update(patch: Partial<TuiState>): void {
    this.state = { ...this.state, ...patch };
    for (const listener of this.listeners) {
      listener();
    }
  }

  private commit(text: string, tone?: Tone): void {
    const line: TranscriptLine = { id: this.nextLineId++, text, tone };
    this.update({ transcript: [...this.state.transcript, line] });
  }

  private reportError(error: unknown): void {
    const message = error instanceof Error ? error.message : String(error);
    this.update({ error: message });
    this.commit(message, "error");
  }

  private async refreshModel(): Promise<void> {
    try {
      const catalog = await this.requireClient().listModelProviders();
      this.update({ modelLabel: formatModelLabel(catalog) });
    } catch {
      // model display is best effort
    }
  }

  private async refreshContext(): Promise<void> {
    const threadId = this.state.threadId;
    if (!threadId) {
      this.update({ contextLabel: "" });
      return;
    }
    try {
      const usage = await this.requireClient().contextUsage(threadId);
      this.update({ contextLabel: formatContextLabel(usage) });
    } catch {
      this.update({ contextLabel: "" });
    }
  }

  private async startMessage(message: string): Promise<void> {
    try {
      const client = this.requireClient();
      let threadId = this.state.threadId;
      if (!threadId) {
        threadId = await client.createThread();
        this.update({ threadId, threadTitle: "" });
      }
      this.commit(`> ${message}`, "user");
      const run = await client.startRun(
        threadId,
        message,
        `tui_${Date.now()}_${Math.random().toString(16).slice(2)}`,
      );
      this.update({
        runId: run.run_id,
        lastRunId: run.run_id,
        runStatus: "running",
        cursor: 0,
        streaming: "",
        reasoning: "",
        tools: [],
        error: null,
      });
      this.startDriver(run.run_id);
    } catch (error) {
      if (error instanceof DaemonRequestError && error.status === 409) {
        const match = /run_[A-Za-z0-9_]+/.exec(error.message);
        this.reportError(
          match
            ? `${error.message} (active run ${match[0]}; /status to inspect)`
            : error,
        );
        return;
      }
      this.reportError(error);
    }
  }

  private startDriver(runId: string): void {
    this.driverRunning = true;
    this.runTask = this.driveRun(runId).finally(() => {
      this.driverRunning = false;
    });
  }

  private async driveRun(runId: string): Promise<void> {
    while (true) {
      const gateOpened = await this.driveOnce(runId);
      if (gateOpened) {
        return;
      }
      let run: AgentRun;
      try {
        run = await this.requireClient().getRun(runId);
      } catch (error) {
        this.reportError(error);
        return;
      }
      if (await this.openGateFromRun(run)) {
        return;
      }
      if (TERMINAL_STATUSES.has(run.status)) {
        await this.completeRun(run);
        return;
      }
      await this.sleep(250);
    }
  }

  private async driveOnce(runId: string): Promise<boolean> {
    if (this.streamMode === "poll") {
      return this.pollOnce(runId);
    }
    const cursor = this.state.cursor;
    this.abortController = new AbortController();
    try {
      for await (const event of this.requireClient().streamEvents(
        runId,
        cursor,
        this.abortController.signal,
      )) {
        if (await this.applyEvent(event)) {
          return true;
        }
      }
    } catch (error) {
      if (error instanceof DaemonRequestError && error.status === 404) {
        this.reportError(error);
        return false;
      }
      this.commit("stream lost; reconnecting...", "warning");
      if (!(await this.reconnect())) {
        this.streamMode = "poll";
        this.commit("SSE unavailable; falling back to polling", "dim");
      }
    } finally {
      this.abortController = null;
    }
    return false;
  }

  private async pollOnce(runId: string): Promise<boolean> {
    const client = this.requireClient();
    let run: AgentRun;
    try {
      run = await client.getRun(runId);
      const events = await client.listEvents(runId, this.state.cursor);
      for (const event of events) {
        if (await this.applyEvent(event)) {
          return true;
        }
      }
    } catch (error) {
      this.reportError(error);
      return false;
    }
    if (!TERMINAL_STATUSES.has(run.status)) {
      await this.sleep(500);
    }
    return false;
  }

  private async reconnect(): Promise<boolean> {
    for (let attempt = 0; attempt < RECONNECT_ATTEMPTS; attempt += 1) {
      await this.sleep(Math.min(500 * 2 ** attempt, 4_000));
      try {
        this.client = await this.createClient();
        this.commit("reconnected", "success");
        return true;
      } catch {
        // keep retrying within the bound
      }
    }
    this.commit("reconnect failed", "error");
    return false;
  }

  private async applyEvent(event: AgentEvent): Promise<boolean> {
    this.update({ cursor: Math.max(this.state.cursor, event.sequence) });
    const message = event.message ?? "";
    const data = event.data ?? {};
    switch (event.type) {
      case "message_delta":
        this.update({ streaming: this.state.streaming + message });
        return false;
      case "reasoning_delta":
        this.update({ reasoning: this.state.reasoning + message });
        return false;
      case "final_response": {
        const answer =
          message || this.state.streaming || "";
        if (answer) {
          this.commit(answer, "assistant");
        }
        this.update({ streaming: "", reasoning: "" });
        return false;
      }
      case "tool_started": {
        const id = String(data.tool_call_id ?? event.sequence);
        const name = String(data.tool_name ?? "tool");
        this.update({
          tools: [
            ...this.state.tools,
            { id, name, summary: message || name, status: "running" },
          ],
        });
        return false;
      }
      case "tool_completed":
      case "tool_failed": {
        const id = String(data.tool_call_id ?? event.sequence);
        const tools = this.state.tools.filter((tool) => tool.id !== id);
        const failed = event.type === "tool_failed";
        const completed: ToolState = {
          id,
          name: String(data.tool_name ?? "tool"),
          summary: message || "tool finished",
          status: failed ? "failed" : "completed",
          result: message,
        };
        this.update({
          tools,
          toolHistory: [...this.state.toolHistory, completed].slice(-20),
        });
        this.commit(
          `${failed ? "x" : "+"} ${message || "tool finished"}`,
          failed ? "error" : "tool",
        );
        return false;
      }
      case "run_status": {
        const status = String(data.status ?? "");
        if (status) {
          this.update({ runStatus: status });
        }
        if (status === "waiting_confirmation") {
          const question = await this.requireClient().getQuestion(event.run_id);
          if (question) {
            this.update({
              gate: { kind: "question", runId: event.run_id, question },
            });
            return true;
          }
        }
        if (status === "waiting_approval") {
          const run = await this.requireClient().getRun(event.run_id);
          if (run.pending_diff_id) {
            await this.openDiffGate(event.run_id, run.pending_diff_id);
            return true;
          }
        }
        return false;
      }
      case "usage_updated": {
        const cumulative = (data.cumulative ?? {}) as Record<string, unknown>;
        const input = Number(cumulative.input_tokens ?? 0);
        const output = Number(cumulative.output_tokens ?? 0);
        if (input || output) {
          this.update({ usageLabel: `tokens ${input}/${output}` });
        }
        return false;
      }
      case "context_compaction_started":
        this.commit("... compacting context", "dim");
        return false;
      case "context_compaction_completed":
        this.commit("... context compaction finished", "dim");
        return false;
      case "progress":
        this.commit(`... ${message || "working"}`, "dim");
        return false;
      case "error":
        this.commit(`error: ${formatProviderError(message)}`, "error");
        return false;
      default:
        return false;
    }
  }

  private async openGateFromRun(run: AgentRun): Promise<boolean> {
    if (run.status === "waiting_confirmation") {
      const question = await this.requireClient().getQuestion(run.run_id);
      if (question) {
        this.update({
          gate: { kind: "question", runId: run.run_id, question },
        });
        return true;
      }
    }
    if (run.status === "waiting_approval" && run.pending_diff_id) {
      await this.openDiffGate(run.run_id, run.pending_diff_id);
      return true;
    }
    return false;
  }

  private async openDiffGate(runId: string, diffId: string): Promise<void> {
    const patch = await this.requireClient().pendingDiffPatch(diffId);
    this.update({
      pendingDiffId: diffId,
      runStatus: "waiting_approval",
      gate: { kind: "diff", runId, diffId, patch },
    });
  }

  private async completeRun(run: AgentRun): Promise<void> {
    this.update({
      runId: null,
      runStatus: run.status,
      gate: null,
      pendingDiffId: run.pending_diff_id ?? null,
      streaming: "",
      reasoning: "",
      tools: [],
    });
    this.commit(formatRunSummary(run), run.status === "failed" ? "error" : "dim");
    await this.refreshContext();
    this.update({ usageLabel: "" });
    const queue = [...this.state.queue];
    const next = queue.shift();
    if (next !== undefined) {
      this.update({ queue });
      await this.startMessage(next);
    }
  }

  private async handleGateInput(text: string): Promise<void> {
    const gate = this.state.gate;
    if (!gate) {
      return;
    }
    if (gate.kind === "diff") {
      if (text === "1") {
        try {
          await this.requireClient().acceptPendingDiff(gate.diffId);
          this.commit(`accepted ${gate.diffId}`, "success");
        } catch (error) {
          this.reportError(error);
        }
        this.update({ gate: null, pendingDiffId: null });
        this.startDriver(gate.runId);
        return;
      }
      if (text === "2") {
        try {
          await this.requireClient().rejectPendingDiff(gate.diffId);
          this.commit(`rejected ${gate.diffId}`, "warning");
        } catch (error) {
          this.reportError(error);
        }
        this.update({ gate: null, pendingDiffId: null });
        this.startDriver(gate.runId);
        return;
      }
      if (text === "3") {
        this.commit(gate.patch, "dim");
        return;
      }
      this.commit("choose 1 accept, 2 reject, 3 view diff, or Esc later", "dim");
      return;
    }
    const options = gate.question.options ?? [];
    let answer = text;
    if (/^\d+$/.test(text)) {
      const index = Number(text) - 1;
      const option = options[index];
      if (option?.label) {
        answer = option.label;
      }
    }
    try {
      await this.requireClient().answerQuestion(gate.runId, answer);
    } catch (error) {
      this.reportError(error);
    }
    this.update({ gate: null });
    this.startDriver(gate.runId);
  }

  private async handleCommand(text: string): Promise<void> {
    const parsed = parseCommand(text);
    if (!parsed) {
      return;
    }
    switch (parsed.name) {
      case "/help":
        for (const line of HELP_LINES) {
          this.commit(line, "dim");
        }
        return;
      case "/new":
        if (this.runActive()) {
          this.commit("a run is active; finish or interrupt it first", "warning");
          return;
        }
        this.update({ threadId: null, threadTitle: "", contextLabel: "" });
        this.commit("new conversation", "dim");
        return;
      case "/resume":
        await this.resumeSession(parsed.argument);
        return;
      case "/clear":
        this.update({ transcript: [] });
        return;
      case "/status":
        await this.printStatus();
        return;
      case "/continue":
        await this.recoverRun(true);
        return;
      case "/retry":
        await this.recoverRun(false);
        return;
      case "/diff":
        if (this.state.pendingDiffId) {
          await this.openDiffGate(
            this.state.runId ?? "",
            this.state.pendingDiffId,
          );
        } else {
          this.commit("no pending diff", "dim");
        }
        return;
      case "/model": {
        const catalog = await this.requireClient().listModelProviders();
        const selection = catalog.default_selection;
        this.commit(
          `model: ${formatModelLabel(catalog)}${
            selection?.model_id ? " (default selection)" : ""
          }`,
        );
        return;
      }
      case "/context": {
        await this.refreshContext();
        this.commit(`context: ${this.state.contextLabel || "unknown"}`, "dim");
        return;
      }
      case "/quit":
        this.requestExit();
        return;
      default:
        this.commit(`unknown command: ${parsed.name}; /help for the list`, "warning");
    }
  }

  private async resumeSession(argument: string): Promise<void> {
    if (this.runActive()) {
      this.commit("a run is active; finish or interrupt it first", "warning");
      return;
    }
    const threads = await this.requireClient().listThreads();
    if (threads.length === 0) {
      this.commit("no conversations in this workspace", "dim");
      return;
    }
    threads.forEach((thread, index) => {
      this.commit(
        `  ${index + 1}. ${thread.title || thread.thread_id}  [${
          thread.latest_status ?? "no runs"
        }]`,
        "dim",
      );
    });
    if (!argument) {
      return;
    }
    const index = Number(argument) - 1;
    const thread = threads[index];
    if (!thread) {
      this.commit("session number out of range", "warning");
      return;
    }
    this.update({
      threadId: thread.thread_id,
      threadTitle: thread.title ?? "",
      transcript: [],
    });
    const messages = await this.requireClient().listMessages(thread.thread_id);
    for (const message of messages.slice(-20)) {
      if (message.role === "user" && message.content) {
        this.commit(`> ${message.content}`, "user");
      } else if (message.role === "assistant" && message.content) {
        this.commit(message.content, "assistant");
      }
    }
    await this.refreshContext();
  }

  private async recoverRun(resume: boolean): Promise<void> {
    const runId = this.state.runId ?? this.state.lastRunId;
    if (!runId) {
      this.commit("no run to recover", "dim");
      return;
    }
    if (this.runActive()) {
      this.commit("a run is already active", "warning");
      return;
    }
    const run = await this.requireClient().getRun(runId);
    if (resume && run.status === "unfinished") {
      await this.requireClient().resumeRun(runId);
      this.update({ runId, runStatus: "running" });
      this.startDriver(runId);
      return;
    }
    if (!resume && run.retryable) {
      await this.requireClient().retryRun(runId);
      this.update({ runId, runStatus: "retrying" });
      this.startDriver(runId);
      return;
    }
    this.commit(
      `run ${runId} is ${run.status}; nothing to ${resume ? "resume" : "retry"}`,
      "dim",
    );
  }

  private async printStatus(): Promise<void> {
    await this.refreshContext();
    this.commit(`workspace: ${this.state.workspace}`, "dim");
    this.commit(
      `thread: ${this.state.threadTitle || this.state.threadId || "(new)"}`,
      "dim",
    );
    this.commit(`model: ${this.state.modelLabel}`, "dim");
    this.commit(
      `run: ${this.state.runStatus}${this.state.runId ? ` (${this.state.runId})` : ""}`,
      "dim",
    );
    if (this.state.contextLabel) {
      this.commit(`context: ${this.state.contextLabel}`, "dim");
    }
    if (this.state.pendingDiffId) {
      this.commit(`pending diff: ${this.state.pendingDiffId} (/diff)`, "dim");
    }
  }
}

const HELP_LINES = [
  "/help            show this help",
  "/new             start a new conversation",
  "/resume [#]      list and switch conversations",
  "/clear           clear the transcript view",
  "/status          workspace, model, run and context status",
  "/continue        resume an unfinished run",
  "/retry           retry a failed run",
  "/diff            reopen the pending diff approval",
  "/model           show the default model",
  "/context         show context usage",
  "/quit            leave the TUI (the daemon keeps running)",
  "Esc              interrupt the active run / defer a decision",
  "Enter            send; while a run is active, queue the message",
];

export function formatModelLabel(catalog: ModelCatalog): string {
  const selection = catalog.default_selection;
  if (!selection?.model_id) {
    return "legacy .env";
  }
  return selection.provider_id
    ? `${selection.provider_id}/${selection.model_id}`
    : selection.model_id;
}

export function formatContextLabel(usage: ContextUsage): string {
  const used = usage.used_tokens ?? 0;
  return used > 0 ? `ctx ${Math.round(used / 1000)}k` : "";
}

export function formatRunSummary(run: AgentRun): string {
  const parts = [`run ${run.run_id}: ${run.status}`];
  const input = run.usage?.input_tokens ?? 0;
  const output = run.usage?.output_tokens ?? 0;
  if (input || output) {
    parts.push(`tokens ${input}/${output}`);
  }
  if (run.error_message) {
    parts.push(formatProviderError(run.error_message));
  }
  return parts.join(" · ");
}

export function formatProviderError(message: string): string {
  const text = (message ?? "").trim();
  if (!text) {
    return "";
  }
  const dataMatch = /(?:^|\n)data:\s*(\{[\s\S]*\})\s*$/.exec(text);
  if (dataMatch?.[1]) {
    try {
      const payload = JSON.parse(dataMatch[1]) as Record<string, unknown>;
      const code = typeof payload.code === "string" ? payload.code : "";
      const detail = typeof payload.message === "string" ? payload.message : "";
      if (detail) {
        return truncate(code ? `${detail} (${code})` : detail);
      }
    } catch {
      // fall through to the framing-stripping path
    }
  }
  const lines = text
    .split("\n")
    .map((line) => line.trim())
    .filter(
      (line) =>
        line &&
        !line.startsWith("id:") &&
        !line.startsWith("event:") &&
        !line.startsWith(":HTTP_STATUS") &&
        !line.startsWith("data:"),
    );
  const collapsed = lines.join(" ").replace(/\s+/g, " ").trim();
  return truncate(collapsed || text);
}

function truncate(value: string, limit = 300): string {
  return value.length > limit ? `${value.slice(0, limit)}…` : value;
}
