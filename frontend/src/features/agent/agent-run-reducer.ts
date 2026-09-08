import type {
  AgentAnswer,
  AgentEvent,
  AgentProcessPhase,
  AgentProcessStep,
  AgentRunStatus,
  AgentTimelineNode,
  AgentTimelineStatusTone,
  AgentToolArgsDisplay,
  AgentToolEditDiff,
  AgentToolResultPreview,
  AgentUsageSegment,
  ChatMessage,
} from "../../types";
// 单一终态来源：reducer 之前自带一份 terminalStatuses，缺 unfinished，与 AppShell
// 的判定各自漂移——同一 run 在两个地方被判成不同生命周期。统一用 run-status 的集合。
import { terminalAgentStatuses } from "./run-status";

export type AgentRunReducerLabels = {
  failed: string;
  cancelled: string;
  unfinished: string;
  /** AgentErrorType 的码 -> 用户可读的一句话（键与后端 domain/runs.py 一一对应）。 */
  errorTypes: Record<string, string>;
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

const statusTones: Record<string, AgentTimelineStatusTone> = {
  subagent_started: "info",
  subagent_completed: "success",
  progress: "info",
  review_required: "warning",
  changeset_ready: "success",
  verification: "info",
};

/**
 * 实测交接问题 E：失败 run 过去把 provider 的原始英文报错当作唯一可见文本，用户看到的
 * 是一串 ``Error code: 500 - {...}``。durable 的 error 事件与终态 run_status 本来就带
 * ``error_type``，reducer 只是从来不读它。
 *
 * 原始文本没有丢：它仍在 ``step.message`` 与诊断面板的 ``error_message`` 里，两处都在
 * API 出口脱敏过。未知码回落到原文——后端新增一个分类不该让前端变成哑巴。
 */
function localizedError(event: AgentEvent, labels: AgentRunReducerLabels): string | null {
  const code = event.data?.error_type;
  if (typeof code !== "string" || !code) return null;
  return labels.errorTypes[code] ?? null;
}

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
      runId: event.run_id,
      streaming: false,
    });
  }

  if (event.type === "error") {
    const errorText = localizedError(event, labels) ?? (event.message || labels.failed);
    // 时间线节点由 appendProcessEventNode 统一追加（"error" 在 processEventTypes 里），
    // 那一份带 step 且按 event_id 去重。这里再追加一次就是同一句话渲染两遍——桌面端
    // 实测每个失败 run 的错误条都成对出现，重放时还会越喂越多。text 仍要写：它是
    // "没有时间线节点"时错误的唯一落点（气泡只在那种情况下渲染正文）。
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

  if (event.type === "task_confirmation_required") {
    // 提问卡挂在 message.runStatus 上（AgentMessageBubble.isAwaitingUserAnswer）。
    // 直播路径此前没有注册这个事件名，EventSource 直接丢弃；回放路径虽然把事件
    // 喂给了 reducer，这里也不认它 —— 两条路径都只能指望随后那条 run_status。
    // 让事件自己把 run 标成"等待用户回答"，卡片就不再依赖事件到达顺序。
    return updateRunMessage(next, event.run_id, (message) => ({
      ...message,
      runStatus: "waiting_confirmation",
      streaming: false,
    }), {
      role: "agent",
      text: "",
      runId: event.run_id,
      runStatus: "waiting_confirmation",
      streaming: false,
    });
  }

  if (event.type === "usage_updated") {
    // 决策 9：用量只累积到诊断专用字段，不碰 text / timeline，也不新建气泡
    // （fallback 传 null）——聊天气泡里永远看不到"用量"这段文本。
    const payload = event.data as Partial<AgentUsageSegment>;
    if (!payload.segment || !payload.cumulative) return next;
    const segment: AgentUsageSegment = {
      event_id: event.event_id,
      segment: payload.segment,
      cumulative: payload.cumulative,
    };
    return updateRunMessage(next, event.run_id, (message) => (
      message.usageSegments?.some((existing) => existing.event_id === segment.event_id)
        ? message
        : { ...message, usageSegments: [...(message.usageSegments ?? []), segment] }
    ), null);
  }

  if (event.type === "run_status") {
    const status = event.data.status as AgentRunStatus | undefined;
    if (!status || !terminalAgentStatuses.has(status)) return next;
    return settleRun(next, event.run_id, status, {
      failed: localizedError(event, labels)
        ?? String(event.data.error_message || event.message || labels.failed),
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
    // meta 只有失败分支会写（"Agent 运行失败 · system"）。retry/续跑复用同一条 run 与
    // 同一个气泡，救活之后第一次失败盖的标签必须让位，否则成功的答案底下永远挂着
    // 上一轮的失败字样（真机实测：重试成功后页脚仍显示运行失败）。
    meta: status === "succeeded" ? undefined : message.meta,
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
      return [...base, {
        kind: "tool",
        phase: "running",
        toolName,
        summary: event.message,
        step,
        argsDisplay: readArgsDisplay(event.data),
        editDiff: readEditDiff(event.data),
      }];
    }
    const callId = String((event.data as Record<string, unknown>).tool_call_id ?? "");
    const index = base.findIndex(
      (node) => node.kind === "tool"
        && String((node.step.data as Record<string, unknown>).tool_call_id ?? "") === callId,
    );
    const phase: AgentProcessPhase = event.type === "tool_failed" ? "failed" : "completed";
    const resultPreview = readResultPreview(event.data);
    if (index >= 0) {
      const updated = [...base];
      const previous = updated[index];
      updated[index] = {
        kind: "tool",
        phase,
        toolName: previous.kind === "tool" ? previous.toolName : toolName,
        summary: event.message || (previous.kind === "tool" ? previous.summary : ""),
        step,
        argsDisplay: previous.kind === "tool" ? previous.argsDisplay : undefined,
        editDiff: previous.kind === "tool" ? previous.editDiff : undefined,
        resultPreview,
      };
      return updated;
    }
    return [...base, {
      kind: "tool",
      phase,
      toolName,
      summary: event.message,
      step,
      resultPreview,
      editDiff: readEditDiff(event.data),
    }];
  }
  const tone: AgentTimelineStatusTone = event.type === "error" ? "danger" : (statusTones[event.type] ?? "info");
  // 失败 run 真正被读到的就是这一条：气泡只在"没有时间线节点"时才渲染 message.text，
  // 而失败 run 必有节点。原始报错留在 step.message 上，不在这里显示。
  const label = localizedError(event, labels)
    ?? (event.message || event.type.replaceAll("_", " "));
  return [...base, { kind: "status", tone, label, step }];
}

/** Bounded projections ride the durable event payload; tolerate their absence. */
function readArgsDisplay(data: Record<string, unknown>): AgentToolArgsDisplay | undefined {
  const value = (data as { args_display?: unknown }).args_display;
  return value && typeof value === "object" ? value as AgentToolArgsDisplay : undefined;
}

function readResultPreview(data: Record<string, unknown>): AgentToolResultPreview | undefined {
  const value = (data as { result_preview?: unknown }).result_preview;
  return value && typeof value === "object" ? value as AgentToolResultPreview : undefined;
}

function readEditDiff(data: Record<string, unknown>): AgentToolEditDiff | undefined {
  const value = (data as { edit_diff_display?: unknown }).edit_diff_display;
  return value && typeof value === "object" ? value as AgentToolEditDiff : undefined;
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
