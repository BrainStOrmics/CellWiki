import { afterEach, describe, expect, it, vi } from "vitest";
import { useEffect, type ReactNode } from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { WorkspaceFileBrowser, buildTree, filterTree, type WorkspaceTreeEntry, type WorkspaceTreeNode } from "./WorkspaceFileBrowser";
import { getJson } from "../../lib/product-api";
import { LanguageProvider, useI18n } from "../../i18n";

vi.mock("../../lib/product-api", () => ({
  getJson: vi.fn(),
}));

// LanguageProvider 会轮询 /api/settings 取界面语言；不 mock 掉 runtime 的话，
// 本机 8000 在跑时会把语言盖回 zh-CN，英文断言就成了环境相关的假失败。
vi.mock("../../runtime", () => ({
  productFetch: vi.fn().mockResolvedValue({ ok: false }),
}));

function entry(path: string, kind: "dir" | "file" = "file", type: WorkspaceTreeEntry["type"] = "md"): WorkspaceTreeEntry {
  return { name: path.split("/").pop() ?? path, path, kind, type };
}

describe("buildTree", () => {
  it("nests entries by path and sorts directories first", () => {
    const tree = buildTree([
      entry("index.md"),
      entry("raw", "dir", "dir"),
      entry("raw/src_a/source.md"),
      entry("wiki", "dir", "dir"),
      entry("wiki/cell_types/alpha.md"),
      entry("wiki/cell_types/beta.md"),
      entry("wiki/overview.md"),
    ]);
    expect(tree.map((node) => node.name)).toEqual(["raw", "wiki", "index.md"]);
    const wiki = tree.find((node) => node.path === "wiki") as WorkspaceTreeNode;
    expect(wiki.children!.map((node) => node.name)).toEqual(["cell_types", "overview.md"]);
    const cellTypes = wiki.children!.find((node) => node.path === "wiki/cell_types") as WorkspaceTreeNode;
    expect(cellTypes.children!.map((node) => node.name)).toEqual(["alpha.md", "beta.md"]);
  });

  it("sorts files naturally", () => {
    const tree = buildTree([entry("wiki/cell_types/a10.md"), entry("wiki/cell_types/a2.md")]);
    const wiki = tree.find((node) => node.path === "wiki") as WorkspaceTreeNode;
    const cellTypes = wiki.children!.find((node) => node.path === "wiki/cell_types") as WorkspaceTreeNode;
    expect(cellTypes.children!.map((node) => node.name)).toEqual(["a2.md", "a10.md"]);
  });
});

describe("filterTree", () => {
  it("keeps matching files and their ancestor chain", () => {
    const tree = buildTree([
      entry("index.md"),
      entry("wiki", "dir", "dir"),
      entry("wiki/cell_types/alpha.md"),
      entry("wiki/overview.md"),
    ]);
    const filtered = filterTree(tree, "alpha");
    expect(filtered.map((node) => node.path)).toEqual(["wiki"]);
    const wiki = filtered[0] as WorkspaceTreeNode;
    expect(wiki.children!.map((node) => node.path)).toEqual(["wiki/cell_types"]);
    expect(wiki.children![0].children!.map((node) => node.path)).toEqual(["wiki/cell_types/alpha.md"]);
  });

  it("keeps the whole subtree when a directory matches", () => {
    const tree = buildTree([
      entry("wiki", "dir", "dir"),
      entry("wiki/cell_types/alpha.md"),
      entry("wiki/cell_types/beta.md"),
    ]);
    const filtered = filterTree(tree, "cell_types");
    const wiki = filtered[0] as WorkspaceTreeNode;
    expect(wiki.children![0].children!.length).toBe(2);
  });
});


describe("WorkspaceFileBrowser refresh", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("refetches the tree when refreshSignal changes", async () => {
    const getJsonMock = vi.mocked(getJson);
    getJsonMock.mockResolvedValue([entry("index.md")]);
    const { rerender } = render(
      <LanguageProvider>
        <WorkspaceFileBrowser />
      </LanguageProvider>,
    );
    await waitFor(() => expect(getJsonMock).toHaveBeenCalledTimes(1));
    rerender(
      <LanguageProvider>
        <WorkspaceFileBrowser refreshSignal={1} />
      </LanguageProvider>,
    );
    await waitFor(() => expect(getJsonMock).toHaveBeenCalledTimes(2));
  });

  it("keeps expanded directories across refreshes", async () => {
    const getJsonMock = vi.mocked(getJson);
    const entries = () => [
      entry("wiki", "dir", "dir"),
      entry("wiki/cell_types", "dir", "dir"),
      entry("wiki/cell_types/alpha.md"),
    ];
    getJsonMock.mockResolvedValue(entries());
    const { rerender } = render(
      <LanguageProvider>
        <WorkspaceFileBrowser />
      </LanguageProvider>,
    );
    fireEvent.click(await screen.findByRole("button", { name: /cell_types/ }));
    expect(await screen.findByText("alpha.md")).toBeTruthy();
    getJsonMock.mockResolvedValue(entries());
    rerender(
      <LanguageProvider>
        <WorkspaceFileBrowser refreshSignal={1} />
      </LanguageProvider>,
    );
    await waitFor(() => expect(getJsonMock).toHaveBeenCalledTimes(2));
    expect(screen.getByText("alpha.md")).toBeTruthy();
  });
});

function EnglishLanguage({ children }: { children: ReactNode }) {
  const { setLanguage } = useI18n();
  useEffect(() => {
    setLanguage("en");
  }, [setLanguage]);
  return <>{children}</>;
}

describe("localized tree states", () => {
  afterEach(() => cleanup());

  it("renders the filtered-empty state in English", async () => {
    vi.mocked(getJson).mockResolvedValue([entry("wiki/alpha.md")]);
    render(
      <LanguageProvider>
        <EnglishLanguage>
          <WorkspaceFileBrowser filter="zzz" />
        </EnglishLanguage>
      </LanguageProvider>,
    );
    expect(await screen.findByText("No matching files")).toBeTruthy();
  });
});

