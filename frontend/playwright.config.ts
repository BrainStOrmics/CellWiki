import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  fullyParallel: false,
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
