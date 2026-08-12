import { BookOpenCheck, Bot, Paperclip } from "lucide-react";
import { MarkdownContent } from "../../components/MarkdownContent";
import { AgentProcessTrace } from "./AgentProcessTrace";
import { AgentRunDiagnostics } from "./AgentRunDiagnostics";
import type { ChatMessage, Citation } from "../../types";

type AgentMessageBubbleProps = {
  message: ChatMessage;
  agentLabel: string;
  userLabel: string;
  missingEvidenceLabel: string;
  processTitle: string;
  processLiveLabel: string;
  processCompletedLabel: string;
  processFailedLabel: string;
  processCancelledLabel: string;
  processEmptyLabel: string;
  diagnosticsLabel: string;
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
  processFailedLabel,
  processCancelledLabel,
  processEmptyLabel,
  diagnosticsLabel,
  onCitationOpen,
}: AgentMessageBubbleProps) {
  const isAgent = message.role === "agent";
  const process = message.process ?? [];

  return (
    <div className={`message ${message.role} ${message.streaming ? "is-streaming" : ""}`}>
      <div className="message-author">{isAgent ? <><Bot size={13} />{agentLabel}</> : userLabel}</div>
      {!isAgent && message.attachments && message.attachments.length > 0 && (
        <div className="message-attachments">
          {message.attachments.map((attachment) => (
            <span className="message-attachment" key={attachment.attachment_id} title={attachment.attachment_id}>
              <Paperclip size={12} />
              <span>{attachment.original_name ?? attachment.attachment_id}</span>
            </span>
          ))}
        </div>
      )}
      <div className="message-bubble">
        {isAgent && process.length > 0 && (
          <AgentProcessTrace
            steps={process}
            live={Boolean(message.streaming)}
            title={processTitle}
            liveLabel={processLiveLabel}
            completedLabel={processCompletedLabel}
            failedLabel={processFailedLabel}
            cancelledLabel={processCancelledLabel}
            terminalStatus={message.runStatus}
            emptyLabel={processEmptyLabel}
          />
        )}
        {isAgent ? <MarkdownContent content={message.text} /> : <p>{message.text}</p>}
      </div>
      {isAgent && message.citations && message.citations.length > 0 && (
        <div className="message-citations">
          {message.citations.map((citation, citationIndex) => {
            const locator = citation.section_locator ?? citation.locator;
            if (citation.attachment_id) {
              return (
                <span
                  className="message-citation"
                  key={`${citation.attachment_id}-${locator ?? "attachment"}-${citationIndex}`}
                  title={locator ?? citation.original_name ?? citation.attachment_id}
                >
                  <BookOpenCheck size={12} />
                  <span>{citation.original_name ?? citation.attachment_id}</span>
                  {locator && <small>{locator}</small>}
                </span>
              );
            }
            if (!citation.page_id) return null;
            return (
              <button
                className="message-citation"
                key={`${citation.page_id}-${locator ?? "page"}-${citationIndex}`}
                onClick={() => onCitationOpen(citation)}
                title={locator ?? `Open ${citation.page_id}`}
              >
                <BookOpenCheck size={12} />
                <span>{citation.page_id}</span>
                {locator && <small>{locator}</small>}
              </button>
            );
          })}
        </div>
      )}
      {message.missingEvidence && message.missingEvidence.length > 0 && (
        <div className="message-evidence-gap">
          <b>{missingEvidenceLabel}</b>
          {message.missingEvidence.map((gap, gapIndex) => <span key={`${gap}-${gapIndex}`}>{gap}</span>)}
        </div>
      )}
      {message.validationIssues && message.validationIssues.length > 0 && (
        <div className="message-evidence-gap">
          <b>{missingEvidenceLabel}</b>
          {message.validationIssues.map((issue, issueIndex) => (
            <span key={`${issue.code}-${issueIndex}`}>{issue.message}</span>
          ))}
        </div>
      )}
      {message.meta && <small className="message-meta">{message.meta}</small>}
      {isAgent && message.runId && !message.streaming && (
        <AgentRunDiagnostics runId={message.runId} label={diagnosticsLabel} />
      )}
    </div>
  );
}
