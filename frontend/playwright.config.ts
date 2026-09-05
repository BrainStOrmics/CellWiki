import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  fullyParallel: false,
  // 所有 spec 共用一个 Product API 进程和同一个 build/e2e-project 运行时库；
  // fullyParallel: false 只串行化单文件内的用例，跨文件仍会并发改同一份会话注册表。
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["html", { open: "never" }], ["list"]] : "list",
  use: {
    baseURL: "http://127.0.0.1:15173",
    trace: "retain-on-failure",
    ...devices["Desktop Chrome"],
  },
  webServer: [
    {
      command: "uv run --project .. python ../scripts/serve_e2e.py",
      url: "http://127.0.0.1:18000/health",
      env: { ...process.env, CELLWIKI_E2E_API_PORT: "18000" },
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: "npm run dev -- --host 127.0.0.1 --port 15173",
      url: "http://127.0.0.1:15173",
      env: {
        ...process.env,
        VITE_PRODUCT_API_ORIGIN: "http://127.0.0.1:18000",
      },
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
});
