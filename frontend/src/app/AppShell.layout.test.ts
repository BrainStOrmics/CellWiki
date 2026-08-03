import { describe, expect, it } from "vitest";
import appShellSource from "./AppShell.tsx?raw";
import graphWorkspaceSource from "../features/graph/GraphWorkspace.tsx?raw";

describe("Agent sidebar layout", () => {
  it("does not render a standalone timeline outside the message process trace", () => {
    expect(appShellSource).not.toContain("agent-timeline");
    expect(appShellSource).not.toContain("agentTimeline");
  });

  it("keeps Composer references separate from Agent threads and supports attachment chips", () => {
    expect(appShellSource).toContain("uploadAgentAttachments");
    expect(appShellSource).toContain("attachmentRef.current?.click()");
    expect(appShellSource).toContain("multiple");
    expect(appShellSource).toContain("composer-reference-row");
    expect(appShellSource).toContain("removeLastComposerReference");
    expect(appShellSource).toContain("setComposerPageRef({");
  });

  it("does not present the reader or source selection as Agent Composer context", () => {
    expect(appShellSource).toContain("page_id: composerPageRef?.page_id ?? null");
    expect(appShellSource).toContain("source_id: null");
    expect(appShellSource).not.toContain("selectedSource ? t(\"chat.sourceContext\") : t(\"chat.pageContext\")");
    expect(appShellSource).not.toContain("<strong>{contextTitle}</strong>");
  });

  it("does not expose graph nodes as a separate attach-to-Agent shortcut", () => {
    expect(appShellSource).not.toContain("onAttachNode");
    expect(graphWorkspaceSource).not.toContain("graph.attach");
  });
});
