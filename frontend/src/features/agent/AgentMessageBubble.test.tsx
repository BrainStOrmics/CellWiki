import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AgentMessageBubble } from "./AgentMessageBubble";
import type { AgentProcessStep, AgentTimelineNode, ChatMessage } from "../../types";

afterEach(cleanup);

const labels = {
  agentLabel: "CewiPilot",
  userLabel: "You",
  reasoningTitle: "Thinking",
  reasoningLiveLabel: "Thinking…",
  diagnosticsLabel: "Run details",
};

function toolStep(node: { phase?: "running" | "completed" | "failed"; message: string; toolName: string; toolCallId: string }): AgentProcessStep {
  return {
    event_id: `e_${node.toolCallId}`,
    run_id: "run_1",
    thread_id: "thread_1",
    sequence: 1,
    type: "tool_completed",
    message: node.message,
    data: { tool_name: node.toolName, tool_call_id: node.toolCallId, label_args: { pattern: "cell" } },
    created_at: "2026-08-27T00:00:00Z",
    phase: node.phase ?? "completed",
  };
}

describe("AgentMessageBubble", () => {
  it("renders context, thinking, tool and text nodes as a flat timeline in order", () => {
    const timeline: AgentTimelineNode[] = [
      { kind: "context", label: "CONTEXT", detail: "wiki/index.md" },
      { kind: "thinking", text: "先读取文件" },
      { kind: "tool", phase: "completed", toolName: "grep", summary: "grep → 2 matches", step: toolStep({ message: "grep → 2 matches", toolName: "grep", toolCallId: "c1" }) },
      { kind: "text", text: "找到了 2 处" },
    ];
    render(
      <AgentMessageBubble
        {...labels}
        message={{ role: "agent", text: "", timeline, streaming: true }}
        onQuestionAnswered={vi.fn()}
      />,
    );

    expect(screen.getByText("先读取文件")).toBeInTheDocument();
    expect(screen.getByText("grep", { selector: ".at-kind" })).toBeInTheDocument();
    expect(screen.getByText("找到了 2 处")).toBeInTheDocument();
    // 上下文节点：label + detail 拼接展示
    expect(screen.getByText(/CONTEXT/)).toBeInTheDocument();
  });

  it("no longer renders citation chips or missing-evidence blocks", () => {
    render(
      <AgentMessageBubble
        {...labels}
        message={{
          role: "agent",
          text: "answer",
          citations: [{ page_id: "wiki/x" }],
          missingEvidence: ["gap-a"],
          validationIssues: [{ code: "missing_citation", message: "issue-1" }],
        }}
        onQuestionAnswered={vi.fn()}
      />,
    );

    expect(screen.queryByText("wiki/x")).not.toBeInTheDocument();
    expect(screen.queryByText("gap-a")).not.toBeInTheDocument();
    expect(screen.queryByText("issue-1")).not.toBeInTheDocument();
    expect(screen.getByText("answer")).toBeInTheDocument();
  });

  it("auto-expands thinking while streaming and collapses after completion", () => {
    const { rerender } = render(
      <AgentMessageBubble
        {...labels}
        message={{ role: "agent", text: "", timeline: [{ kind: "thinking", text: "思考中" }], streaming: true }}
        onQuestionAnswered={vi.fn()}
      />,
    );
    const details = document.querySelector(".agent-timeline-think") as HTMLDetailsElement;
    expect(details.open).toBe(true);
    expect(screen.getByText("思考中")).toBeInTheDocument();

    rerender(
      <AgentMessageBubble
        {...labels}
        message={{ role: "agent", text: "done", timeline: [{ kind: "thinking", text: "思考中" }, { kind: "text", text: "done" }], streaming: false }}
        onQuestionAnswered={vi.fn()}
      />,
    );
    expect((document.querySelector(".agent-timeline-think") as HTMLDetailsElement).open).toBe(false);
  });

  it("renders persisted answer text for legacy messages that only carry process steps", () => {
    render(
      <AgentMessageBubble
        {...labels}
        message={{
          role: "agent",
          text: "古老答案文本",
          process: [toolStep({ message: "grep → 2 matches", toolName: "grep", toolCallId: "c1" })],
        }}
        onQuestionAnswered={vi.fn()}
      />,
    );

    expect(screen.getByText("grep", { selector: ".at-kind" })).toBeInTheDocument();
    expect(screen.getByText("古老答案文本")).toBeInTheDocument();
  });

  it("expands a tool line to its safe detail on click", () => {
    const timeline: AgentTimelineNode[] = [
      { kind: "tool", phase: "completed", toolName: "grep", summary: "grep → 2 matches", step: toolStep({ message: "grep → 2 matches", toolName: "grep", toolCallId: "c1" }) },
    ];
    const { container } = render(
      <AgentMessageBubble {...labels} message={{ role: "agent", text: "", timeline }} onQuestionAnswered={vi.fn()} />,
    );
    expect(container.querySelector(".at-detail")).toBeNull();
    const button = container.querySelector(".at-line") as HTMLButtonElement;
    fireEvent.click(button);
    const detail = container.querySelector(".at-detail");
    expect(detail).not.toBeNull();
    expect(detail?.textContent).toContain("pattern");
  });
});