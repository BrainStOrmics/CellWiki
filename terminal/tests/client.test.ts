import { afterEach, describe, expect, it, vi } from "vitest";

import { DaemonClient } from "../src/api/client";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("DaemonClient", () => {
  it("unwraps the pending-diff envelope", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({ pending_diffs: [{ diff_id: "diff_1" }] }),
            { status: 200, headers: { "content-type": "application/json" } },
          ),
      ),
    );
    const client = new DaemonClient("http://127.0.0.1:1", "token");
    await expect(client.listPendingDiffs()).resolves.toEqual([
      { diff_id: "diff_1" },
    ]);
  });

  it("extracts the patch from the pending-diff envelope", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({
              diff_id: "diff_1",
              patch: "diff --git a/x b/x\n+new\n",
            }),
            { status: 200 },
          ),
      ),
    );
    const client = new DaemonClient("http://127.0.0.1:1", "token");
    await expect(client.pendingDiffPatch("diff_1")).resolves.toBe(
      "diff --git a/x b/x\n+new\n",
    );
  });

  it("sends the session model selection when starting a run", async () => {
    const fetchMock = vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            run_id: "run_1",
            thread_id: "thread_1",
            status: "running",
          }),
          { status: 200, headers: { "content-type": "application/json" } },
        ),
    );
    vi.stubGlobal("fetch", fetchMock);
    const client = new DaemonClient("http://127.0.0.1:1", "token");
    await client.startRun("thread_1", "hi", "req_1", {
      provider_id: "deepseek",
      model_id: "deepseek-flash",
    });
    const call = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(JSON.parse(String(call[1].body))).toMatchObject({
      thread_id: "thread_1",
      message: "hi",
      request_id: "req_1",
      model: { provider_id: "deepseek", model_id: "deepseek-flash" },
    });
  });

  it("omits the model field without a session override", async () => {
    const fetchMock = vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            run_id: "run_1",
            thread_id: "thread_1",
            status: "running",
          }),
          { status: 200, headers: { "content-type": "application/json" } },
        ),
    );
    vi.stubGlobal("fetch", fetchMock);
    const client = new DaemonClient("http://127.0.0.1:1", "token");
    await client.startRun("thread_1", "hi", "req_1");
    const call = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(JSON.parse(String(call[1].body))).not.toHaveProperty("model");
  });
});
