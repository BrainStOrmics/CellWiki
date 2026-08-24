import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { getJson } from "../../lib/product-api";
import type { SearchResult } from "../../types";
import { useI18n } from "../../i18n";

type OpenResult = (result: SearchResult) => void;

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
