import type { AgentEvent, AgentRunStatus } from "../../types";
import { terminalAgentStatuses } from "./run-status";

/** 流式平滑层：把 SSE 事件的**聊天渲染**按 rAF 自适应投放。
 *
 * 每条 delta 都直接 setState，会让 reducer 与 React 渲染跟着网络节奏跑：模型吐字密时
 * 一帧内十几次重排，稀时又完全没有合批。这里只排队渲染这一步，事件的其他副作用
 * （busy、活动标签、串行门禁出口）仍由调用方同步执行，所以对外语义不变。
 *
 * 判据是"终态前最后一段 delta 不丢字"：任何让 UI 进入稳定态的时刻都必须先投完积压，
 * 由调用方在这些点上调用 flush()。`flushesChatImmediately` 是其中事件驱动的那部分。
 */
export type AgentEventScheduler = {
  /** 排队一次聊天渲染；同一帧内严格按入队顺序投放。 */
  enqueue(apply: () => void): void;
  /** 立即投完积压并取消未跑的帧回调。 */
  flush(): void;
  /** 放弃积压并取消帧回调（卸载时用，此时已经没有可渲染的视图）。 */
  dispose(): void;
  /** 仍在排队的渲染次数。 */
  pending(): number;
};

/** 积压的目标投放帧数：缓冲短时逐帧细投（打字机效果），长时按比例追。 */
const DRAIN_FRAMES = 6;
/** 积压超过这个量就一次投完，避免追赶速度永远低于到达速度。 */
const COALESCE_ALL = 96;

export function createAgentEventScheduler(
  schedule: (frame: () => void) => number = (frame) => window.requestAnimationFrame(frame),
  cancel: (handle: number) => void = (handle) => window.cancelAnimationFrame(handle),
): AgentEventScheduler {
  const queue: Array<() => void> = [];
  let frame: number | null = null;

  function drain() {
    frame = null;
    try {
      const batch = queue.length >= COALESCE_ALL
        ? queue.length
        : Math.max(1, Math.ceil(queue.length / DRAIN_FRAMES));
      for (let index = 0; index < batch; index += 1) {
        const apply = queue.shift();
        if (!apply) break;
        apply();
      }
    } finally {
      // 某次渲染抛错也不能让队列永久停摆：剩下的继续排队等下一帧。
      if (queue.length > 0 && frame === null) frame = schedule(drain);
    }
  }

  return {
    enqueue(apply) {
      queue.push(apply);
      if (frame === null) frame = schedule(drain);
    },
    flush() {
      if (frame !== null) {
        cancel(frame);
        frame = null;
      }
      while (queue.length > 0) queue.shift()?.();
    },
    dispose() {
      if (frame !== null) {
        cancel(frame);
        frame = null;
      }
      queue.length = 0;
    },
    pending: () => queue.length,
  };
}

/** 必须先投完积压再处理的事件：这之后 UI 进入稳定态（回答定稿、SSE 结束、问题卡挂载），
 *  缓冲里的最后一段 delta 若还没落地，终态画面就会少字。 */
export function flushesChatImmediately(event: AgentEvent): boolean {
  if (event.type === "final_response") return true;
  return (
    event.type === "run_status"
    && terminalAgentStatuses.has(event.data.status as AgentRunStatus)
  );
}
