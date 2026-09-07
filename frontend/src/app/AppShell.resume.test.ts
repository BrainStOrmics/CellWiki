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

describe("停止是暂停而不是死结（composer 单按钮合并）", () => {
  function sliceBetween(start: string, end: string): string {
    const startIndex = appShellSource.indexOf(start);
    expect(startIndex, `missing anchor: ${start}`).toBeGreaterThan(-1);
    const endIndex = appShellSource.indexOf(end, startIndex);
    expect(endIndex, `missing anchor: ${end}`).toBeGreaterThan(startIndex);
    return appShellSource.slice(startIndex, endIndex);
  }

  it("放弃一个中断的 run 时清掉恢复线索，否则「继续」残留下来点一次 409 一次", () => {
    const cancel = sliceBetween(
      "async function cancelActiveAgentRun",
      "async function resumeUnfinishedAgentRun",
    );
    expect(cancel).toContain("setResumableAgentRunId(null);");
    expect(cancel).toContain("setRetryableAgentRunId(null);");
    // 新 run 起来时同样要失效：runAgent 早就清了 retryable，resumable 不能漏。
    const runAgent = sliceBetween("async function runAgent(", "async function resumeAgent(");
    expect(runAgent).toContain("setResumableAgentRunId(null);");
  });

  it("中断态下发送新消息必须先放弃旧 run：门禁还占着，直接发必然 409", () => {
    const send = sliceBetween(
      "async function sendMessage()",
      "async function cancelActiveAgentRun",
    );
    expect(send).toContain("if (resumableAgentRunId) {");
    expect(send).toContain("await cancelActiveAgentRun();");
    // 没放开就别发：第二个 409 会盖掉真正的原因。
    expect(send).toContain("if (!released) return;");

    // 放弃的收尾会把 busy 清零（它以为这一轮到此结束），而新 run 马上要起来：
    // 不重新置上，思考指示器与停止键整轮都不会出现。
    const afterCancel = send.slice(send.indexOf("await cancelActiveAgentRun();"));
    expect(afterCancel.indexOf("setAgentBusy(true);"))
      .toBeLessThan(afterCancel.indexOf("await runAgent"));
  });

  it("主动停止与被动中断读起来不是同一句话，横幅也不再卡在停止中", () => {
    const live = sliceBetween(
      'if (status === "unfinished") {',
      "if (status && terminalAgentStatuses.has(status)) {",
    );
    expect(live).toContain('event.data.reason === "user_stopped"');
    expect(live).toContain('t("chat.runStopped")');
    // 停止不再落 cancelled，所以横幅不会再由 cancel 那条路收尾。
    expect(live).toContain('{ phase: "unfinished", message: t("workflow.unfinished") }');
  });
});