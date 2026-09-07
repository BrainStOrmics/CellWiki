import { describe, expect, it } from "vitest";
import { ProductApiError } from "../lib/product-api";
import { agentRequestFailure } from "./AppShell";

describe("agent request error presentation", () => {
  it("preserves Product API details instead of reporting the runtime offline", () => {
    const result = agentRequestFailure(
      new ProductApiError(
        "another AgentRuntimeManager already owns this project",
        503,
      ),
      "runtime offline",
    );

    expect(result).toEqual({
      text: "another AgentRuntimeManager already owns this project",
      meta: "AGENT REQUEST FAILED · HTTP 503",
      code: null,
    });
  });

  it("keeps the offline guidance for transport failures", () => {
    expect(agentRequestFailure(new TypeError("Failed to fetch"), "runtime offline"))
      .toEqual({ text: "runtime offline", meta: "RUNTIME OFFLINE", code: null });
  });

  it("交出后端的稳定判别码，让调用方按类别而不是按文案分流", () => {
    const result = agentRequestFailure(
      new ProductApiError(
        "run r1 has no usable checkpoint",
        409,
        { detail: { code: "checkpoint_missing", message: "run r1 has no usable checkpoint" } },
        "checkpoint_missing",
      ),
      "runtime offline",
    );

    expect(result.code).toBe("checkpoint_missing");
    expect(result.meta).toBe("AGENT REQUEST FAILED · HTTP 409");
  });
});
