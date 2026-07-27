import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { BookOpen, Database, FileCheck2, FileSearch, Search, ShieldAlert, X } from "lucide-react";
import { getJson } from "../../lib/product-api";
import { useUiStore } from "../../stores/ui-store";
import type { SearchDocumentType, SearchResult } from "../../types";
import { useI18n } from "../../i18n";

const iconByType = {
  page: BookOpen,
  entity: FileSearch,
  source: Database,
  claim: FileCheck2,
  evidence: FileSearch,
  lint: ShieldAlert,
} satisfies Record<SearchDocumentType, typeof BookOpen>;

function HighlightedSnippet({ value }: { value: string }) {
  const parts = value.split(/(<mark>|<\/mark>)/i);
  let highlighted = false;
  return <small>{parts.map((part, index) => {
    if (/^<mark>$/i.test(part)) { highlighted = true; return null; }
    if (/^<\/mark>$/i.test(part)) { highlighted = false; return null; }
    return highlighted ? <mark key={index}>{part}</mark> : <span key={index}>{part}</span>;
  })}</small>;
}

export function CommandPalette({ onOpen }: { onOpen: (result: SearchResult) => void }) {
  const { t } = useI18n();
  const open = useUiStore((state) => state.commandPaletteOpen);
  const setOpen = useUiStore((state) => state.setCommandPaletteOpen);
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const searchPath = useMemo(() => `/api/search?q=${encodeURIComponent(query.trim())}&limit=40`, [query]);
  const results = useQuery({
    queryKey: ["global-search", query.trim()],
    queryFn: () => getJson<SearchResult[]>(searchPath),
    enabled: open && query.trim().length > 0,
    placeholderData: (previous) => previous,
  });

  useEffect(() => {
    if (!open) return;
    setActiveIndex(0);
    window.requestAnimationFrame(() => inputRef.current?.focus());
  }, [open]);

  if (!open) return null;
  const items = results.data ?? [];

  function choose(item: SearchResult) {
    onOpen(item);
    setOpen(false);
    setQuery("");
  }

  return (
    <div className="command-backdrop" role="presentation" onMouseDown={() => setOpen(false)}>
      <section className="command-palette" role="dialog" aria-modal="true" onMouseDown={(event) => event.stopPropagation()}>
        <div className="command-input">
          <Search size={17} />
          <input
            ref={inputRef}
            value={query}
            placeholder={t("search.palettePlaceholder")}
            onChange={(event) => { setQuery(event.target.value); setActiveIndex(0); }}
            onKeyDown={(event) => {
              if (event.key === "Escape") setOpen(false);
              if (event.key === "ArrowDown") {
                event.preventDefault();
                setActiveIndex((index) => Math.min(index + 1, items.length - 1));
              }
              if (event.key === "ArrowUp") {
                event.preventDefault();
                setActiveIndex((index) => Math.max(index - 1, 0));
              }
              if (event.key === "Enter" && items[activeIndex]) choose(items[activeIndex]);
            }}
          />
          <kbd>ESC</kbd>
          <button onClick={() => setOpen(false)} aria-label={t("common.close")}><X size={15} /></button>
        </div>
        <div className="command-results">
          {results.isLoading && <div className="command-state">{t("search.loading")}</div>}
          {results.isError && <div className="command-state error">{t("search.error")}</div>}
          {!results.isLoading && query.trim() && items.length === 0 && <div className="command-state">{t("search.empty")}</div>}
          {!query.trim() && <div className="command-state">{t("search.hint")}</div>}
          {items.map((item, index) => {
            const Icon = iconByType[item.type];
            return (
              <button
                key={item.document_id}
                className={index === activeIndex ? "command-result active" : "command-result"}
                onMouseEnter={() => setActiveIndex(index)}
                onClick={() => choose(item)}
              >
                <span className={`result-type ${item.type}`}><Icon size={15} /></span>
                <span>
                  <strong>{item.title}</strong>
                  <HighlightedSnippet value={item.snippet} />
                </span>
                <em>{item.type}</em>
              </button>
            );
          })}
        </div>
        <footer><span>{t("search.navigate")}</span><span>{t("search.open")}</span><span>{t("search.provenance")}</span></footer>
      </section>
    </div>
  );
}
