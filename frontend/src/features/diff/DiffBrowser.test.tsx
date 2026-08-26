import { describe, expect, it, vi } from "vitest";
import { afterEach } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

afterEach(() => {
  cleanup();
});
import { DiffBrowser, parsePatch } from "./DiffBrowser";
import { getJson, postJson } from "../../lib/product-api";

vi.mock("../../lib/product-api", () => ({
  getJson: vi.fn(),
  postJson: vi.fn(),
}));

describe("parsePatch", () => {
  it("splits unified diff into files and colored lines", () => {
    const patch = [
      "diff --git a/wiki/a.md b/wiki/a.md",
      "index 123..456 100644",
      "--- a/wiki/a.md",
      "+++ b/wiki/a.md",
      "@@ -1,3 +1,4 @@",
      " title",
      "-old",
      "+new",
      " same",
      "diff --git a/raw/b.txt b/raw/b.txt",
      "index 111..222 100644",
      "--- a/raw/b.txt",
      "+++ b/raw/b.txt",
      "@@ -0,0 +1 @@",
      "+hello",
    ].join("\n");
    const files = parsePatch(patch);
    expect(files.map((file) => file.path)).toEqual(["wiki/a.md", "raw/b.txt"]);
    expect(files[0].hunks).toHaveLength(1);
    const lines = files[0].hunks[0].lines;
    expect(lines.map((line) => line.kind)).toEqual(["ctx", "del", "add", "ctx"]);
    expect(lines[2].text).toBe("+new");
    expect(files[1].hunks[0].lines[0].kind).toBe("add");
  });

  it("keeps backslash continuation lines as headers", () => {
    const patch = [
      "diff --git a/x.md b/x.md",
      "--- a/x.md",
      "+++ b/x.md",
      "@@ -1 +1 @@",
      "-a",
      "+b",
      "\\ No newline at end of file",
    ].join("\n");
    const files = parsePatch(patch);
    const hdr = files[0].hunks[0].lines.at(-1)!;
    expect(hdr.kind).toBe("hdr");
    expect(hdr.oldLine).toBeUndefined();
    expect(hdr.newLine).toBeUndefined();
  });

  it("assigns old/new line numbers across ctx/del/add", () => {
    const patch = [
      "diff --git a/wiki/a.md b/wiki/a.md",
      "index 123..456 100644",
      "--- a/wiki/a.md",
      "+++ b/wiki/a.md",
      "@@ -2,3 +2,4 @@",
      " context2",
      "-old3",
      "+new3",
      " context4",
    ].join("\n");
    const lines = parsePatch(patch)[0].hunks[0].lines;
    expect(lines.map((line) => line.kind)).toEqual(["ctx", "del", "add", "ctx"]);
    expect(lines[0].oldLine).toBe(2);
    expect(lines[0].newLine).toBe(2);
    expect(lines[1].oldLine).toBe(3);
    expect(lines[1].newLine).toBeUndefined();
    expect(lines[2].oldLine).toBeUndefined();
    expect(lines[2].newLine).toBe(3);
    expect(lines[3].oldLine).toBe(4);
    expect(lines[3].newLine).toBe(4);
  });

  it("supports hunk headers without counts", () => {
    const patch = [
      "diff --git a/x.md b/x.md",
      "--- a/x.md",
      "+++ b/x.md",
      "@@ -1 +1 @@",
      "-a",
      "+b",
    ].join("\n");
    const lines = parsePatch(patch)[0].hunks[0].lines;
    expect(lines[0].kind).toBe("del");
    expect(lines[0].oldLine).toBe(1);
    expect(lines[1].kind).toBe("add");
    expect(lines[1].newLine).toBe(1);
  });

  it("numbers new-file hunks starting at line zero", () => {
    const patch = [
      "diff --git a/raw/new.txt b/raw/new.txt",
      "new file mode 100644",
      "index 000..111",
      "--- /dev/null",
      "+++ b/raw/new.txt",
      "@@ -0,0 +1,3 @@",
      "+one",
      "+two",
      "+three",
    ].join("\n");
    const lines = parsePatch(patch)[0].hunks[0].lines;
    expect(lines.map((line) => line.newLine)).toEqual([1, 2, 3]);
    expect(lines.every((line) => line.oldLine === undefined)).toBe(true);
  });

  it("preserves non-hunk body for binary diffs", () => {
    const patch = [
      "diff --git a/raw/data.bin b/raw/data.bin",
      "index 123..456 100644",
      "Binary files a/raw/data.bin and b/raw/data.bin differ",
    ].join("\n");
    const file = parsePatch(patch)[0];
    expect(file.hunks).toHaveLength(0);
    expect(file.body).toContain("Binary files");
  });
});

