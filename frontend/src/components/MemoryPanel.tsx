import { useEffect, useState } from "react";
import { LoaderCircle, Pencil, RefreshCcw, Trash2, XCircle } from "lucide-react";

import { useI18n } from "../i18n";
import { deleteJson, getJson, postJson, putJson } from "../lib/product-api";

type MemoryPanelView = {
  file_name: string;
  read_only: boolean;
  exists: boolean;
  updated_at: string | null;
  content?: string;
};

type MemoryPanelEntry = {
  memory_id: string;
  kind: string;
  topic_family: string;
  title: string;
  file_name: string;
  user_edited: boolean;
  auto_update: boolean;
  origin_thread_id?: string;
  origin_run_id?: string;
  source_refs?: string[];
  updated_at: string;
  body?: string;
};

type EntryDraft = {
  memory_id: string;
  body: string;
  reenableAutoUpdate: boolean;
};

const TOPIC_FAMILIES = [
  "wiki 内容维护",
  "raw 与来源",
  "prompt 与上下文",
  "run 与审批",
  "评估与测试",
  "工作区与环境",
];

export function MemoryPanel() {
  const { t } = useI18n();
  const [views, setViews] = useState<MemoryPanelView[]>([]);
  const [entries, setEntries] = useState<MemoryPanelEntry[]>([]);
  const [selectedView, setSelectedView] = useState<MemoryPanelView>();
  const [selectedEntry, setSelectedEntry] = useState<MemoryPanelEntry>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<EntryDraft>();
  const [consolidating, setConsolidating] = useState(false);
  const [source, setSource] = useState("");

  async function load() {
    setLoading(true);
    try {
      const payload = await getJson<{
        entries: MemoryPanelEntry[];
        views: MemoryPanelView[];
      }>("/api/memory");
      setViews(payload.views ?? []);
      setEntries(payload.entries);
      setError("");
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : t("memory.loadError"));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    // 面板打开时加载一次；条目变化由本面板的显式动作触发重新加载。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function openView(view: MemoryPanelView) {
    if (!view.exists) return;
    try {
      const detail = await getJson<MemoryPanelView>(
        `/api/memory/views/${encodeURIComponent(view.file_name)}`,
      );
      setSelectedView(detail);
      setSelectedEntry(undefined);
      setEditing(undefined);
      setError("");
    } catch (readError) {
      setError(readError instanceof Error ? readError.message : t("memory.readError"));
    }
  }

  async function openEntry(entry: MemoryPanelEntry) {
    try {
      const detail = await getJson<MemoryPanelEntry>(`/api/memory/${entry.memory_id}`);
      setSelectedEntry(detail);
      setSelectedView(undefined);
      setEditing(undefined);
      setError("");
    } catch (readError) {
      setError(readError instanceof Error ? readError.message : t("memory.readError"));
    }
  }

  function startEdit(entry: MemoryPanelEntry) {
    setEditing({
      memory_id: entry.memory_id,
      body: entry.body ?? "",
      reenableAutoUpdate: false,
    });
  }

  async function saveEdit() {
    if (!editing) return;
    try {
      await putJson(`/api/memory/${editing.memory_id}`, {
        body: editing.body,
        reenable_auto_update: editing.reenableAutoUpdate,
      });
      setEditing(undefined);
      setSelectedEntry(undefined);
      await load();
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : t("memory.saveError"));
    }
  }

  async function remove(memoryId: string) {
    try {
      await deleteJson(`/api/memory/${memoryId}`);
      setSelectedEntry(undefined);
      setEditing(undefined);
      await load();
    } catch (deleteError) {
      setError(deleteError instanceof Error ? deleteError.message : t("memory.deleteError"));
    }
  }

  async function consolidate() {
    setConsolidating(true);
    try {
      await postJson("/api/memory/consolidate", {});
      await load();
    } catch (consolidateError) {
      setError(
        consolidateError instanceof Error
          ? consolidateError.message
          : t("memory.consolidateError"),
      );
    } finally {
      setConsolidating(false);
    }
  }

  async function cleanSource() {
    const trimmed = source.trim();
    if (!trimmed) return;
    try {
      await deleteJson(`/api/memory/sources/${encodeURIComponent(trimmed)}`);
      setSource("");
      setSelectedEntry(undefined);
      setEditing(undefined);
      await load();
    } catch (cleanupError) {
      setError(
        cleanupError instanceof Error
          ? cleanupError.message
          : t("memory.cleanupError"),
      );
    }
  }

  function viewLabel(fileName: string) {
    if (fileName === "memory_summary.md") return t("memory.summaryFile");
    if (fileName === "MEMORY.md") return t("memory.indexFile");
    return fileName;
  }

  return (
    <section className="settings-card memory-panel" data-testid="memory-panel">
      <div className="settings-card-title">
        <RefreshCcw size={16} />
        <div>
          <h3>{t("memory.title")}</h3>
          <small>{t("memory.hint")}</small>
        </div>
      </div>
      {error ? (
        <div className="settings-error" role="alert">
          <XCircle size={14} />
          {error}
        </div>
      ) : null}
      {loading ? (
        <div className="settings-loading">
          <LoaderCircle size={14} className="spin" />
          {t("memory.loading")}
        </div>
      ) : null}
      <div className="memory-actions">
        <button
          type="button"
          data-testid="memory-consolidate"
          onClick={() => void consolidate()}
          disabled={consolidating}
        >
          {consolidating ? (
            <LoaderCircle size={12} className="spin" />
          ) : (
            <RefreshCcw size={12} />
          )}
          {consolidating ? t("memory.consolidating") : t("memory.consolidate")}
        </button>
        <div className="memory-source-cleanup">
          <input
            value={source}
            onChange={(event) => setSource(event.target.value)}
            placeholder={t("memory.sourcePlaceholder")}
          />
          <button
            type="button"
            data-testid="memory-clean-source"
            onClick={() => void cleanSource()}
            disabled={!source.trim()}
          >
            <Trash2 size={12} />
            {t("memory.cleanSource")}
          </button>
        </div>
      </div>

      <h4 className="memory-section-title">{t("memory.derivedViews")}</h4>
      {!loading && views.length === 0 ? (
        <p className="settings-empty">{t("memory.noViews")}</p>
      ) : null}
      <ul className="memory-list memory-view-list">
        {views.map((view) => (
          <li key={view.file_name} data-testid="memory-view">
            <button
              type="button"
              className="memory-file-button"
              data-testid={`memory-view-${view.file_name}`}
              onClick={() => void openView(view)}
              disabled={!view.exists}
            >
              <span className="memory-file-name">{view.file_name}</span>
              <span className="memory-file-meta">
                {viewLabel(view.file_name)} · {t("memory.readOnly")}
              </span>
            </button>
            <small className="memory-file-time">
              {view.exists
                ? new Date(view.updated_at ?? "").toLocaleString()
                : t("memory.notGenerated")}
            </small>
            {selectedView?.file_name === view.file_name ? (
              <pre className="memory-file-content" data-testid="memory-view-content">
                {selectedView.content ?? ""}
              </pre>
            ) : null}
          </li>
        ))}
      </ul>

      <h4 className="memory-section-title">{t("memory.topicFiles")}</h4>
      {!loading && entries.length === 0 ? (
        <p className="settings-empty">{t("memory.empty")}</p>
      ) : null}
      <ul className="memory-list">
        {entries.map((entry) => (
          <li key={entry.memory_id} data-testid="memory-entry">
            <button
              type="button"
              className="memory-file-button"
              data-testid="memory-entry-open"
              onClick={() => void openEntry(entry)}
            >
              <span className="memory-file-name">{entry.file_name}</span>
              <span className="memory-file-meta">
                {entry.title} · {entry.topic_family}
              </span>
            </button>
            <small>
              {entry.kind}
              {entry.user_edited ? ` · ${t("memory.userEdited")}` : ""}
            </small>
            {entry.origin_thread_id ? (
              <small>
                {t("memory.source")}: {entry.origin_thread_id}
              </small>
            ) : null}
            {selectedEntry?.memory_id === entry.memory_id && !editing ? (
              <div className="memory-entry-detail">
                <pre className="memory-file-content" data-testid="memory-file-content">
                  {selectedEntry.body ?? ""}
                </pre>
                <div className="memory-entry-actions">
                  <button type="button" onClick={() => startEdit(selectedEntry)}>
                    <Pencil size={12} />
                    {t("memory.edit")}
                  </button>
                  <button type="button" onClick={() => void remove(entry.memory_id)}>
                    <Trash2 size={12} />
                    {t("memory.delete")}
                  </button>
                </div>
              </div>
            ) : null}
            {editing?.memory_id === entry.memory_id ? (
              <div className="memory-editor" data-testid="memory-editor">
                <textarea
                  value={editing.body}
                  onChange={(event) =>
                    setEditing({ ...editing, body: event.target.value })
                  }
                />
                <label className="clear-secret">
                  <input
                    type="checkbox"
                    checked={editing.reenableAutoUpdate}
                    onChange={(event) =>
                      setEditing({
                        ...editing,
                        reenableAutoUpdate: event.target.checked,
                      })
                    }
                  />
                  <span>{t("memory.reenableAutoUpdate")}</span>
                </label>
                <div className="memory-entry-actions">
                  <button type="button" onClick={() => void saveEdit()}>
                    {t("memory.save")}
                  </button>
                  <button type="button" onClick={() => setEditing(undefined)}>
                    {t("memory.cancel")}
                  </button>
                </div>
              </div>
            ) : null}
          </li>
        ))}
      </ul>
      <small className="memory-families">
        {t("memory.families")}: {TOPIC_FAMILIES.join(" / ")}
      </small>
    </section>
  );
}
