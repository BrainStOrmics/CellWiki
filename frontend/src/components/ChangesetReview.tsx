// ChangesetReview —— 独立的 ChangeSet 审查详情（从 SourceReview 中解耦抽出）
import {
  AlertTriangle,
  Check,
  CheckCircle2,
  Dna,
  ExternalLink,
  FileSearch,
  GitCompareArrows,
  ListChecks,
  LoaderCircle,
  Quote,
  RotateCcw,
  ShieldCheck,
  ShieldX,
  Trash2,
} from "lucide-react";
import { useState } from "react";
import { useI18n, type AppLanguage } from "../i18n";
import { apiUrl } from "../runtime";
import type { ChangeSetReview, IngestWorkflow, QualityReport, TaskEvent } from "../types";

type ChangesetReviewProps = {
  review: ChangeSetReview;
  workflow: IngestWorkflow;
  quality?: QualityReport;
  taskEvents: TaskEvent[];
  onApprove: () => void;
  onReject: () => void;
  onRollback: () => void;
  onDelete: () => void;
  onRequestRevision?: (comment: string) => void;
};

export function ChangesetReview({
  review,
  workflow,
  quality,
  taskEvents,
  onApprove,
  onReject,
  onRollback,
  onDelete,
  onRequestRevision,
}: ChangesetReviewProps) {
  const { language, t } = useI18n();
  const [revisionComment, setRevisionComment] = useState("");
  const isBusy = workflow.phase === "preparing" || workflow.phase === "cancelling" || workflow.phase === "committing";
  const canDecide = review.status === "awaiting_review" && !isBusy;
  const canRequestRevision = canDecide && Boolean(onRequestRevision);
  const canRollback = review.status === "committed" && !isBusy;
  // 删除只对已终止/已决策的提案开放；等待审核的须先拒绝，committed 须先回滚
  const canDelete = (review.status === "approved" || review.status === "rejected" || review.status === "rolled_back") && !isBusy;

  return (
    <article className="changeset-review">
      <section className={`workflow-banner ${workflow.phase}`}>
        {isBusy ? <LoaderCircle className="spin" size={17} /> : workflowIcon(workflow.phase)}
        <div className="workflow-copy"><strong>{workflowTitle(workflow.phase, t)}</strong><span>{workflow.error ?? workflow.message}</span></div>
      </section>

      {taskEvents.length > 0 && <TaskTimeline events={taskEvents} />}

      <section className="changeset-card">
        <div className="changeset-heading">
          <div><span>{t("source.changeSet")}</span><h2>{review.change_set.change_set_id}</h2><p>{review.change_set.reason}</p></div>
          <span className={`risk-badge ${review.change_set.risk}`}>{localizedRisk(review.change_set.risk, language)}</span>
        </div>

        <div className="changeset-summary">
          <span><GitCompareArrows size={14} /><b>{review.change_set.operations.length}</b> {t("source.operations")}</span>
          <span><Dna size={14} /><b>{review.preview.operations.reduce((total, operation) => total + operation.entity_count, 0)}</b> {t("source.cellTypes")}</span>
          <span><ShieldCheck size={14} /><b>{review.change_set.evidence.length}</b> {t("source.evidence")}</span>
        </div>

        <div className="operation-list">
          {review.preview.operations.map((operation) => (
            <div className="operation-card" key={`${operation.type}-${operation.target_id}`}>
              <div className="operation-title"><span>{localizedOperation(operation.type, language)}</span><b>{operation.target_id}</b></div>
              {operation.entities.length > 0 ? (
                <div className="entity-preview-table">
                  <div className="entity-preview-row header"><span>{t("source.entity")}</span><span>{t("source.standardName")}</span><span>{t("source.markers")}</span></div>
                  {operation.entities.slice(0, 12).map((entity, index) => (
                    <div className="entity-preview-row" key={`${entity.standard_name ?? entity.name}-${index}`}>
                      <span>{entity.name}</span><span>{entity.standard_name ?? t("source.unresolved")}</span><span>{entity.marker_count}</span>
                    </div>
                  ))}
                  {operation.entities.length > 12 && <div className="entity-overflow">+ {operation.entities.length - 12} {t("source.moreEntities")}</div>}
                </div>
              ) : (
                <div className="operation-empty">{t("source.emptyOperation")}</div>
              )}
              <div className="field-diff-block">
                <div className="field-diff-heading">
                  <span>{t("source.diffTitle")}</span>
                  <small>
                    +{operation.field_diffs.filter((item) => item.change_type === "added").length}
                    &nbsp; −{operation.field_diffs.filter((item) => item.change_type === "removed").length}
                    &nbsp; ~{operation.field_diffs.filter((item) => item.change_type === "changed").length}
                  </small>
                </div>
                <div className="field-diff-list">
                  {operation.field_diffs.slice(0, 80).map((difference, index) => (
                    <div className={`field-diff-row ${difference.change_type}`} key={`${difference.path}-${index}`}>
                      <span>{difference.change_type === "added" ? "+" : difference.change_type === "removed" ? "−" : "~"}</span>
                      <code>{difference.path}</code>
                      <div>
                        {difference.change_type !== "added" && <small><b>{t("source.before")}</b>{formatDiffValue(difference.before)}</small>}
                        {difference.change_type !== "removed" && <small><b>{t("source.after")}</b>{formatDiffValue(difference.after)}</small>}
                      </div>
                    </div>
                  ))}
                  {operation.diff_truncated && <div className="entity-overflow">500+ differences</div>}
                </div>
              </div>
            </div>
          ))}
        </div>

        {review.change_set.review_items.length > 0 && (
          <section className="review-findings">
            <div className="review-section-label"><AlertTriangle size={14} />{t("source.reviewItems")}</div>
            {review.change_set.review_items.map((item) => (
              <div className={`review-finding ${item.severity}`} key={item.review_item_id}>
                <span>{localizedRisk(item.severity, language)}</span>
                <div><b>{item.target_id}</b><p>{item.description}</p></div>
              </div>
            ))}
          </section>
        )}

        {review.change_set.evidence.length > 0 && (
          <section className="evidence-locators">
            <div className="review-section-label"><Quote size={14} />{t("source.evidenceTitle")}</div>
            <div className="evidence-grid">
              {review.change_set.evidence.slice(0, 24).map((evidence, index) => (
                <a
                  href={`${apiUrl(`/api/sources/${encodeURIComponent(evidence.source_id)}/file`)}${evidence.page_start ? `#page=${evidence.page_start}` : ""}`}
                  target="_blank"
                  rel="noreferrer"
                  key={evidence.evidence_id ?? `${evidence.locator}-${index}`}
                  title={evidence.block_id ?? evidence.locator}
                >
                  <span>{evidence.locator}<ExternalLink size={10} /></span>
                  <p>{evidence.excerpt}</p>
                  <small>{evidence.evidence_type ?? "supporting"} · {evidence.confidence ?? "medium"}</small>
                </a>
              ))}
            </div>
          </section>
        )}

        {review.change_set.evidence.length === 0 && (
          <div className="review-warning"><AlertTriangle size={15} /><span>{t("source.noEvidence")}</span></div>
        )}

        {canRequestRevision && (
          <section className="revision-request">
            <label htmlFor="revision-comment">{t("source.revisionComment")}</label>
            <textarea
              id="revision-comment"
              data-testid="revision-comment"
              value={revisionComment}
              onChange={(event) => setRevisionComment(event.target.value)}
              placeholder={t("source.revisionCommentPlaceholder")}
              maxLength={4000}
              rows={3}
            />
            <button
              className="revision-action"
              data-testid="request-revision"
              disabled={!revisionComment.trim()}
              onClick={() => {
                const comment = revisionComment.trim();
                if (!comment) return;
                onRequestRevision?.(comment);
                setRevisionComment("");
              }}
            >
              <RotateCcw size={14} />{t("source.requestRevision")}
            </button>
          </section>
        )}

        <footer className="review-actions">
          <div>
            <span className={`review-state ${review.status}`}>{localizedStatus(review.status, language)}</span>
            {review.commit && <small>{review.commit.snapshot_id}</small>}
          </div>
          <div className="decision-buttons">
            {canRollback && <button className="rollback-action" onClick={onRollback}><RotateCcw size={15} />{t("source.rollback")}</button>}
            {canDelete && <button className="delete-action" data-testid="delete-changeset" onClick={onDelete}><Trash2 size={15} />{t("changesets.delete")}</button>}
            <button className="reject-action" onClick={onReject} disabled={!canDecide}><ShieldX size={15} />{t("source.reject")}</button>
            <button className="approve-action" onClick={onApprove} disabled={!canDecide}><ShieldCheck size={15} />{t("source.approve")}</button>
          </div>
        </footer>
      </section>

      {(review.status === "committed" || review.status === "rolled_back") && quality && <QualityDetails quality={quality} />}
    </article>
  );
}

function TaskTimeline({ events }: { events: TaskEvent[] }) {
  const { language, t } = useI18n();
  const latest = events.at(-1)!;
  const chunkIndex = numericDetail(latest.detail, "chunk_index");
  const chunkCount = numericDetail(latest.detail, "chunk_count");
  const attempt = numericDetail(latest.detail, "attempt");
  const maxAttempts = numericDetail(latest.detail, "max_attempts");
  const elapsed = numericDetail(latest.detail, "elapsed_seconds");
  const remaining = numericDetail(latest.detail, "estimated_remaining_seconds");
  return (
    <section className="task-timeline">
      <div className="task-timeline-heading">
        <div><span>{t("source.timeline").toUpperCase()}</span><strong>{latest.run_id}</strong></div>
        <b>{latest.progress}%</b>
      </div>
      <div className="task-progress"><i style={{ width: `${latest.progress}%` }} /></div>
      <div className="task-metrics" aria-label={t("source.progressDetails")}>
        {chunkIndex !== null && chunkCount !== null && (
          <span>{formatTemplate(t("source.chunkProgress"), { current: chunkIndex, total: chunkCount })}</span>
        )}
        {attempt !== null && maxAttempts !== null && (
          <span>{formatTemplate(t("source.attemptProgress"), { current: attempt, total: maxAttempts })}</span>
        )}
        {elapsed !== null && <span>{t("source.elapsed")} {formatDuration(elapsed, language)}</span>}
        {remaining !== null && <span>{t("source.remaining")} {formatDuration(remaining, language)}</span>}
      </div>
      <div className="task-events">
        {events.map((event, index) => (
          <div className={`task-event ${event.status}`} key={event.event_id}>
            <span className="task-event-node">{index + 1}</span>
            <div><b>{localizedStage(event.stage, language)}</b><p>{localizedEventMessage(event.message, language)}</p></div>
            <time>{new Date(event.created_at).toLocaleTimeString(language === "zh-CN" ? "zh-CN" : "en-US", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</time>
          </div>
        ))}
      </div>
    </section>
  );
}

function QualityDetails({ quality }: { quality: QualityReport }) {
  const { language, t } = useI18n();
  return (
    <section className={`quality-report ${quality.status}`}>
      <div className="quality-report-heading">
        {quality.status === "passed" ? <CheckCircle2 size={17} /> : <AlertTriangle size={17} />}
        <div>
          <strong>{t("quality.title")} · {localizedQualityStatus(quality.status, language)}</strong>
          <span>{quality.page_count} {t("quality.pages")} · {quality.error_count} {t("quality.errors")} · {quality.warning_count} {t("quality.warnings")}</span>
        </div>
      </div>
      <div className="quality-levels">
        {(["L0", "L1", "L2"] as const).map((level) => (
          <div className={`quality-level ${quality.levels[level].status}`} key={level} title={quality.levels[level].description}>
            <b>{level}</b>
            <span>{localizedQualityStatus(quality.levels[level].status, language)}</span>
            <small>{quality.levels[level].issue_count} {t("quality.issues")}</small>
          </div>
        ))}
      </div>
      {quality.issues.length > 0 && (
        <div className="quality-issues">
          <div className="quality-issues-title"><ListChecks size={14} /><span>{t("quality.issues")}</span></div>
          {quality.issues.map((issue, index) => (
            <div className={`quality-issue ${issue.severity}`} key={`${issue.page_id}-${issue.type}-${index}`}>
              <span className="quality-issue-level">{issue.level}</span>
              <div><b>{issue.page_id}</b><p>{issue.detail}</p><small>{issue.category} · {issue.locator}{issue.auto_fixable ? ` · ${t("quality.autoFixable")}` : ""}</small></div>
              {issue.auto_fixable && <small>{t("quality.autoFixable")}</small>}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function workflowTitle(phase: IngestWorkflow["phase"], t: ReturnType<typeof useI18n>["t"]) {
  return {
    idle: t("source.readyTitle"),
    preparing: t("source.preparingTitle"),
    cancelling: t("source.cancellingTitle"),
    cancelled: t("source.cancelledTitle"),
    awaiting_review: t("source.reviewTitle"),
    committing: t("source.committingTitle"),
    committed: t("source.committedTitle"),
    rolled_back: t("source.rolledBackTitle"),
    rejected: t("source.rejectedTitle"),
    failed: t("source.failedTitle"),
  }[phase];
}

function localizedRisk(value: string, language: AppLanguage) {
  if (language === "en") return { low: "Low", medium: "Medium", high: "High" }[value] ?? value;
  return { low: "低风险", medium: "中风险", high: "高风险" }[value] ?? value;
}

function localizedOperation(value: string, language: AppLanguage) {
  if (language === "en") {
    return {
      upsert_cell_type: "Upsert cell type",
      upsert_extraction: "Upsert extraction",
      update_curation: "Update curation",
      apply_lint_fix: "Apply lint repair",
      update_domain: "Update domain",
      update_page: "Update page",
    }[value] ?? value;
  }
  return {
    upsert_cell_type: "写入细胞类型",
    upsert_extraction: "更新结构化提取",
    update_curation: "更新人工整理",
    apply_lint_fix: "应用 Lint 修复",
    update_domain: "更新领域",
    update_page: "更新页面",
  }[value] ?? value;
}

function localizedStatus(value: string, language: AppLanguage) {
  if (language === "en") {
    return {
      awaiting_review: "Awaiting review",
      approved: "Approved",
      rejected: "Rejected",
      committed: "Committed",
      rolled_back: "Rolled back",
    }[value] ?? value;
  }
  return {
    awaiting_review: "等待审核",
    approved: "已批准",
    rejected: "已拒绝",
    committed: "已提交",
    rolled_back: "已回滚",
  }[value] ?? value;
}

function localizedStage(value: string, language: AppLanguage) {
  if (language === "en") return value;
  return {
    source_read: "读取来源",
    parsing: "解析来源",
    chunking: "文档分块",
    entity_extraction: "提取实体",
    conflict_analysis: "冲突分析",
    extraction: "提取实体",
    validation: "校验结果",
    changeset: "生成变更集",
    commit: "提交变更",
  }[value] ?? value;
}

function localizedQualityStatus(value: string, language: AppLanguage) {
  if (language === "en") {
    return {
      passed: "Passed",
      passed_with_warnings: "Passed with warnings",
      warning: "Warning",
      failed: "Failed",
      not_run: "Not run",
    }[value] ?? value;
  }
  return {
    passed: "通过",
    passed_with_warnings: "通过（有警告）",
    warning: "警告",
    failed: "失败",
    not_run: "未运行",
  }[value] ?? value;
}

function localizedEventMessage(value: string, language: AppLanguage) {
  if (language === "en") return value;
  return {
    "Loading the registered source.": "正在加载已注册来源。",
    "Parsing the source with page locators.": "正在解析来源并保留页码定位。",
    "Merging duplicate entities and detecting conflicts.": "正在合并重复实体并检测冲突。",
    "Validating claim-level evidence against parsed source blocks.": "正在根据来源文本块验证声明级证据。",
    "Extracting normalized text from the source.": "正在从来源中提取标准化文本。",
    "Extracting cell types, markers, and evidence.": "正在提取细胞类型、标记基因和证据。",
    "Assembling the immutable ChangeSet proposal.": "正在组装不可变的变更集提案。",
    "ChangeSet is ready for human review.": "变更集已准备好，等待人工审核。",
    "Ingest analysis failed.": "来源分析失败。",
    "Publishing the approved ChangeSet.": "正在发布已批准的变更集。",
    "Projection lint completed.": "投影检查已完成。",
    "ChangeSet was published and verified.": "变更集已发布并完成验证。",
    "Publish failed; CentralWriter rolled back the projection.": "发布失败，CentralWriter 已回滚投影。",
    "ChangeSet was rejected; formal Wiki data was not changed.": "变更集已拒绝，正式 Wiki 数据未发生变化。",
  }[value] ?? value;
}

function workflowIcon(phase: IngestWorkflow["phase"]) {
  if (phase === "committed" || phase === "rolled_back") return <CheckCircle2 size={17} />;
  if (phase === "rejected" || phase === "failed" || phase === "cancelled") return <AlertTriangle size={17} />;
  return <FileSearch size={17} />;
}

function numericDetail(detail: Record<string, unknown>, key: string): number | null {
  const value = detail[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function formatTemplate(template: string, values: Record<string, number>) {
  return Object.entries(values).reduce(
    (result, [key, value]) => result.replace(`{${key}}`, String(value)),
    template,
  );
}

function formatDuration(seconds: number, language: AppLanguage) {
  const totalSeconds = Math.max(0, Math.round(seconds));
  const minutes = Math.floor(totalSeconds / 60);
  const remainingSeconds = totalSeconds % 60;
  if (language === "en") return `${minutes}m ${String(remainingSeconds).padStart(2, "0")}s`;
  return `${minutes}分${String(remainingSeconds).padStart(2, "0")}秒`;
}

function formatDiffValue(value: unknown) {
  const rendered = typeof value === "string" ? value : JSON.stringify(value);
  if (rendered === undefined) return "—";
  return rendered.length > 180 ? `${rendered.slice(0, 177)}…` : rendered;
}

