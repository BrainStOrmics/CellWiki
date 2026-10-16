import { SseParser } from "./sse";
import type {
  AgentEvent,
  AgentRun,
  ContextUsage,
  MessageRecord,
  ModelCatalog,
  PendingDiffSummary,
  PendingQuestion,
  ThreadRecord,
} from "./types";

const REQUEST_TIMEOUT_MS = 60_000;

export class DaemonRequestError extends Error {
  constructor(
    message: string,
    readonly status?: number,
  ) {
    super(message);
    this.name = "DaemonRequestError";
  }
}

export class DaemonClient {
  constructor(
    readonly baseUrl: string,
    readonly token: string,
  ) {}

  async listThreads(): Promise<ThreadRecord[]> {
    return this.request<ThreadRecord[]>("GET", "/api/agent/threads");
  }

  async createThread(): Promise<string> {
    const payload = await this.request<{ thread_id: string }>(
      "POST",
      "/api/agent/threads",
    );
    return payload.thread_id;
  }

  async listMessages(threadId: string): Promise<MessageRecord[]> {
    return this.request<MessageRecord[]>(
      "GET",
      `/api/agent/threads/${encodeURIComponent(threadId)}/messages`,
    );
  }

  async startRun(
    threadId: string,
    message: string,
    requestId: string,
  ): Promise<AgentRun> {
    return this.request<AgentRun>("POST", "/api/agent/runs", {
      thread_id: threadId,
      message,
      request_id: requestId,
    });
  }

  async getRun(runId: string): Promise<AgentRun> {
    return this.request<AgentRun>(
      "GET",
      `/api/agent/runs/${encodeURIComponent(runId)}`,
    );
  }

  async listEvents(runId: string, after = 0): Promise<AgentEvent[]> {
    return this.request<AgentEvent[]>(
      "GET",
      `/api/agent/runs/${encodeURIComponent(runId)}/events?after=${after}`,
    );
  }

  async getQuestion(runId: string): Promise<PendingQuestion | null> {
    try {
      return await this.request<PendingQuestion>(
        "GET",
        `/api/agent/runs/${encodeURIComponent(runId)}/question`,
      );
    } catch (error) {
      if (error instanceof DaemonRequestError && error.status === 404) {
        return null;
      }
      throw error;
    }
  }

  async answerQuestion(
    runId: string,
    answers: string | string[] | null,
    timedOut = false,
  ): Promise<AgentRun> {
    return this.request<AgentRun>(
      "POST",
      `/api/agent/runs/${encodeURIComponent(runId)}/question`,
      timedOut ? { timed_out: true } : { answers },
    );
  }

  async cancelRun(runId: string): Promise<AgentRun> {
    return this.request<AgentRun>(
      "POST",
      `/api/agent/runs/${encodeURIComponent(runId)}/cancel`,
    );
  }

  async retryRun(runId: string): Promise<AgentRun> {
    return this.request<AgentRun>(
      "POST",
      `/api/agent/runs/${encodeURIComponent(runId)}/retry`,
    );
  }

  async resumeRun(runId: string): Promise<AgentRun> {
    return this.request<AgentRun>(
      "POST",
      `/api/agent/runs/${encodeURIComponent(runId)}/resume`,
    );
  }

  async listPendingDiffs(): Promise<PendingDiffSummary[]> {
    return this.request<PendingDiffSummary[]>("GET", "/api/pending-diffs");
  }

  async pendingDiffPatch(diffId: string): Promise<string> {
    const response = await fetch(
      `${this.baseUrl}/api/pending-diffs/${encodeURIComponent(diffId)}/patch`,
      { headers: this.headers() },
    );
    if (!response.ok) {
      throw await this.toError(response);
    }
    return response.text();
  }

  async acceptPendingDiff(diffId: string): Promise<Record<string, unknown>> {
    return this.request<Record<string, unknown>>(
      "POST",
      `/api/pending-diffs/${encodeURIComponent(diffId)}/accept`,
    );
  }

  async rejectPendingDiff(diffId: string): Promise<Record<string, unknown>> {
    return this.request<Record<string, unknown>>(
      "POST",
      `/api/pending-diffs/${encodeURIComponent(diffId)}/reject`,
    );
  }

  async listModelProviders(): Promise<ModelCatalog> {
    return this.request<ModelCatalog>("GET", "/api/model-providers");
  }

  async contextUsage(threadId: string): Promise<ContextUsage> {
    return this.request<ContextUsage>(
      "GET",
      `/api/agent/threads/${encodeURIComponent(threadId)}/context-usage`,
    );
  }

  async *streamEvents(
    runId: string,
    after = 0,
    signal?: AbortSignal,
  ): AsyncGenerator<AgentEvent> {
    const response = await fetch(
      `${this.baseUrl}/api/agent/runs/${encodeURIComponent(runId)}/stream?after=${after}`,
      { headers: this.headers(), signal },
    );
    if (!response.ok || !response.body) {
      throw await this.toError(response);
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    const parser = new SseParser();
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) {
          break;
        }
        for (const event of parser.push(decoder.decode(value, { stream: true }))) {
          yield event as AgentEvent;
        }
      }
      for (const event of parser.finish()) {
        yield event as AgentEvent;
      }
    } finally {
      reader.releaseLock();
    }
  }

  private headers(json = false): Record<string, string> {
    const headers: Record<string, string> = {
      Authorization: `Bearer ${this.token}`,
    };
    if (json) {
      headers["Content-Type"] = "application/json";
    }
    return headers;
  }

  private async request<T>(
    method: string,
    path: string,
    body?: unknown,
  ): Promise<T> {
    const response = await fetch(`${this.baseUrl}${path}`, {
      method,
      headers: this.headers(body !== undefined),
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });
    if (!response.ok) {
      throw await this.toError(response);
    }
    return (await response.json()) as T;
  }

  private async toError(response: Response): Promise<DaemonRequestError> {
    let detail = response.statusText;
    try {
      const payload = (await response.json()) as { detail?: unknown };
      if (payload.detail !== undefined) {
        detail =
          typeof payload.detail === "string"
            ? payload.detail
            : JSON.stringify(payload.detail);
      }
    } catch {
      // keep the status text
    }
    return new DaemonRequestError(
      `daemon request failed (${response.status}): ${detail}`,
      response.status,
    );
  }
}
