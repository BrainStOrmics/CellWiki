import { BookOpenCheck, Bot } from "lucide-react";
import { MarkdownContent } from "../../components/MarkdownContent";
import { AgentProcessTrace } from "./AgentProcessTrace";
import type { ChatMessage, Citation } from "../../types";

type AgentMessageBubbleProps = {
  message: ChatMessage;
  agentLabel: string;
  userLabel: string;
  missingEvidenceLabel: string;
  processTitle: string;
  processLiveLabel: string;
  processCompletedLabel: string;
  processEmptyLabel: string;
  onCitationOpen: (citation: Citation) => void;
};

/** Render one durable chat message while keeping role layout and content semantics together. */
export function AgentMessageBubble({
  message,
  agentLabel,
  userLabel,
  missingEvidenceLabel,
  processTitle,
  processLiveLabel,
  processCompletedLabel,
  processEmptyLabel,
  onCitationOpen,
}: AgentMessageBubbleProps) {
  const isAgent = message.role === "agent";
  const process = message.process ?? [];

  return (
    <div className={`message ${message.role} ${message.streaming ? "is-streaming" : ""}`}>
      <div className="message-author">{isAgent ? <><Bot size={13} />{agentLabel}</> : userLabel}</div>
      <div className="message-bubble">
        {isAgent && process.length > 0 && (
          <AgentProcessTrace
            steps={process}
            live={Boolean(message.streaming)}
            title={processTitle}
            liveLabel={processLiveLabel}
            completedLabel={processCompletedLabel}
            emptyLabel={processEmptyLabel}
          />
        )}
        {isAgent ? <MarkdownContent content={message.text} /> : <p>{message.text}</p>}
      </div>
      {isAgent && message.citations && message.citations.length > 0 && (
        <div className="message-citations">
          {message.citations.map((citation, citationIndex) => (
            <button
              key={`${citation.page_id}-${citation.locator ?? "page"}-${citationIndex}`}
              onClick={() => onCitationOpen(citation)}
              title={citation.locator ?? `Open ${citation.page_id}`}
            >
              <BookOpenCheck size={12} />
              <span>{citation.page_id}</span>
              {citation.locator && <small>{citation.locator}</small>}
            </button>
          ))}
        </div>
      )}
      {message.missingEvidence && message.missingEvidence.length > 0 && (
        <div className="message-evidence-gap">
          <b>{missingEvidenceLabel}</b>
          {message.missingEvidence.map((gap, gapIndex) => <span key={`${gap}-${gapIndex}`}>{gap}</span>)}
        </div>
      )}
      {message.meta && <small className="message-meta">{message.meta}</small>}
    </div>
  );
}
