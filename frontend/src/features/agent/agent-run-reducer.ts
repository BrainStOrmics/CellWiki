import type {
  AgentAnswer,
  AgentEvent,
  AgentProcessPhase,
  AgentProcessStep,
  AgentRunStatus,
  AgentTimelineNode,
  AgentTimelineStatusTone,
  ChatMessage,
} from "../../types";

export type AgentRunReducerLabels = {
  evidenceMeta: string;
  failed: string;
  cancelled: string;
  unfinished: string;
  formatConfidence: (confidence: "low" | "medium" | "high") => string;
  timelineContext?: { label: string; detail?: string } | null;
};

const processEventTypes = new Set([
  "tool_started",
  "tool_completed",
  "tool_failed",
  "subagent_started",
  "subagent_completed",
  "progress",
  "review_required",
  "changeset_ready",
  "verification",
  "error",
]);

const terminalStatuses = new Set<AgentRunStatus>([
  "waiting_confirmation",
  "waiting_approval",
  "succeeded",
  "rejected",
  "failed",
  "cancelled",
]);

const statusTones: Record<string, AgentTimelineStatusTone> = {
  subagent_started: "info",
  subagent_completed: "success",
  progress: "info",
  review_required: "warning",
  changeset_ready: "success",
  verification: "info",
};

/** Pure projection from durable run events to the user-visible transcript. */
export function reduceAgentRunMessages(
  messages: ChatMessage[],
  event: AgentEvent,
  labels: AgentRunReducerLabels,
): ChatMessage[] {
  let next = messages;
  if (processEventTypes.has(event.type)) {
    next = appendProcessStep(next, event, labels);
  }

  if (event.type === "message_delta" && event.message) {
    return updateRunMessage(next, event.run_id, (message) => ({
      ...message,
      text: `${message.text}${event.message}`,
      timeline: appendTextNode(message.timeline, event.message, labels),
      streaming: true,
    }), {
      role: "agent",
      text: event.message,
      meta: labels.evidenceMeta,
      runId: event.run_id,
      timeline: appendTextNode(undefined, event.message, labels),
      streaming: true,
    });
  }

  if (event.type === "reasoning_delta" && event.message) {
    return updateRunMessage(next, event.run_id, (message) => ({
      ...message,
      reasoning: `${message.reasoning ?? ""}${event.message}`,
      timeline: appendThinkingNode(message.timeline, event.message, labels),
      streaming: true,
    }), {
      role: "agent",
      text: "",
      reasoning: event.message,
      runId: event.run_id,
      timeline: appendThinkingNode(undefined, event.message, labels),
      streaming: true,
    });
  }

  if (event.type === "final_response") {
    const structured = event.data as Partial<AgentAnswer>;
    const answer = structured.answer || event.message;
    if (!answer) return next;
    const verificationLevel = structured.verification_level ?? "unvalidated";
    const knowledgeScope = structured.knowledge_scope ?? "unvalidated";
    const effectiveConfidence = knowledgeScope === "general"
      ? undefined
      : verificationLevel === "unvalidated"
        ? "low"
        : structured.confidence;
    return updateRunMessage(next, event.run_id, (message) => ({
      ...message,
      text: answer,
      citations: structured.citations ?? [],
      confidence: effectiveConfidence,
      declaredConfidence: structured.declared_confidence,
      verificationLevel,
      knowledgeScope,
      validationIssues: structured.validation_issues ?? [],
      missingEvidence: structured.missing_evidence ?? [],
      timeline: ensureTextNodeAnswer(message.timeline, answer, labels),
      meta: effectiveConfidence
        ? `${labels.evidenceMeta} · ${labels.formatConfidence(effectiveConfidence)}`
        : labels.evidenceMeta,
      streaming: false,
    }), {
      role: "agent",
      text: answer,
      citations: structured.citations ?? [],
      confidence: effectiveConfidence,
      declaredConfidence: structured.declared_confidence,
      verificationLevel,
      knowledgeScope,
      validationIssues: structured.validation_issues ?? [],
      missingEvidence: structured.missing_evidence ?? [],
      timeline: ensureTextNodeAnswer(undefined, answer, labels),
      meta: effectiveConfidence
        ? `${labels.evidenceMeta} · ${labels.formatConfidence(effectiveConfidence)}`
        : labels.evidenceMeta,
      runId: event.run_id,
      streaming: false,
    });
  }

  if (event.type === "error") {
    const errorText = event.message || labels.failed;
    return updateRunMessage(next, event.run_id, (message) => ({
      ...message,
      text: message.text || errorText,
      timeline: [...(message.timeline ?? freshTimeline(labels)), { kind: "status", tone: "danger", label: errorText }],
      meta: `${labels.failed} · ${String(event.data.error_type ?? "system")}`,
    }), {
      role: "agent",
      text: errorText,
      meta: `${labels.failed} · ${String(event.data.error_type ?? "system")}`,
      runId: event.run_id,
      timeline: [...freshTimeline(labels), { kind: "status", tone: "danger", label: errorText }],
      streaming: true,
    });
  }

  if (event.type === "run_status") {
    const status = event.data.status as AgentRunStatus | undefined;
    if (!status || !terminalStatuses.has(status)) return next;
    return settleRun(next, event.run_id, status, {
      failed: String(event.data.error_message || event.message || labels.failed),
      cancelled: event.message || labels.cancelled,
    });
  }
  return next;
}

