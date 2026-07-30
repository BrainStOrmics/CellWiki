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
      {diagnostics && (
        <div>
          <dl>
            <dt>Route</dt><dd>{diagnostics.task_kind} · {diagnostics.model_role}</dd>
            <dt>Model</dt><dd>{diagnostics.model || "No model call"}</dd>
            <dt>Latency</dt><dd>{Math.round(diagnostics.usage.elapsed_seconds * 1000)} ms</dd>
            <dt>TTFT</dt><dd>{diagnostics.usage.ttft_ms == null ? "—" : `${Math.round(diagnostics.usage.ttft_ms)} ms`}</dd>
            <dt>Tokens</dt><dd>{diagnostics.usage.input_tokens} in · {diagnostics.usage.output_tokens} out</dd>
            <dt>Tools</dt>
            <dd>
              {diagnostics.usage.tool_calls_started ?? diagnostics.usage.tool_calls} started ·{" "}
              {diagnostics.usage.tool_calls_completed ?? diagnostics.usage.tool_calls} completed ·{" "}
              {diagnostics.usage.tool_calls_failed ?? 0} failed ·{" "}
              {diagnostics.usage.tool_calls_cancelled ?? 0} cancelled
            </dd>
          </dl>
          <ul>
            {diagnostics.spans.map((span) => (
              <li key={span.span_id}>
                <span>{span.kind} · {span.name}</span>
                <small>{span.status} · {Math.round(span.duration_ms ?? 0)} ms</small>
              </li>
            ))}
          </ul>
        </div>
      )}
    </details>
  );
}

