import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { LanguageProvider } from "../i18n";
import { ProviderManager } from "./ProviderManager";
import type { ModelProviderCatalog } from "../types";

const baseCatalog: ModelProviderCatalog = {
  version: 1,
  default_selection: { provider_id: "gw-a", model_id: "model-a1" },
  providers: [
    {
      id: "gw-a",
      name: "Gateway A",
      base_url: "https://a.example.com/v1",
      protocol: "chat_completions",
      enabled: true,
      models: [{ id: "model-a1", enabled: true }],
      request_overrides: {},
      source: "user",
      api_key_configured: true,
      api_key_hint: "••••9876",
    },
  ],
};

const { getJson, postJson, putJson, deleteJson } = vi.hoisted(() => ({
  getJson: vi.fn(),
  postJson: vi.fn(),
  putJson: vi.fn(),
  deleteJson: vi.fn(),
}));

vi.mock("../lib/product-api", () => ({ getJson, postJson, putJson, deleteJson }));

function renderManager() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <LanguageProvider>
        <ProviderManager onNotice={vi.fn()} />
      </LanguageProvider>
    </QueryClientProvider>,
  );
}

afterEach(cleanup);

describe("ProviderManager", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getJson.mockResolvedValue(baseCatalog);
    window.confirm = vi.fn(() => true);
  });

  it("loads the catalog, lists providers with badges, and prefills the editor", async () => {
    renderManager();

    await waitFor(() => expect(screen.getByText("Gateway A")).toBeVisible());
    expect(screen.getByText("默认")).toBeVisible();
    expect(screen.getByDisplayValue("Gateway A")).toBeVisible();
    expect(screen.getByDisplayValue("https://a.example.com/v1")).toBeVisible();
    // key 只回显掩码 placeholder，不回明文
    expect(screen.getByPlaceholderText(/••••9876/)).toBeVisible();
  });

  it("creates a provider via POST and selects the created id", async () => {
    postJson.mockResolvedValue({
      ...baseCatalog,
      created_id: "openrouter",
      providers: [
        ...baseCatalog.providers,
        {
          id: "openrouter",
          name: "OpenRouter",
          base_url: "https://openrouter.ai/api/v1",
          protocol: "chat_completions",
          enabled: true,
          models: [{ id: "openrouter/auto", enabled: true }],
          request_overrides: {},
          source: "user",
          api_key_configured: true,
          api_key_hint: null,
        },
      ],
    });

    renderManager();
    await waitFor(() => expect(screen.getByText("新建供应商")).toBeVisible());
    fireEvent.click(screen.getByText("新建供应商"));

    fireEvent.change(screen.getByPlaceholderText("OpenRouter"), { target: { value: "OpenRouter" } });
    const modelInput = screen.getByPlaceholderText(/输入模型名后回车添加/);
    fireEvent.change(modelInput, { target: { value: "openrouter/auto" } });
    fireEvent.keyDown(modelInput, { key: "Enter" });
    fireEvent.click(screen.getByRole("button", { name: /保存供应商/ }));

    await waitFor(() => expect(postJson).toHaveBeenCalledWith(
      "/api/model-providers",
      expect.objectContaining({ name: "OpenRouter", api_key: null }),
    ));
    // 保存后仍选中新建的供应商（模型清单以 code 行呈现）
    await waitFor(() => expect(screen.getByText("openrouter/auto")).toBeVisible());
  });

  it("sets a model as default via the star action", async () => {
    putJson.mockResolvedValue({
      ...baseCatalog,
      default_selection: { provider_id: "gw-a", model_id: "model-a2" },
    });

    renderManager();
    await waitFor(() => expect(screen.getByDisplayValue("Gateway A")).toBeVisible());

    fireEvent.change(screen.getByPlaceholderText(/输入模型名后回车添加/), { target: { value: "model-a2" } });
    fireEvent.keyDown(screen.getByPlaceholderText(/输入模型名后回车添加/), { key: "Enter" });
    fireEvent.click(screen.getByRole("button", { name: /设为默认: model-a2/ }));

    await waitFor(() => expect(putJson).toHaveBeenCalledWith(
      "/api/model-providers/default-selection",
      { provider_id: "gw-a", model_id: "model-a2" },
    ));
  });

  it("deletes a provider after confirmation and clears the editor", async () => {
    deleteJson.mockResolvedValue({ ...baseCatalog, providers: [], default_selection: null });

    renderManager();
    await waitFor(() => expect(screen.getByRole("button", { name: "删除供应商" })).toBeVisible());
    fireEvent.click(screen.getByRole("button", { name: "删除供应商" }));

    await waitFor(() => expect(deleteJson).toHaveBeenCalledWith("/api/model-providers/gw-a"));
    await waitFor(() => expect(screen.getByText(/尚未配置供应商/)).toBeVisible());
  });

  it("rejects invalid JSON overrides without sending", async () => {
    renderManager();
    await waitFor(() => expect(screen.getByDisplayValue("Gateway A")).toBeVisible());

    fireEvent.change(screen.getByPlaceholderText('{"thinking_budget": 1000}'), {
      target: { value: "{not json" },
    });
    fireEvent.click(screen.getByRole("button", { name: /保存供应商/ }));

    expect(putJson).not.toHaveBeenCalled();
    expect(postJson).not.toHaveBeenCalled();
  });
});
