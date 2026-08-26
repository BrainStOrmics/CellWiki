import { describe, expect, it } from "vitest";
import appShellSource from "./AppShell.tsx?raw";
import viewerSource from "../features/workspace/WorkspaceFileViewer.tsx?raw";

describe("Wiki link navigation", () => {
  it("resolves wiki links from the page registry first and falls back to the workspace tree", () => {
    const start = appShellSource.indexOf("async function openWikiTarget(");
    const end = appShellSource.indexOf("function openDiffPanel()", start);
    expect(start).toBeGreaterThanOrEqual(0);
    expect(end).toBeGreaterThan(start);
    const source = appShellSource.slice(start, end);

    expect(source).toContain("pages.some((page) => page.page_id === pageId)");
    expect(source).toContain("setSelectedId(pageId);");
    expect(source).toContain('getJson<WorkspaceTreeEntry[]>("/api/workspace/tree")');
    expect(source).toContain("entry.path.endsWith(`/${fileName}`)");
    expect(source).toContain("openWorkspaceFile(match)");
  });

  it("wires the wiki-link handler into the reader and the workspace file viewer", () => {
    expect(appShellSource).toContain("onWikiLink={(pageId) => { void openWikiTarget(pageId); }}");
    expect(viewerSource).toContain("onWikiLink?: (pageId: string) => void");
    expect(viewerSource).toContain("<MarkdownReader markdown={content} onWikiLink={onWikiLink} />");
  });
});
