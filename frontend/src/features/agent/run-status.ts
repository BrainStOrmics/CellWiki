import type { AgentRunStatus } from "../../types";

/** 运行是否处于“可继续/恢复”的暂停态（预算/超时/重启恢复后）。 */
export function isResumableRunStatus(status: AgentRunStatus | undefined): boolean {
  return status === "unfinished";
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