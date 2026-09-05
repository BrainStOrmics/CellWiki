import { useEffect, useState } from "react";
import { getJson } from "../../lib/product-api";
import { useI18n, type MessageKey } from "../../i18n";
import type { AgentDiagnostics, AgentSpan, AgentUsageSegment } from "../../types";

type AgentRunDiagnosticsProps = {
  runId: string;
  /** ADR-0010 决策 9：每段流的用量，唯一允许的展示位置就是本诊断面板。 */
  usageSegments?: AgentUsageSegment[];
};

/**
 * One compact stats line per settled run (model · rounds · steps | LLM and
 * tool time | first-token average · throughput | cache hit | token totals).
 * The line wraps freely with the sidebar width; clicking it expands the
 * per-round detail table.
 */
export function AgentRunDiagnostics({ runId, usageSegments }: AgentRunDiagnosticsProps) {
  const { t } = useI18n();
  const [diagnostics, setDiagnostics] = useState<AgentDiagnostics | null>(null);

  useEffect(() => {
    let active = true;
    void getJson<AgentDiagnostics>(
      `/api/agent/runs/${encodeURIComponent(runId)}/diagnostics`,
    )
      .then((value) => {
        if (active) setDiagnostics(value);
      })
      .catch(() => {
        // A run without diagnostics simply shows no stats line.
      });
    return () => {
      active = false;
    };
  }, [runId]);

  const usage = diagnostics?.usage;
  if (!diagnostics || !usage) return null;

  const modelSpans = diagnostics.spans.filter((span) => span.kind === "model");
  const toolSpans = diagnostics.spans.filter((span) => span.kind === "tool");
  const segments = summarySegments(diagnostics, modelSpans, toolSpans, usage, t);
  if (segments.length === 0) return null;

  const hasTtft = modelSpans.some((span) => span.ttft_ms != null);
  const thread = diagnostics.thread_summary;

  return (
    <details className="agent-run-diagnostics">
      <summary className="agent-run-summary">
        {segments.map((segment, index) => (
          <span className="agent-run-segment" key={`${segment}-${index}`}>
            {index > 0 && <span className="agent-run-sep">|</span>}
            {segment}
          </span>
        ))}
      </summary>
      <div className="agent-run-detail">
        <dl>
          <dt>Model</dt><dd>{diagnostics.model || "No model call"}</dd>
          <dt>Latency</dt><dd>{Math.round(usage.elapsed_seconds * 1000)} ms</dd>
          <dt>Tokens</dt>
          <dd>
            {usage.input_tokens} in · {usage.output_tokens} out
            {usage.cached_input_tokens
              ? ` · ${usage.cached_input_tokens} cached (${hitRate(usage.cached_input_tokens, usage.input_tokens)})`
              : ""}
          </dd>
          <dt>Tools</dt>
          <dd>
            {usage.tool_calls_started ?? usage.tool_calls} started ·{" "}
            {usage.tool_calls_completed ?? usage.tool_calls} completed ·{" "}
            {usage.tool_calls_failed ?? 0} failed ·{" "}
            {usage.tool_calls_cancelled ?? 0} cancelled
          </dd>
          {(usageSegments?.length ?? 0) > 0 && (
            <>
              <dt>Segments</dt>
              <dd>
                {usageSegments?.map((entry, index) => (
                  <span key={entry.event_id ?? `segment-${index}`}>
                    {index > 0 && " · "}
                    #{index + 1} {entry.segment.input_tokens} in /{" "}
                    {entry.segment.output_tokens} out (
                    {formatSeconds(entry.segment.elapsed_seconds * 1000)})
                  </span>
                ))}
              </dd>
            </>
          )}
          {diagnostics.checkpoint && (
            <>
              <dt>Checkpoint</dt>
              <dd>
                {diagnostics.checkpoint.backend} ·{" "}
                {diagnostics.checkpoint.id ?? "none"} ·{" "}
                {formatBytes(diagnostics.checkpoint.file_bytes)}
              </dd>
            </>
          )}
        </dl>
        {thread && (
          <p className="agent-run-thread-summary">
            {thread.run_count} runs · {thread.total_input_tokens} in ·{" "}
            {thread.total_output_tokens} out · {thread.total_cached_input_tokens} cached ·{" "}
            avg hit {Math.round(thread.avg_cache_hit_rate * 100)}%
          </p>
        )}
        {modelSpans.length > 0 && (
          <table className="agent-run-spans">
            <thead>
              <tr>
                <th>Round</th><th>In</th><th>Out</th><th>Cached</th><th>Hit</th><th>Duration</th>
                {hasTtft && <th>TTFT</th>}
              </tr>
            </thead>
            <tbody>
              {modelSpans.map((span, index) => (
                <tr key={span.span_id}>
                  <td>{index + 1}</td>
                  <td>{span.input_tokens}</td>
                  <td>{span.output_tokens}</td>
                  <td>{span.cached_input_tokens ?? 0}</td>
                  <td>{hitRate(span.cached_input_tokens ?? 0, span.input_tokens)}</td>
                  <td>{Math.round(span.duration_ms ?? 0)} ms</td>
                  {hasTtft && <td>{span.ttft_ms == null ? "—" : `${Math.round(span.ttft_ms)} ms`}</td>}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </details>
  );
}

type Translate = (key: MessageKey) => string;

function summarySegments(
  diagnostics: AgentDiagnostics,
  modelSpans: AgentSpan[],
  toolSpans: AgentSpan[],
  usage: AgentDiagnostics["usage"],
  t: Translate,
): string[] {
  const segments: string[] = [];
  // Conversation semantics: one run is one round; "steps" counts how often
  // the model was called inside this run (usage.model_calls mixes LangGraph
  // supersteps, so model spans are the reliable count).
  const rounds = diagnostics.thread_summary?.run_count ?? 0;
  const steps = modelSpans.length;
  const head = [
    diagnostics.model,
    rounds > 0 ? fill(t("chat.diagRounds"), rounds) : "",
    steps > 0 ? fill(t("chat.diagSteps"), steps) : "",
  ].filter(Boolean).join(" · ");
  if (head) segments.push(head);

  const llmMs = sumDuration(modelSpans);
  const toolMs = sumDuration(toolSpans);
  const timing = [
    llmMs > 0 ? fill(t("chat.diagLlm"), formatSeconds(llmMs)) : "",
    toolMs > 0 ? fill(t("chat.diagToolTime"), formatSeconds(toolMs)) : "",
  ].filter(Boolean).join(" · ");
  if (timing) segments.push(timing);

  const ttfts = modelSpans
    .map((span) => span.ttft_ms)
    .filter((value): value is number => value != null);
  const throughput = llmMs > 0 && usage.output_tokens > 0
    ? `${Math.round(usage.output_tokens / (llmMs / 1000))} tok/s`
    : "";
  const speed = [
    ttfts.length > 0 ? fill(t("chat.diagTtft"), formatSeconds(ttfts.reduce((a, b) => a + b, 0) / ttfts.length)) : "",
    throughput,
  ].filter(Boolean).join(" · ");
  if (speed) segments.push(speed);

  if (usage.cached_input_tokens && usage.input_tokens > 0) {
    segments.push(fill(t("chat.diagCache"), hitRate(usage.cached_input_tokens, usage.input_tokens).replace("%", "")));
  }
  const totals = [
    usage.input_tokens > 0 ? fill(t("chat.diagInput"), formatTokens(usage.input_tokens)) : "",
    usage.output_tokens > 0 ? fill(t("chat.diagOutput"), formatTokens(usage.output_tokens)) : "",
  ].filter(Boolean).join(" · ");
  if (totals) segments.push(totals);
  return segments;
}

function fill(template: string, value: string | number): string {
  return template.replace("{n}", String(value)).replace("{t}", String(value)).replace("{p}", String(value));
}

function sumDuration(spans: AgentSpan[]): number {
  return spans.reduce((total, span) => total + (span.duration_ms ?? 0), 0);
}

/** 50s / 45.6s / 2.5s — one decimal, trailing .0 dropped. */
function formatSeconds(ms: number): string {
  const rounded = Math.round((ms / 1000) * 10) / 10;
  return `${Number.isInteger(rounded) ? rounded : rounded.toFixed(1)}s`;
}

/** 108K / 2.2K / 340 — K units above 1000, one decimal below 100K. */
function formatTokens(value: number): string {
  if (value < 1000) return String(value);
  const k = value / 1000;
  const rounded = k >= 100 ? Math.round(k) : Math.round(k * 10) / 10;
  return `${Number.isInteger(rounded) ? rounded : rounded.toFixed(1)}K`;
}

/** checkpoints.sqlite 体积：1 KB 以下按字节报，往上 KB/MB 各留一位小数。 */
function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  const kb = value / 1024;
  if (kb < 1024) return `${Math.round(kb * 10) / 10} KB`;
  return `${Math.round((kb / 1024) * 10) / 10} MB`;
}

function hitRate(part: number, whole: number): string {
  if (whole <= 0) return "—";
  return `${Math.round((part / whole) * 100)}%`;
}
