import { describe, expect, it } from "vitest";
import {
  cacheCoversDurableHistory,
  rebuildAgentTranscript,
  runReplayAnchor,
  threadViewIsCurrent,
} from "./AppShell";
import type { AgentRunReducerLabels } from "../features/agent/agent-run-reducer";
import type { AgentEvent, AgentMessage, ChatMessage } from "../types";

const labels: AgentRunReducerLabels = {
  failed: "FAILED",
  cancelled: "CANCELLED",
  unfinished: "UNFINISHED",
  errorTypes: {},
  maintenance: {},
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

  it("keeps the durable answer when the event log carries no answer text", () => {
    const answer = "## Evidence summary\n\nFOXP3 is the fixture marker.";
    const base: ChatMessage[] = [
      { role: "user", text: "which markers?", runId: "run_1" },
      { role: "agent", text: answer, runId: "run_1", runStatus: "succeeded", streaming: false },
    ];
    const events = [
      event(1, "tool_started", "Reading", { tool_name: "read_wiki_page" }),
      event(2, "tool_completed", "Read", { tool_name: "read_wiki_page" }),
      event(3, "progress", "Ledger assembled", { stage: "evidence" }),
      event(4, "run_status", "", { status: "succeeded", terminal: true }),
    ];
    const rebuilt = rebuildAgentTranscript(base, "run_1", events, labels);

    const agentMessages = rebuilt.filter((message) => message.role === "agent");
    expect(agentMessages).toHaveLength(1);
    expect(agentMessages[0].text).toBe(answer);
    // The bubble renders the timeline when it has nodes, so the answer must be a
    // timeline text node too or the markdown never reaches the DOM.
    expect(agentMessages[0].timeline?.some((node) => node.kind === "text" && node.text === answer)).toBe(true);
    expect(agentMessages[0].timeline?.some((node) => node.kind === "tool")).toBe(true);
  });

  it("keeps the durable answer when the run has no events at all", () => {
    const base: ChatMessage[] = [
      { role: "user", text: "which markers?", runId: "run_1" },
      { role: "agent", text: "durable answer", runId: "run_1", runStatus: "succeeded", streaming: false },
    ];
    const rebuilt = rebuildAgentTranscript(base, "run_1", [], labels);

    expect(rebuilt).toHaveLength(2);
    expect(rebuilt[1]).toMatchObject({ role: "agent", runId: "run_1", text: "durable answer" });
  });
});

describe("cacheCoversDurableHistory", () => {
  function durable(runId: string, role: "user" | "assistant" = "assistant"): AgentMessage {
    return {
      message_id: `m_${runId}_${role}`,
      thread_id: "thread_1",
      run_id: runId,
      sequence: 1,
      role,
      content: "x",
      data: {},
      created_at: "",
    };
  }

  it("accepts a cache that still holds every durable run", () => {
    const cache: ChatMessage[] = [
      { role: "user", text: "q1", runId: "run_1" },
      { role: "agent", text: "a1", runId: "run_1" },
      { role: "user", text: "q2", runId: "run_2" },
      { role: "agent", text: "a2", runId: "run_2", streaming: true },
    ];
    expect(cacheCoversDurableHistory(cache, [durable("run_1"), durable("run_2")])).toBe(true);
  });

  it("rejects a truncated cache that lost an earlier run", () => {
    // 实测 2026-09-12：一次失败的历史加载留下"欢迎语 + 后一轮"的残局；该缓存若不算
    // 作"缺覆盖"，服务端历史就永远铺不进去，早先的轮次再也回不来。
    const truncated: ChatMessage[] = [
      { role: "agent", text: "CellWiki 已就绪。" },
      { role: "user", text: "q2", runId: "run_2" },
      { role: "agent", text: "a2", runId: "run_2", streaming: false },
    ];
    const history = [durable("run_1", "user"), durable("run_1"), durable("run_2")];
    expect(cacheCoversDurableHistory(truncated, history)).toBe(false);
  });
});

describe("rebuildAgentTranscript（历史折叠保持原位）", () => {
  const base: ChatMessage[] = [
    { role: "user", text: "第一问" },
    { role: "agent", text: "第一答", runId: "run_1" },
    { role: "user", text: "第二问" },
    { role: "agent", text: "第二答", runId: "run_2" },
  ];

  it("折叠老 run 时回答留在原位，而不是被挪到最后", () => {
    const rebuilt = rebuildAgentTranscript(
      base,
      "run_1",
      [event(1, "message_delta", "第一答（回放）"), event(2, "run_status", "", { status: "succeeded", terminal: true })],
      labels,
    );
    expect(rebuilt.map((message) => message.text)).toEqual([
      "第一问",
      "第一答（回放）",
      "第二问",
      "第二答",
    ]);
  });

  it("没有可回放事件时，持久化回答也放回原位", () => {
    const rebuilt = rebuildAgentTranscript(base, "run_1", [], labels);
    expect(rebuilt.map((message) => message.text)).toEqual([
      "第一问",
      "第一答",
      "第二问",
      "第二答",
    ]);
  });

  it("回放没有回答文本时，持久化回答补成 text 节点且留在原位", () => {
    const rebuilt = rebuildAgentTranscript(
      base,
      "run_1",
      [event(1, "tool_started", "glob started.", { tool_name: "glob", tool_call_id: "c1" })],
      labels,
    );
    expect(rebuilt.map((message) => message.text)).toEqual([
      "第一问",
      "第一答",
      "第二问",
      "第二答",
    ]);
    const node = rebuilt[1].timeline?.at(-1);
    expect(node).toMatchObject({ kind: "text", text: "第一答" });
  });
});

