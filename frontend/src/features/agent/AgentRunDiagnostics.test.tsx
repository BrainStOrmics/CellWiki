import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AgentRunDiagnostics } from "./AgentRunDiagnostics";
import type { AgentDiagnostics } from "../../types";

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
  ],
  thread_summary: {
    run_count: 3,
    total_input_tokens: 3600,
    total_output_tokens: 800,
    total_cached_input_tokens: 1900,
    avg_cache_hit_rate: 0.5278,
  },
};

function openDetails(): void {
  fireEvent.click(screen.getByText("Run details"));
}

describe("AgentRunDiagnostics", () => {
  it("renders totals, per-round table, thread summary and a TTFT column", async () => {
    vi.mocked(getJson).mockResolvedValue(base);

    render(<AgentRunDiagnostics runId="run_1" label="Run details" />);
    openDetails();

    expect(await screen.findByText("1200 in · 340 out · 800 cached (67%)")).toBeInTheDocument();
    expect(
      screen.getByText("3 runs · 3600 in · 800 out · 1900 cached · avg hit 53%"),
    ).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "TTFT" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Round" })).toBeInTheDocument();
    expect(screen.getByText("800 ms")).toBeInTheDocument();
  });

  it("hides the TTFT column entirely when no span captures it", async () => {
    const payload: AgentDiagnostics = {
      ...base,
      spans: base.spans.map((span) => ({ ...span, ttft_ms: null })),
      usage: { ...base.usage, ttft_ms: null },
    };
    vi.mocked(getJson).mockResolvedValue(payload);

    render(<AgentRunDiagnostics runId="run_1" label="Run details" />);
    openDetails();

    expect(await screen.findByText("1200 in · 340 out · 800 cached (67%)")).toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "TTFT" })).not.toBeInTheDocument();
    expect(screen.queryByText("TTFT")).not.toBeInTheDocument();
  });

  it("renders totals without cached tokens and without thread stats when absent", async () => {
    const payload: AgentDiagnostics = {
      ...base,
      usage: { ...base.usage, cached_input_tokens: 0 },
      spans: [],
      thread_summary: undefined,
    };
    vi.mocked(getJson).mockResolvedValue(payload);

    render(<AgentRunDiagnostics runId="run_1" label="Run details" />);
    openDetails();

    expect(await screen.findByText("1200 in · 340 out")).toBeInTheDocument();
    expect(screen.queryByText("cached")).not.toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Round" })).not.toBeInTheDocument();
  });
});