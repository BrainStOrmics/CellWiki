import { RotateCcw, ShieldCheck, ShieldX } from "lucide-react";
import { useState } from "react";
import { useI18n } from "../../i18n";

export type AgentReviewSummary = {
  reason: string;
  risk: string;
  operationCount: number;
  evidenceCount: number;
};

type AgentReviewCardProps = {
  changeSetId: string;
  summary?: AgentReviewSummary;
  allowRevision?: boolean;
  disabled?: boolean;
  onApprove: () => void;
  onReject: () => void;
  onRequestRevision: (comment: string) => void;
};

export function AgentReviewCard({
  changeSetId,
  summary,
  allowRevision = true,
  disabled = false,
  onApprove,
  onReject,
  onRequestRevision,
}: AgentReviewCardProps) {
  const { t } = useI18n();
  const [comment, setComment] = useState("");

  function submitRevision() {
    const value = comment.trim();
    if (!value || disabled) return;
    onRequestRevision(value);
    setComment("");
  }

  return (
    <section className="agent-review-card" data-testid="assistant-review-card">
      <span>{t("chat.humanReviewMeta")}</span>
      <strong>{changeSetId}</strong>
      {summary && (
        <>
          <p className="agent-review-summary">{summary.reason}</p>
          <div className="agent-review-metrics">
            <span>{summary.operationCount} {t("common.operations")}</span>
            <span>{summary.evidenceCount} {t("common.evidenceLocators")}</span>
            <span>{summary.risk}</span>
          </div>
        </>
      )}
      <small>{t("agent.formalUnchanged")}</small>
      {allowRevision && <>
        <label className="agent-review-comment-label" htmlFor="assistant-review-comment">
          {t("source.revisionComment")}
        </label>
        <textarea
          id="assistant-review-comment"
          data-testid="assistant-review-comment"
          value={comment}
          onChange={(event) => setComment(event.target.value)}
          placeholder={t("source.revisionCommentPlaceholder")}
          maxLength={4000}
          rows={3}
          disabled={disabled}
        />
      </>}
      <div className="agent-review-actions">
        {allowRevision && <button
            data-testid="assistant-request-revision"
            onClick={submitRevision}
            disabled={disabled || !comment.trim()}
          >
            <RotateCcw size={12} />{t("source.requestRevision")}
          </button>}
        <button onClick={onReject} disabled={disabled}>
          <ShieldX size={12} />{t("common.reject")}
        </button>
        <button onClick={onApprove} disabled={disabled}>
          <ShieldCheck size={12} />{t("chat.approveIngest")}
        </button>
      </div>
    </section>
  );
}
