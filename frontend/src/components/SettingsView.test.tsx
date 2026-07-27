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
    if (path === "/api/pipeline/status") {
      return Promise.resolve({
        ok: true,
        json: async () => ({
          project_id: "cellwiki",
          knowledge_version: "sha256:test",
          approval_policy: "manual",
          default_reviewer: "default-reviewer",
          active_task: null,
        }),
      });
    }
    if (path === "/health") return Promise.resolve({ ok: true });
    return Promise.resolve({ ok: true, json: async () => ({ approval_policy: "auto_all" }) });
  }),
}));

vi.mock("../runtime", () => ({
  productFetch,
  openLogsDirectory: vi.fn(),
  restartBackend: vi.fn(),
  runtimeConfig: () => ({ productApiOrigin: "http://127.0.0.1:8000", mode: "development", logsDir: "logs", ready: true }),
}));

describe("SettingsView pipeline governance", () => {
  it("shows the approval policy and can switch it", async () => {
    render(<LanguageProvider><SettingsView onClose={vi.fn()} /></LanguageProvider>);

    fireEvent.click(screen.getByRole("button", { name: /运行环境/ }));
    await waitFor(() => expect(screen.getByTestId("pipeline-policy")).toHaveValue("manual"));
    fireEvent.change(screen.getByTestId("pipeline-policy"), { target: { value: "auto_all" } });

    expect(productFetch).toHaveBeenCalledWith(
      "/api/pipeline/approval-policy",
      expect.objectContaining({ method: "POST" }),
    );
  });
});
