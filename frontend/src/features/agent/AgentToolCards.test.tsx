import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { AgentMessageBubble } from "./AgentMessageBubble";
import { reduceAgentRunMessages, type AgentRunReducerLabels } from "./agent-run-reducer";
import { LanguageProvider } from "../../i18n";
import type { AgentEvent, AgentProcessStep, AgentTimelineNode, ChatMessage } from "../../types";

afterEach(cleanup);

const labels: AgentRunReducerLabels = {
  failed: "FAILED",
  cancelled: "CANCELLED",
  unfinished: "UNFINISHED",
  errorTypes: {},
  maintenance: {},
};

const EDIT_DIFF = {
  lines: [
    { kind: "context" as const, text: "alpha", old_no: 1, new_no: 1 },
    { kind: "removed" as const, text: "beta", old_no: 2, new_no: null },
    { kind: "added" as const, text: "BETA", old_no: null, new_no: 2 },
  ],
  removed: 1,
  added: 1,
  truncated: false,
};

function event(
  type: AgentEvent["type"],
  data: Record<string, unknown>,
  message = "",
): AgentEvent {
  return {
    event_id: `e-${type}-${Math.random().toString(16).slice(2)}`,
    run_id: "run_1",
    thread_id: "thread_1",
    sequence: 1,
    type,
    message,
    data,
    created_at: "",
  };
}

function renderBubble(message: ChatMessage) {
  return render(
    <LanguageProvider>
      <AgentMessageBubble
        message={message}
        agentLabel="Agent"
        userLabel="You"
        reasoningTitle="Thinking"
        reasoningLiveLabel="live"
      />
    </LanguageProvider>,
  );
}

function openFirstCard(container: HTMLElement) {
  const head = container.querySelector(".at-card-head") as HTMLElement;
  expect(head).not.toBeNull();
  fireEvent.click(head);
  return container.querySelector(".at-card-body") as HTMLElement;
}

/** 直播路径：事件 -> reducer -> 时间线节点。 */
function liveEditMessage(): ChatMessage {
  const started = event(
    "tool_started",
    {
      tool_name: "edit_file",
      tool_call_id: "call_1",
      args_display: { path: "wiki/cell_types/a.md", title: "a.md" },
      edit_diff_display: EDIT_DIFF,
    },
    "edit_file · a.md",
  );
  const completed = event(
    "tool_completed",
    { tool_name: "edit_file", tool_call_id: "call_1" },
    "edit_file done",
  );
  const messages = reduceAgentRunMessages(
    [{ role: "user", text: "改一下" }],
    started,
    labels,
  );
  return reduceAgentRunMessages(messages, completed, labels)[1];
}

/** 刷新回放路径：只有持久化的 process 步骤，没有 timeline。 */
function replayedEditMessage(): ChatMessage {
  const step: AgentProcessStep = {
    ...event(
      "tool_completed",
      {
        tool_name: "edit_file",
        tool_call_id: "call_1",
        args_display: { path: "wiki/cell_types/a.md", title: "a.md" },
        edit_diff_display: EDIT_DIFF,
      },
      "edit_file · a.md",
    ),
    phase: "completed",
  };
  return { role: "agent", text: "", runId: "run_1", process: [step] };
}

function diffRows(container: HTMLElement) {
  return Array.from(container.querySelectorAll(".at-diff-line"));
}

