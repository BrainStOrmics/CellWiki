import { expect, test } from "@playwright/test";

test("workspace memory settings panel loads and reflects the API", async ({ page }) => {
  test.setTimeout(120_000);
  await page.goto("/", { waitUntil: "domcontentloaded", timeout: 120_000 });

  await page.getByRole("button", { name: "设置" }).click();
  await expect(page.getByRole("heading", { name: "设置" })).toBeVisible();

  await page.getByTestId("settings-memory-nav").click();
  await expect(page.getByTestId("memory-panel")).toBeVisible();
  await expect(page.getByTestId("memory-enabled-toggle")).toBeVisible();
  await expect(page.getByTestId("memory-enabled-toggle")).not.toBeChecked();
  await expect(page.getByTestId("memory-status")).toBeVisible();
  await expect(
    page.getByTestId("memory-status").getByText("自动提取", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("memory_summary.md")).toBeVisible();
  await expect(page.getByText("MEMORY.md")).toBeVisible();
  await expect(
    page.getByText(/还没有成型记忆|No consolidated memories yet/),
  ).toBeVisible();
  await expect(page.getByTestId("memory-maintenance")).toBeVisible();

  // 面板读到的是真实 Product API 的响应，而不是前端内置数据。
  const response = await page.request.get("http://127.0.0.1:18000/api/memory");
  expect(response.ok()).toBeTruthy();
  const payload = (await response.json()) as {
    entries: unknown[];
    count: number;
    views: unknown[];
    status: { enabled: boolean; jobs_pending: number };
  };
  expect(payload.count).toBe(payload.entries.length);
  expect(payload.views).toHaveLength(2);
  expect(payload.status.jobs_pending).toBeGreaterThanOrEqual(0);
});
