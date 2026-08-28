import { describe, expect, it } from "vitest";
import { isDisposableEmptyThread, seedAgentThreadList, type CachedThreadState } from "./AppShell";
import type { AgentThreadEntry, ChatMessage } from "../types";

function entry(overrides: Partial<AgentThreadEntry> = {}): AgentThreadEntry {
  return {
    thread_id: "thread_placeholder",
    title: null,
    created_at: "2026-08-28T07:00:00+00:00",
    updated_at: "2026-08-28T07:00:00+00:00",
    run_count: 0,
    latest_run_id: null,
    latest_status: null,
    ...overrides,
  };
}

function cached(overrides: Partial<CachedThreadState> = {}): CachedThreadState {
  return {
    messages: [{ role: "agent", text: "welcome" }] as ChatMessage[],
    draft: "",
    attachments: [],
    runId: null,
    ...overrides,
  };
}

describe("seedAgentThreadList", () => {
  it("prepares a zero-run placeholder immediately and keeps only one entry per thread", () => {
    const seeded = seedAgentThreadList([entry({ thread_id: "thread_old" })], "thread_new", "now");
    expect(seeded.map((item) => item.thread_id)).toEqual(["thread_new", "thread_old"]);
    expect(seeded[0]).toMatchObject({ run_count: 0, latest_run_id: null, title: null });

    // 同一会话重复占位不会追加第二条，也不会把服务端已有条目留在后面。
    const twice = seedAgentThreadList(seeded, "thread_new", "later");
    expect(twice.filter((item) => item.thread_id === "thread_new")).toHaveLength(1);
    expect(twice[0].updated_at).toBe("later");
  });

  it("works when the registry cache is still empty", () => {
    expect(seedAgentThreadList(undefined, "thread_first", "now").map((item) => item.thread_id))
      .toEqual(["thread_first"]);
  });
});

describe("isDisposableEmptyThread", () => {
  it("recycles a never-used placeholder slot", () => {
    expect(isDisposableEmptyThread(cached(), entry())).toBe(true);
  });

  it("keeps every session the user could still come back to", () => {
    expect(isDisposableEmptyThread(cached({ draft: "  问题草稿  " }), entry())).toBe(false);
    expect(
      isDisposableEmptyThread(
        cached({ attachments: [{ attachment_id: "att_1" } as never] }),
        entry(),
      ),
    ).toBe(false);
    // 首条消息被串行门禁 409 拒绝：用户必须还能切回来看到错误并重试
    expect(
      isDisposableEmptyThread(
        cached({
          messages: [
            { role: "agent", text: "welcome" },
            { role: "user", text: "总结细胞类型" },
            { role: "agent", text: "another agent run is active" },
          ] as ChatMessage[],
        }),
        entry(),
      ),
    ).toBe(false);
    expect(isDisposableEmptyThread(cached(), entry({ run_count: 1 }))).toBe(false);
    expect(isDisposableEmptyThread(cached(), entry({ latest_run_id: "run_1" }))).toBe(false);
    // 本地或注册表状态未知时一律保留，宁可少删。
    expect(isDisposableEmptyThread(undefined, entry())).toBe(false);
    expect(isDisposableEmptyThread(cached(), undefined)).toBe(false);
  });
});
