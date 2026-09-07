import { describe, expect, it } from "vitest";
import appShellSource from "./AppShell.tsx?raw";

/**
 * 会话恢复三症状（F1/F3/F7）的源码行为锁。三者同族：恢复挂在持久化的会话身份
 * 加一条 run 线索上，线索缺失或滞留都会让"当前会话"和"渲染出来的会话"脱节。
 * 端到端复现与验收在 e2e/session-restore.spec.ts。
 */

function sliceBetween(start: string, end: string, from = 0): string {
  const startIndex = appShellSource.indexOf(start, from);
  expect(startIndex, `missing anchor: ${start}`).toBeGreaterThan(-1);
  const endIndex = appShellSource.indexOf(end, startIndex);
  expect(endIndex, `missing anchor: ${end}`).toBeGreaterThan(startIndex);
  return appShellSource.slice(startIndex, endIndex);
}

describe("刷新后恢复已完成的会话（F1）", () => {
  const effectSource = sliceBetween(
    "const preferredRunId = threadRestorePrefRef.current",
    "}, [activeThreadId]);",
  );

  it("没有 run 线索时也重新拉历史，而不是只更新 ref", () => {
    expect(effectSource).toContain("renderedThreadIdRef.current !== activeThreadId");
    expect(effectSource).toContain("void restoreAgentThread(activeThreadId);");
  });

  it("已经渲染过该会话时不重复恢复（应用内切换与 `+` 新建不受影响）", () => {
    expect(effectSource.indexOf("renderedThreadIdRef.current !== activeThreadId"))
      .toBeGreaterThan(effectSource.indexOf("if (preferredRunId) {"));
    expect(effectSource).toContain("agentThreadIdRef.current = activeThreadId;");
  });
});

describe("恢复线索不得滞留到下一次切换（F3）", () => {
  it("点当前会话不武装线索：状态值不变，effect 不会重跑也就不会清它", () => {
    expect(appShellSource).toContain(
      "threadRestorePrefRef.current = thread.threadId === activeThreadId",
    );
  });

  it("`+` 新建会话先清掉遗留线索", () => {
    const startNewChat = sliceBetween(
      "async function startNewChat()",
      "function openSearchResult(",
    );
    expect(startNewChat.indexOf("threadRestorePrefRef.current = null"))
      .toBeGreaterThan(-1);
    expect(startNewChat.indexOf("threadRestorePrefRef.current = null"))
      .toBeLessThan(startNewChat.indexOf("await postJson<{ thread_id: string }>"));
  });
});

describe("续跑被拒时收敛 busy 并留下可重试出口（F7）", () => {
  const resumeSource = sliceBetween(
    "async function resumeUnfinishedAgentRun()",
    "async function retryAgentRun()",
  );

  it("整个续跑尝试被 try 包住", () => {
    expect(resumeSource).toContain("} catch (error) {");
    expect(resumeSource).toContain("} finally {");
  });

  it("失败时按判别码分流，并给出可诊断的错误消息", () => {
    expect(resumeSource).toContain("agentRequestFailure(");
    expect(resumeSource).toContain("failure.code === checkpointMissingCode");

    // 永久拒绝（载体里没有该 run 的图状态）：「继续」再点也是 409，必须摘掉并换成
    // retry——它清状态后从有界 transcript 重放，不依赖 checkpoint。修订前这里无条件
    // 把「继续」还回去，于是成了死结：按钮点不动，而 UNFINISHED 仍占着串行门禁。
    const permanent = resumeSource.slice(
      resumeSource.indexOf("failure.code === checkpointMissingCode"),
      resumeSource.indexOf("} else {"),
    );
    expect(permanent).toContain("setRetryableAgentRunId(resumedRunId);");
    expect(permanent).not.toContain("setResumableAgentRunId(resumedRunId);");

    // 可重试拒绝（典型是门禁冲突 409）仍要把「继续」还回来，这是 F7 的原意。
    expect(resumeSource.slice(resumeSource.indexOf("} else {")))
      .toContain("setResumableAgentRunId(resumedRunId);");
  });

  it("busy 在 finally 里清零，任何路径都不会留下永久思考指示器", () => {
    expect(resumeSource.indexOf("} finally {"))
      .toBeLessThan(resumeSource.lastIndexOf("setAgentBusy(false);"));
  });
});
