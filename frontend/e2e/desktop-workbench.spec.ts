import { expect, test } from "@playwright/test";

test("three-pane workspace, grounded search, and language settings remain usable", async ({ page }) => {
  // The first Vite run may optimize the Markdown and graph bundles before the
  // workbench can answer its first DOM request.
  test.setTimeout(120_000);
  await page.goto("/", { waitUntil: "domcontentloaded", timeout: 120_000 });

  await expect(page.getByText("CellWiki", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("资源管理器")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Regulatory T cell" }).first()).toBeVisible();

  // The three columns own separate scroll containers; a regression to one shared
  // page scroller breaks the desktop workbench interaction model.
  const scrollContainers = page.locator(".file-tree-scroll, .reader-scroll, .chat-scroll");
  await expect(scrollContainers).toHaveCount(3);
  for (let index = 0; index < 3; index += 1) {
    await expect(scrollContainers.nth(index)).toHaveCSS("overflow-y", /auto|scroll/);
  }

  await page.keyboard.press("Control+=");
  await expect.poll(() => page.locator("html").evaluate((root) => root.style.getPropertyValue("--ui-zoom"))).toBe("1.1");
  await page.keyboard.press("Control+0");
  await expect.poll(() => page.locator("html").evaluate((root) => root.style.getPropertyValue("--ui-zoom"))).toBe("1");

  const themeToggle = page.getByRole("button", { name: /切换到深色模式|Switch to dark mode/ });
  await themeToggle.click();
  await expect.poll(() => page.locator("html").getAttribute("data-theme")).toBe("dark");

  await page.keyboard.press("Control+K");
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.getByRole("dialog").getByRole("textbox").fill("FOXP3");
  await expect(
    page.getByRole("dialog").getByText("Regulatory T cell", { exact: true }).first(),
  ).toBeVisible();
  await page.keyboard.press("Escape");

  await page.getByRole("button", { name: /对话 1|Threads 1/ }).click();
  await page.locator(".thread-list-select").first().click();
  await expect(page.locator(".markdown-content h2", { hasText: /Evidence summary|证据摘要/ })).toBeVisible();
  await expect(page.locator(".markdown-content table")).toBeVisible();
  await expect(page.locator(".markdown-content pre code")).toContainText("Evidence");
  await expect(page.locator(".message.user .message-bubble")).toBeVisible();
  await expect(page.locator(".message.agent .message-bubble")).toBeVisible();
  const restoredTrace = page.locator(".agent-process-trace").first();
  await expect(restoredTrace).toBeVisible();
  await expect(restoredTrace).not.toHaveAttribute("open", "");

  await page.getByRole("button", { name: "设置" }).click();
  await expect(page.getByRole("heading", { name: "设置" })).toBeVisible();
  await page.getByRole("button", { name: /界面/ }).click();
  await page.getByRole("button", { name: /English/ }).click();
  await page.getByRole("button", { name: "保存设置" }).click();
  await expect(page.getByRole("heading", { name: "Settings" })).toBeVisible();
});
