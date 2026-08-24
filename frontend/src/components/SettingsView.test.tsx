import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { LanguageProvider } from "../i18n";
import { SettingsView } from "./SettingsView";

const { productFetch } = vi.hoisted(() => ({
  productFetch: vi.fn((path: string) => {
    if (path === "/api/settings") {
      return Promise.resolve({
        ok: true,
        json: async () => ({
          openai_base_url: "",
          openai_model: "test-model",
          openai_api_protocol: "chat_completions",
          openai_api_key_configured: false,
          log_level: "INFO",
          app_language: "zh-CN",
          enable_agent_memory: false,
          enable_external_research: false,
          memory_recall_token_budget: 800,
        }),
      });
    }
    if (path === "/api/workspace") {
      return Promise.resolve({
        ok: true,
        json: async () => ({ path: "D:\\KB\\current", git_ready: true, wiki_page_count: 3 }),
      });
    }
    if (path === "/api/workspace/select") {
      return Promise.resolve({
        ok: true,
        json: async () => ({ path: "D:\\KB\\new", status: "saved", requires_restart: true }),
      });
    }
    if (path === "/health") return Promise.resolve({ ok: true });
    return Promise.resolve({ ok: true, json: async () => ({}) });
  }),
}));

vi.mock("../runtime", () => ({
  isDesktopRuntime: false,
  productFetch,
  openLogsDirectory: vi.fn(),
  restartBackend: vi.fn(),
  runtimeConfig: () => ({ productApiOrigin: "http://127.0.0.1:8000", mode: "development", logsDir: "logs", ready: true }),
}));

describe("SettingsView workspace", () => {
  it("shows the current workspace path and switches to a new one", async () => {
    render(<LanguageProvider><SettingsView onClose={vi.fn()} /></LanguageProvider>);

    fireEvent.click(screen.getByTestId("settings-workspace-nav"));
    await waitFor(() => expect(screen.getByTestId("workspace-path")).toHaveValue("D:\\KB\\current"));

    fireEvent.change(screen.getByTestId("workspace-path"), { target: { value: "D:\\KB\\new" } });
    fireEvent.click(screen.getByRole("button", { name: /切换并使用/ }));

    await waitFor(() => expect(productFetch).toHaveBeenCalledWith(
      "/api/workspace/select",
      expect.objectContaining({ method: "POST" }),
    ));
    await waitFor(() => expect(screen.getByTestId("workspace-path")).toHaveValue("D:\\KB\\new"));
  });
});