import { render } from "ink-testing-library";
import { describe, expect, it } from "vitest";

import { App } from "../src/components/App";
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
    const { stdin, unmount } = render(<App controller={controller} />);
    await waitFor(() => controller.state.connected);
    stdin.write("hi");
    await new Promise((resolve) => setTimeout(resolve, 10));
    stdin.write("\r");
    await waitFor(() => client.started.length === 1);
    expect(client.started[0]).toEqual(["thread_1", "hi"]);
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
});
