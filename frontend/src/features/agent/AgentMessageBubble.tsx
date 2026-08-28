import {
  Brain,
  CircleAlert,
  CircleCheck,
  FileText,
  LoaderCircle,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { MarkdownContent } from "../../components/MarkdownContent";
import { AgentRunDiagnostics } from "./AgentRunDiagnostics";
import { QuestionCard } from "./QuestionCard";
import type {
  AgentProcessStep,
  AgentRunStatus,
  AgentTimelineNode,
  ChatMessage,
} from "../../types";

type AgentMessageBubbleProps = {
  message: ChatMessage;
  agentLabel: string;
  userLabel: string;
  reasoningTitle: string;
  reasoningLiveLabel: string;
  diagnosticsLabel: string;
  onQuestionAnswered?: (runId: string) => void;
};

/** One agent message rendered as a flat, chronological timeline of lightweight nodes. */
export function AgentMessageBubble({
  message,
  agentLabel,
  userLabel,
  reasoningTitle,
  reasoningLiveLabel,
  diagnosticsLabel,
  onQuestionAnswered,
}: AgentMessageBubbleProps) {
  const isAgent = message.role === "agent";
  const nodes = timelineNodes(message);

  return (
    <div className={`message ${message.role} ${message.streaming ? "is-streaming" : ""}`}>
      <div className="message-author">
        {isAgent ? <><Brain size={13} />{agentLabel}</> : userLabel}
      </div>
      {!isAgent && message.attachments && message.attachments.length > 0 && (
        <div className="message-attachments">
          {message.attachments.map((attachment) => (
            <span
              className="message-attachment"
              key={attachment.attachment_id}
              title={attachment.attachment_id}
            >
              <FileText size={12} />
              <span>{attachment.original_name ?? attachment.attachment_id}</span>
            </span>
          ))}
        </div>
      )}
      <div className="message-bubble">
        {isAgent && nodes.length > 0 ? (
          <div className="agent-timeline">
            {nodes.map((node, index) => (
              <TimelineNode
                key={`${node.kind}-${index}`}
                node={node}
                streaming={Boolean(message.streaming)}
                reasoningTitle={reasoningTitle}
                reasoningLiveLabel={reasoningLiveLabel}
              />
            ))}
          </div>
        ) : isAgent ? (
          <MarkdownContent content={message.text} />
        ) : (
          <p>{message.text}</p>
        )}
      </div>
      {message.meta && <small className="message-meta">{message.meta}</small>}
      {isAgent && message.runId && (
        <>
          {!message.streaming && (
            <AgentRunDiagnostics runId={message.runId} label={diagnosticsLabel} />
          )}
          {isAwaitingUserAnswer(message.runStatus) && (
            <QuestionCard runId={message.runId} onAnswered={onQuestionAnswered} />
          )}
        </>
      )}
    </div>
  );
}

/** 只有等待用户回应的 run 才需要问题卡；历史消息不挂载，避免每个气泡都轮询 /question。 */
function isAwaitingUserAnswer(status: AgentRunStatus | undefined): boolean {
  return status === "waiting_confirmation" || status === "waiting_approval";
}

function timelineNodes(message: ChatMessage): AgentTimelineNode[] {
  if (message.timeline && message.timeline.length > 0) return message.timeline;
  // Legacy fallback: rebuild lightweight nodes from persisted process steps.
  const nodes: AgentTimelineNode[] = [];
  for (const step of message.process ?? []) {
    if (step.type === "tool_started" || step.type === "tool_completed" || step.type === "tool_failed") {
      nodes.push({
        kind: "tool",
        phase: step.phase,
        toolName: String((step.data as Record<string, unknown>).tool_name ?? "tool"),
        summary: step.message,
        step,
      });
    } else {
      nodes.push({
        kind: "status",
        tone: step.phase === "failed" || step.phase === "cancelled" ? "danger" : "info",
        label: step.message || step.type.replaceAll("_", " "),
        step,
      });
    }
  }
  if (message.reasoning) nodes.push({ kind: "thinking", text: message.reasoning });
  if (message.text) nodes.push({ kind: "text", text: message.text });
  return nodes;
}

type TimelineNodeProps = {
  node: AgentTimelineNode;
  streaming: boolean;
  reasoningTitle: string;
  reasoningLiveLabel: string;
};

function TimelineNode({ node, streaming, reasoningTitle, reasoningLiveLabel }: TimelineNodeProps) {
  switch (node.kind) {
    case "context":
      return (
        <div className="agent-timeline-node">
          <FileText size={12} />
          <span className="at-kind">context</span>
          <span className="at-label">{node.label}{node.detail ? ` · ${node.detail}` : ""}</span>
        </div>
      );
    case "thinking":
      return (
        <ThinkingNode
          text={node.text}
          streaming={streaming}
          title={reasoningTitle}
          live={reasoningLiveLabel}
        />
      );
    case "tool":
      return <ToolNode node={node} />;
    case "status":
      return (
        <div className={`agent-timeline-node tone-${node.tone}`}>
          <span className="at-dot" />
          <span className="at-label">{node.label}</span>
        </div>
      );
    case "text":
      return (
        <div className="agent-timeline-text">
          <MarkdownContent content={node.text} />
        </div>
      );
  }
}

function ThinkingNode({
  text,
  streaming,
  title,
  live,
}: {
  text: string;
  streaming: boolean;
  title: string;
  live: string;
}) {
  const [open, setOpen] = useState(streaming);
  const wasLive = useRef(streaming);

  useEffect(() => {
    if (streaming) setOpen(true);
    else if (wasLive.current) setOpen(false);
    wasLive.current = streaming;
  }, [streaming]);

  return (
    <details
      className={`agent-timeline-think ${streaming ? "is-live" : ""}`}
      open={open}
      onToggle={(event) => setOpen((event.currentTarget as HTMLDetailsElement).open)}
    >
      <summary>
        <Brain size={12} />
        <span>{title}</span>
        {streaming && <small>{live}</small>}
      </summary>
      <div className="agent-timeline-think-body">{text}</div>
    </details>
  );
}

function ToolNode({ node }: { node: Extract<AgentTimelineNode, { kind: "tool" }> }) {
  const [open, setOpen] = useState(false);
  const detail = toolDetail(node.step);

  return (
    <div className={`agent-timeline-node tool ${node.phase}`}>
      {node.phase === "failed"
        ? <CircleAlert size={12} />
        : node.phase === "completed"
          ? <CircleCheck size={12} />
          : <LoaderCircle size={12} className="spin" />}
      <button className="at-line" type="button" onClick={() => setOpen((value) => !value)}>
        <span className="at-kind">{node.toolName}</span>
        <span className="at-label">{toolLabel(node.summary, node.toolName)}</span>
        {detail && <small>{open ? "hide" : "detail"}</small>}
      </button>
      {open && detail && <pre className="at-detail">{detail}</pre>}
    </div>
  );
}

function toolLabel(summary: string, toolName: string): string {
  const escaped = escapeRegExp(toolName);
  return summary.replace(new RegExp(`^${escaped}\\s*(?:·|→|-)?\\s*`), "") || summary;
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function toolDetail(step: AgentProcessStep): string | null {
  const lines: string[] = [];
  const labelArgs = (step.data as Record<string, unknown>).label_args;
  if (labelArgs && typeof labelArgs === "object") {
    for (const [key, value] of Object.entries(labelArgs as Record<string, unknown>)) {
      lines.push(`${key}: ${String(value)}`);
    }
  }
  if (step.message) lines.push(step.message);
  return lines.length > 0 ? lines.join("\n") : null;
}
