import type {
  AgentAnswer,
  AgentEvent,
  AgentProcessPhase,
  AgentProcessStep,
  AgentRunStatus,
  ChatMessage,
} from "../../types";

export type AgentRunReducerLabels = {
  evidenceMeta: string;
  failed: string;
  cancelled: string;
  formatConfidence: (confidence: "low" | "medium" | "high") => string;
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

/** Pure projection from durable run events to the user-visible transcript. */
export function reduceAgentRunMessages(
  messages: ChatMessage[],
  event: AgentEvent,
  labels: AgentRunReducerLabels,
): ChatMessage[] {
  let next = messages;
  if (processEventTypes.has(event.type)) {
    next = appendProcessStep(next, event);
  }

  if (event.type === "message_delta" && event.message) {
    return updateRunMessage(next, event.run_id, (message) => ({
      ...message,
      text: `${message.text}${event.message}`,
      streaming: true,
    }), {
      role: "agent",
      text: event.message,
      meta: labels.evidenceMeta,
      runId: event.run_id,
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
      meta: `${labels.failed} · ${String(event.data.error_type ?? "system")}`,
    }), {
      role: "agent",
      text: errorText,
      meta: `${labels.failed} · ${String(event.data.error_type ?? "system")}`,
      runId: event.run_id,
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

function appendProcessStep(messages: ChatMessage[], event: AgentEvent): ChatMessage[] {
  const step = processStepFromEvent(event);
  return updateRunMessage(messages, event.run_id, (message) => {
    if (message.process?.some((existing) => existing.event_id === event.event_id)) {
      return message;
    }
    return { ...message, process: [...(message.process ?? []), step] };
  }, {
    role: "agent",
    text: "",
    process: [step],
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
    text: status === "failed"
      ? message.text || terminalText.failed
      : status === "cancelled"
        ? message.text || terminalText.cancelled
        : message.text,
    process: message.process?.map((step) => (
      step.phase === "running" ? { ...step, phase } : step
    )),
    streaming: false,
  }), status === "failed" || status === "cancelled" ? {
    role: "agent",
    text: status === "failed" ? terminalText.failed : terminalText.cancelled,
    runId,
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

