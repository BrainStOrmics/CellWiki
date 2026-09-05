import { describe, expect, it } from "vitest";
import { agentEventTypes } from "./AppShell";
import { reduceAgentRunMessages, type AgentRunReducerLabels } from "../features/agent/agent-run-reducer";
import type { AgentEvent, AgentEventType, ChatMessage } from "../types";

const labels: AgentRunReducerLabels = {
  failed: "FAILED",
  cancelled: "CANCELLED",
  unfinished: "UNFINISHED",
};

/**
 * Compile-time drift lock: `Record<AgentEventType, true>` stops building the
 * moment the union in types.ts gains a member, which is exactly when the SSE
 * listener list tends to be forgotten.
 */
const EVENT_TYPE_CONTRACT: Record<AgentEventType, true> = {
  run_status: true,
  message_delta: true,
  reasoning_delta: true,
  final_response: true,
  tool_started: true,
  tool_completed: true,
  tool_failed: true,
  subagent_started: true,
  subagent_completed: true,
  progress: true,
  task_confirmation_required: true,
  review_required: true,
  changeset_ready: true,
  verification: true,
  error: true,
};

function event(
  type: AgentEventType,
  data: Record<string, unknown> = {},
  message = "",
): AgentEvent {
  return {
    event_id: `e-${type}`,
    run_id: "run_1",
    thread_id: "thread_1",
    sequence: 1,
    type,
    message,
    data,
    created_at: "",
  };
}

describe("SSE 订阅表与事件合同", () => {
  it("覆盖 AgentEventType 的每一个成员（漏一个 = 直播静默丢事件）", () => {
    expect([...agentEventTypes].sort()).toEqual(Object.keys(EVENT_TYPE_CONTRACT).sort());
  });

  it("登记了 task_confirmation_required：提问卡不再只靠随后的 run_status", () => {
    expect(agentEventTypes).toContain("task_confirmation_required");
  });
});

describe("提问卡在直播与回放两条路径", () => {
  it("task_confirmation_required 把该 run 的消息标成等待用户回答", () => {
    const base: ChatMessage[] = [{ role: "user", text: "help" }];

    const reduced = reduceAgentRunMessages(
      base,
      event("task_confirmation_required", { interrupt: { question: "which page?" } }),
      labels,
    );

    expect(reduced).toHaveLength(2);
    expect(reduced[1]).toMatchObject({
      role: "agent",
      runId: "run_1",
      runStatus: "waiting_confirmation",
    });
  });

  it("已经存在的 agent 消息就地标记，不追加第二条气泡", () => {
    const base: ChatMessage[] = [
      { role: "user", text: "help" },
      { role: "agent", text: "thinking", runId: "run_1", streaming: true },
    ];

    const reduced = reduceAgentRunMessages(base, event("task_confirmation_required"), labels);

    expect(reduced).toHaveLength(2);
    expect(reduced[1]).toMatchObject({ runStatus: "waiting_confirmation", streaming: false });
  });
});

describe("未知事件类型 fail-open", () => {
  it("不认识的类型原样忽略，不抛错也不改转录", () => {
    const base: ChatMessage[] = [
      { role: "user", text: "help" },
      { role: "agent", text: "partial answer", runId: "run_1" },
    ];
    const future = event("some_future_type" as AgentEventType, { anything: 1 });

    const reduced = reduceAgentRunMessages(base, future, labels);

    expect(reduced).toEqual(base);
  });

  it("未知类型之后，后续已知事件仍然继续被处理（不中断流）", () => {
    const base: ChatMessage[] = [{ role: "user", text: "help" }];

    const afterUnknown = reduceAgentRunMessages(
      base,
      event("some_future_type" as AgentEventType),
      labels,
    );
    const afterDelta = reduceAgentRunMessages(
      afterUnknown,
      event("message_delta", {}, "still streaming"),
      labels,
    );

    expect(afterDelta).toHaveLength(2);
    expect(afterDelta[1]).toMatchObject({ role: "agent", text: "still streaming" });
  });
});
