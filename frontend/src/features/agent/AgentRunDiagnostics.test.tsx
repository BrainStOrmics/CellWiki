import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AgentRunDiagnostics } from "./AgentRunDiagnostics";
import { LanguageProvider } from "../../i18n";
import type { AgentDiagnostics, AgentUsageSegment } from "../../types";

afterEach(cleanup);

vi.mock("../../lib/product-api", () => ({
  getJson: vi.fn(),
}));

import { getJson } from "../../lib/product-api";

const base: AgentDiagnostics = {
  run_id: "run_1",
  thread_id: "thread_1",
  status: "succeeded",
  task_kind: "conversation",
  model: "gpt-x",
  model_role: "coordinator",
  usage: {
    model_calls: 2,
    input_tokens: 1200,
    output_tokens: 340,
    cached_input_tokens: 800,
    estimated_cost_usd: 0,
    tool_calls: 3,
    tool_calls_started: 3,
    tool_calls_completed: 3,
    tool_calls_failed: 0,
    tool_calls_cancelled: 0,
    elapsed_seconds: 12.5,
  },
  spans: [
    {
      span_id: "s1", run_id: "run_1", kind: "model", name: "gpt-x", status: "completed",
      started_at: "2026-08-27T00:00:00Z", duration_ms: 6000, ttft_ms: 800,
      input_tokens: 700, output_tokens: 200, cached_input_tokens: 500, data: {},
    },
    {
      span_id: "s2", run_id: "run_1", kind: "model", name: "gpt-x", status: "completed",
      started_at: "2026-08-27T00:00:01Z", duration_ms: 6500, ttft_ms: null,
      input_tokens: 500, output_tokens: 140, cached_input_tokens: 300, data: {},
    },
    {
      span_id: "t1", run_id: "run_1", kind: "tool", name: "grep", status: "completed",
      started_at: "2026-08-27T00:00:00Z", duration_ms: 1200, ttft_ms: null,
      input_tokens: 0, output_tokens: 0, data: {},
    },
  ],
  thread_summary: {
    run_count: 3,
    total_input_tokens: 3600,
    total_output_tokens: 800,
    total_cached_input_tokens: 1900,
    avg_cache_hit_rate: 0.5278,
  },
};

function renderDiagnostics(usageSegments?: AgentUsageSegment[]) {
  return render(
    <LanguageProvider>
      <AgentRunDiagnostics runId="run_1" usageSegments={usageSegments} />
    </LanguageProvider>,
  );
}

