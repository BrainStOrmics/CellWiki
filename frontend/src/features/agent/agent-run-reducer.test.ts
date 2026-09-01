import { describe, expect, it } from "vitest";
import type { AgentEvent, ChatMessage } from "../../types";
import { reduceAgentRunMessages } from "./agent-run-reducer";

const labels = {
  failed: "failed",
  cancelled: "cancelled",
  unfinished: "unfinished",
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
  it("accumulates reasoning deltas into reasoning without touching the answer", () => {
    const first = reduceAgentRunMessages([], event(1, "reasoning_delta", {}, "思考"), labels);
    const second = reduceAgentRunMessages(first, event(2, "reasoning_delta", {}, "过程"), labels);
    expect(second[0].reasoning).toBe("思考过程");
    expect(second[0].text).toBe("");
    expect(second[0].process).toBeUndefined();
  });

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
    expect(cancelled[0].runStatus).toBe("cancelled");
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

describe("reduceAgentRunMessages timeline", () => {
  it("builds context, tool, narration and thinking nodes in arrival order", () => {
    const withContext = { ...labels, timelineContext: { label: "CONTEXT", detail: "wiki/index.md" } };
    const started = reduceAgentRunMessages([], event(1, "tool_started", { tool_name: "grep", tool_call_id: "c1" }, "grep · pattern=cell"), withContext);
    const completed = reduceAgentRunMessages(started, event(2, "tool_completed", { tool_name: "grep", tool_call_id: "c1" }, "grep → 2 matches"), withContext);
    const narrated = reduceAgentRunMessages(completed, event(3, "message_delta", {}, "找到了 2 处"), withContext);
    const thought = reduceAgentRunMessages(narrated, event(4, "reasoning_delta", {}, "再确认一下"), withContext);

    const nodes = thought[0].timeline ?? [];
    expect(nodes.map((node) => node.kind)).toEqual(["context", "tool", "text", "thinking"]);
    const tool = nodes[1];
    expect(tool.kind).toBe("tool");
    if (tool.kind === "tool") {
      expect(tool.toolName).toBe("grep");
      expect(tool.phase).toBe("completed");
      expect(tool.summary).toBe("grep → 2 matches");
    }
    const context = nodes[0];
    if (context.kind === "context") {
      expect(context.label).toBe("CONTEXT");
      expect(context.detail).toBe("wiki/index.md");
    }
  });

  it("passes bounded card projections through and preserves them on completion", () => {
    const argsDisplay = { command: "Get-ChildItem -Force", title: "Get-ChildItem -Force" };
    const resultPreview = { head: "Path\n----", tail: "wiki", total_chars: 20, total_lines: 3, truncated: true, kind: "text" };
    const started = reduceAgentRunMessages(
      [],
      event(1, "tool_started", { tool_name: "run_powershell", tool_call_id: "p1", args_display: argsDisplay }, "run_powershell started."),
      labels,
    );
    const startNode = (started[0].timeline ?? [])[0];
    if (startNode.kind === "tool") {
      expect(startNode.argsDisplay).toEqual(argsDisplay);
      expect(startNode.resultPreview).toBeUndefined();
    }
    const completed = reduceAgentRunMessages(
      started,
      event(2, "tool_completed", { tool_name: "run_powershell", tool_call_id: "p1", result_preview: resultPreview }, "run_powershell → Path"),
      labels,
    );
    const doneNode = (completed[0].timeline ?? [])[0];
    if (doneNode.kind === "tool") {
      expect(doneNode.phase).toBe("completed");
      expect(doneNode.argsDisplay).toEqual(argsDisplay);
      expect(doneNode.resultPreview).toEqual(resultPreview);
    }
  });

  it("merges adjacent text deltas and adjacent thinking deltas", () => {
    const one = reduceAgentRunMessages([], event(1, "message_delta", {}, "第一段 "), labels);
    const two = reduceAgentRunMessages(one, event(2, "message_delta", {}, "第二段"), labels);
    const textNodes = (two[0].timeline ?? []).filter((node) => node.kind === "text");
    expect(textNodes).toHaveLength(1);
    if (textNodes[0].kind === "text") expect(textNodes[0].text).toBe("第一段 第二段");

    const r1 = reduceAgentRunMessages([], event(3, "reasoning_delta", {}, "思考一"), labels);
    const r2 = reduceAgentRunMessages(r1, event(4, "reasoning_delta", {}, "思考二"), labels);
    const thoughtNodes = (r2[0].timeline ?? []).filter((node) => node.kind === "thinking");
    expect(thoughtNodes).toHaveLength(1);
    if (thoughtNodes[0].kind === "thinking") expect(thoughtNodes[0].text).toBe("思考一思考二");
  });

  it("maps review/verification events to status nodes with tone", () => {
    const reviewed = reduceAgentRunMessages([], event(1, "review_required", {}, "需要审核"), labels);
    const reviewNodes = reviewed[0].timeline ?? [];
    const reviewNode = reviewNodes[reviewNodes.length - 1];
    expect(reviewNode.kind).toBe("status");
    if (reviewNode.kind === "status") expect(reviewNode.tone).toBe("warning");

    const verified = reduceAgentRunMessages([], event(1, "verification", {}, "校验通过"), labels);
    const verifyNodes = verified[0].timeline ?? [];
    const verifyNode = verifyNodes[verifyNodes.length - 1];
    if (verifyNode.kind === "status") expect(verifyNode.tone).toBe("info");
  });

  it("does not duplicate the answer when text nodes already streamed", () => {
    const narrated = reduceAgentRunMessages([], event(1, "message_delta", {}, "答案第一段"), labels);
    const finished = reduceAgentRunMessages(narrated, event(2, "final_response", { answer: "答案第一段" }, "答案第一段"), labels);
    const textNodes = (finished[0].timeline ?? []).filter((node) => node.kind === "text");
    expect(textNodes).toHaveLength(1);
  });

  it("seeds the answer text node when no text streamed before final_response", () => {
    const finished = reduceAgentRunMessages([], event(1, "final_response", { answer: "纯答案" }, "纯答案"), labels);
    const nodes = finished[0].timeline ?? [];
    expect(nodes.map((node) => node.kind)).toEqual(["text"]);
  });
});
