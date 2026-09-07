import { describe, expect, it } from "vitest";
import { isResumableRunStatus, terminalAgentStatuses } from "../features/agent/run-status";
import reducerSource from "../features/agent/agent-run-reducer.ts?raw";
import appShellSource from "./AppShell.tsx?raw";

describe("isResumableRunStatus", () => {
  it("返回 true：unfinished（预算/超时/重启恢复后）可继续/恢复", () => {
    expect(isResumableRunStatus("unfinished")).toBe(true);
  });

  it("返回 false：已终结或活跃中的状态不可继续", () => {
    expect(isResumableRunStatus("succeeded")).toBe(false);
    expect(isResumableRunStatus("failed")).toBe(false);
    expect(isResumableRunStatus("cancelled")).toBe(false);
    expect(isResumableRunStatus("running")).toBe(false);
    expect(isResumableRunStatus("queued")).toBe(false);
    expect(isResumableRunStatus(undefined)).toBe(false);
  });
});

describe("terminalAgentStatuses", () => {
  it("把 unfinished 视为流终态：SSE 已关闭，busy 必须能清零", () => {
    expect(terminalAgentStatuses.has("unfinished")).toBe(true);
    // 终态与可恢复不矛盾：run 停在预算上，既不再生成事件，又允许继续或取消。
    expect(isResumableRunStatus("unfinished")).toBe(true);
  });

  it("AppShell 与 reducer 不再各自复制终态集合（复制漂移就是卡死的根因）", () => {
    expect(appShellSource).not.toContain("const terminalAgentStatuses");
    expect(reducerSource).not.toContain("const terminalStatuses");
    expect(appShellSource).toContain('from "../features/agent/run-status"');
    expect(reducerSource).toContain('from "./run-status"');
  });
});

describe("续跑出路不得是死结（决策 4 修订 / 实测交接问题 A）", () => {
  function sliceBetween(start: string, end: string): string {
    const startIndex = appShellSource.indexOf(start);
    expect(startIndex, `missing anchor: ${start}`).toBeGreaterThan(-1);
    const endIndex = appShellSource.indexOf(end, startIndex);
    expect(endIndex, `missing anchor: ${end}`).toBeGreaterThan(startIndex);
    return appShellSource.slice(startIndex, endIndex);
  }

  it("UNFINISHED 同时给出「重试」：retry 不依赖 checkpoint，是图状态丢失时唯一的出路", () => {
    // 后端 is_retryable_run 对 unfinished 也返回真，但 UI 曾经只在 failed 时亮重试，
    // 于是图状态丢了的 run 只剩一个必然 409 的「继续」。
    const live = sliceBetween(
      'if (status === "unfinished") {',
      "if (status && terminalAgentStatuses.has(status)) {",
    );
    expect(live).toContain("setResumableAgentRunId(event.run_id);");
    expect(live).toContain("setRetryableAgentRunId(event.run_id);");

    // 会话恢复路径：重启后端再回到会话正是 P0 的复现路径。
    const restored = sliceBetween(
      '} else if (run.status === "unfinished") {',
      "} else if (!terminalAgentStatuses.has(run.status)) {",
    );
    expect(restored).toContain("setResumableAgentRunId(runId);");
    expect(restored).toContain("if (run.retryable) setRetryableAgentRunId(runId);");
  });

  it("恢复线索不得跨会话滞留：`+` 新建与删除会话都清掉 resumable", () => {
    const startNewChat = sliceBetween(
      "async function startNewChat()",
      "function openSearchResult(",
    );
    expect(startNewChat).toContain("setResumableAgentRunId(null);");

    const deleteThread = sliceBetween(
      "async function deleteAgentThread(",
      "async function sendMessage()",
    );
    expect(deleteThread).toContain("setResumableAgentRunId(null);");
  });
});