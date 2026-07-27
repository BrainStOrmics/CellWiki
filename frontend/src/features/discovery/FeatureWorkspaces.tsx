import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArchiveX,
  BookMarked,
  BrainCircuit,
  DatabaseZap,
  ExternalLink,
  FlaskConical,
  Search,
  ShieldAlert,
} from "lucide-react";
import { deleteJson, getJson, postJson } from "../../lib/product-api";
import type { ChangeSetReview, MemoryRecord, ResearchCandidate, SearchResult } from "../../types";
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

type L2Finding = {
  finding_id: string;
  severity: "error" | "warning" | "info";
  category: string;
  target_id: string;
  locator: string;
  message: string;
  evidence: Array<{
    supporting_claims?: Array<{ claim_id?: string; source_ids?: string[] }>;
    counterexamples?: Array<{ claim_id?: string; source_ids?: string[] }>;
    uncertainty?: string;
  }>;
};

export function LintWorkspace() {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const findings = useQuery({ queryKey: ["lint-l2"], queryFn: () => getJson<L2Finding[]>("/api/lint/l2") });
  const createReviews = useMutation({
    mutationFn: () => postJson("/api/lint/l2/review", {}),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["lint-l2"] }),
  });
  return (
    <div className="feature-workspace">
      <header className="feature-header">
        <div><ShieldAlert size={17} /><span><strong>{t("lint.title")}</strong><small>{t("lint.subtitle")}</small></span></div>
        <button disabled={createReviews.isPending} onClick={() => createReviews.mutate()}><BookMarked size={14} />{t("lint.createReviews")}</button>
      </header>
      <div className="feature-list">
        {findings.isLoading && <div className="feature-state">{t("lint.loading")}</div>}
        {findings.data?.length === 0 && <div className="feature-state">{t("lint.empty")}</div>}
        {findings.data?.map((item) => (
          <article className={`semantic-card ${item.severity}`} key={item.finding_id}>
            <div><span>{item.category.replaceAll("_", " ")}</span><code>{item.finding_id}</code></div>
            <h3>{item.message}</h3>
            <p>{item.evidence[0]?.uncertainty}</p>
            <footer>
              <span>{item.target_id}</span>
              <span>{item.evidence[0]?.supporting_claims?.length ?? 0} {t("common.supporting")}</span>
              <span>{item.evidence[0]?.counterexamples?.length ?? 0} {t("common.counterexamples")}</span>
            </footer>
          </article>
        ))}
      </div>
    </div>
  );
}

export function MemoryWorkspace() {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const memories = useQuery({
    queryKey: ["memories"],
    queryFn: () => getJson<MemoryRecord[]>("/api/memories?project_id=cellwiki&include_inactive=true"),
  });
  const remove = useMutation({
    mutationFn: (id: string) => deleteJson(`/api/memories/${encodeURIComponent(id)}?project_id=cellwiki`),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["memories"] }),
  });
  const resolve = useMutation({
    mutationFn: ({ id, activate }: { id: string; activate: boolean }) => postJson(
      `/api/memories/${encodeURIComponent(id)}/resolve?project_id=cellwiki`,
      { activate },
    ),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["memories"] }),
  });
  return (
    <div className="feature-workspace">
      <header className="feature-header"><div><BrainCircuit size={17} /><span><strong>{t("memory.title")}</strong><small>{t("memory.subtitle")}</small></span></div></header>
      <div className="memory-policy"><DatabaseZap size={15} /><span>{t("memory.policy")}</span></div>
      <div className="feature-list">
        {memories.isLoading && <div className="feature-state">{t("memory.loading")}</div>}
        {memories.data?.length === 0 && <div className="feature-state">{t("memory.empty")}</div>}
        {memories.data?.map((item) => (
          <article className={`memory-card ${item.status}`} key={item.memory_id}>
            <div><span>{item.kind}</span><em>{item.status}</em></div>
            <p>{item.content}</p>
            <footer>
              <code>{item.key || item.memory_id}</code>
              <span>{Math.round(item.confidence * 100)}% {t("common.confidence")}</span>
              {item.status === "conflict" && <>
                <button onClick={() => resolve.mutate({ id: item.memory_id, activate: true })}>{t("memory.admit")}</button>
                <button onClick={() => resolve.mutate({ id: item.memory_id, activate: false })}>{t("common.reject")}</button>
              </>}
              {item.status === "active" && <button onClick={() => remove.mutate(item.memory_id)}><ArchiveX size={12} />{t("common.delete")}</button>}
            </footer>
          </article>
        ))}
      </div>
    </div>
  );
}

export function ResearchWorkspace({ onOpenSource }: { onOpenSource: (sourceId: string) => void }) {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [query, setQuery] = useState("");
  const candidates = useQuery({
    queryKey: ["research-candidates"],
    queryFn: () => getJson<ResearchCandidate[]>("/api/research/candidates"),
  });
  const research = useMutation({
    mutationFn: () => postJson<ResearchCandidate[]>("/api/research/search", { query, project_id: "cellwiki", limit: 5 }),
    onSuccess: () => {
      setQuery("");
      void queryClient.invalidateQueries({ queryKey: ["research-candidates"] });
    },
  });
  return (
    <div className="feature-workspace">
      <header className="feature-header"><div><FlaskConical size={17} /><span><strong>{t("research.title")}</strong><small>{t("research.subtitle")}</small></span></div></header>
      <form className="feature-search" onSubmit={(event) => { event.preventDefault(); if (query.trim()) research.mutate(); }}>
        <Search size={15} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t("research.placeholder")} />
        <button disabled={!query.trim() || research.isPending}>{t("research.action")}</button>
      </form>
      {research.isError && <div className="feature-state error">{t("research.error")}</div>}
      <div className="feature-list">
        {candidates.data?.length === 0 && <div className="feature-state">{t("research.empty")}</div>}
        {candidates.data?.map((item) => (
          <article className="research-card" key={item.candidate_id}>
            <div><span>{item.status.replaceAll("_", " ")}</span><code>{item.source_id}</code></div>
            <h3>{item.title}</h3>
            <p>{item.query}</p>
            <div className="warning-chips">{item.warnings.map((warning) => <span key={warning}>{warning.replaceAll("_", " ")}</span>)}</div>
            <footer>
              <button onClick={() => onOpenSource(item.source_id)}>{t("research.openSource")}</button>
              <a href={item.url} target="_blank" rel="noreferrer">{t("research.publisher")}<ExternalLink size={12} /></a>
            </footer>
          </article>
        ))}
      </div>
    </div>
  );
}