describe("AgentRunDiagnostics", () => {
  it("renders the compact stats summary without expanding", async () => {
    vi.mocked(getJson).mockResolvedValue(base);
    renderDiagnostics();

    // model · rounds(run count in thread) · steps(model calls in this run) | LLM time · tool time | ttft · tok/s | cache | tokens
    expect(await screen.findByText("gpt-x · 3轮 · 2步")).toBeInTheDocument();
    expect(screen.getByText("LLM 12.5s · 工具调用 1.2s")).toBeInTheDocument();
    expect(screen.getByText("首token平均 0.8s · 27 tok/s")).toBeInTheDocument();
    expect(screen.getByText("缓存命中 67%")).toBeInTheDocument();
    expect(screen.getByText("输入 1.2K tok · 输出 340 tok")).toBeInTheDocument();
  });

  it("expands to the per-round detail table with a TTFT column", async () => {
    vi.mocked(getJson).mockResolvedValue(base);
    const { container } = renderDiagnostics();
    await screen.findByText("gpt-x · 3轮 · 2步");
    const details = container.querySelector(".agent-run-diagnostics") as HTMLDetailsElement;
    expect(details.open).toBe(false);

    fireEvent.click(container.querySelector(".agent-run-summary") as HTMLElement);
    expect((container.querySelector(".agent-run-diagnostics") as HTMLDetailsElement).open).toBe(true);
    expect(screen.getByRole("columnheader", { name: "TTFT" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Round" })).toBeInTheDocument();
    expect(screen.getByText("800 ms")).toBeInTheDocument();
    expect(
      screen.getByText("3 runs · 3600 in · 800 out · 1900 cached · avg hit 53%"),
    ).toBeInTheDocument();
  });

  it("omits speed and tool segments when no span captures them", async () => {
    // The single tool span is folded into a model span, so rounds become 3 and
    // the tool-time segment disappears.
    vi.mocked(getJson).mockResolvedValue({
      ...base,
      spans: base.spans.map((span) => ({ ...span, kind: span.kind === "tool" ? "model" : span.kind, ttft_ms: null })),
    });
    renderDiagnostics();

    expect(await screen.findByText("gpt-x · 3轮 · 3步")).toBeInTheDocument();
    expect(screen.queryByText(/工具调用/)).not.toBeInTheDocument();
    expect(screen.queryByText(/首token/)).not.toBeInTheDocument();
    // Throughput still derives from model span durations (12.5s + 1.2s).
    expect(screen.getByText("25 tok/s")).toBeInTheDocument();
  });

  it("renders nothing when diagnostics fail to load", async () => {
    vi.mocked(getJson).mockRejectedValue(new Error("offline"));
    const { container } = renderDiagnostics();
    await new Promise((resolve) => window.setTimeout(resolve, 0));
    expect(container.querySelector(".agent-run-diagnostics")).toBeNull();
  });

  it("formats large token totals in K units", async () => {
    vi.mocked(getJson).mockResolvedValue({
      ...base,
      usage: { ...base.usage, input_tokens: 108_400, output_tokens: 2_200, cached_input_tokens: 82_000 },
    });
    renderDiagnostics();
    expect(await screen.findByText("输入 108K tok · 输出 2.2K tok")).toBeInTheDocument();
    expect(screen.getByText("缓存命中 76%")).toBeInTheDocument();
  });

  it("renders each stream segment's own usage (ADR-0010 决策 9)", async () => {
    vi.mocked(getJson).mockResolvedValue(base);
    const { container } = renderDiagnostics([
      {
        event_id: "u-1",
        segment: { ...base.usage, input_tokens: 700, output_tokens: 200, elapsed_seconds: 6 },
        cumulative: base.usage,
      },
      {
        event_id: "u-2",
        segment: { ...base.usage, input_tokens: 500, output_tokens: 140, elapsed_seconds: 6.5 },
        cumulative: base.usage,
      },
    ]);
    await screen.findByText("gpt-x · 3轮 · 2步");

    const detail = container.querySelector(".agent-run-detail")?.textContent ?? "";
    expect(detail).toContain("Segments");
    expect(detail).toContain("#1 700 in / 200 out (6s)");
    expect(detail).toContain("#2 500 in / 140 out (6.5s)");
  });

  it("reports the checkpoint carrier and its on-disk size (决策 4/12)", async () => {
    vi.mocked(getJson).mockResolvedValue({
      ...base,
      checkpoint: { id: "1f1a95b7", backend: "sqlite", file_bytes: 24_576 },
    });
    const { container } = renderDiagnostics();
    await screen.findByText("gpt-x · 3轮 · 2步");

    const detail = container.querySelector(".agent-run-detail")?.textContent ?? "";
    expect(detail).toContain("Checkpoint");
    expect(detail).toContain("sqlite · 1f1a95b7 · 24 KB");
  });

  it("shows none for a run that predates checkpoint persistence", async () => {
    vi.mocked(getJson).mockResolvedValue({
      ...base,
      checkpoint: { id: null, backend: "sqlite", file_bytes: 512 },
    });
    const { container } = renderDiagnostics();
    await screen.findByText("gpt-x · 3轮 · 2步");

    expect(container.querySelector(".agent-run-detail")?.textContent ?? "").toContain(
      "sqlite · none · 512 B",
    );
  });

  it("omits the segment and checkpoint rows when neither is supplied", async () => {
    vi.mocked(getJson).mockResolvedValue(base);
    const { container } = renderDiagnostics();
    await screen.findByText("gpt-x · 3轮 · 2步");

    const detail = container.querySelector(".agent-run-detail")?.textContent ?? "";
    expect(detail).not.toContain("Segments");
    expect(detail).not.toContain("Checkpoint");
  });
});
