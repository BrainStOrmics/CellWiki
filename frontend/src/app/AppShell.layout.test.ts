import { describe, expect, it } from "vitest";
import appShellSource from "./AppShell.tsx?raw";

describe("Agent sidebar layout", () => {
  it("does not render a standalone timeline outside the message process trace", () => {
    expect(appShellSource).not.toContain("agent-timeline");
    expect(appShellSource).not.toContain("agentTimeline");
  });

  it("keeps Composer references separate from Agent threads and supports attachment chips", () => {
    expect(appShellSource).toContain("uploadAgentAttachments");
    expect(appShellSource).toContain("attachmentUploadRef.current");
    expect(appShellSource).toContain("queueAgentAttachmentUpload");
    expect(appShellSource).toContain("threadCreationRef");
    expect(appShellSource).toContain("attachmentUploadBusy");
    expect(appShellSource).toContain("useUiStore.getState().activeAttachmentIds");
    expect(appShellSource).toContain("attachmentRef.current?.click()");
    expect(appShellSource).toContain("multiple");
    expect(appShellSource).toContain("composer-reference-row");
    expect(appShellSource).toContain("removeLastComposerReference");
    expect(appShellSource).toContain("setComposerPageRef({");
    expect(appShellSource).toContain("clearPendingAttachments: true");
    expect(appShellSource).toContain("attachments: messageAttachments");
    expect(appShellSource).toContain("removeComposerAttachment");
    expect(appShellSource).toContain("/attachments/${encodeURIComponent(attachmentId)}");
    expect(appShellSource).toContain("attachmentAlreadySent");
  });

  it("commits the composer only after the Agent run is accepted", () => {
    const runStart = appShellSource.indexOf("async function runAgent(");
    const runEnd = appShellSource.indexOf("async function resumeAgent", runStart);
    const runSource = appShellSource.slice(runStart, runEnd);
    const sendStart = appShellSource.indexOf("async function sendMessage()");
    const sendEnd = appShellSource.indexOf("async function cancelActiveAgentRun", sendStart);
    const sendSource = appShellSource.slice(sendStart, sendEnd);

    expect(runSource).toContain("onAccepted?: () => void");
    expect(runSource).toContain("options.onAccepted?.();");
    expect(runSource.indexOf("options.onAccepted?.();")).toBeLessThan(
      runSource.indexOf("if (options.clearPendingAttachments)"),
    );
    expect(sendSource).toContain("onAccepted: () => {");
    expect(sendSource.indexOf("await runAgent")).toBeLessThan(sendSource.indexOf("setDraft(\"\")"));
    expect(sendSource.indexOf("await runAgent")).toBeLessThan(sendSource.indexOf("setMessages((current) =>"));
  });

  it("does not present the reader or source selection as Agent Composer context", () => {
    expect(appShellSource).toContain("page_id: composerPageRef?.page_id ?? null");
    expect(appShellSource).toContain("source_id: null");
    expect(appShellSource).not.toContain("selectedSource ? t(\"chat.sourceContext\") : t(\"chat.pageContext\")");
    expect(appShellSource).not.toContain("<strong>{contextTitle}</strong>");
  });

  it("clears the previous thread runtime state before restoring another thread", () => {
    const restoreStart = appShellSource.indexOf("async function restoreAgentThread");
    const restoreEnd = appShellSource.indexOf("async function restoreAgentRun", restoreStart);
    const restoreSource = appShellSource.slice(restoreStart, restoreEnd);
    const eventStart = appShellSource.indexOf("function applyAgentEvent");
    const eventEnd = appShellSource.indexOf("function subscribeToAgentRun", eventStart);
    const eventSource = appShellSource.slice(eventStart, eventEnd);

    expect(restoreSource).toContain("agentEventSourceRef.current?.close()");
    expect(restoreSource).not.toContain("setPendingInterrupt(");
    expect(restoreSource).toContain("setActiveAgentRunId(null)");
    expect(restoreSource).toContain("setMessages([initialAgentMessage])");
    expect(restoreSource).not.toContain("setActiveAttachmentIds(");
    expect(eventSource).toContain("event.thread_id !== agentThreadIdRef.current");
  });

  it("restores paused-run answers and guards malformed stream events", () => {
    expect(appShellSource).toContain("pausedAgentStatuses.has(run.status)");
    expect(appShellSource).toContain("[cellwiki] ignoring malformed agent event");
    expect(appShellSource).toContain("chat.waitingForConfirmation");
    expect(appShellSource).toContain("waitingOnQuestion");
    expect(appShellSource).toContain("legacyTerminalEvent(run, agentEventSequenceRef.current + 1)");
  });

  it("no longer keeps removed registry/review/graph workspace code paths", () => {
    expect(appShellSource).not.toContain("/api/sources");
    expect(appShellSource).not.toContain("/api/changesets");
    expect(appShellSource).not.toContain("/api/quality");
    expect(appShellSource).not.toContain("/api/tasks/");
    expect(appShellSource).not.toContain("loadChangeSetReview");
    expect(appShellSource).not.toContain("GraphWorkspace");
  });

  it("把运行中的中断入口放在 composer 里原位切换，并标注得能被读屏发现", () => {
    const composeStart = appShellSource.indexOf('<div className="compose-actions">');
    expect(composeStart, "missing anchor: compose-actions").toBeGreaterThan(-1);
    const composeSource = appShellSource.slice(
      composeStart,
      appShellSource.indexOf("<input", composeStart),
    );

    // 原位切换：同一个位置既有发送也有停止，用户不必把视线移开 composer，
    // 自动化与读屏也能按 role+name 命中（标题栏那颗 13px 方块两者都做不到）。
    expect(composeSource).toContain("{activeAgentRunId ? (");
    expect(composeSource).toContain('className="stop-run"');
    expect(composeSource).toContain("onClick={() => void cancelActiveAgentRun()}");
    expect(composeSource).toContain('aria-label={t("chat.cancel")}');
    expect(composeSource).toContain('aria-label={t("chat.send")}');
    // 标题栏那颗保留：它是 UNFINISHED 下唯一能释放串行门禁的出口。
    expect(appShellSource).toContain('className="icon-button stop-run"');
  });

  it("运行开始时重置活动条，不让上一个 run 的终态文案漏进新 run", () => {
    const eventStart = appShellSource.indexOf("function applyAgentEvent");
    const eventSource = appShellSource.slice(
      eventStart,
      appShellSource.indexOf("function subscribeToAgentRun", eventStart),
    );
    expect(eventSource).toContain(
      'if (status === "running" || status === "queued") setAgentActivity("");',
    );

    const sendStart = appShellSource.indexOf("async function sendMessage()");
    const sendSource = appShellSource.slice(
      sendStart,
      appShellSource.indexOf("async function cancelActiveAgentRun", sendStart),
    );
    expect(sendSource.indexOf('setAgentActivity("");'))
      .toBeLessThan(sendSource.indexOf("await runAgent"));

    // 兜底文案曾是 ChangeSet 时代的「正在追踪证据」，而因为它兜底，反而是最常见的
    // 那条。chat.reasoningLive 早已存在，不需要新键。
    expect(appShellSource).toContain('{agentActivity || t("chat.reasoningLive")}');
    expect(appShellSource).not.toContain('{agentActivity || t("chat.tracing")}');
  });
});