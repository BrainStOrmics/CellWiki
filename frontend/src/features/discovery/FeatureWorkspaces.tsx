import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  BookMarked,
  Search,
} from "lucide-react";
import { getJson } from "../../lib/product-api";
import type { ChangeSetReview, SearchResult } from "../../types";
import { useI18n } from "../../i18n";

type OpenResult = (result: SearchResult) => void;

export function ReviewsWorkspace({
  reviews,
  onOpen,
}: {
  reviews: ChangeSetReview[];
  onOpen: (review: ChangeSetReview) => void;
}) {
  const { t } = useI18n();
  return (
    <div className="feature-workspace">
      <header className="feature-header"><div><BookMarked size={17} /><span><strong>{t("reviews.title")}</strong><small>{t("reviews.subtitle")}</small></span></div></header>
      <div className="feature-list">
        {reviews.length === 0 && <div className="feature-state">{t("reviews.empty")}</div>}
        {reviews.map((review) => (
          <button className="review-list-card" key={review.change_set.change_set_id} onClick={() => onOpen(review)}>
            <span className={`review-risk ${review.change_set.risk}`}>{review.change_set.risk}</span>
            <span>
              <strong>{review.change_set.reason}</strong>
              <small>{review.change_set.operations.length} {t("common.operations")} · {review.change_set.evidence.length} {t("common.evidenceLocators")}</small>
            </span>
            <em>{review.status.replaceAll("_", " ")}</em>
          </button>
        ))}
      </div>
    </div>
  );
}

export function SearchWorkspace({ onOpen }: { onOpen: OpenResult }) {
  const { t } = useI18n();
  const [query, setQuery] = useState("");
  const results = useQuery({
    queryKey: ["search-workspace", query.trim()],
    queryFn: () => getJson<SearchResult[]>(`/api/search?q=${encodeURIComponent(query.trim())}&limit=80`),
    enabled: query.trim().length > 0,
  });
  return (
    <div className="feature-workspace">
      <header className="feature-header"><div><Search size={17} /><span><strong>{t("search.title")}</strong><small>{t("search.subtitle")}</small></span></div></header>
      <label className="feature-search"><Search size={15} /><input value={query} onChange={(event) => setQuery(event.target.value)} autoFocus placeholder={t("search.placeholder")} /></label>
      <div className="feature-list">
        {results.isFetching && <div className="feature-state">{t("search.loading")}</div>}
        {results.isError && <div className="feature-state error">{t("search.error")}</div>}
        {!results.isFetching && query && results.data?.length === 0 && <div className="feature-state">{t("search.empty")}</div>}
        {results.data?.map((item) => (
          <button className="feature-result" key={item.document_id} onClick={() => onOpen(item)}>
            <span className={`result-type ${item.type}`}>{item.type}</span>
            <span><strong>{item.title}</strong><small>{item.snippet.replaceAll("<mark>", "").replaceAll("</mark>", "")}</small></span>
            <em>{item.locator || item.page_id || item.source_id}</em>
          </button>
        ))}
      </div>
    </div>
  );
}
