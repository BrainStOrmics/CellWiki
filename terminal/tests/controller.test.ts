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
    expect(client.started).toEqual([["thread_1", "hi"]]);
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
        { run_id: "run_1", thread_id: "thread_1", status: "succeeded" },
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
      ["thread_1", "first"],
      ["thread_1", "second"],
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
    expect(controller.state.picker).toEqual({ query: "", index: 0 });

    controller.setPickerQuery("second");
    expect(filterThreads(controller.state.threads, "second")).toHaveLength(1);
    await controller.confirmPicker();

    expect(controller.state.picker).toBeNull();
    expect(controller.state.threadId).toBe("thread_2");
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
