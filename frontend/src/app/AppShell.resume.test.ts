import { describe, expect, it } from "vitest";
import { isResumableRunStatus } from "../features/agent/run-status";

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