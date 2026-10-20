import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { DaemonRequestError } from "../src/api/client";
import type { AgentRun } from "../src/api/types";
import {
  filterThreads,
  formatRunSummary,
  TuiController,
} from "../src/controller";
import { DaemonVersionMismatch } from "../src/daemon/discovery";
import { FakeClient } from "./fake-client";

const noSleep = async (): Promise<void> => undefined;

function controllerFor(client: FakeClient): TuiController {
  const workspace = mkdtempSync(join(tmpdir(), "cellwiki-tui-"));
  return new TuiController(workspace, {
    clientFactory: async () => client,
    sleep: noSleep,
  });
}

async function waitFor(
  predicate: () => boolean,
  timeoutMs = 2_000,
): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (predicate()) {
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 1));
  }
  throw new Error("timed out waiting for the TUI condition");
}

describe("TuiController", () => {
  it("streams an answer into the transcript", async () => {
    const client = new FakeClient(
      [
        { run_id: "run_1", thread_id: "thread_1", status: "running" },
        {
          run_id: "run_1",
          thread_id: "thread_1",
          status: "succeeded",
          usage: { input_tokens: 10, output_tokens: 5 },
        },
      ],
      {
        events: {
          run_1: [
            {
              run_id: "run_1",
              sequence: 1,
              type: "message_delta",
              message: "hello ",
            },
            {
              run_id: "run_1",
              sequence: 2,
              type: "final_response",
              message: "hello world",
            },
          ],
        },
      },
    );
    const controller = controllerFor(client);
    await controller.connect();
    await controller.submit("hi");
    expect(await controller.waitIdle()).toBe(true);
    expect(controller.state.runStatus).toBe("succeeded");
    expect(controller.state.modelLabel).toBe("openai/gpt-5");
    expect(controller.state.contextLabel).toBe("ctx 12k");
    expect(
      controller.state.transcript.some((line) => line.text === "hello world"),
    ).toBe(true);
    expect(client.started).toEqual([["thread_new", "hi"]]);
  });

  it("coalesces reasoning deltas while preserving the final cursor", async () => {
    const reasoning = "r".repeat(240);
    const events = [
      ...Array.from({ length: 240 }, (_, index) => ({
        run_id: "run_1",
        sequence: index + 1,
        type: "reasoning_delta" as const,
        message: "r",
      })),
      {
        run_id: "run_1",
        sequence: 241,
        type: "final_response" as const,
        message: "done",
      },
    ];
    const client = new FakeClient(
      [{ run_id: "run_1", thread_id: "thread_1", status: "succeeded" }],
      { events: { run_1: events } },
    );
    const controller = controllerFor(client);
    await controller.connect();
    const snapshots: string[] = [];
    let updatesAfterSubmit = 0;
    const unsubscribe = controller.subscribe(() => {
      updatesAfterSubmit += 1;
      snapshots.push(controller.state.reasoning);
    });

    await controller.submit("hi");
    expect(await controller.waitIdle()).toBe(true);
    unsubscribe();

    expect(snapshots).toContain(reasoning);
    expect(controller.state.cursor).toBe(241);
    expect(updatesAfterSubmit).toBeLessThan(events.length / 2);
    expect(
      controller.state.transcript.some((line) => line.text === "done"),
    ).toBe(true);
  });

  it("starts a new conversation on connect", async () => {
    const client = new FakeClient(
      [{ run_id: "run_1", thread_id: "thread_1", status: "succeeded" }],
      {
        threads: [{ thread_id: "thread_1", title: "First" }],
      },
    );
    const controller = controllerFor(client);
    await controller.connect();
    expect(controller.state.threadId).toBeNull();
    expect(controller.state.threadTitle).toBe("");
    expect(controller.state.welcome).toBe(true);
    expect(controller.state.threads).toHaveLength(1);
    await controller.submit("hello");
    expect(await controller.waitIdle()).toBe(true);
    expect(client.createdThreads).toBe(1);
    expect(client.started).toEqual([["thread_new", "hello"]]);
  });

  it("clears the transcript when starting a new conversation", async () => {
    const client = new FakeClient(
      [{ run_id: "run_1", thread_id: "thread_1", status: "succeeded" }],
      {
        events: {
          run_1: [
            {
              run_id: "run_1",
              sequence: 1,
              type: "final_response",
              message: "hello world",
            },
          ],
        },
      },
    );
    const controller = controllerFor(client);
    await controller.connect();
    await controller.submit("hi");
    expect(await controller.waitIdle()).toBe(true);
    expect(controller.state.welcome).toBe(false);
    expect(controller.state.threadId).toBe("thread_new");
    expect(controller.state.transcript.length).toBeGreaterThan(1);

    await controller.submit("/new");
    expect(controller.state.threadId).toBeNull();
    expect(controller.state.threadTitle).toBe("");
    expect(controller.state.runStatus).toBe("idle");
    expect(controller.state.transcript).toEqual([]);
    expect(controller.state.welcome).toBe(true);
  });

  it("restores the welcome banner with /clear", async () => {
    const client = new FakeClient(
      [{ run_id: "run_1", thread_id: "thread_1", status: "succeeded" }],
      {
        events: {
          run_1: [
            {
              run_id: "run_1",
              sequence: 1,
              type: "final_response",
              message: "hello",
            },
          ],
        },
      },
    );
    const controller = controllerFor(client);
    await controller.connect();
    await controller.submit("hi");
    expect(await controller.waitIdle()).toBe(true);
    expect(controller.state.welcome).toBe(false);

    await controller.submit("/clear");
    expect(controller.state.welcome).toBe(true);
    expect(controller.state.transcript).toEqual([]);
  });

  it("answers an inline question gate", async () => {
    const client = new FakeClient(
      [
        {
          run_id: "run_1",
          thread_id: "thread_1",
          status: "waiting_confirmation",
        },
        { run_id: "run_1", thread_id: "thread_1", status: "succeeded" },
      ],
      {
        events: {
          run_1: [
            {
              run_id: "run_1",
              sequence: 1,
              type: "run_status",
              data: { status: "waiting_confirmation" },
            },
          ],
        },
        question: {
          run_id: "run_1",
          question: "Proceed?",
          options: [{ label: "Yes", recommended: true }],
          required: true,
        },
      },
    );
    const controller = controllerFor(client);
    await controller.connect();
    await controller.submit("go");
    await waitFor(() => controller.state.gate?.kind === "question");
    await controller.submit("1");
    expect(await controller.waitIdle()).toBe(true);
    expect(client.answers).toEqual([["Yes", false]]);
  });

  it("defers, reopens, and accepts a pending diff", async () => {
    const client = new FakeClient(
      [
        {
          run_id: "run_1",
          thread_id: "thread_1",
          status: "waiting_approval",
          pending_diff_id: "diff_1",
        },
        {
          run_id: "run_1",
          thread_id: "thread_1",
          status: "succeeded",
          pending_diff_id: "diff_1",
        },
      ],
      {
        events: {
          run_1: [
            {
              run_id: "run_1",
              sequence: 1,
              type: "run_status",
              data: { status: "waiting_approval" },
            },
          ],
        },
        pendingDiffs: [
          { diff_id: "diff_1", run_id: "run_1", status: "pending" },
        ],
      },
    );
    const controller = controllerFor(client);
    await controller.connect();
    await controller.submit("edit");
    await waitFor(() => controller.state.gate?.kind === "diff");
    await controller.submit("3");
    expect(
      controller.state.transcript.some((line) => line.text.includes("diff --git")),
    ).toBe(true);
    await controller.escape();
    expect(controller.state.gate).toBeNull();
    expect(controller.state.pendingDiffId).toBe("diff_1");
    expect(client.accepted).toEqual([]);
    await controller.submit("/diff");
    await waitFor(() => controller.state.gate?.kind === "diff");
    await controller.submit("1");
    expect(await controller.waitIdle()).toBe(true);
    expect(client.accepted).toEqual(["diff_1"]);
    expect(controller.state.gate).toBeNull();
    expect(controller.state.pendingDiffId).toBeNull();
    expect(controller.state.runStatus).toBe("succeeded");
  });

  it("refreshes a stale approval preview when the unit grew", async () => {
    const client = new FakeClient(
      [
        {
          run_id: "run_1",
          thread_id: "thread_1",
          status: "succeeded",
          pending_diff_id: "diff_1",
        },
      ],
      {
        pendingDiffs: [{ diff_id: "diff_1", run_id: "run_1", status: "pending" }],
      },
    );
    const controller = controllerFor(client);
    await controller.connect();
    await controller.submit("/diff");
    await waitFor(() => controller.state.gate?.kind === "diff");

    // daemon 把同一审批单元就地刷新了（提问挂起之后又落了提交），门里的缓存落后。
    client.patch =
      "diff --git a/notes/language.md b/notes/language.md\n+new file\n";
    await controller.submit("3");

    expect(
      controller.state.transcript.some((line) =>
        line.text.includes("notes/language.md"),
      ),
    ).toBe(true);
    const gate = controller.state.gate;
    expect(gate?.kind === "diff" && gate.patch.includes("notes/language.md")).toBe(
      true,
    );
  });

  it("asks again when the approval unit changed before a decision", async () => {
    const client = new FakeClient(
      [
        {
          run_id: "run_1",
          thread_id: "thread_1",
          status: "succeeded",
          pending_diff_id: "diff_1",
        },
      ],
      {
        pendingDiffs: [{ diff_id: "diff_1", run_id: "run_1", status: "pending" }],
      },
    );
    const controller = controllerFor(client);
    await controller.connect();
    await controller.submit("/diff");
    await waitFor(() => controller.state.gate?.kind === "diff");

    client.patch =
      "diff --git a/notes/language.md b/notes/language.md\n+new file\n";
    await controller.submit("1");

    expect(client.accepted).toEqual([]);
    expect(
      controller.state.transcript.some((line) =>
        line.text.includes("changed since this gate opened"),
      ),
    ).toBe(true);

    // 刷新后的内容已进缓存，第二次确认才真的判定。
    await controller.submit("1");
    expect(await controller.waitIdle()).toBe(true);
    expect(client.accepted).toEqual(["diff_1"]);
  });

  it("surfaces a pending diff published after a succeeded run", async () => {
    const client = new FakeClient(
      [
        {
          run_id: "run_1",
          thread_id: "thread_1",
          status: "succeeded",
          pending_diff_id: "diff_1",
        },
      ],
      {
        events: { run_1: [] },
        pendingDiffs: [
          { diff_id: "diff_1", run_id: "run_1", status: "pending" },
        ],
      },
    );
    const controller = controllerFor(client);
    await controller.connect();
    await controller.submit("edit");
    await waitFor(() => controller.state.gate?.kind === "diff");
    expect(controller.state.pendingDiffId).toBe("diff_1");
  });

  it("advances through multiple pending diffs after accept", async () => {
    const client = new FakeClient(
      [{ run_id: "run_1", thread_id: "thread_1", status: "succeeded" }],
      {
        pendingDiffs: [
          { diff_id: "diff_1", run_id: "run_1", status: "pending" },
          { diff_id: "diff_2", run_id: "run_2", status: "pending" },
        ],
      },
    );
    const controller = controllerFor(client);
    await controller.connect();
    await controller.submit("/diff");
    await waitFor(() => {
      const gate = controller.state.gate;
      return gate?.kind === "diff" && gate.diffId === "diff_1";
    });
    await controller.submit("1");
    await waitFor(() => {
      const gate = controller.state.gate;
      return gate?.kind === "diff" && gate.diffId === "diff_2";
    });
    await controller.submit("1");
    expect(await controller.waitIdle()).toBe(true);
    expect(client.accepted).toEqual(["diff_1", "diff_2"]);
    expect(controller.state.pendingDiffId).toBeNull();
  });

  it("does not reopen the gate when the run still references an accepted diff", async () => {
    const client = new FakeClient(
      [
        {
          run_id: "run_1",
          thread_id: "thread_1",
          status: "succeeded",
          pending_diff_id: "diff_1",
        },
      ],
      {
        pendingDiffs: [
          { diff_id: "diff_1", run_id: "run_1", status: "accepted" },
        ],
      },
    );
    const controller = controllerFor(client);
    await controller.connect();
    await controller.submit("edit");
    expect(await controller.waitIdle()).toBe(true);
    expect(controller.state.gate).toBeNull();
    expect(controller.state.pendingDiffId).toBeNull();
  });

  it("opens the gate from the run reference when the pending list lags", async () => {
    const client = new FakeClient(
      [
        {
          run_id: "run_1",
          thread_id: "thread_1",
          status: "succeeded",
          pending_diff_id: "diff_1",
        },
      ],
      {
        pendingDiffs: [
          { diff_id: "diff_1", run_id: "run_1", status: "pending" },
        ],
        pendingDiffListOverride: [],
      },
    );
    const controller = controllerFor(client);
    await controller.connect();
    await controller.submit("edit");
    await waitFor(() => controller.state.gate?.kind === "diff");
    expect(controller.state.pendingDiffId).toBe("diff_1");
  });

  it("waits for a late-published diff before opening the gate", async () => {
    const client = new FakeClient(
      [
        {
          run_id: "run_1",
          thread_id: "thread_1",
          status: "succeeded",
          pending_diff_id: null,
        },
      ],
      {
        pendingDiffs: [
          { diff_id: "diff_1", run_id: "run_1", status: "pending" },
        ],
        // The runtime finalizes the run before publishing its diff: the list
        // stays empty for the first calls after the run settles.
        pendingDiffVisibleAfter: 3,
      },
    );
    const controller = controllerFor(client);
    await controller.connect();
    await controller.submit("edit");
    await waitFor(() => controller.state.gate?.kind === "diff");
    expect(controller.state.pendingDiffId).toBe("diff_1");
  });

  it("queues messages while a run is active", async () => {
    const client = new FakeClient(
      [
        { run_id: "run_1", thread_id: "thread_1", status: "running" },
        { run_id: "run_1", thread_id: "thread_1", status: "succeeded" },
        { run_id: "run_2", thread_id: "thread_1", status: "running" },
        { run_id: "run_2", thread_id: "thread_1", status: "succeeded" },
      ],
      { events: { run_1: [], run_2: [] } },
    );
    const controller = controllerFor(client);
    await controller.connect();
    await controller.submit("first");
    await controller.submit("second");
    expect(controller.state.queue).toEqual(["second"]);
    expect(await controller.waitIdle()).toBe(true);
    expect(client.started).toEqual([
      ["thread_new", "first"],
      ["thread_new", "second"],
    ]);
  });

  it("interrupts a run and resumes it with /continue", async () => {
    class HoldClient extends FakeClient {
      private stopped = false;

      override async getRun(runId: string): Promise<AgentRun> {
        return this.stopped
          ? { run_id: runId, thread_id: "thread_1", status: "unfinished" }
          : { run_id: runId, thread_id: "thread_1", status: "running" };
      }

      override async cancelRun(runId: string): Promise<AgentRun> {
        this.stopped = true;
        return super.cancelRun(runId);
      }
    }

    const client = new HoldClient([
      { run_id: "run_1", thread_id: "thread_1", status: "running" },
    ]);
    const controller = controllerFor(client);
    await controller.connect();
    await controller.submit("long task");
    await waitFor(() => controller.state.runId === "run_1");
    await controller.escape();
    expect(client.cancelled).toEqual(["run_1"]);
    expect(await controller.waitIdle()).toBe(true);
    expect(controller.state.runStatus).toBe("unfinished");
    await controller.submit("/continue");
    expect(await controller.waitIdle()).toBe(true);
    expect(client.resumed).toEqual(["run_1"]);
  });

  it("reports a busy run from a 409", async () => {
    class BusyClient extends FakeClient {
      override async startRun(): Promise<AgentRun> {
        throw new DaemonRequestError(
          "daemon request failed (409): another agent run is active: run_busy",
          409,
        );
      }
    }

    const client = new BusyClient([
      { run_id: "run_busy", thread_id: "thread_1", status: "running" },
    ]);
    const controller = controllerFor(client);
    await controller.connect();
    await controller.submit("hello");
    expect(
      controller.state.transcript.some((line) => line.text.includes("run_busy")),
    ).toBe(true);
  });

  it("reconnects after a stream failure", async () => {
    const client = new FakeClient(
      [
        { run_id: "run_1", thread_id: "thread_1", status: "running" },
        { run_id: "run_1", thread_id: "thread_1", status: "succeeded" },
      ],
      {
        events: {
          run_1: [
            {
              run_id: "run_1",
              sequence: 1,
              type: "message_delta",
              message: "ok",
            },
          ],
        },
        failStreamOnce: true,
      },
    );
    const controller = controllerFor(client);
    await controller.connect();
    await controller.submit("hello");
    expect(await controller.waitIdle()).toBe(true);
    expect(client.streamCalls).toBeGreaterThanOrEqual(2);
    expect(
      controller.state.transcript.some((line) => line.text === "reconnected"),
    ).toBe(true);
  });

  it("switches threads with /resume", async () => {
    const client = new FakeClient(
      [{ run_id: "run_1", thread_id: "thread_1", status: "succeeded" }],
      {
        threads: [
          {
            thread_id: "thread_1",
            title: "First",
            latest_status: "succeeded",
          },
          {
            thread_id: "thread_2",
            title: "Second",
            latest_status: "unfinished",
          },
        ],
      },
    );
    client.messages.thread_2 = [
      { role: "assistant", content: "second thread answer" },
    ];
    const controller = controllerFor(client);
    await controller.connect();
    await controller.submit("/resume 2");
    expect(controller.state.threadId).toBe("thread_2");
    expect(
      controller.state.transcript.some(
        (line) => line.text === "second thread answer",
      ),
    ).toBe(true);
  });

  it("opens a resume picker and switches the selected session", async () => {
    const client = new FakeClient(
      [{ run_id: "run_1", thread_id: "thread_1", status: "succeeded" }],
      {
        threads: [
          {
            thread_id: "thread_1",
            title: "First",
            latest_status: "succeeded",
          },
          {
            thread_id: "thread_2",
            title: "Second",
            latest_status: "unfinished",
          },
        ],
      },
    );
    client.messages.thread_2 = [
      { role: "user", content: "second question" },
      { role: "assistant", content: "second thread answer" },
    ];
    const controller = controllerFor(client);
    await controller.connect();
    await controller.submit("/resume");
    expect(controller.state.picker).toEqual({
      kind: "resume",
      query: "",
      index: 0,
    });

    controller.setPickerQuery("second");
    expect(filterThreads(controller.state.threads, "second")).toHaveLength(1);
    await controller.confirmPicker();

    expect(controller.state.picker).toBeNull();
    expect(controller.state.threadId).toBe("thread_2");
    expect(controller.state.welcome).toBe(false);
    expect(
      controller.state.transcript.some(
        (line) => line.text === "second thread answer",
      ),
    ).toBe(true);
    expect(
      controller.state.transcript.find((line) => line.text === "second question")
        ?.tone,
    ).toBe("user");
  });

  it("closes the resume picker with escape", async () => {
    const client = new FakeClient(
      [{ run_id: "run_1", thread_id: "thread_1", status: "succeeded" }],
      {
        threads: [{ thread_id: "thread_1", title: "First" }],
      },
    );
    const controller = controllerFor(client);
    await controller.connect();
    await controller.submit("/resume");
    expect(controller.state.picker).not.toBeNull();
    await controller.escape();
    expect(controller.state.picker).toBeNull();
  });

  it("previews and applies a theme from the picker", async () => {
    const saved: string[] = [];
    const client = new FakeClient([
      { run_id: "run_1", thread_id: "thread_1", status: "succeeded" },
    ]);
    const workspace = mkdtempSync(join(tmpdir(), "cellwiki-tui-"));
    const controller = new TuiController(workspace, {
      clientFactory: async () => client,
      sleep: noSleep,
      env: {},
      themeStore: {
        load: () => null,
        save: (themeId) => saved.push(themeId),
      },
    });
    await controller.connect();
    expect(controller.state.themeId).toBe("auto");

    await controller.submit("/theme");
    expect(controller.state.picker?.kind).toBe("theme");
    controller.movePicker(1);
    expect(controller.state.themeId).toBe("dark");
    await controller.confirmPicker();
    expect(saved).toEqual(["dark"]);
    expect(controller.state.picker).toBeNull();

    await controller.submit("/theme");
    controller.movePicker(1);
    expect(controller.state.themeId).toBe("light");
    await controller.escape();
    expect(controller.state.themeId).toBe("dark");
    expect(controller.state.picker).toBeNull();
  });

  it("picks a session model from the /model picker", async () => {
    const client = new FakeClient([
      { run_id: "run_1", thread_id: "thread_1", status: "succeeded" },
    ]);
    const controller = controllerFor(client);
    await controller.connect();
    expect(controller.state.modelLabel).toBe("openai/gpt-5");

    await controller.submit("/model");
    expect(controller.state.picker?.kind).toBe("model");
    expect(
      controller
        .modelPickerItems("")
        .map((item) =>
          item.kind === "default" ? "default" : item.choice.modelId,
        ),
    ).toEqual(["default", "gpt-5", "deepseek-flash"]);

    controller.movePicker(2);
    await controller.confirmPicker();
    expect(controller.state.modelSelection).toEqual({
      provider_id: "deepseek",
      model_id: "deepseek-flash",
    });
    expect(controller.state.modelLabel).toBe("deepseek/deepseek-flash (session)");

    await controller.submit("hi");
    expect(await controller.waitIdle()).toBe(true);
    expect(client.models[0]).toEqual({
      provider_id: "deepseek",
      model_id: "deepseek-flash",
    });
  });

  it("clears the session model override with the catalog default entry", async () => {
    const client = new FakeClient([
      { run_id: "run_1", thread_id: "thread_1", status: "succeeded" },
    ]);
    const controller = controllerFor(client);
    await controller.connect();
    await controller.submit("/model deepseek-flash");
    expect(controller.state.modelSelection).toEqual({
      provider_id: "deepseek",
      model_id: "deepseek-flash",
    });

    await controller.submit("/model");
    controller.setPickerQuery("default");
    await controller.confirmPicker();
    expect(controller.state.modelSelection).toBeNull();
    expect(controller.state.modelLabel).toBe("openai/gpt-5");
  });

  it("applies a model by id and rejects unknown ids", async () => {
    const client = new FakeClient([
      { run_id: "run_1", thread_id: "thread_1", status: "succeeded" },
    ]);
    const controller = controllerFor(client);
    await controller.connect();
    await controller.submit("/model deepseek-flash");
    expect(controller.state.modelSelection).toEqual({
      provider_id: "deepseek",
      model_id: "deepseek-flash",
    });

    await controller.submit("/model nope");
    expect(controller.state.modelSelection).toEqual({
      provider_id: "deepseek",
      model_id: "deepseek-flash",
    });
    expect(
      controller.state.transcript.some((line) =>
        line.text.includes("unknown model: nope"),
      ),
    ).toBe(true);

    await controller.submit("/model default");
    expect(controller.state.modelSelection).toBeNull();
  });

  it("reports the session model marker in /status", async () => {
    const client = new FakeClient([
      { run_id: "run_1", thread_id: "thread_1", status: "succeeded" },
    ]);
    const controller = controllerFor(client);
    await controller.connect();
    await controller.submit("/model deepseek-flash");
    await controller.submit("/status");
    expect(
      controller.state.transcript.some(
        (line) => line.text === "model: deepseek/deepseek-flash (session)",
      ),
    ).toBe(true);
  });

  it("formats a done summary with duration and clock", () => {
    const summary = formatRunSummary({
      run_id: "run_1",
      thread_id: "thread_1",
      status: "succeeded",
      usage: { elapsed_seconds: 2, input_tokens: 12, output_tokens: 34 },
    });
    expect(summary).toMatch(/^✻ done in 2s · \d{2}:\d{2} · tokens 12\/34$/);
  });

  it("retries a failed run with /retry", async () => {
    const client = new FakeClient([
      {
        run_id: "run_1",
        thread_id: "thread_1",
        status: "failed",
        retryable: true,
      },
      {
        run_id: "run_1",
        thread_id: "thread_1",
        status: "failed",
        retryable: true,
      },
    ]);
    const controller = controllerFor(client);
    await controller.connect();
    await controller.submit("hello");
    expect(await controller.waitIdle()).toBe(true);
    expect(controller.state.runStatus).toBe("failed");
    await controller.submit("/retry");
    expect(await controller.waitIdle()).toBe(true);
    expect(client.retried).toEqual(["run_1"]);
  });

  it("shows the workspace-blocking run in /status", async () => {
    const client = new FakeClient(
      [{ run_id: "run_1", thread_id: "thread_1", status: "succeeded" }],
      {
        blockingRuns: [
          { run_id: "run_block", thread_id: "thread_other", status: "unfinished" },
        ],
      },
    );
    const controller = controllerFor(client);
    await controller.connect();
    await controller.submit("/status");
    expect(
      controller.state.transcript.some((line) =>
        line.text.startsWith("blocking run: run_block (unfinished)"),
      ),
    ).toBe(true);
  });

  it("resumes the workspace-blocking run with /continue", async () => {
    const client = new FakeClient(
      [{ run_id: "run_1", thread_id: "thread_1", status: "succeeded" }],
      {
        blockingRuns: [
          { run_id: "run_block", thread_id: "thread_other", status: "unfinished" },
        ],
      },
    );
    const controller = controllerFor(client);
    await controller.connect();
    await controller.submit("/continue");
    expect(client.resumed).toEqual(["run_block"]);
    expect(await controller.waitIdle()).toBe(true);
  });

  it("abandons the workspace-blocking run with /cancel", async () => {
    const client = new FakeClient(
      [{ run_id: "run_1", thread_id: "thread_1", status: "succeeded" }],
      {
        blockingRuns: [
          { run_id: "run_block", thread_id: "thread_other", status: "unfinished" },
        ],
      },
    );
    const controller = controllerFor(client);
    await controller.connect();
    await controller.submit("/cancel");
    expect(client.cancelled).toEqual(["run_block"]);
    expect(
      controller.state.transcript.some((line) =>
        line.text.includes("cancelling run_block"),
      ),
    ).toBe(true);
  });

  it("prompts and restarts on a daemon version mismatch", async () => {
    const coordinates = {
      schema_version: 1,
      pid: 1,
      port: 1,
      workspace: "/tmp/ws",
      package_version: "0.0.1",
      api_version: "old",
      started_at: "",
      log_path: "",
    };
    const client = new FakeClient([
      { run_id: "run_1", thread_id: "thread_1", status: "succeeded" },
    ]);
    let attempts = 0;
    let restarts = 0;
    const controller = new TuiController("/tmp/ws", {
      clientFactory: async () => {
        attempts += 1;
        if (attempts === 1) {
          throw new DaemonVersionMismatch(coordinates);
        }
        return client;
      },
      restart: async () => {
        restarts += 1;
      },
      sleep: noSleep,
    });
    await controller.connect();
    expect(controller.state.versionMismatch).not.toBeNull();
    await controller.restart();
    expect(restarts).toBe(1);
    expect(controller.state.connected).toBe(true);
    expect(controller.state.versionMismatch).toBeNull();
  });

  it("lists workspace files for @ completion", () => {
    const workspace = mkdtempSync(join(tmpdir(), "cellwiki-mention-"));
    mkdirSync(join(workspace, "wiki"));
    writeFileSync(join(workspace, "wiki", "foxp3.md"), "# FOXP3\n");
    writeFileSync(join(workspace, ".env"), "OPENAI_API_KEY=secret\n");
    const client = new FakeClient([
      { run_id: "run_1", thread_id: "thread_1", status: "succeeded" },
    ]);
    const controller = new TuiController(workspace, {
      clientFactory: async () => client,
      sleep: noSleep,
    });
    expect(controller.mentionCandidates("foxp3")).toContain("wiki/foxp3.md");
    expect(controller.mentionCandidates("")).not.toContain(".env");
  });

  it("formats provider SSE error payloads", async () => {
    const framed =
      "id:1\nevent:error\n:HTTP_STATUS/400\n" +
      'data:{"code":"Arrearage","message":"Access denied, please make sure ' +
      'your account is in good standing."}';
    const client = new FakeClient(
      [
        { run_id: "run_1", thread_id: "thread_1", status: "running" },
        {
          run_id: "run_1",
          thread_id: "thread_1",
          status: "failed",
          error_message: framed,
        },
      ],
      {
        events: {
          run_1: [
            {
              run_id: "run_1",
              sequence: 1,
              type: "error",
              message: framed,
            },
          ],
        },
      },
    );
    const controller = controllerFor(client);
    await controller.connect();
    await controller.submit("hello");
    expect(await controller.waitIdle()).toBe(true);
    const text = controller.state.transcript
      .map((line) => line.text)
      .join("\n");
    expect(text).toContain(
      "Access denied, please make sure your account is in good standing. " +
        "(Arrearage)",
    );
    expect(text).not.toContain("event:error");
  });
});
