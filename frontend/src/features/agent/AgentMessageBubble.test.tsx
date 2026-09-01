import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AgentMessageBubble } from "./AgentMessageBubble";
import { LanguageProvider } from "../../i18n";
import type { AgentProcessStep, AgentTimelineNode, ChatMessage } from "../../types";

vi.mock("../../lib/product-api", () => ({
  getJson: vi.fn((path: string) => Promise.resolve(
    String(path).endsWith("/question") ? pendingQuestion() : { spans: [] },
  )),
  postJson: vi.fn(),
  getText: vi.fn(() => Promise.resolve("# Full file\nline 2\nline 3")),
}));

function pendingQuestion() {
  return {
    question_id: "q_1",
    run_id: "run_1",
    thread_id: "thread_1",
    tool_call_id: null,
    question: "确认收录这篇论文吗？",
    options: ["确认，开始 ingest", "先不处理"],
    required: false,
    status: "pending",
    answers: null,
    created_at: "2026-08-27T00:00:00Z",
    answered_at: null,
  };
}

afterEach(cleanup);

const labels = {
  agentLabel: "CewiPilot",
  userLabel: "You",
  reasoningTitle: "think",
  reasoningLiveLabel: "思考中…",
};

function renderBubble(message: ChatMessage) {
  return render(
    <LanguageProvider>
      <AgentMessageBubble {...labels} message={message} onQuestionAnswered={vi.fn()} />
    </LanguageProvider>,
  );
}

function toolStep(node: { phase?: "running" | "completed" | "failed"; message: string; toolName: string; toolCallId: string; data?: Record<string, unknown> }): AgentProcessStep {
  return {
    event_id: `e_${node.toolCallId}`,
    run_id: "run_1",
    thread_id: "thread_1",
    sequence: 1,
    type: "tool_completed",
    message: node.message,
    data: {
      tool_name: node.toolName,
      tool_call_id: node.toolCallId,
      label_args: { pattern: "cell" },
      ...node.data,
    },
    created_at: "2026-08-27T00:00:00Z",
    phase: node.phase ?? "completed",
  };
}

function toolNode(overrides: Partial<Extract<AgentTimelineNode, { kind: "tool" }>> & { toolCallId: string }): Extract<AgentTimelineNode, { kind: "tool" }> {
  const toolName = overrides.toolName ?? "grep";
  return {
    kind: "tool",
    phase: overrides.phase ?? "completed",
    toolName,
    summary: overrides.summary ?? `${toolName} → 2 matches`,
    step: toolStep({
      message: overrides.summary ?? `${toolName} → 2 matches`,
      toolName,
      toolCallId: overrides.toolCallId,
      data: {
        args_display: overrides.argsDisplay,
        result_preview: overrides.resultPreview,
      },
    }),
    argsDisplay: overrides.argsDisplay,
    resultPreview: overrides.resultPreview,
  };
}

