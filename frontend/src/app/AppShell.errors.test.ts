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
    });
  });

  it("keeps the offline guidance for transport failures", () => {
    expect(agentRequestFailure(new TypeError("Failed to fetch"), "runtime offline"))
      .toEqual({ text: "runtime offline", meta: "RUNTIME OFFLINE" });
  });
});
