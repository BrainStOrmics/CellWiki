import { describe, expect, it } from "vitest";
import appShellSource from "./AppShell.tsx?raw";

describe("Diff review panel toggle and view restore", () => {
  it("captures the open page/file when opening and restores it on close", () => {
    const openStart = appShellSource.indexOf("function openDiffPanel()");
    const openEnd = appShellSource.indexOf("function closeDiffPanel()", openStart);
    const closeEnd = appShellSource.indexOf("return (", openEnd);
    expect(openStart).toBeGreaterThanOrEqual(0);
    expect(openEnd).toBeGreaterThan(openStart);
    expect(closeEnd).toBeGreaterThan(openEnd);

    const openSource = appShellSource.slice(openStart, openEnd);
    const closeSource = appShellSource.slice(openEnd, closeEnd);

    expect(openSource).toContain("diffReturnRef.current = { workspaceFile, selectedId }");
    expect(openSource).toContain("setDiffPanelOpen(true);");
    expect(openSource).toContain("setWorkspaceFile(null);");

    expect(closeSource).toContain("setDiffPanelOpen(false);");
    expect(closeSource).toContain("setWorkspaceFile(saved.workspaceFile);");
    expect(closeSource).toContain("setSelectedId(saved.selectedId);");
  });

  it("toggles from the footer button and routes the diff close button through the same restore", () => {
    expect(appShellSource).toContain("onClick={() => (diffPanelOpen ? closeDiffPanel() : openDiffPanel())}");
    expect(appShellSource).toContain("<DiffBrowser onExit={closeDiffPanel}");
  });

  it("lets new navigation take over from an open diff panel instead of swallowing it", () => {
    // 工作区按 CRLF 检出，?raw 里带 \r\n；多行片段断言前先归一化。
    const source = appShellSource.replaceAll("\r\n", "\n");
    expect(source).toContain("function leaveDiffPanelForNavigation()");
    expect(source).toContain(
      "function openWorkspaceFile(entry: WorkspaceTreeEntry) {\n    if (diffPanelOpen) leaveDiffPanelForNavigation();",
    );
    expect(source).toContain(
      "async function openWikiTarget(pageId: string) {\n    if (diffPanelOpen) leaveDiffPanelForNavigation();",
    );
    expect(source).toContain(
      "if (result.page_id) {\n      if (diffPanelOpen) leaveDiffPanelForNavigation();",
    );
  });
});
