import { describe, expect, it } from "vitest";
import { createAgentEventScheduler, flushesChatImmediately } from "./agent-event-scheduler";
import type { AgentEvent, AgentRunStatus } from "../../types";

/** 手工帧驱动：测试自己决定"一帧过去了"，不依赖 jsdom 的 rAF 时序。 */
function createFrames() {
  let nextHandle = 1;
  const scheduled = new Map<number, () => void>();
  const cancelled: number[] = [];
  return {
    schedule(frame: () => void) {
      const handle = nextHandle;
      nextHandle += 1;
      scheduled.set(handle, frame);
      return handle;
    },
    cancel(handle: number) {
      if (scheduled.delete(handle)) cancelled.push(handle);
    },
    /** 跑最早的若干帧回调。 */
    run(count: number) {
      for (let index = 0; index < count; index += 1) {
        const entry = scheduled.entries().next();
        if (entry.done) return;
        const [handle, frame] = entry.value;
        scheduled.delete(handle);
        frame();
      }
    },
    get queuedFrames() {
      return scheduled.size;
    },
    cancelled,
  };
}

function createScheduler() {
  const frames = createFrames();
  const scheduler = createAgentEventScheduler(frames.schedule, frames.cancel);
  return { frames, scheduler };
}

/** 造 count 个渲染闭包，落地时按序把标签写进 sink。 */
function applies(count: number, sink: string[]) {
  return Array.from({ length: count }, (_, index) => () => {
    sink.push(`d${index}`);
  });
}

function event(type: AgentEvent["type"], data: Record<string, unknown> = {}): AgentEvent {
  return {
    event_id: `e-${type}`,
    run_id: "run_1",
    thread_id: "thread_1",
    sequence: 1,
    type,
    message: "",
    data,
    created_at: "",
  };
}

describe("agent-event-scheduler", () => {
  it("入队当帧不投放，帧回调来了才按入队顺序落地", () => {
    const { frames, scheduler } = createScheduler();
    const applied: string[] = [];

    scheduler.enqueue(() => applied.push("first"));
    scheduler.enqueue(() => applied.push("second"));
    expect(applied).toEqual([]);

    frames.run(1);
    expect(applied).toEqual(["first"]);
    frames.run(1);
    expect(applied).toEqual(["first", "second"]);
    expect(scheduler.pending()).toBe(0);
    expect(frames.queuedFrames).toBe(0);
  });

  it("按缓冲长度自适应投放：短积压逐帧细投，目标是几帧内投完", () => {
    const { frames, scheduler } = createScheduler();
    const applied: string[] = [];
    applies(12, applied).forEach((apply) => scheduler.enqueue(apply));

    frames.run(1);
    expect(scheduler.pending()).toBe(10);
    frames.run(1);
    expect(scheduler.pending()).toBe(8);
    // 尾部收敛到每帧一条（打字机效果），但一定在有限帧内清空
    frames.run(8);
    expect(scheduler.pending()).toBe(0);
    expect(applied).toEqual(Array.from({ length: 12 }, (_, index) => `d${index}`));
  });

  it("积压过大时一帧合并投完，不会永远掉队", () => {
    const { frames, scheduler } = createScheduler();
    const applied: string[] = [];
    for (let index = 0; index < 200; index += 1) {
      scheduler.enqueue(() => applied.push(`d${index}`));
    }

    frames.run(1);

    expect(applied).toHaveLength(200);
    expect(applied[199]).toBe("d199");
    expect(scheduler.pending()).toBe(0);
  });

  it("flush 立即投完积压并取消已排的帧回调", () => {
    const { frames, scheduler } = createScheduler();
    const applied: string[] = [];
    scheduler.enqueue(() => applied.push("a"));
    scheduler.enqueue(() => applied.push("b"));
    frames.run(1);
    scheduler.enqueue(() => applied.push("c"));

    scheduler.flush();

    expect(applied).toEqual(["a", "b", "c"]);
    expect(frames.queuedFrames).toBe(0);
    expect(frames.cancelled).toHaveLength(1);
    // flush 之后帧回调即使被漏跑也不会重复投放
    frames.run(1);
    expect(applied).toEqual(["a", "b", "c"]);
  });

  it("dispose 丢弃积压：卸载后不再有可渲染的视图", () => {
    const { frames, scheduler } = createScheduler();
    const applied: string[] = [];
    scheduler.enqueue(() => applied.push("a"));

    scheduler.dispose();
    frames.run(1);

    expect(applied).toEqual([]);
    expect(scheduler.pending()).toBe(0);
    expect(frames.queuedFrames).toBe(0);
  });

  it("终态前最后一段 delta 不丢字：全部入队后 flush，一条不少且顺序不变", () => {
    const { scheduler } = createScheduler();
    const applied: string[] = [];
    for (let index = 0; index < 50; index += 1) {
      scheduler.enqueue(() => applied.push(`段${index}`));
    }

    scheduler.flush();

    expect(applied).toHaveLength(50);
    expect(applied.join("")).toBe(Array.from({ length: 50 }, (_, index) => `段${index}`).join(""));
  });

  it("一次渲染抛错不会让队列永久停摆", () => {
    const { frames, scheduler } = createScheduler();
    const applied: string[] = [];
    scheduler.enqueue(() => {
      throw new Error("boom");
    });
    scheduler.enqueue(() => applied.push("after"));

    expect(() => frames.run(1)).toThrow("boom");
    frames.run(1);

    expect(applied).toEqual(["after"]);
  });
});

describe("flushesChatImmediately", () => {
  it("final_response 与任何终态 run_status 都强制先投完积压", () => {
    expect(flushesChatImmediately(event("final_response"))).toBe(true);
    const terminal: AgentRunStatus[] = [
      "waiting_confirmation",
      "waiting_approval",
      "succeeded",
      "rejected",
      "failed",
      "cancelled",
      "unfinished",
    ];
    for (const status of terminal) {
      expect(flushesChatImmediately(event("run_status", { status }))).toBe(true);
    }
  });

  it("普通 delta 与非终态 run_status 继续排队，保持逐帧平滑", () => {
    expect(flushesChatImmediately(event("message_delta"))).toBe(false);
    expect(flushesChatImmediately(event("reasoning_delta"))).toBe(false);
    expect(flushesChatImmediately(event("run_status", { status: "running" }))).toBe(false);
    expect(flushesChatImmediately(event("tool_started"))).toBe(false);
  });
});
