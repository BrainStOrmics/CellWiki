import { describe, expect, it } from "vitest";
import { buildRunContextDetail } from "./AppShell";

const labels = {
  workspaceLabel: "CellWiki 工作区",
  attachmentsLabel: (count: number) => `已附加 ${count} 个附件`,
  selectedTextLabel: (chars: number) => `选中文本 ${chars} 字符`,
};

describe("buildRunContextDetail", () => {
  it("shows the referenced page with its path", () => {
    expect(buildRunContextDetail({
      ...labels,
      page: { title: "巨噬细胞", path: "wiki/macrophage.md" },
      attachments: [],
      selectedText: null,
    })).toBe("巨噬细胞 (wiki/macrophage.md)");
  });

  it("falls back to the workspace label when nothing is referenced", () => {
    expect(buildRunContextDetail({
      ...labels, page: null, attachments: [], selectedText: null,
    })).toBe("CellWiki 工作区");
  });

  it("lists attachment names and the selected-text size", () => {
    expect(buildRunContextDetail({
      ...labels,
      page: { title: "论文页" },
      attachments: ["paper.pdf", "figure.png"],
      selectedText: "一段被选中的文字",
    })).toBe("论文页 · 已附加 2 个附件: paper.pdf、figure.png · 选中文本 8 字符");
  });
});