describe("工具卡片注册表", () => {
  it("edit_file 卡片渲染真行级 diff：旧/新行号与 +/- 标记", () => {
    const { container } = renderBubble(liveEditMessage());

    const body = openFirstCard(container);
    const rows = diffRows(body);

    expect(rows).toHaveLength(3);
    expect(rows[0].className).toContain("context");
    expect(rows[1].className).toContain("removed");
    expect(rows[2].className).toContain("added");
    expect(rows[1].textContent).toContain("2");
    expect(rows[1].textContent).toContain("−");
    expect(rows[1].textContent).toContain("beta");
    expect(rows[2].textContent).toContain("+");
    expect(rows[2].textContent).toContain("BETA");
    expect(body.textContent).toContain("wiki/cell_types/a.md");
    expect(body.textContent).toContain("−1 / +1");
  });

  it("直播与刷新后回放分型一致（同一种卡片、同样三行 diff）", () => {
    const live = renderBubble(liveEditMessage());
    const liveBody = openFirstCard(live.container);
    const liveKind = live.container.querySelector(".at-kind")?.textContent;
    const liveRows = diffRows(liveBody).map((row) => row.className + "|" + row.textContent);
    cleanup();

    const replayed = renderBubble(replayedEditMessage());
    const replayedBody = openFirstCard(replayed.container);

    expect(replayed.container.querySelector(".at-kind")?.textContent).toBe(liveKind);
    expect(diffRows(replayedBody).map((row) => row.className + "|" + row.textContent)).toEqual(liveRows);
  });

  it("截断标记只在 diff 真的被截断时出现", () => {
    const message = liveEditMessage();
    const node = (message.timeline ?? [])[0] as Extract<AgentTimelineNode, { kind: "tool" }>;
    node.editDiff = { ...EDIT_DIFF, truncated: true };

    const { container } = renderBubble(message);
    const body = openFirstCard(container);

    expect(body.textContent).toContain("改动过大，diff 已按上界截断");
  });

  it("没有 diff 投影时 edit_file 退回通用卡身，不炸也不空白", () => {
    const message = liveEditMessage();
    const node = (message.timeline ?? [])[0] as Extract<AgentTimelineNode, { kind: "tool" }>;
    node.editDiff = undefined;
    node.resultPreview = {
      head: "ok: 1 file changed",
      tail: "",
      total_chars: 20,
      truncated: false,
      kind: "text",
    };

    const { container } = renderBubble(message);
    const body = openFirstCard(container);

    expect(diffRows(body)).toHaveLength(0);
    expect(body.textContent).toContain("ok: 1 file changed");
  });

  it("lint 卡片先给结论，再给原始报告", () => {
    const message: ChatMessage = {
      role: "agent",
      text: "",
      runId: "run_1",
      timeline: [
        {
          kind: "tool",
          phase: "completed",
          toolName: "lint_knowledge_base",
          summary: "lint_knowledge_base",
          step: { ...event("tool_completed", { tool_name: "lint_knowledge_base" }), phase: "completed" },
          resultPreview: {
            head: "{\"status\":\"passed_with_warnings\"}",
            tail: "",
            total_chars: 32,
            truncated: true,
            kind: "text",
            summary: {
              status: "passed_with_warnings",
              page_count: 12,
              error_count: 0,
              warning_count: 40,
            },
          },
        },
      ],
    };

    const { container } = renderBubble(message);
    const body = openFirstCard(container);

    expect(container.querySelector(".at-kind")?.textContent).toBe("Lint");
    expect(body.querySelector(".at-lint-status")?.textContent).toBe("passed_with_warnings");
    expect(body.textContent).toContain("12 pages · 0 errors · 40 warnings");
  });

  it("git 卡片把子命令与路径参数还原成一行命令", () => {
    const message: ChatMessage = {
      role: "agent",
      text: "",
      runId: "run_1",
      timeline: [
        {
          kind: "tool",
          phase: "completed",
          toolName: "git",
          summary: "git commit",
          step: { ...event("tool_completed", { tool_name: "git" }), phase: "completed" },
          argsDisplay: { args: ["commit", "-m", "docs: sync"], title: "commit -m docs: sync" },
        },
      ],
    };

    const { container } = renderBubble(message);
    const body = openFirstCard(container);

    expect(container.querySelector(".at-kind")?.textContent).toBe("Git");
    expect(body.textContent).toContain("git commit -m docs: sync");
  });

  it("附件卡片报出附件标识与晋升目标", () => {
    const message: ChatMessage = {
      role: "agent",
      text: "",
      runId: "run_1",
      timeline: [
        {
          kind: "tool",
          phase: "completed",
          toolName: "promote_attachment",
          summary: "promote_attachment",
          step: { ...event("tool_completed", { tool_name: "promote_attachment" }), phase: "completed" },
          argsDisplay: { attachment_id: "att_123", source_type: "paper", title: "att_123" },
        },
      ],
    };

    const { container } = renderBubble(message);
    openFirstCard(container);

    expect(container.querySelector(".at-kind")?.textContent).toBe("Promote");
    expect(container.querySelector(".at-file-path")?.textContent).toBe("att_123");
    expect(container.querySelector(".at-file-lang")?.textContent).toBe("paper");
  });

  it("未登记的工具 fail-open：报出自己的名字并走通用卡身", () => {
    const message: ChatMessage = {
      role: "agent",
      text: "",
      runId: "run_1",
      timeline: [
        {
          kind: "tool",
          phase: "completed",
          toolName: "some_future_tool",
          summary: "some_future_tool did a thing",
          step: { ...event("tool_completed", { tool_name: "some_future_tool" }), phase: "completed" },
        },
      ],
    };

    const { container } = renderBubble(message);
    const body = openFirstCard(container);

    expect(container.querySelector(".at-kind")?.textContent).toBe("some_future_tool");
    expect(body.querySelector(".at-detail")).not.toBeNull();
  });

  it("搜索卡片保留命中数那一行", () => {
    const message: ChatMessage = {
      role: "agent",
      text: "",
      runId: "run_1",
      timeline: [
        {
          kind: "tool",
          phase: "completed",
          toolName: "grep",
          summary: "grep CL:0000624",
          step: { ...event("tool_completed", { tool_name: "grep" }), phase: "completed" },
          resultPreview: {
            head: "wiki/a.md:1: hit",
            tail: "",
            total_chars: 18,
            truncated: false,
            kind: "results",
            count: 7,
          },
        },
      ],
    };

    const { container } = renderBubble(message);
    const body = openFirstCard(container);

    expect(body.textContent).toContain("7 条结果");
  });

  it("既有卡片的分型没有因为注册表化而漂移", () => {
    const cases: Array<[string, string]> = [
      ["run_powershell", "Pwsh"],
      ["read_file", "Read"],
      ["write_file", "Write"],
      ["delete_file", "Delete"],
      ["rename_file", "Rename"],
      ["glob", "Glob"],
      ["ls", "LS"],
      ["search_wiki", "Search"],
      ["ingest_sources", "Ingest"],
      ["ask_user_question", "Ask"],
      ["get_project_status", "Status"],
      ["read_attachment", "Attachment"],
    ];
    for (const [toolName, label] of cases) {
      const message: ChatMessage = {
        role: "agent",
        text: "",
        runId: "run_1",
        timeline: [
          {
            kind: "tool",
            phase: "completed",
            toolName,
            summary: toolName,
            step: { ...event("tool_completed", { tool_name: toolName }), phase: "completed" },
          },
        ],
      };
      const { container } = renderBubble(message);
      expect(container.querySelector(".at-kind")?.textContent).toBe(label);
      cleanup();
    }
  });
});
