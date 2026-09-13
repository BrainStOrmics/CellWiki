import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { LanguageProvider } from "../../i18n";
import { useUiStore } from "../../stores/ui-store";
import type { ModelProviderCatalog } from "../../types";

const catalog: ModelProviderCatalog = {
  version: 1,
  default_selection: { provider_id: "gw-a", model_id: "model-a1" },
  providers: [
    {
      id: "gw-a",
      name: "Gateway A",
      base_url: "https://a.example.com/v1",
      protocol: "chat_completions",
      enabled: true,
      models: [
        { id: "model-a1", enabled: true },
        { id: "model-a2", enabled: true },
      ],
      request_overrides: {},
      source: "user",
      api_key_configured: true,
      api_key_hint: "••••1234",
    },
    {
      id: "gw-off",
      name: "Disabled GW",
      base_url: "",
      protocol: "chat_completions",
      enabled: false,
      models: [{ id: "model-off", enabled: true }],
      request_overrides: {},
      source: "user",
      api_key_configured: true,
      api_key_hint: null,
    },
  ],
};

vi.mock("../../lib/product-api", () => ({
  getJson: vi.fn(() => Promise.resolve(catalog)),
  postJson: vi.fn(),
  putJson: vi.fn(),
  deleteJson: vi.fn(),
}));

import { ModelSwitcher } from "./ModelSwitcher";

function renderSwitcher() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <LanguageProvider>
        <ModelSwitcher />
      </LanguageProvider>
    </QueryClientProvider>,
  );
}

afterEach(cleanup);

describe("ModelSwitcher", () => {
  beforeEach(() => {
    localStorage.clear();
    useUiStore.setState({ selectedModel: null });
  });

  it("opens the popover, groups models by provider, and hides disabled providers", async () => {
    renderSwitcher();
    fireEvent.click(screen.getByRole("button", { name: /切换模型/ }));

    const options = await waitFor(() => {
      const popover = screen.getByRole("dialog", { name: /切换模型/ });
      expect(within(popover).getByText("Gateway A")).toBeVisible();
      return popover;
    });
    expect(within(options).getAllByText("model-a1").length).toBeGreaterThan(0);
    expect(within(options).getByText("model-a2")).toBeVisible();
    // 已停用供应商整组不出现
    expect(within(options).queryByText("Disabled GW")).toBeNull();
  });

  it("stores the selected model in the ui store and shows it on the button", async () => {
    renderSwitcher();
    fireEvent.click(screen.getByRole("button", { name: /切换模型/ }));
    const options = await waitFor(() => {
      const popover = screen.getByRole("dialog", { name: /切换模型/ });
      expect(within(popover).getByText("model-a2")).toBeVisible();
      return popover;
    });
    fireEvent.click(within(options).getByText("model-a2"));

    await waitFor(() => expect(useUiStore.getState().selectedModel).toEqual({
      provider_id: "gw-a",
      model_id: "model-a2",
    }));
    expect(screen.getByRole("button", { name: /切换模型/ })).toHaveTextContent("model-a2");
    // popover 已关闭
    expect(screen.queryByText("Gateway A")).toBeNull();
  });

  it("offers 跟随默认设置 which clears the explicit selection", async () => {
    act(() => {
      useUiStore.getState().setSelectedModel({ provider_id: "gw-a", model_id: "model-a2" });
    });
    renderSwitcher();
    fireEvent.click(screen.getByRole("button", { name: /切换模型/ }));

    const options = await waitFor(() => {
      const popover = screen.getByRole("dialog", { name: /切换模型/ });
      expect(within(popover).getByText("跟随默认设置")).toBeVisible();
      return popover;
    });
    fireEvent.click(within(options).getByText("跟随默认设置"));

    expect(useUiStore.getState().selectedModel).toBeNull();
  });
});