describe("DiffBrowser rendering", () => {
  it("shows old/new line numbers and +/- markers for a patch", async () => {
    const getJsonMock = vi.mocked(getJson);
    const patch = [
      "diff --git a/wiki/a.md b/wiki/a.md",
      "index 123..456 100644",
      "--- a/wiki/a.md",
      "+++ b/wiki/a.md",
      "@@ -1,3 +1,4 @@",
      " title",
      "-old",
      "+new",
      " same",
    ].join("\n");
    getJsonMock.mockImplementation((url: string) => {
      if (url.endsWith("/patch")) {
        return Promise.resolve({ diff_id: "diff_1", patch });
      }
      return Promise.resolve({
        pending_diffs: [{
          diff_id: "diff_1",
          run_id: "run_1",
          thread_id: "thread_1",
          commits: [],
          files: ["wiki/a.md"],
          insertions: 1,
          deletions: 1,
          status: "pending",
          created_at: "2026-08-25T00:00:00Z",
        }],
      });
    });

    render(<DiffBrowser />);
    fireEvent.click(await screen.findByText("run_1"));
    // 默认折叠：先出现文件头，内容需要点击才展示
    const header1 = await screen.findByRole("button", { name: "wiki/a.md" });
    expect(screen.queryByText("new")).toBeNull();
    fireEvent.click(header1);
    await screen.findByText("new");

    const oldRow = screen.getByText("old").closest(".diff-line");
    expect(oldRow?.querySelector(".diff-line-num.old")?.textContent).toBe("2");
    expect(oldRow?.querySelector(".diff-line-num.new")?.textContent).toBe("");
    expect(screen.getByText("+").className).toContain("diff-line-marker");
  });

  it("collapses and re-expands a single file diff via its header", async () => {
    const getJsonMock = vi.mocked(getJson);
    const patch = [
      "diff --git a/wiki/a.md b/wiki/a.md",
      "index 123..456 100644",
      "--- a/wiki/a.md",
      "+++ b/wiki/a.md",
      "@@ -1,3 +1,4 @@",
      " title",
      "-old",
      "+new",
      " same",
    ].join("\n");
    getJsonMock.mockImplementation((url: string) => {
      if (url.endsWith("/patch")) {
        return Promise.resolve({ diff_id: "diff_1", patch });
      }
      return Promise.resolve({
        pending_diffs: [{
          diff_id: "diff_1",
          run_id: "run_1",
          thread_id: "thread_1",
          commits: [],
          files: ["wiki/a.md"],
          insertions: 1,
          deletions: 1,
          status: "pending",
          created_at: "2026-08-25T00:00:00Z",
        }],
      });
    });

    render(<DiffBrowser />);
    fireEvent.click(await screen.findByText("run_1"));
    const header = await screen.findByRole("button", { name: "wiki/a.md" });
    // 默认折叠：打开后不显示任何内容
    expect(screen.queryByText("new")).toBeNull();
    expect(screen.queryByText("old")).toBeNull();

    fireEvent.click(header);
    await screen.findByText("new");

    fireEvent.click(header);
    expect(screen.queryByText("new")).toBeNull();
    expect(screen.queryByText("old")).toBeNull();

    fireEvent.click(header);
    expect(screen.getByText("new")).toBeTruthy();
  });
});
