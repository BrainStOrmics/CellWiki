import type { AgentRunStatus } from "../../types";

/** 运行是否处于“可继续/恢复”的暂停态（预算/超时/重启恢复后）。 */
export function isResumableRunStatus(status: AgentRunStatus | undefined): boolean {
  return status === "unfinished";
}

/**
 * 运行正停在“等用户回答/审批”上。
 *
 * 它同时是两条 UI 规则的前提：这类 run 要挂问题卡、挡住新消息；而一旦运行继续
 * （答题后的非终态 run_status），标记必须让位——等待提示不能挂到 run 结束。
 */
export function isWaitingRunStatus(status: AgentRunStatus | undefined): boolean {
  return status === "waiting_confirmation" || status === "waiting_approval";
}

/**
 * 真正定局的状态：既不可续跑，也不在等用户——终态清理（活动 run、续跑/重试标记）
 * 只认这一组。
 */
export function isSettledRunStatus(status: AgentRunStatus | undefined): boolean {
  return status === "succeeded" || status === "failed" || status === "cancelled"
    || status === "rejected";
}

export const terminalAgentStatuses = new Set<AgentRunStatus>([
  "waiting_confirmation",
  "waiting_approval",
  "succeeded",
  "rejected",
  "failed",
  "cancelled",
  "unfinished",
]);