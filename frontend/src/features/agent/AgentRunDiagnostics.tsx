import { Activity, ChevronDown } from "lucide-react";
import { useState } from "react";
import { getJson } from "../../lib/product-api";
import type { AgentDiagnostics } from "../../types";

type AgentRunDiagnosticsProps = {
  runId: string;
  label: string;
};

/** Lazily show redacted operational telemetry for one durable run. */
export function AgentRunDiagnostics({ runId, label }: AgentRunDiagnosticsProps) {
  const [diagnostics, setDiagnostics] = useState<AgentDiagnostics | null>(null);
  const [failed, setFailed] = useState(false);
  const usage = diagnostics?.usage;
  const spans = diagnostics?.spans ?? [];
  const hasTtft = spans.some((span) => span.ttft_ms != null);
  const thread = diagnostics?.thread_summary;

  return (
    <details
      className="agent-run-diagnostics"
      onToggle={(event) => {
        if (!event.currentTarget.open || diagnostics || failed) return;
        void getJson<AgentDiagnostics>(
          `/api/agent/runs/${encodeURIComponent(runId)}/diagnostics`,
        )
          .then(setDiagnostics)
          .catch(() => setFailed(true));
      }}
    >
      <summary><ChevronDown size={12} /><Activity size={12} />{label}</summary>
      {failed && <p>Diagnostics unavailable.</p>}
      {diagnostics && usage && (
        <div>
          <dl>
            <dt>Route</dt><dd>{diagnostics.task_kind} · {diagnostics.model_role}</dd>
            <dt>Model</dt><dd>{diagnostics.model || "No model call"}</dd>
            <dt>Latency</dt><dd>{Math.round(usage.elapsed_seconds * 1000)} ms</dd>
            {usage.ttft_ms != null && (
              <>
                <dt>TTFT</dt><dd>{Math.round(usage.ttft_ms)} ms</dd>
              </>
            )}
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
          </dl>
          {thread && (
            <p className="agent-run-thread-summary">
              {thread.run_count} runs · {thread.total_input_tokens} in ·{" "}
              {thread.total_output_tokens} out · {thread.total_cached_input_tokens} cached ·{" "}
              avg hit {Math.round(thread.avg_cache_hit_rate * 100)}%
            </p>
          )}
          {spans.length > 0 && (
            <table className="agent-run-spans">
              <thead>
                <tr>
                  <th>Round</th><th>In</th><th>Out</th><th>Cached</th><th>Hit</th><th>Duration</th>
                  {hasTtft && <th>TTFT</th>}
                </tr>
              </thead>
              <tbody>
                {spans.map((span, index) => (
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
      )}
    </details>
  );
}

function hitRate(part: number, whole: number): string {
  if (whole <= 0) return "—";
  return `${Math.round((part / whole) * 100)}%`;
}
