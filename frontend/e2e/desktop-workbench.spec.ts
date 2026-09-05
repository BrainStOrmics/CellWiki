import path from "node:path";
import { expect, test, type Page } from "@playwright/test";

async function persistedActiveThreadId(page: Page) {
  return page.evaluate(() => {
    const raw = window.localStorage.getItem("cellwiki.ui.v2");
    if (!raw) return null;
    try {
      return JSON.parse(raw).state?.activeThreadId ?? null;
    } catch {
      return null;
    }
  });
}

// 工作区引导会在根目录生成 audit_report.md / overview.md 等系统文件，它们按名称排在
// wiki 子树之前，所以用路径定位而不是 .first()，避免随工作区骨架漂移。
const SEEDED_PAGE_PATH = "wiki/cell_types/regulatory_t_cell.md";
// serve_e2e.py 的种子 run 输入消息；阶段 A 起会话标题由它确定性派生。
const SEEDED_THREAD_LABEL = "Which markers support this cell type?";

async function clickSeededWikiTreeFile(page: Page) {
  const file = page.locator(`.tree-file[title="${SEEDED_PAGE_PATH}"]`);
  if (!(await file.isVisible().catch(() => false))) {
    await page.locator('.tree-folder-row[title="wiki/cell_types"]').click();
  }
  await expect(file).toBeVisible();
  await file.click();
}

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
  await page.locator(".thread-list-select", { hasText: SEEDED_THREAD_LABEL }).first().click();
  await expect(page.locator(".markdown-content h2", { hasText: /Evidence summary|证据摘要/ })).toBeVisible();
  await expect(page.locator(".markdown-content table")).toBeVisible();
  await expect(page.locator(".markdown-content pre code")).toContainText("Evidence");
  await expect(page.locator(".message.user .message-bubble")).toBeVisible();
  await expect(page.locator(".message.agent .message-bubble")).toBeVisible();
  const restoredTrace = page.locator(".agent-run-diagnostics").first();
  await expect(restoredTrace).toBeVisible();
  await expect(restoredTrace).not.toHaveAttribute("open", "");

  await page.getByRole("button", { name: "设置" }).click();
  await expect(page.getByRole("heading", { name: "设置" })).toBeVisible();
  await page.getByRole("button", { name: /界面/ }).click();
  await page.getByRole("button", { name: /English/ }).click();
  await page.getByRole("button", { name: "保存设置" }).click();
  await expect(page.getByRole("heading", { name: "Settings" })).toBeVisible();

  // 语言会写进 e2e 项目的 .env 并在整个服务进程内生效：不还原就会把英文界面
  // 泄漏给之后每个 spec，让它们的中文文案断言莫名失败。
  await page.getByRole("button", { name: /Interface/ }).click();
  await page.getByRole("button", { name: /简体中文/ }).click();
  await page.getByRole("button", { name: /Save settings/ }).click();
  await expect(page.getByRole("heading", { name: "设置" })).toBeVisible();
});

test("Agent composer references stay separate from threads and temporary attachments", async ({ page }) => {
  test.setTimeout(120_000);
  await page.goto("/", { waitUntil: "domcontentloaded", timeout: 120_000 });
  await expect(page.getByText("CellWiki", { exact: true }).first()).toBeVisible();
  await expect(page.locator(".chat-compose textarea")).toBeVisible();
  await page.getByRole("button", { name: /Wiki 浏览器|Wiki explorer/ }).click();
  await expect(page.locator('.tree-folder-row[title="wiki/cell_types"]')).toBeVisible();

  await page.getByRole("button", { name: /新建对话|New conversation/ }).click();
  await expect.poll(() => persistedActiveThreadId(page)).not.toBeNull();
  const firstThreadId = await persistedActiveThreadId(page);

  await clickSeededWikiTreeFile(page);
  await expect(page.locator(".composer-chip.page-chip")).toBeVisible();
  await expect.poll(() => persistedActiveThreadId(page)).toBe(firstThreadId);

  await page.locator(".chat-compose textarea").focus();
  await page.keyboard.press("Backspace");
  await expect(page.locator(".composer-chip.page-chip")).toHaveCount(0);
  await expect.poll(() => persistedActiveThreadId(page)).toBe(firstThreadId);

  await clickSeededWikiTreeFile(page);
  await expect(page.locator(".composer-chip.page-chip")).toBeVisible();
  await page
    .locator('input[type="file"][accept=".pdf,.md,.txt"]')
    .setInputFiles(path.join(process.cwd(), "..", "build", "e2e-project", "fixture_source.md"));
  await expect(page.locator(".composer-chip.attachment-chip")).toContainText("fixture_source.md");

  await page.getByRole("button", { name: /新建对话|New conversation/ }).click();
  await expect(page.locator(".composer-chip.page-chip")).toBeVisible();
  await expect(page.locator(".composer-chip.attachment-chip")).toHaveCount(0);
  await expect.poll(() => persistedActiveThreadId(page)).not.toBe(firstThreadId);
});

test("Agent streams ordinary text through the browser, runtime, SSE, and durable store", async ({ page }) => {
  test.setTimeout(120_000);
  await page.goto("/", { waitUntil: "domcontentloaded", timeout: 120_000 });
  await expect(page.getByText("CellWiki", { exact: true }).first()).toBeVisible();

  await page.getByRole("button", { name: /新建对话|New conversation/ }).click();
  await expect.poll(() => persistedActiveThreadId(page)).not.toBeNull();
  const threadId = await persistedActiveThreadId(page);
  expect(threadId).not.toBeNull();

  const prompt = "请查找 FOXP3 并说明你实际读取了哪些文件。";
  await page.locator(".chat-compose textarea").fill(prompt);
  await page.getByRole("button", { name: /发送消息|Send message/ }).click();

  await expect(page.locator(".message.user .message-bubble").last()).toContainText("FOXP3");
  const answer = page.locator(".message.agent .message-bubble", {
    hasText: "FOXP3 是 Regulatory T cell 的证据标记。",
  });
  await expect(answer).toBeVisible();
  await expect(answer).toContainText("实际读取：wiki/cell_types/regulatory_t_cell.md");
  await expect(page.locator(".message.agent.is-streaming")).toHaveCount(0);

  const evidence = await page.evaluate(async ({ activeThreadId }) => {
    const origin = "http://127.0.0.1:18000";
    const runs = await fetch(`${origin}/api/agent/runs?thread_id=${encodeURIComponent(activeThreadId)}&limit=10`)
      .then((response) => response.json());
    const run = runs.find((candidate: { thread_id: string }) => candidate.thread_id === activeThreadId);
    const [events, messages] = await Promise.all([
      fetch(`${origin}/api/agent/runs/${encodeURIComponent(run.run_id)}/events`).then((response) => response.json()),
      fetch(`${origin}/api/agent/threads/${encodeURIComponent(activeThreadId)}/messages`).then((response) => response.json()),
    ]);
    return { run, events, messages };
  }, { activeThreadId: threadId! });

  expect(evidence.run.status).toBe("succeeded");
  expect(evidence.events.map((event: { type: string }) => event.type)).toEqual(expect.arrayContaining([
    "tool_started",
    "tool_completed",
    "message_delta",
    "final_response",
    "run_status",
  ]));
  const final = evidence.events.find((event: { type: string }) => event.type === "final_response");
  expect(final.message).toContain("FOXP3 是 Regulatory T cell 的证据标记。");
  const assistant = evidence.messages.find((message: { role: string }) => message.role === "assistant");
  expect(assistant.content).toContain("实际读取：wiki/cell_types/regulatory_t_cell.md");
});
