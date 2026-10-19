import { DaemonRequestError } from "../src/api/client";
import type {
  AgentEvent,
  AgentRun,
  ContextUsage,
  MessageRecord,
  ModelCatalog,
  ModelSelection,
  PendingDiffSummary,
  PendingQuestion,
  ThreadRecord,
} from "../src/api/types";
import type { ClientLike } from "../src/controller";

export interface FakeClientOptions {
  events?: Record<string, AgentEvent[]>;
  question?: PendingQuestion | null;
  patch?: string;
  pendingDiffs?: PendingDiffSummary[];
  /** When set, listPendingDiffs returns this instead of pendingDiffs
   * (models a lagging list while getPendingDiff sees the real record). */
  pendingDiffListOverride?: PendingDiffSummary[];
  /** Hides pendingDiffs from listPendingDiffs until this many list calls have
   * happened (models the runtime publishing a diff after the run settles). */
  pendingDiffVisibleAfter?: number;
  failStreamOnce?: boolean;
  threads?: ThreadRecord[];
  /** Runs the daemon would report as occupying the workspace's serial gate. */
  blockingRuns?: AgentRun[];
}

export class FakeClient implements ClientLike {
  private runs: AgentRun[];
  private current: AgentRun;
  private events: Record<string, AgentEvent[]>;
  private question: PendingQuestion | null;
  patch: string;
  pendingDiffs: PendingDiffSummary[];
  private pendingDiffListOverride: PendingDiffSummary[] | undefined;
  private pendingDiffVisibleAfter: number | undefined;
  private pendingDiffListCalls = 0;
  private failStreamOnce: boolean;
  threads: ThreadRecord[];
  blockingRuns: AgentRun[];
  messages: Record<string, MessageRecord[]>;
  started: Array<[string, string]> = [];
  models: Array<ModelSelection | null> = [];
  answers: Array<[unknown, boolean]> = [];
  accepted: string[] = [];
  rejected: string[] = [];
  cancelled: string[] = [];
  retried: string[] = [];
  resumed: string[] = [];
  streamCalls = 0;
  createdThreads = 0;

  constructor(runs: AgentRun[], options: FakeClientOptions = {}) {
    this.runs = runs.map((run) => ({ ...run }));
    this.current = { ...this.runs[0]! };
    this.events = options.events ?? {};
    this.question = options.question ?? null;
    this.patch =
      options.patch ??
      [
        "diff --git a/wiki/x.md b/wiki/x.md",
        "--- a/wiki/x.md",
        "+++ b/wiki/x.md",
        "@@ -1 +1 @@",
        "-old",
        "+new",
        "",
      ].join("\n");
    this.pendingDiffs = options.pendingDiffs ?? [];
    this.pendingDiffListOverride = options.pendingDiffListOverride;
    this.pendingDiffVisibleAfter = options.pendingDiffVisibleAfter;
    this.failStreamOnce = options.failStreamOnce ?? false;
    this.threads = options.threads ?? [
      {
        thread_id: "thread_1",
        title: "First",
        latest_status: "succeeded",
        updated_at: "2026-10-16T10:00:00",
      },
    ];
    this.blockingRuns = options.blockingRuns ?? [];
    this.messages = {
      thread_1: [
        { role: "user", content: "hello" },
        { role: "assistant", content: "hi" },
      ],
    };
  }

  async listThreads(): Promise<ThreadRecord[]> {
    return this.threads.map((thread) => ({ ...thread }));
  }

  async createThread(): Promise<string> {
    this.createdThreads += 1;
    return "thread_new";
  }

  async listMessages(threadId: string): Promise<MessageRecord[]> {
    return this.messages[threadId] ?? [];
  }

  async startRun(
    threadId: string,
    message: string,
    _requestId: string,
    model?: ModelSelection | null,
  ): Promise<AgentRun> {
    this.started.push([threadId, message]);
    this.models.push(model ?? null);
    return {
      run_id: `run_${this.started.length}`,
      thread_id: threadId,
      status: "running",
    };
  }

