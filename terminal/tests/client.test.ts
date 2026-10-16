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
});
