import { describe, expect, it } from "vitest";
import appShellSource from "./AppShell.tsx?raw";

/**
 * 附件上传的前后端契约锁。后端 `services/attachment_store.py` 的
 * `SUPPORTED_ATTACHMENT_SUFFIXES` 只收 pdf/md/txt；选择器曾经额外广告 .csv/.json，
 * 用户选中后必然吃 422，而 UI 统一回一句"请确认 Product API 正在运行"，
 * 把一个类型门禁问题报成运行时离线。端到端复现在 e2e/desktop-workbench.spec.ts。
 */

function sliceBetween(start: string, end: string, from = 0): string {
  const startIndex = appShellSource.indexOf(start, from);
  expect(startIndex, `missing anchor: ${start}`).toBeGreaterThan(-1);
  const endIndex = appShellSource.indexOf(end, startIndex);
  expect(endIndex, `missing anchor: ${end}`).toBeGreaterThan(startIndex);
  return appShellSource.slice(startIndex, endIndex);
}

describe("附件选择器与后端类型门禁一致", () => {
  it("只广告后端真正接受的三种后缀", () => {
    expect(appShellSource).toContain('accept=".pdf,.md,.txt"');
  });

  it("不再广告会被 422 拒绝的 .csv / .json", () => {
    expect(appShellSource).not.toContain(".csv");
    expect(appShellSource).not.toContain(",.json");
  });
});

describe("上传失败要区分服务端拒绝与运行时离线", () => {
  const uploadSource = sliceBetween(
    "async function uploadAgentAttachments(",
    "async function removeComposerAttachment(",
  );

  it("非 2xx 时读出服务端的 detail 作为原因", () => {
    expect(uploadSource).toContain("if (!response.ok) {");
    expect(uploadSource).toContain("detail");
    expect(uploadSource).toContain("throw new ProductApiError(reason");
  });

  it("有原因时用拒绝文案，没有原因时才回退到离线文案", () => {
    expect(uploadSource).toContain('t("chat.attachmentRejected").replace("{reason}", reason)');
    expect(uploadSource).toContain('t("chat.attachmentUploadFailed")');
    expect(uploadSource.indexOf("chat.attachmentRejected"))
      .toBeLessThan(uploadSource.indexOf("chat.attachmentUploadFailed"));
  });
});
