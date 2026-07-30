import { describe, expect, it } from "vitest";
import type { AgentEvent, ChatMessage } from "../../types";
import { reduceAgentRunMessages } from "./agent-run-reducer";

const labels = {
  evidenceMeta: "evidence",
  failed: "failed",
  cancelled: "cancelled",
  formatConfidence: (value: "low" | "medium" | "high") => value,
};

function event(
  sequence: number,
  type: AgentEvent["type"],
  data: Record<string, unknown> = {},
  message = "",
): AgentEvent {
  return {
    event_id: `event_${sequence}`,
    run_id: "run_1",
    thread_id: "thread_1",
    sequence,
    type,
    message,
    data,
    created_at: "2026-07-29T00:00:00Z",
  };
}

describe("reduceAgentRunMessages", () => {
  it("is idempotent for replayed process events", () => {
    const started = event(1, "tool_started", { activity_code: "reading_page" }, "Reading page");
    const once = reduceAgentRunMessages([], started, labels);
    const twice = reduceAgentRunMessages(once, started, labels);
    expect(twice[0].process).toHaveLength(1);
  });

  it("settles every running step on a failed terminal event and preserves the error", () => {
    const started = reduceAgentRunMessages(
      [],
      event(1, "tool_started", {}, "Reading page"),
      labels,
    );
    const failed = reduceAgentRunMessages(
      started,
      event(2, "run_status", {
        status: "failed",
        terminal: true,
        error_message: "Provider timed out",
      }),
      labels,
    );
    expect(failed[0].text).toBe("Provider timed out");
    expect(failed[0].streaming).toBe(false);
    expect(failed[0].process?.[0].phase).toBe("failed");
  });

  it("reuses the existing streaming bubble when cancellation arrives", () => {
    const messages: ChatMessage[] = [{
      role: "agent",
      text: "",
      runId: "run_1",
      streaming: true,
    }];
    const cancelled = reduceAgentRunMessages(
      messages,
      event(2, "run_status", { status: "cancelled", terminal: true }, "Cancelled safely"),
      labels,
    );
    expect(cancelled).toHaveLength(1);
    expect(cancelled[0].text).toBe("Cancelled safely");
    expect(cancelled[0].streaming).toBe(false);
  });

  it("downgrades legacy high-confidence answers without verification fields", () => {
    const result = reduceAgentRunMessages(
      [],
      event(2, "final_response", {
        answer: "Legacy answer",
        confidence: "high",
        citations: [],
      }),
      labels,
    );
    expect(result[0].verificationLevel).toBe("unvalidated");
    expect(result[0].confidence).toBe("low");
  });
});

