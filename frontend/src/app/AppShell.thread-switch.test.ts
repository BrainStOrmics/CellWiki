import { describe, expect, it } from "vitest";
import { rebuildAgentTranscript } from "./AppShell";
import type { AgentRunReducerLabels } from "../features/agent/agent-run-reducer";
import type { AgentEvent, ChatMessage } from "../types";

const labels: AgentRunReducerLabels = {
  evidenceMeta: "EVIDENCE",
  failed: "FAILED",
  cancelled: "CANCELLED",
  unfinished: "UNFINISHED",
  formatConfidence: (confidence) => confidence,
};

function event(
  sequence: number,
  type: AgentEvent["type"],
  message = "",
  data: Record<string, unknown> = {},
): AgentEvent {
  return {
    event_id: `e-${sequence}`,
    run_id: "run_1",
    thread_id: "thread_1",
    sequence,
    type,
    message,
    data,
    created_at: "",
  };
}

describe("rebuildAgentTranscript", () => {
  it("rebuilds a partial in-flight answer from accumulated message deltas", () => {
    const base: ChatMessage[] = [{ role: "user", text: "hello?" }];
    const events = [
      event(1, "message_delta", "Hel"),
      event(2, "message_delta", "lo"),
      event(3, "run_status", "", { status: "running", terminal: false }),
    ];
    const rebuilt = rebuildAgentTranscript(base, "run_1", events, labels);

    expect(rebuilt).toHaveLength(2);
    expect(rebuilt[0]).toEqual({ role: "user", text: "hello?" });
    expect(rebuilt[1]).toMatchObject({
      role: "agent",
      runId: "run_1",
      text: "Hello",
      streaming: true,
    });
  });

  it("replaces a stale persisted answer instead of duplicating text", () => {
    const base: ChatMessage[] = [
      { role: "user", text: "review this", runId: "run_1" },
      {
        role: "agent",
        text: "STALE OLD ANSWER",
        runId: "run_1",
        runStatus: "succeeded",
        streaming: false,
      },
    ];
    const events = [
      event(1, "message_delta", "New"),
      event(2, "message_delta", " final"),
      event(3, "final_response", "New final answer", {
        answer: "New final answer",
        verification_level: "unvalidated",
        knowledge_scope: "unvalidated",
        citations: [],
      }),
      event(4, "run_status", "", { status: "succeeded", terminal: true }),
    ];
    const rebuilt = rebuildAgentTranscript(base, "run_1", events, labels);

    const agentMessages = rebuilt.filter((message) => message.role === "agent");
    expect(agentMessages).toHaveLength(1);
    expect(agentMessages[0]).toMatchObject({
      runId: "run_1",
      text: "New final answer",
      runStatus: "succeeded",
      streaming: false,
    });
  });

  it("keeps other runs' messages untouched", () => {
    const other = {
      role: "agent" as const,
      text: "earlier answer",
      runId: "run_0",
      runStatus: "succeeded" as const,
    };
    const base: ChatMessage[] = [other, { role: "user", text: "continue", runId: "run_1" }];
    const events = [event(1, "message_delta", "next")];
    const rebuilt = rebuildAgentTranscript(base, "run_1", events, labels);

    expect(rebuilt[0]).toEqual(other);
    expect(rebuilt.filter((message) => message.role === "agent")).toHaveLength(2);
  });

  it("settles a failed run to the terminal status", () => {
    const base: ChatMessage[] = [{ role: "user", text: "go" }];
    const events = [
      event(1, "message_delta", "partial"),
      event(2, "run_status", "boom", {
        status: "failed",
        terminal: true,
        error_message: "boom",
      }),
    ];
    const rebuilt = rebuildAgentTranscript(base, "run_1", events, labels);

    expect(rebuilt[1]).toMatchObject({
      role: "agent",
      runId: "run_1",
      text: "partial",
      runStatus: "failed",
    });
  });
});