  async getRun(runId: string): Promise<AgentRun> {
    const blocking = this.blockingRuns.find((run) => run.run_id === runId);
    if (blocking) {
      return { ...blocking };
    }
    if (this.runs.length > 0) {
      this.current = { ...this.runs.shift()! };
    }
    return { ...this.current, run_id: runId };
  }

  async listRuns(limit = 20): Promise<AgentRun[]> {
    return this.blockingRuns.slice(0, limit).map((run) => ({ ...run }));
  }

  async listEvents(runId: string, after = 0): Promise<AgentEvent[]> {
    return (this.events[runId] ?? []).filter((event) => event.sequence > after);
  }

  async getQuestion(runId: string): Promise<PendingQuestion | null> {
    return this.question ? { ...this.question, run_id: runId } : null;
  }

  async answerQuestion(
    runId: string,
    answers: string | string[] | null,
    timedOut = false,
  ): Promise<AgentRun> {
    this.answers.push([answers, timedOut]);
    this.question = null;
    return { run_id: runId, thread_id: "thread_1", status: "running" };
  }

  async cancelRun(runId: string): Promise<AgentRun> {
    this.cancelled.push(runId);
    return { run_id: runId, thread_id: "thread_1", status: "cancelling" };
  }

  async retryRun(runId: string): Promise<AgentRun> {
    this.retried.push(runId);
    return { run_id: runId, thread_id: "thread_1", status: "retrying" };
  }

  async resumeRun(runId: string): Promise<AgentRun> {
    this.resumed.push(runId);
    return { run_id: runId, thread_id: "thread_1", status: "running" };
  }

  async pendingDiffPatch(_diffId: string): Promise<string> {
    return this.patch;
  }

  async listPendingDiffs(): Promise<PendingDiffSummary[]> {
    this.pendingDiffListCalls += 1;
    if (
      this.pendingDiffVisibleAfter !== undefined &&
      this.pendingDiffListCalls < this.pendingDiffVisibleAfter
    ) {
      return [];
    }
    return (this.pendingDiffListOverride ?? this.pendingDiffs).map((diff) => ({
      ...diff,
    }));
  }

  async getPendingDiff(diffId: string): Promise<PendingDiffSummary | null> {
    const record = this.pendingDiffs.find((diff) => diff.diff_id === diffId);
    if (!record) {
      throw new DaemonRequestError(
        "daemon request failed (404): pending diff not found",
        404,
      );
    }
    return { ...record };
  }

  async acceptPendingDiff(diffId: string): Promise<unknown> {
    this.accepted.push(diffId);
    this.pendingDiffs = this.pendingDiffs.map((diff) =>
      diff.diff_id === diffId ? { ...diff, status: "accepted" } : diff,
    );
    return { diff_id: diffId };
  }

  async rejectPendingDiff(diffId: string): Promise<unknown> {
    this.rejected.push(diffId);
    this.pendingDiffs = this.pendingDiffs.map((diff) =>
      diff.diff_id === diffId ? { ...diff, status: "rejected" } : diff,
    );
    return { diff_id: diffId };
  }

  async listModelProviders(): Promise<ModelCatalog> {
    return {
      default_selection: { provider_id: "openai", model_id: "gpt-5" },
      providers: [
        {
          id: "openai",
          name: "OpenAI",
          enabled: true,
          api_key_configured: true,
          models: [{ id: "gpt-5", display_name: "GPT-5", enabled: true }],
        },
        {
          id: "deepseek",
          name: "DeepSeek",
          enabled: true,
          api_key_configured: false,
          models: [
            {
              id: "deepseek-flash",
              display_name: "DeepSeek Flash",
              enabled: true,
            },
            { id: "deepseek-pro", enabled: false },
          ],
        },
      ],
    };
  }

  async contextUsage(threadId: string): Promise<ContextUsage> {
    return { thread_id: threadId, used_tokens: 12_000 };
  }

  async *streamEvents(
    runId: string,
    after = 0,
    _signal?: AbortSignal,
  ): AsyncGenerator<AgentEvent> {
    this.streamCalls += 1;
    if (this.failStreamOnce && this.streamCalls === 1) {
      throw new DaemonRequestError("daemon unreachable");
    }
    for (const event of this.events[runId] ?? []) {
      if (event.sequence > after) {
        yield { ...event };
      }
    }
  }
}
