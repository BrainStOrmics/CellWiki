// ChangesetList —— 左侧栏的 ChangeSet 列表（rail 入口激活时替换 wiki 文件树）
import { useI18n, type AppLanguage } from "../i18n";
import type { ChangeSetReview } from "../types";

type ChangesetListProps = {
  reviews: ChangeSetReview[];
  selectedId: string | null;
  onSelect: (changeSetId: string) => void;
};

export function ChangesetList({ reviews, selectedId, onSelect }: ChangesetListProps) {
  const { language, t } = useI18n();
  return (
    <div className="changeset-panel">
      <div className="file-search"></div>
      <div className="changeset-list">
        {reviews.length === 0 && <div className="tree-empty">{t("changesets.empty")}</div>}
        {reviews.map((review) => {
          const changeSetId = review.change_set.change_set_id;
          const targetId = review.change_set.operations[0]?.target_id ?? "";
          return (
            <button
              className={changeSetId === selectedId ? "changeset-list-item selected" : "changeset-list-item"}
              key={changeSetId}
              data-change-set-id={changeSetId}
              onClick={() => onSelect(changeSetId)}
              title={`${changeSetId}\n${review.change_set.reason}`}
            >
              <span className={`review-state ${review.status}`}>{localizedStatus(review.status, language)}</span>
              <strong>{review.change_set.reason}</strong>
              <small>{targetId}</small>
              <em>{new Date(review.change_set.created_at).toLocaleDateString(language === "zh-CN" ? "zh-CN" : "en-US")}</em>
            </button>
          );
        })}
      </div>
      <div className="file-panel-footer">
        <span>{reviews.length} {t("changesets.count")}</span>
      </div>
    </div>
  );
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
