import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { LanguageProvider } from "../../i18n";
import { useUiStore } from "../../stores/ui-store";
import type { AgentContextUsage, AppSettings, ModelProviderCatalog } from "../../types";

// ---------------------------------------------------------------------------
// 容量浮层的读数规则：总量用 provider 实测值、上限取"设置与模型窗口的较小值"、
// 分节只出占比，实测比估算多出来的那截单列"其他"——四条都锁在渲染结果上。
// ---------------------------------------------------------------------------

const usage: AgentContextUsage = {
  thread_id: "thread_1",
  used_tokens: 158_000,
  last_input_tokens: 143_600,
  last_output_tokens: 14_400,
  estimated_tokens: 120_000,
  sections: { messages: 90_000, injection: 20_000, tools: 6_000, system_prompt: 4_000 },
  avg_cache_hit_rate: 0.846,
  model_input_tokens: 1_000_000,
  input_window_source: "configured",
  effective_context_limit: 512_000,
  compaction_threshold: 479_000,
  retained_tokens: 32_768,
};

let usageResponse: AgentContextUsage = usage;
let settingsResponse = { agent_context_max_tokens: 512_000 } as AppSettings;
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
      models: [{ id: "model-a1", enabled: true, max_input_tokens: 1_000_000 }],
      request_overrides: {},
      source: "user",
      api_key_configured: true,
      api_key_hint: null,
    },
  ],
};
let catalogResponse: ModelProviderCatalog = baseCatalog;

vi.mock("../../lib/product-api", () => ({
  getJson: vi.fn((url: string) => {
    if (url.includes("/context-usage")) return Promise.resolve(usageResponse);
    if (url === "/api/settings") return Promise.resolve(settingsResponse);
    if (url === "/api/model-providers") return Promise.resolve(catalogResponse);
    return Promise.reject(new Error(`unexpected url ${url}`));
  }),
  postJson: vi.fn(),
  putJson: vi.fn(),
  deleteJson: vi.fn(),
}));

import { ContextUsage, effectiveContextCap, formatShare } from "./ContextUsage";

function renderUsage(threadId: string | null = "thread_1") {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <LanguageProvider>
        <ContextUsage threadId={threadId} />
      </LanguageProvider>
    </QueryClientProvider>,
  );
}

async function openPopover() {
  const anchor = document.querySelector(".context-usage") as HTMLElement;
  fireEvent.mouseEnter(anchor);
  return waitFor(() => screen.getByRole("tooltip"));
}

afterEach(cleanup);

describe("effectiveContextCap / formatShare", () => {
  it("上限取设置与模型输入窗口的较小值", () => {
    expect(effectiveContextCap(512_000, 1_000_000)).toBe(512_000);
    expect(effectiveContextCap(512_000, 128_000)).toBe(128_000);
    expect(effectiveContextCap(512_000, null)).toBe(512_000);
    expect(effectiveContextCap(undefined, undefined)).toBeNull();
  });

  it("占比一位小数、整数不留小数点", () => {
    expect(formatShare(0.73)).toBe("73%");
    expect(formatShare(0.2183)).toBe("21.8%");
    expect(formatShare(0)).toBe("0%");
  });
});

describe("ContextUsage", () => {
  beforeEach(() => {
    localStorage.clear();
    useUiStore.setState({ selectedModel: null });
    usageResponse = usage;
    settingsResponse = { agent_context_max_tokens: 512_000 } as AppSettings;
    catalogResponse = baseCatalog;
  });

  it("悬停展开：总量用实测值、上限取较小值，分节与缓存命中率都出占比", async () => {
    const { container } = renderUsage();
    await openPopover();

    // 158K/512K = 30.9%（实测与上限都来自接口，等它们到齐）
    expect(await screen.findByText("158K/512K（30.9%）", {}, { timeout: 3000 })).toBeVisible();
    const rows = [...container.querySelectorAll(".context-usage-rows li")].map((node) =>
      node.textContent,
    );
    expect(rows).toEqual([
      "对话消息57%",
      "上下文注入12.7%",
      "工具定义3.8%",
      "系统提示词2.5%",
      // 上轮回答的输出也占着上下文（下一轮会被重发），单列一行
      "上轮回答9.1%",
      // 实测与估算的差额落在"其他"，六项加起来才是占用总量
      "其他14.9%",
    ]);
    expect(screen.getByText("平均缓存命中率")).toBeVisible();
    expect(screen.getByText("84.6%")).toBeVisible();
    expect(screen.getByText("压缩保留尾部")).toBeVisible();
    expect(screen.getByText("32.8K")).toBeVisible();
    expect(screen.getByText("configured")).toBeVisible();
  });

  it("上限使用服务端解析后的 effective_context_limit", async () => {
    usageResponse = {
      ...usage,
      model_input_tokens: 128_000,
      effective_context_limit: 128_000,
      compaction_threshold: 95_000,
    };
    renderUsage();
    await openPopover();

    expect(await screen.findByText("158K/128K（100%）", {}, { timeout: 3000 })).toBeVisible();
  });

  it("模型窗口未声明时显示真实 fallback 与压缩阈值", async () => {
    usageResponse = {
      ...usage,
      model_input_tokens: 65_536,
      input_window_source: "fallback",
      effective_context_limit: 65_536,
      compaction_threshold: 32_536,
      retained_tokens: 8_536,
    };
    renderUsage();
    await openPopover();

    expect(await screen.findByText("158K/65.5K（100%）", {}, { timeout: 3000 })).toBeVisible();
    expect(screen.getByText("32.5K")).toBeVisible();
    expect(screen.getByText("8.5K")).toBeVisible();
    expect(screen.getByText("fallback")).toBeVisible();
    expect(screen.getByText("模型窗口未声明，使用 65.5K 安全回退")).toBeVisible();
  });

  it("还没跑过模型：不编造已用值，也没有\"其他\"行", async () => {
    usageResponse = {
      ...usage,
      used_tokens: 0,
      last_input_tokens: 0,
      last_output_tokens: 0,
      avg_cache_hit_rate: 0,
    };
    const { container } = renderUsage();
    await openPopover();

    expect(await screen.findByText("0/512K（0%）", {}, { timeout: 3000 })).toBeVisible();
    const rows = [...container.querySelectorAll(".context-usage-rows li")].map((node) =>
      node.textContent,
    );
    expect(rows).toHaveLength(4);
    expect(rows.some((row) => row?.startsWith("其他"))).toBe(false);
    expect(rows.some((row) => row?.startsWith("上轮回答"))).toBe(false);
    expect(screen.getAllByText("0%").length).toBeGreaterThan(0);
  });

  it("移开指针收起床层", async () => {
    renderUsage();
    await openPopover();

    fireEvent.mouseLeave(document.querySelector(".context-usage") as HTMLElement);
    await waitFor(() => expect(screen.queryByRole("tooltip")).toBeNull());
  });
});