function appendProcessStep(
  messages: ChatMessage[],
  event: AgentEvent,
  labels: AgentRunReducerLabels,
): ChatMessage[] {
  const step = processStepFromEvent(event);
  return updateRunMessage(messages, event.run_id, (message) => {
    if (message.process?.some((existing) => existing.event_id === event.event_id)) {
      return message;
    }
    return {
      ...message,
      process: [...(message.process ?? []), step],
      timeline: appendProcessEventNode(message.timeline, event, step, labels),
    };
  }, {
    role: "agent",
    text: "",
    process: [step],
    timeline: appendProcessEventNode(undefined, event, step, labels),
    runId: event.run_id,
    streaming: true,
  });
}

function settleRun(
  messages: ChatMessage[],
  runId: string,
  status: AgentRunStatus,
  terminalText: { failed: string; cancelled: string },
): ChatMessage[] {
  const phase: AgentProcessPhase = status === "failed"
    ? "failed"
    : status === "cancelled"
      ? "cancelled"
      : "completed";
  return updateRunMessage(messages, runId, (message) => ({
    ...message,
    runStatus: status,
    text: status === "failed"
      ? message.text || terminalText.failed
      : status === "cancelled"
        ? message.text || terminalText.cancelled
        : message.text,
    process: message.process?.map((step) => (
      step.phase === "running" ? { ...step, phase } : step
    )),
    timeline: message.timeline?.map((node) => (
      node.kind === "tool" && node.phase === "running" ? { ...node, phase } : node
    )),
    streaming: false,
  }), status === "failed" || status === "cancelled" ? {
    role: "agent",
    text: status === "failed" ? terminalText.failed : terminalText.cancelled,
    runId,
    runStatus: status,
    streaming: false,
  } : null);
}

function processStepFromEvent(event: AgentEvent): AgentProcessStep {
  const phase = event.type === "tool_failed" || event.type === "error"
    ? "failed"
    : event.type === "tool_started" || event.type === "subagent_started"
      ? "running"
      : "completed";
  return { ...event, phase };
}

function freshTimeline(labels: AgentRunReducerLabels): AgentTimelineNode[] {
  if (!labels.timelineContext) return [];
  return [{ kind: "context", label: labels.timelineContext.label, detail: labels.timelineContext.detail }];
}

function appendTextNode(
  timeline: AgentTimelineNode[] | undefined,
  text: string,
  labels: AgentRunReducerLabels,
): AgentTimelineNode[] {
  const base = timeline ?? freshTimeline(labels);
  const last = base[base.length - 1];
  if (last && last.kind === "text") {
    return [...base.slice(0, -1), { kind: "text", text: `${last.text}${text}` }];
  }
  return [...base, { kind: "text", text }];
}

function appendThinkingNode(
  timeline: AgentTimelineNode[] | undefined,
  text: string,
  labels: AgentRunReducerLabels,
): AgentTimelineNode[] {
  const base = timeline ?? freshTimeline(labels);
  const last = base[base.length - 1];
  if (last && last.kind === "thinking") {
    return [...base.slice(0, -1), { kind: "thinking", text: `${last.text}${text}` }];
  }
  return [...base, { kind: "thinking", text }];
}

function ensureTextNodeAnswer(
  timeline: AgentTimelineNode[] | undefined,
  text: string,
  labels: AgentRunReducerLabels,
): AgentTimelineNode[] {
  const base = timeline ?? freshTimeline(labels);
  if (base.some((node) => node.kind === "text")) return base;
  return [...base, { kind: "text", text }];
}

function appendProcessEventNode(
  timeline: AgentTimelineNode[] | undefined,
  event: AgentEvent,
  step: AgentProcessStep,
  labels: AgentRunReducerLabels,
): AgentTimelineNode[] {
  const base = timeline ?? freshTimeline(labels);
  if (event.type === "tool_started" || event.type === "tool_completed" || event.type === "tool_failed") {
    const toolName = String((event.data as Record<string, unknown>).tool_name ?? "tool");
    if (event.type === "tool_started") {
      return [...base, { kind: "tool", phase: "running", toolName, summary: event.message, step }];
    }
    const callId = String((event.data as Record<string, unknown>).tool_call_id ?? "");
    const index = base.findIndex(
      (node) => node.kind === "tool"
        && String((node.step.data as Record<string, unknown>).tool_call_id ?? "") === callId,
    );
    const phase: AgentProcessPhase = event.type === "tool_failed" ? "failed" : "completed";
    if (index >= 0) {
      const updated = [...base];
      const previous = updated[index];
      updated[index] = {
        kind: "tool",
        phase,
        toolName: previous.kind === "tool" ? previous.toolName : toolName,
        summary: event.message || (previous.kind === "tool" ? previous.summary : ""),
        step,
      };
      return updated;
    }
    return [...base, { kind: "tool", phase, toolName, summary: event.message, step }];
  }
  const tone: AgentTimelineStatusTone = event.type === "error" ? "danger" : (statusTones[event.type] ?? "info");
  const label = event.message || event.type.replaceAll("_", " ");
  return [...base, { kind: "status", tone, label, step }];
}

function updateRunMessage(
  messages: ChatMessage[],
  runId: string,
  update: (message: ChatMessage) => ChatMessage,
  fallback: ChatMessage | null,
): ChatMessage[] {
  const reverseIndex = [...messages].reverse().findIndex(
    (message) => message.role === "agent" && message.runId === runId,
  );
  if (reverseIndex < 0) return fallback ? [...messages, fallback] : messages;
  const index = messages.length - 1 - reverseIndex;
  const next = [...messages];
  next[index] = update(next[index]);
  return next;
}
