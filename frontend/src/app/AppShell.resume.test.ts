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