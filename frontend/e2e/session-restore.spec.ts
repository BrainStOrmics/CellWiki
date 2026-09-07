import { expect, test, type Page } from "@playwright/test";

const SEEDED_RUN_ID = "run_e2e_history";
// serve_e2e.py seeds this run with that input_message; the store now derives the
// conversation title from it, so the seeded thread is selectable by text instead
// of by list position (other specs leave newer threads in the registry).
const SEEDED_THREAD_LABEL = "Which markers support this cell type?";

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

async function selectSeededThread(page: Page) {
  await page.getByRole("button", { name: /对话 \d+|Threads \d+/ }).click();
  const item = page.locator(".thread-list-item", { hasText: SEEDED_THREAD_LABEL }).first();
  await expect(item).toBeVisible();
  await item.locator(".thread-list-select").click();
  await expect(page.locator(".markdown-content h2", { hasText: /Evidence summary|证据摘要/ })).toBeVisible();
}

/**
 * These three symptoms are one family: session restore hangs off persisted UI
 * state plus a run-id hint, so a conversation whose run already settled has no
 * hint left and never reloads its transcript.
 */

test("a settled conversation is still there after a page reload", async ({ page }) => {
  test.setTimeout(120_000);
  await page.goto("/", { waitUntil: "domcontentloaded", timeout: 120_000 });
  await expect(page.getByText("CellWiki", { exact: true }).first()).toBeVisible();

  await selectSeededThread(page);
  await expect(page.locator(".message.user .message-bubble")).toBeVisible();
  const threadId = await persistedActiveThreadId(page);
  expect(threadId).not.toBeNull();

  // 刷新前后可见历史必须一致：会话身份是持久化的，转录也必须跟着回来。
  await page.reload({ waitUntil: "domcontentloaded", timeout: 120_000 });
  await expect.poll(() => persistedActiveThreadId(page)).toBe(threadId);
  await expect(page.locator(".markdown-content h2", { hasText: /Evidence summary|证据摘要/ })).toBeVisible();
  await expect(page.locator(".message.user .message-bubble")).toBeVisible();
  await expect(page.locator(".message.agent .message-bubble")).toBeVisible();
});

test("reselecting the open conversation then + starts a new one", async ({ page }) => {
  test.setTimeout(120_000);
  await page.goto("/", { waitUntil: "domcontentloaded", timeout: 120_000 });
  await expect(page.getByText("CellWiki", { exact: true }).first()).toBeVisible();

  await selectSeededThread(page);
  const seededThreadId = await persistedActiveThreadId(page);
  expect(seededThreadId).not.toBeNull();

  // 再点一次当前会话：状态值没变，恢复线索不得滞留到下一次切换。
  await page.getByRole("button", { name: /对话 \d+|Threads \d+/ }).click();
  await page.locator(".thread-list-item", { hasText: SEEDED_THREAD_LABEL }).first()
    .locator(".thread-list-select").click();

  await page.getByRole("button", { name: /新建对话|New conversation/ }).click();
  await expect.poll(() => persistedActiveThreadId(page)).not.toBe(seededThreadId);
  const newThreadId = await persistedActiveThreadId(page);

  // 恢复是异步的：等它落定，再断言没有"弹回旧会话"。立即断言会在竞态窗口里假绿。
  await page.waitForTimeout(2_500);
  expect(await persistedActiveThreadId(page)).toBe(newThreadId);
  await expect(page.locator(".markdown-content h2", { hasText: /Evidence summary|证据摘要/ })).toHaveCount(0);
  await expect(page.locator(".message.user .message-bubble")).toHaveCount(0);
});

test("a refused resume clears busy and keeps the continue affordance", async ({ page }) => {
  test.setTimeout(120_000);
  await page.goto("/", { waitUntil: "domcontentloaded", timeout: 120_000 });
  await expect(page.getByText("CellWiki", { exact: true }).first()).toBeVisible();

  // 夹具 adapter 复用同一个 model_call_id，预算永远数不出第二次调用，因此用
  // 响应改写把 seeded run 呈现为 unfinished：确定性、不依赖后端预算语义。
  await page.route(`**/api/agent/runs/${SEEDED_RUN_ID}`, async (route) => {
    const response = await route.fetch();
    const body = await response.json() as Record<string, unknown>;
    await route.fulfill({
      response,
      body: JSON.stringify({ ...body, status: "unfinished", resumable: true }),
    });
  });
  await page.route(`**/api/agent/runs/${SEEDED_RUN_ID}/resume`, (route) => (
    route.fulfill({
      status: 409,
      contentType: "application/json",
      body: JSON.stringify({ detail: "invalid resume: unfinished -> running" }),
    })
  ));

  await selectSeededThread(page);
  const continueButton = page.getByRole("button", { name: /继续|Resume|Continue/ });
  await expect(continueButton).toBeVisible();

  // 门禁冲突按 409 返回（阶段 A）：前端必须收敛 busy 并留下可重试出口，
  // 而不是让"继续"消失、思考指示器永远转下去。
  await continueButton.click();

  await expect(page.locator(".agent-thinking")).toHaveCount(0);
  await expect(page.locator(".message.agent .message-bubble").last()).toContainText(
    /invalid resume|409/,
  );
  await expect(continueButton).toBeVisible();
});

test("a permanently refused resume swaps the dead end for a way out", async ({ page }) => {
  test.setTimeout(120_000);
  await page.goto("/", { waitUntil: "domcontentloaded", timeout: 120_000 });
  await expect(page.getByText("CellWiki", { exact: true }).first()).toBeVisible();

  await page.route(`**/api/agent/runs/${SEEDED_RUN_ID}`, async (route) => {
    const response = await route.fetch();
    const body = await response.json() as Record<string, unknown>;
    await route.fulfill({
      response,
      body: JSON.stringify({
        ...body,
        status: "unfinished",
        resumable: true,
        retryable: true,
      }),
    });
  });
  // 永久性拒绝：detail 是带稳定码的 dict（决策 4 修订后的形状）。与上一条测试的
  // 裸字符串 detail 形成对照——那个是门禁冲突，可重试，必须把「继续」还回来。
  await page.route(`**/api/agent/runs/${SEEDED_RUN_ID}/resume`, (route) => (
    route.fulfill({
      status: 409,
      contentType: "application/json",
      body: JSON.stringify({
        detail: {
          code: "checkpoint_missing",
          message: "run has no usable checkpoint; resend the message to start a new run",
        },
      }),
    })
  ));

  await selectSeededThread(page);
  const continueButton = page.getByRole("button", { name: /继续|Resume|Continue/ });
  const retryButton = page.getByRole("button", { name: /重试|Retry/ });
  await expect(continueButton).toBeVisible();
  // retry 不依赖 checkpoint（清状态 + 从有界 transcript 重放），所以它必须在用户
  // 撞 409 之前就已可见，而不是等失败后才出现。
  await expect(retryButton).toBeVisible();

  await continueButton.click();

  // 死结的两半都要解除：「继续」不再被还回来（点多少次都是同一个 409），
  // 「重试」仍在，思考指示器不残留。
  await expect(page.locator(".agent-thinking")).toHaveCount(0);
  await expect(continueButton).toHaveCount(0);
  await expect(retryButton).toBeVisible();
});
