// SourceDetail —— 来源内容视图：元数据 + 原生文件预览（PDF 内嵌 / Markdown 渲染）
import { Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useI18n, type AppLanguage } from "../i18n";
import { apiUrl, productFetch } from "../runtime";
import { MarkdownReader } from "../features/wiki/MarkdownReader";
import type { Source } from "../types";

type SourceDetailProps = {
  source: Source;
  onDelete: () => void;
};

function isPdf(source: Source): boolean {
  return source.original_name.toLowerCase().endsWith(".pdf") || source.source_type.toLowerCase() === "pdf";
}

export function SourceDetail({ source, onDelete }: SourceDetailProps) {
  const { language, t } = useI18n();
  const [markdown, setMarkdown] = useState("");
  const [loadFailed, setLoadFailed] = useState(false);
  // productFetch 内部会再次调用 apiUrl，因此这里只保留相对路径
  const filePath = `/api/sources/${encodeURIComponent(source.source_id)}/file`;

  useEffect(() => {
    if (isPdf(source)) return;
    let disposed = false;
    setLoadFailed(false);
    void productFetch(filePath)
      .then((response) => (response.ok ? response.text() : Promise.reject(new Error(String(response.status)))))
      .then((text) => {
        if (!disposed) setMarkdown(text);
      })
      .catch(() => {
        if (!disposed) setLoadFailed(true);
      });
    return () => { disposed = true; };
  }, [source.source_id, filePath]);

  return (
    <article className="source-detail">
      <header className="source-review-header">
        <div>
          <div className="document-kicker">{t("source.registered").toUpperCase()} · {source.source_type.toUpperCase()}</div>
          <h1 className="source-review-title" title={source.original_name}>{source.original_name}</h1>
          <p>{source.source_id}</p>
        </div>
        <span className={`source-status ${source.status}`}>{localizedSourceStatus(source.status, language)}</span>
      </header>

      <section className="source-runtime-meta">
        <div><span>{t("source.parser")}</span><b>{source.parser_name ? `${source.parser_name} ${source.parser_version ?? ""}` : "—"}</b></div>
        <div><span>{t("source.pageCount")}</span><b>{String(source.metadata?.page_count ?? "—")}</b></div>
        <div><span>{t("source.contentHash")}</span><code>{source.content_hash.slice(0, 24)}</code></div>
        <div><span>{t("source.parseHash")}</span><code>{source.parse_hash?.slice(0, 24) ?? "—"}</code></div>
        {source.error_reason && <div className="source-error-reason"><span>{t("source.failureReason")}</span><b>{source.error_reason}</b></div>}
      </section>

      <div className="source-detail-actions">
        <button className="delete-action" data-testid="delete-source" onClick={onDelete}><Trash2 size={14} />{t("sources.delete")}</button>
      </div>

      <div className="source-viewer">
        {isPdf(source) ? (
          <iframe src={apiUrl(filePath)} title={source.original_name} />
        ) : loadFailed ? (
          <div className="feature-state error">{t("sources.previewFailed")}</div>
        ) : (
          <MarkdownReader markdown={markdown} />
        )}
      </div>
    </article>
  );
}

function localizedSourceStatus(value: string, language: AppLanguage) {
  if (language === "en") return value;
  return { ready: "待分析", analyzed: "已分析", failed: "失败" }[value] ?? value;
}