describe("rebuildAgentTranscript（超时中断的 run：库里只有提问行）", () => {
  // 真机形状（2026-09-23 thread_caea08…）：timeout 的 run 在 agent_messages 里没有
  // assistant 行，回答只存在于事件日志里。
  const base: ChatMessage[] = [
    { role: "user", text: "对raw里前五篇论文进行ingest", runId: "run_timeout" },
    { role: "user", text: "继续", runId: "run_2" },
    { role: "agent", text: "第二答", runId: "run_2" },
    { role: "user", text: "生成methods页", runId: "run_3" },
    { role: "agent", text: "第三答", runId: "run_3" },
  ];

  // reducer 按 event.run_id 定位气泡，夹具必须带上被回放那条 run 的 id。
  const interrupted = (
    sequence: number,
    type: AgentEvent["type"],
    message = "",
    data: Record<string, unknown> = {},
  ): AgentEvent => ({ ...event(sequence, type, message, data), run_id: "run_timeout" });

  it("中断的回放落在它自己那条提问之后，而不是整段跑到转录末尾", () => {
    const rebuilt = rebuildAgentTranscript(
      base,
      "run_timeout",
      [
        interrupted(1, "tool_started", "Write leiden_clustering.md", { tool_name: "write_file", tool_call_id: "c1" }),
        interrupted(2, "run_status", "模型响应超时", {
          status: "failed",
          terminal: true,
          error_message: "timeout",
        }),
      ],
      labels,
    );

    expect(rebuilt.map((message) => `${message.role}:${message.runId ?? "-"}`)).toEqual([
      "user:run_timeout",
      "agent:run_timeout",
      "user:run_2",
      "agent:run_2",
      "user:run_3",
      "agent:run_3",
    ]);
    expect(rebuilt[1]).toMatchObject({ runStatus: "failed", streaming: false });
    expect(rebuilt[1].timeline?.some((node) => node.kind === "tool")).toBe(true);
  });

  it("只剩终态事件时，失败标记也留在原位", () => {
    const rebuilt = rebuildAgentTranscript(
      base,
      "run_timeout",
      [interrupted(1, "run_status", "Agent 运行失败 · timeout", { status: "failed", terminal: true })],
      labels,
    );

    expect(rebuilt).toHaveLength(base.length + 1);
    expect(rebuilt[1]).toMatchObject({ role: "agent", runId: "run_timeout", runStatus: "failed" });
  });
});

describe("runReplayAnchor", () => {
  it("优先用持久化回答的位置", () => {
    const base: ChatMessage[] = [
      { role: "user", text: "q1", runId: "run_1" },
      { role: "agent", text: "a1", runId: "run_1" },
    ];
    expect(runReplayAnchor(base, "run_1")).toBe(1);
  });

  it("没有回答行时用它自己的提问行，且取最后一条", () => {
    const base: ChatMessage[] = [
      { role: "user", text: "q1", runId: "run_1" },
      { role: "agent", text: "a1", runId: "run_1" },
      { role: "user", text: "中断的提问", runId: "run_2" },
      { role: "user", text: "同一条 run 上又追了一句", runId: "run_2" },
      { role: "user", text: "q3", runId: "run_3" },
    ];
    expect(runReplayAnchor(base, "run_2")).toBe(4);
  });

  it("两样都没有时留在末尾（直播中的新 run 正是这种）", () => {
    const base: ChatMessage[] = [
      { role: "user", text: "刚敲下去、还没有 run_id 的一句" },
      { role: "agent", text: "上一答", runId: "run_1" },
    ];
    expect(runReplayAnchor(base, "run_new")).toBe(2);
  });
});

describe("threadViewIsCurrent", () => {
  it("只有全量重建到最新、且该 run 已定局时才能吃缓存", () => {
    const succeeded = { run_id: "run_2", status: "succeeded" as const };
    expect(threadViewIsCurrent("run_2", succeeded)).toBe(true);
    // 服务端又长出了新 run：缓存不再是当前视图
    expect(threadViewIsCurrent("run_1", succeeded)).toBe(false);
    // 最新 run 还没定局（正在流式输出 / 等用户回答）：事件还会长，不能吃缓存
    expect(threadViewIsCurrent("run_2", { run_id: "run_2", status: "running" })).toBe(false);
    expect(threadViewIsCurrent("run_2", { run_id: "run_2", status: "waiting_confirmation" })).toBe(false);
    expect(threadViewIsCurrent("run_2", { run_id: "run_2", status: "unfinished" })).toBe(false);
    // 本次会话没重建过 / 服务端没有任何 run
    expect(threadViewIsCurrent(undefined, succeeded)).toBe(false);
    expect(threadViewIsCurrent("run_2", undefined)).toBe(false);
  });
});
