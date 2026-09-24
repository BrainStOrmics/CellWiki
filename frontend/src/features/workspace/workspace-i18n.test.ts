import { describe, expect, it } from "vitest";
import browserSource from "./WorkspaceFileBrowser.tsx?raw";
import viewerSource from "./WorkspaceFileViewer.tsx?raw";

/** 组件里只有注释可以写中文；渲染文案必须走 i18n 键，否则英文界面会露中文。 */
function withoutComments(source: string): string {
  return source
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .split("\n")
    .filter((line) => !/^\s*\/\//.test(line))
    .join("\n");
}

describe("workspace panel localization", () => {
  it("keeps the file tree's user-facing text behind i18n keys", () => {
    expect(withoutComments(browserSource)).not.toMatch(/[一-鿿]/);
  });

  it("keeps the file viewer's user-facing text behind i18n keys", () => {
    expect(withoutComments(viewerSource)).not.toMatch(/[一-鿿]/);
  });
});
