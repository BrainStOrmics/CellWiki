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

  it("把运行控制收进 composer 的同一个槽位，并标注得能被读屏发现", () => {
    const composeStart = appShellSource.indexOf('<div className="compose-actions">');
    expect(composeStart, "missing anchor: compose-actions").toBeGreaterThan(-1);
    const composeSource = appShellSource.slice(
      composeStart,
      appShellSource.indexOf("<input", composeStart),
    );

    // 一个槽位三种动作，判定收在纯函数里（composer-action.ts 有自己的单测）。
    // 原位切换：用户不必把视线移开 composer，自动化与读屏也能按 role+name 命中。
    expect(composeSource).toContain('composerAction.kind === "stop"');
    expect(composeSource).toContain('composerAction.kind === "resume"');
    expect(composeSource).toContain('composerAction.kind === "send"');
    expect(composeSource).toContain('className="stop-run"');
    expect(composeSource).toContain("onClick={() => void cancelActiveAgentRun()}");
    expect(composeSource).toContain("onClick={() => void resumeUnfinishedAgentRun()}");
    expect(composeSource).toContain('aria-label={t("chat.cancel")}');
    expect(composeSource).toContain('aria-label={t("chat.resume")}');
    expect(composeSource).toContain('aria-label={t("chat.send")}');
    // 停止键的 title 要说出键盘入口，否则 Esc 无从发现。
    expect(composeSource).toContain('title={t("chat.cancelHint")}');

    // 标题栏那颗 13px 停止键已删（实测像素点击 4 次偏 3 次，读屏也找不到）。它原本
    // 担的活——"中断态下只放弃、不发新消息"——现在由 run 脚注里那颗显式的键接过去
    // （渲染在 AgentTranscriptMessage 里）。AppShell 这边只剩判定与投递：每条消息拿到
    // 属于自己 run 的动作，另给"transcript 里没有消息可挂"的 run 兜一条同样的脚注。
    // 不能没有：中断的 run 占着串行门禁，而 delete_thread 有活动 run 守卫，否则连会话
    // 都删不掉。
    expect(appShellSource).not.toContain('className="icon-button stop-run"');
    expect(appShellSource).not.toContain('className="agent-retry"');
    expect(appShellSource).toContain('kind: "abandon"');
    expect(appShellSource).toContain("runActionsFor(message.runId ?? null)");
    expect(appShellSource).toContain("<AgentRunFootnote");
  });

  it("Esc 停止运行，但让位给命令面板，且不碰提问态与中断态", () => {
    const escStart = appShellSource.indexOf("const stopRunOnEscape");
    expect(escStart, "missing anchor: stopRunOnEscape").toBeGreaterThan(-1);
    const escSource = appShellSource.slice(
      escStart,
      appShellSource.indexOf("}, [agentBusy, waitingOnQuestion, commandPaletteOpen]);", escStart),
    );

    // 命令面板自己的 Esc 关面板且不 stopPropagation，事件照样冒到 window。
    expect(escSource).toContain("if (commandPaletteOpen) return;");
    // 提问态下 Esc 不该顺手毁掉一个待答问题；中断态下也不绑"放弃"——误触一下就把
    // 一个可续跑的 run 打成终态，代价太大。
    expect(escSource).toContain("if (!agentBusy || waitingOnQuestion) return;");
    expect(escSource).toContain("void cancelActiveAgentRun();");
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