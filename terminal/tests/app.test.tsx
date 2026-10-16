import { render } from "ink-testing-library";
import { describe, expect, it } from "vitest";

import { App } from "../src/components/App";
import { LiveView } from "../src/components/LiveView";
import { TuiController } from "../src/controller";
import { FakeClient } from "./fake-client";

const noSleep = async (): Promise<void> => undefined;

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
  throw new Error("timed out waiting for the Ink frame");
}

describe("App", () => {
  it("renders transcript, status bar and composer", async () => {
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
              message: "hello world",
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
    const controller = new TuiController("/tmp/cellwiki-app-test", {
      clientFactory: async () => client,
      sleep: noSleep,
    });
    const { lastFrame, unmount } = render(<App controller={controller} />);
    await waitFor(() => controller.state.connected);
    await controller.submit("hi");
    await waitFor(() =>
      controller.state.transcript.some((line) => line.text === "hello world"),
    );
    await waitFor(() => lastFrame()?.includes("hello world") ?? false);
    const frame = lastFrame() ?? "";
    expect(frame).toContain("cellwiki");
    expect(frame).toContain("model openai/gpt-5");
    expect(frame).toContain("ctx 12k");
    expect(frame).toContain("hello world");
    unmount();
  });

  it("submits typed composer input", async () => {
    const client = new FakeClient([
      { run_id: "run_1", thread_id: "thread_1", status: "succeeded" },
    ]);
    const controller = new TuiController("/tmp/cellwiki-app-test", {
      clientFactory: async () => client,
      sleep: noSleep,
    });
    const { stdin, lastFrame, unmount } = render(
      <App controller={controller} />,
    );
    await waitFor(() => controller.state.connected);
    stdin.write("hi");
    await new Promise((resolve) => setTimeout(resolve, 10));
    stdin.write("\r");
    await waitFor(() => client.started.length === 1);
    expect(client.started[0]).toEqual(["thread_1", "hi"]);
    stdin.write("\u0010");
    await waitFor(() => (lastFrame() ?? "").includes("> hi") ?? false);
    expect(lastFrame() ?? "").toContain("> hi");
    unmount();
  });

  it("renders the pending diff gate", async () => {
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
    const controller = new TuiController("/tmp/cellwiki-app-test", {
      clientFactory: async () => client,
      sleep: noSleep,
    });
    const { lastFrame, unmount } = render(<App controller={controller} />);
    await waitFor(() => controller.state.connected);
    await controller.submit("edit");
    await waitFor(() => lastFrame()?.includes("Pending diff diff_1") ?? false);
    const frame = lastFrame() ?? "";
    expect(frame).toContain("1 accept");
    expect(frame).toContain("+new");
    unmount();
  });

  it("runs a fully typed slash command on the first Enter", async () => {
    const client = new FakeClient([
      { run_id: "run_1", thread_id: "thread_1", status: "succeeded" },
    ]);
    const controller = new TuiController("/tmp/cellwiki-app-test", {
      clientFactory: async () => client,
      sleep: noSleep,
    });
    const { stdin, unmount } = render(<App controller={controller} />);
    await waitFor(() => controller.state.connected);
    stdin.write("/help\r");
    await waitFor(() =>
      controller.state.transcript.some((line) =>
        line.text.includes("show this help"),
      ),
    );
    unmount();
  });

  it("keeps long reasoning compact in the live view", () => {
    const controller = new TuiController("/tmp/cellwiki-app-test", {
      clientFactory: async () =>
        new FakeClient([
          { run_id: "run_1", thread_id: "thread_1", status: "succeeded" },
        ]),
    });
    const state = { ...controller.state, reasoning: "x".repeat(5_000) };
    const { lastFrame, unmount } = render(<LiveView state={state} />);
    const frame = lastFrame() ?? "";
    expect(frame).toContain("Thinking…");
    expect(frame.length).toBeLessThan(500);
    unmount();
  });

  it("windows the transcript in fullscreen and scrolls with PgUp/PgDn", async () => {
    const events = {
      run_1: Array.from({ length: 20 }, (_, index) => ({
        run_id: "run_1",
        sequence: index + 1,
        type: "final_response" as const,
        message: `answer ${index}`,
      })),
    };
    const client = new FakeClient(
      [{ run_id: "run_1", thread_id: "thread_1", status: "succeeded" }],
      { events },
    );
    const controller = new TuiController("/tmp/cellwiki-app-test", {
      clientFactory: async () => client,
      sleep: noSleep,
    });
    const { stdin, lastFrame, unmount } = render(
      <App
        controller={controller}
        mode="fullscreen"
        viewport={{ rows: 10, columns: 60 }}
      />,
    );
    await waitFor(() => controller.state.connected);
    await controller.submit("hi");
    await waitFor(() => lastFrame()?.includes("answer 19") ?? false);
    expect(lastFrame() ?? "").not.toContain("answer 0");

    stdin.write("\u001b[5~");
    await waitFor(() => lastFrame()?.includes("newer line") ?? false);
    const scrolled = lastFrame() ?? "";
    expect(scrolled).toContain("newer line");

    stdin.write("\u001b[6~");
    await waitFor(() => !(lastFrame() ?? "").includes("newer line"));
    expect(lastFrame() ?? "").toContain("answer 19");

    stdin.write("\u001b[A");
    await waitFor(() => lastFrame()?.includes("1 newer line") ?? false);
    stdin.write("\u001b[B");
    await waitFor(() => !(lastFrame() ?? "").includes("newer line"));
    unmount();
  });

  it("scrolls the slash menu to keep the selection visible", async () => {
    const client = new FakeClient([
      { run_id: "run_1", thread_id: "thread_1", status: "succeeded" },
    ]);
    const controller = new TuiController("/tmp/cellwiki-app-test", {
      clientFactory: async () => client,
      sleep: noSleep,
    });
    const { stdin, lastFrame, unmount } = render(
      <App
        controller={controller}
        mode="fullscreen"
        viewport={{ rows: 16, columns: 60 }}
      />,
    );
    await waitFor(() => controller.state.connected);
    stdin.write("/");
    await waitFor(() => lastFrame()?.includes("/help") ?? false);
    for (let index = 0; index < 10; index += 1) {
      stdin.write("\u001b[B");
      await new Promise((resolve) => setTimeout(resolve, 5));
    }
    const frame = lastFrame() ?? "";
    expect(frame).toContain("/quit");
    expect(frame).not.toContain("/help");
    unmount();
  });

  it("bottom-aligns a short transcript in fullscreen", async () => {
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
    const controller = new TuiController("/tmp/cellwiki-app-test", {
      clientFactory: async () => client,
      sleep: noSleep,
    });
    const { lastFrame, unmount } = render(
      <App
        controller={controller}
        mode="fullscreen"
        viewport={{ rows: 12, columns: 60 }}
      />,
    );
    await waitFor(() => controller.state.connected);
    await controller.submit("hi");
    await waitFor(() => lastFrame()?.includes("hello world") ?? false);
    const lines = (lastFrame() ?? "").split("\n");
    expect(lines.slice(0, 3).every((line) => line.trim() === "")).toBe(true);
    unmount();
  });

  it("keeps the classic scrollback renderer available", async () => {
    const client = new FakeClient(
      [{ run_id: "run_1", thread_id: "thread_1", status: "succeeded" }],
      {
        events: {
          run_1: [
            {
              run_id: "run_1",
              sequence: 1,
              type: "final_response",
              message: "classic hello",
            },
          ],
        },
      },
    );
    const controller = new TuiController("/tmp/cellwiki-app-test", {
      clientFactory: async () => client,
      sleep: noSleep,
    });
    const { lastFrame, unmount } = render(
      <App controller={controller} mode="classic" />,
    );
    await waitFor(() => controller.state.connected);
    await controller.submit("hi");
    await waitFor(() => lastFrame()?.includes("classic hello") ?? false);
    expect(lastFrame() ?? "").toContain("cellwiki");
    unmount();
  });

  it("renders assistant markdown without raw markers", async () => {
    const client = new FakeClient(
      [{ run_id: "run_1", thread_id: "thread_1", status: "succeeded" }],
      {
        events: {
          run_1: [
            {
              run_id: "run_1",
              sequence: 1,
              type: "final_response",
              message: "**bold** and `code`\n- item",
            },
          ],
        },
      },
    );
    const controller = new TuiController("/tmp/cellwiki-app-test", {
      clientFactory: async () => client,
      sleep: noSleep,
    });
    const { lastFrame, unmount } = render(
      <App
        controller={controller}
        mode="fullscreen"
        viewport={{ rows: 14, columns: 60 }}
      />,
    );
    await waitFor(() => controller.state.connected);
    await controller.submit("hi");
    await waitFor(() => lastFrame()?.includes("bold and code") ?? false);
    const frame = lastFrame() ?? "";
    expect(frame).toContain("bold and code");
    expect(frame).toContain("• item");
    expect(frame).not.toContain("**bold**");
    expect(frame).not.toContain("`code`");
    unmount();
  });

  it("opens the resume picker and switches sessions", async () => {
    const client = new FakeClient(
      [{ run_id: "run_1", thread_id: "thread_1", status: "succeeded" }],
      {
        threads: [
          {
            thread_id: "thread_1",
            title: "First",
            latest_status: "succeeded",
            updated_at: "2026-10-16T10:00:00Z",
          },
          {
            thread_id: "thread_2",
            title: "Second",
            latest_status: "unfinished",
            updated_at: "2026-10-15T10:00:00Z",
          },
        ],
      },
    );
    client.messages.thread_2 = [
      { role: "assistant", content: "second thread answer" },
    ];
    const controller = new TuiController("/tmp/cellwiki-app-test", {
      clientFactory: async () => client,
      sleep: noSleep,
    });
    const { stdin, lastFrame, unmount } = render(
      <App
        controller={controller}
        mode="fullscreen"
        viewport={{ rows: 16, columns: 60 }}
      />,
    );
    await waitFor(() => controller.state.connected);
    await controller.submit("/resume");
    await waitFor(() => lastFrame()?.includes("Resume session") ?? false);
    const pickerFrame = lastFrame() ?? "";
    expect(pickerFrame).toContain("First");
    expect(pickerFrame).toContain("Second");
    expect(pickerFrame).toContain("Type to search");

    stdin.write("Second");
    await waitFor(() => !(lastFrame() ?? "").includes("First"));
    stdin.write("\r");
    await waitFor(() => controller.state.threadId === "thread_2");
    await waitFor(() => lastFrame()?.includes("second thread answer") ?? false);
    expect(controller.state.picker).toBeNull();
    unmount();
  });

  it("selects a question option with arrows and Enter", async () => {
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
          options: [{ label: "Yes", recommended: true }, { label: "No" }],
          required: true,
        },
      },
    );
    const controller = new TuiController("/tmp/cellwiki-app-test", {
      clientFactory: async () => client,
      sleep: noSleep,
    });
    const { stdin, lastFrame, unmount } = render(
      <App
        controller={controller}
        mode="fullscreen"
        viewport={{ rows: 18, columns: 60 }}
      />,
    );
    await waitFor(() => controller.state.connected);
    await controller.submit("go");
    await waitFor(() => controller.state.gate?.kind === "question");
    await waitFor(() => lastFrame()?.includes("Proceed?") ?? false);

    stdin.write("\u001b[B");
    await new Promise((resolve) => setTimeout(resolve, 10));
    stdin.write("\r");
    await waitFor(() => client.answers.length === 1);
    expect(client.answers).toEqual([["No", false]]);
    unmount();
  });
});