describe("AgentMessageBubble", () => {
  it("renders context, thinking, tool and text nodes as a flat timeline in order", () => {
    const timeline: AgentTimelineNode[] = [
      { kind: "context", label: "上下文注入", detail: "wiki/index.md" },
      { kind: "thinking", text: "先读取文件" },
      toolNode({ toolCallId: "c1", summary: "grep → 2 matches" }),
      { kind: "text", text: "找到了 2 处" },
    ];
    renderBubble({ role: "agent", text: "", timeline, streaming: true });

    expect(screen.getByText(/上下文注入 · wiki\/index.md/)).toBeInTheDocument();
    expect(screen.getByText("Grep", { selector: ".at-kind" })).toBeInTheDocument();
    expect(screen.getByText("找到了 2 处")).toBeInTheDocument();
  });

  it("no longer renders citation chips or missing-evidence blocks", () => {
    renderBubble({
      role: "agent",
      text: "answer",
      citations: [{ page_id: "wiki/x" }],
      missingEvidence: ["gap-a"],
      validationIssues: [{ code: "missing_citation", message: "issue-1" }],
    });

    expect(screen.queryByText("wiki/x")).not.toBeInTheDocument();
    expect(screen.queryByText("gap-a")).not.toBeInTheDocument();
    expect(screen.queryByText("issue-1")).not.toBeInTheDocument();
    expect(screen.getByText("answer")).toBeInTheDocument();
  });

  it("renders thinking as a collapsed single line with a truncated preview", () => {
    renderBubble({
      role: "agent",
      text: "",
      timeline: [{ kind: "thinking", text: "第一段思考内容\n第二段思考内容" }],
      streaming: true,
    });
    const details = document.querySelector(".agent-timeline-think") as HTMLDetailsElement;
    // Streaming shows the newest line only; the body stays collapsed.
    expect(details.open).toBe(false);
    expect(screen.getByText("第二段思考内容", { selector: ".at-think-preview" })).toBeInTheDocument();
  });

  it("shows the first line as preview and full text after expanding when settled", () => {
    renderBubble({
      role: "agent",
      text: "done",
      timeline: [{ kind: "thinking", text: "第一段思考内容\n第二段思考内容" }, { kind: "text", text: "done" }],
      streaming: false,
    });
    expect(screen.getByText("第一段思考内容", { selector: ".at-think-preview" })).toBeInTheDocument();
    const summary = document.querySelector(".agent-timeline-think summary") as HTMLElement;
    fireEvent.click(summary);
    expect((document.querySelector(".agent-timeline-think") as HTMLDetailsElement).open).toBe(true);
    expect(document.querySelector(".agent-timeline-think-body")?.textContent).toContain("第二段思考内容");
  });

  it("truncates a long thinking preview line", () => {
    const long = "x".repeat(150);
    renderBubble({ role: "agent", text: "", timeline: [{ kind: "thinking", text: long }] });
    const preview = screen.getByText(/…$/, { selector: ".at-think-preview" });
    expect(preview.textContent?.length).toBeLessThanOrEqual(101);
  });

  it("renders persisted answer text for legacy messages that only carry process steps", () => {
    renderBubble({
      role: "agent",
      text: "古老答案文本",
      process: [toolStep({ message: "grep → 2 matches", toolName: "grep", toolCallId: "c1" })],
    });

    expect(screen.getByText("Grep", { selector: ".at-kind" })).toBeInTheDocument();
    expect(screen.getByText("古老答案文本")).toBeInTheDocument();
  });

  it("expands a legacy tool card to its safe detail on click", () => {
    const timeline: AgentTimelineNode[] = [toolNode({ toolCallId: "c1", summary: "grep → 2 matches" })];
    const { container } = renderBubble({ role: "agent", text: "", timeline });
    expect(container.querySelector(".at-card-body")).toBeNull();
    fireEvent.click(container.querySelector(".at-card-head") as HTMLButtonElement);
    const detail = container.querySelector(".at-detail");
    expect(detail).not.toBeNull();
    expect(detail?.textContent).toContain("pattern");
  });

  it("renders a Pwsh card with the full command and output preview", () => {
    const timeline: AgentTimelineNode[] = [toolNode({
      toolCallId: "p1",
      toolName: "run_powershell",
      summary: "run_powershell started.",
      argsDisplay: { command: "Get-Location; Get-ChildItem -Force", title: "Get-Location; Get-ChildItem -Force" },
      resultPreview: { head: "Path\n----\nD:\\GitHub\\CellWiki", tail: "", total_chars: 30, total_lines: 3, truncated: false, kind: "text" },
    })];
    const { container } = renderBubble({ role: "agent", text: "", timeline });
    expect(screen.getByText("Pwsh", { selector: ".at-kind" })).toBeInTheDocument();
    expect(screen.getByText("Get-Location; Get-ChildItem -Force", { selector: ".at-label" })).toBeInTheDocument();
    fireEvent.click(container.querySelector(".at-card-head") as HTMLButtonElement);
    const body = container.querySelector(".at-card-body");
    expect(body?.textContent).toContain("Get-ChildItem -Force");
    expect(body?.textContent).toContain("D:\\GitHub\\CellWiki");
    expect(container.querySelector(".at-copy")).not.toBeNull();
  });

  it("renders a Read card with line numbers, rest-lines loader, and copy", async () => {
    const timeline: AgentTimelineNode[] = [toolNode({
      toolCallId: "r1",
      toolName: "read_file",
      summary: "read_file → wiki/a.md",
      argsDisplay: { path: "wiki/a.md", title: "a.md" },
      resultPreview: {
        head: "# CellWiki Domain Context\n\n本文档定义术语",
        tail: "10. 系统维护文件",
        total_chars: 5_000,
        total_lines: 61,
        truncated: true,
        kind: "text",
      },
    })];
    const { container } = renderBubble({ role: "agent", text: "", timeline });
    expect(screen.getByText("Read", { selector: ".at-kind" })).toBeInTheDocument();
    fireEvent.click(container.querySelector(".at-card-head") as HTMLButtonElement);
    expect(container.querySelectorAll(".at-code-no").length).toBeGreaterThan(0);
    fireEvent.click(screen.getByText("其余 57 行"));
    // Prism tokenizes the text, so assert on the rendered code block content.
    await vi.waitFor(() => {
      const blocks = [...container.querySelectorAll(".at-code")];
      expect(blocks.some((block) => block.textContent?.includes("# Full file"))).toBe(true);
    });
    expect(screen.getByText("wiki/a.md", { selector: ".at-file-path" })).toBeInTheDocument();
  });

  it("marks failed and running tool cards", () => {
    const { container } = renderBubble({
      role: "agent",
      text: "",
      timeline: [
        toolNode({ toolCallId: "f1", toolName: "grep", phase: "failed", summary: "grep → error: bad path" }),
        toolNode({ toolCallId: "g1", toolName: "glob", phase: "running", summary: "glob started." }),
      ],
    });
    expect(container.querySelector(".agent-timeline-card.failed")).not.toBeNull();
    expect(container.querySelector(".agent-timeline-card.running")).not.toBeNull();
  });

  it("mounts the question card only while its run awaits the user's answer", async () => {
    renderBubble({ role: "agent", text: "answer", runId: "run_1", runStatus: "waiting_confirmation" });
    expect(await screen.findByTestId("question-card")).toBeInTheDocument();
    expect(screen.getByText("确认，开始 ingest")).toBeInTheDocument();
  });

  it("does not mount a question card for a settled run", async () => {
    renderBubble({ role: "agent", text: "answer", runId: "run_1", runStatus: "succeeded" });
    await new Promise((resolve) => window.setTimeout(resolve, 0));
    expect(screen.queryByTestId("question-card")).toBeNull();
  });
});
