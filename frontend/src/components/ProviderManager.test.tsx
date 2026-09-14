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

function renderManager(
  onNotice: (notice: { kind: "ok" | "error"; text: string } | undefined) => void = vi.fn(),
) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <LanguageProvider>
        <ProviderManager onNotice={onNotice} />
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

  it("loads the catalog, lists providers as single-row entries, and prefills the editor", async () => {
    renderManager();

    await waitFor(() => expect(screen.getByText("Gateway A")).toBeVisible());
    // 列表行只保留 名称 + 状态点，base_url 只出现在编辑器的输入框里
    expect(screen.queryByText("https://a.example.com/v1")).not.toBeInTheDocument();
    expect(screen.getByDisplayValue("Gateway A")).toBeVisible();
    expect(screen.getByDisplayValue("https://a.example.com/v1")).toBeVisible();
    // key 只回显掩码 placeholder，不回明文
    expect(screen.getByPlaceholderText(/••••9876/)).toBeVisible();
  });

  it("marks provider health with a status dot on the right edge", async () => {
    getJson.mockResolvedValue({
      ...baseCatalog,
      providers: [
        baseCatalog.providers[0],
        { ...baseCatalog.providers[0], id: "gw-b", name: "Gateway B", enabled: false, api_key_hint: "••••1111" },
        { ...baseCatalog.providers[0], id: "gw-c", name: "Gateway C", api_key_configured: false, api_key_hint: null },
      ],
    });

    const { container } = renderManager();
    await waitFor(() => expect(screen.getByText("Gateway C")).toBeVisible());

    const dots = Array.from(container.querySelectorAll(".provider-dot"));
    expect(dots.map((dot) => dot.className)).toEqual([
      "provider-dot ok",
      "provider-dot off",
      "provider-dot warn",
    ]);
    expect(screen.getByTitle("已停用")).toBeVisible();
    expect(screen.getByTitle("缺 Key")).toBeVisible();
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
    fireEvent.click(screen.getByText("添加模型"));
    fireEvent.click(screen.getByText("添加模型"));
    const idInputs = screen.getAllByPlaceholderText("模型调用名");
    expect(idInputs).toHaveLength(2);
    fireEvent.change(idInputs[0], { target: { value: "openrouter/auto" } });
    fireEvent.change(screen.getAllByPlaceholderText("显示名称")[0], { target: { value: "Auto Router" } });
    fireEvent.click(screen.getByRole("button", { name: /保存供应商/ }));

    await waitFor(() => expect(postJson).toHaveBeenCalledWith(
      "/api/model-providers",
      expect.objectContaining({
        name: "OpenRouter",
        api_key: null,
        // 未填调用名的空行在保存时丢弃
        models: [{ id: "openrouter/auto", display_name: "Auto Router", enabled: true }],
      }),
    ));
    // 保存后仍选中新建的供应商
    await waitFor(() => expect(screen.getByDisplayValue("openrouter/auto")).toBeVisible());
  });

  it("sets the default model from the row star, one default at a time", async () => {
    getJson.mockResolvedValue({
      ...baseCatalog,
      default_selection: { provider_id: "gw-a", model_id: "model-a2" },
      providers: [{
        ...baseCatalog.providers[0],
        models: [{ id: "model-a1", enabled: true }, { id: "model-a2", enabled: true }],
      }],
    });
    putJson.mockResolvedValue({
      ...baseCatalog,
      default_selection: { provider_id: "gw-a", model_id: "model-a1" },
    });

    renderManager();
    await waitFor(() => expect(screen.getByDisplayValue("Gateway A")).toBeVisible());

    // 每行一颗星；只有当前默认那颗是点亮态
    expect(screen.getAllByRole("button", { name: /设为默认: / })).toHaveLength(2);
    expect(screen.getByRole("button", { name: "设为默认: model-a2" })).toHaveClass("active");
    expect(screen.getByRole("button", { name: "设为默认: model-a1" })).not.toHaveClass("active");

    fireEvent.click(screen.getByRole("button", { name: "设为默认: model-a1" }));
    await waitFor(() => expect(putJson).toHaveBeenCalledWith(
      "/api/model-providers/default-selection",
      { provider_id: "gw-a", model_id: "model-a1" },
    ));
  });

  it("keeps the available list out of the catalog and fills a row by picking", async () => {
    const onNotice = vi.fn();
    postJson.mockResolvedValue({ models: ["model-a1", "model-extra"] });

    renderManager(onNotice);
    await waitFor(() => expect(screen.getByDisplayValue("Gateway A")).toBeVisible());

    fireEvent.click(screen.getByRole("button", { name: "获取可用模型" }));
    await waitFor(() => expect(onNotice).toHaveBeenCalledWith({
      kind: "ok",
      text: "已获取 2 个可用模型。",
    }));
    // 拉取只刷新可用清单，不往目录里塞行
    expect(screen.queryByDisplayValue("model-extra")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /模型选项: model-a1/ }));
    await waitFor(() => expect(screen.getByText("model-extra")).toBeVisible());
    fireEvent.click(screen.getByText("model-extra"));

    await waitFor(() => expect(screen.getByDisplayValue("model-extra")).toBeVisible());
  });

  it("fetches draft models before saving once base url and key are filled", async () => {
    const onNotice = vi.fn();
    postJson.mockResolvedValue({ models: ["draft-model-a", "draft-model-b"] });

    renderManager(onNotice);
    await waitFor(() => expect(screen.getByText("新建供应商")).toBeVisible());
    fireEvent.click(screen.getByText("新建供应商"));

    // 草稿未填 base_url / key 时拉取按钮禁用，行内下拉也不可用
    const fetchButton = screen.getByRole("button", { name: "获取可用模型" });
    expect(fetchButton).toBeDisabled();
    fireEvent.click(screen.getByText("添加模型"));
    const rowToggle = screen.getByRole("button", { name: /模型选项/ });
    expect(rowToggle).toBeDisabled();

    fireEvent.change(screen.getByPlaceholderText("https://api.openai.com/v1"), {
      target: { value: "https://gw.example/v1" },
    });
    fireEvent.change(screen.getByPlaceholderText("输入服务商 API Key"), {
      target: { value: "sk-draft-key" },
    });
    expect(fetchButton).toBeEnabled();

    fireEvent.click(fetchButton);
    // 草稿没有 provider id：走草稿端点，key 随该次请求体发送
    await waitFor(() => expect(postJson).toHaveBeenCalledWith(
      "/api/model-providers/fetch-models",
      {
        base_url: "https://gw.example/v1",
        protocol: "chat_completions",
        api_key: "sk-draft-key",
      },
    ));
    await waitFor(() => expect(onNotice).toHaveBeenCalledWith({
      kind: "ok",
      text: "已获取 2 个可用模型。",
    }));

    // 拉取成功后行内下拉亮起，展开即可挑选并填入该行
    await waitFor(() => expect(rowToggle).toBeEnabled());
    fireEvent.click(rowToggle);
    await waitFor(() => expect(screen.getByText("draft-model-b")).toBeVisible());
    fireEvent.click(screen.getByText("draft-model-b"));

    await waitFor(() => expect(screen.getByDisplayValue("draft-model-b")).toBeVisible());
  });

  it("renders no field hint lines under the editor inputs", async () => {
    renderManager();
    await waitFor(() => expect(screen.getByDisplayValue("Gateway A")).toBeVisible());

    expect(screen.queryByText("用于界面展示，如「阿里云百炼」。")).not.toBeInTheDocument();
    expect(screen.queryByText("留空时使用 OpenAI SDK 默认端点。")).not.toBeInTheDocument();
    expect(screen.queryByText("模型调用名需与供应商文档完全一致。")).not.toBeInTheDocument();
    expect(screen.queryByText("已保存的密钥不会返回到桌面界面。")).not.toBeInTheDocument();
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

  it("offers the anthropic protocol option and template, switching the protocol on pick", async () => {
    postJson.mockResolvedValue({ ...baseCatalog, created_id: "anthropic" });
    renderManager();
    await waitFor(() => expect(screen.getByText("新建供应商")).toBeVisible());
    fireEvent.click(screen.getByText("新建供应商"));

    // 协议下拉含原生 Anthropic 选项
    expect(screen.getByRole("option", { name: "Anthropic Messages API" })).toBeInTheDocument();

    fireEvent.click(screen.getByText("Anthropic 官方"));
    expect(screen.getByDisplayValue("Anthropic 官方")).toBeVisible();
    expect(screen.getByDisplayValue("https://api.anthropic.com")).toBeVisible();
    // 模板选中即把协议切到 anthropic（base_url 是官方端点）
    expect(screen.getByRole("combobox")).toHaveValue("anthropic");

    fireEvent.click(screen.getByText("添加模型"));
    fireEvent.change(screen.getAllByPlaceholderText("模型调用名")[0], {
      target: { value: "claude-sonnet-4-5-20250929" },
    });
    fireEvent.click(screen.getByRole("button", { name: /保存供应商/ }));

    await waitFor(() => expect(postJson).toHaveBeenCalledWith(
      "/api/model-providers",
      expect.objectContaining({
        name: "Anthropic 官方",
        base_url: "https://api.anthropic.com",
        protocol: "anthropic",
        models: [{ id: "claude-sonnet-4-5-20250929", display_name: null, enabled: true }],
      }),
    ));
  });

  it("switches the template endpoint when the protocol changes unless the url was edited", async () => {
    renderManager();
    await waitFor(() => expect(screen.getByText("新建供应商")).toBeVisible());
    fireEvent.click(screen.getByText("新建供应商"));

    // 快填 DeepSeek：默认协议 chat_completions → /v1 端点
    fireEvent.click(screen.getByText("DeepSeek"));
    expect(screen.getByDisplayValue("https://api.deepseek.com/v1")).toBeVisible();

    // 改协议为 Anthropic → 端点跟随切到 /anthropic
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "anthropic" } });
    expect(screen.getByDisplayValue("https://api.deepseek.com/anthropic")).toBeVisible();

    // 切回 Chat Completions → 回到 /v1
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "chat_completions" } });
    expect(screen.getByDisplayValue("https://api.deepseek.com/v1")).toBeVisible();

    // 手改 URL 后切协议不再覆盖用户输入
    fireEvent.change(screen.getByDisplayValue("https://api.deepseek.com/v1"), {
      target: { value: "https://my-gateway.example/deepseek" },
    });
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "anthropic" } });
    expect(screen.getByDisplayValue("https://my-gateway.example/deepseek")).toBeVisible();
  });

  it("keeps the saved provider base url when the protocol changes while editing", async () => {
    renderManager();
    await waitFor(() => expect(screen.getByDisplayValue("Gateway A")).toBeVisible());

    fireEvent.change(screen.getByRole("combobox"), { target: { value: "responses" } });
    expect(screen.getByDisplayValue("https://a.example.com/v1")).toBeVisible();
  });
});
