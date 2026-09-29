import { useEffect, useState } from "react";
import {
  ChevronDown,
  FileText,
  LoaderCircle,
  Pencil,
  RefreshCcw,
  Trash2,
  Wrench,
  XCircle,
} from "lucide-react";

import { useI18n } from "../i18n";
import { deleteJson, getJson, postJson, putJson } from "../lib/product-api";

type MemoryPanelStatus = {
  enabled: boolean;
  auto_extract: boolean;
  min_idle_hours: number;
  debounce_minutes: number;
  daily_extractions: number;
  pending_candidates: number;
  jobs_pending: number;
  jobs_leased: number;
  jobs_failed: number;
  next_job_at: string | null;
  last_job_status: string | null;
  last_job_error: string;
  last_job_updated_at: string | null;
  last_consolidated_at: string | null;
};

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

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString();
}

export function MemoryPanel() {
  const { t } = useI18n();
  const [status, setStatus] = useState<MemoryPanelStatus>();
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
        status: MemoryPanelStatus;
      }>("/api/memory");
      setStatus(payload.status);
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

  async function toggleView(view: MemoryPanelView) {
    if (!view.exists) return;
    if (selectedView?.file_name === view.file_name) {
      setSelectedView(undefined);
      return;
    }
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

  async function toggleEntry(entry: MemoryPanelEntry) {
    if (selectedEntry?.memory_id === entry.memory_id) {
      setSelectedEntry(undefined);
      setEditing(undefined);
      return;
    }
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
    if (
      typeof window !== "undefined" &&
      !window.confirm(t("memory.deleteBySourceConfirm"))
    ) {
      return;
    }
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

  const autoOn = Boolean(status?.enabled && status?.auto_extract);
  const queueSummary = status
    ? `${status.jobs_pending} ${t("memory.jobsPending")} · ${status.jobs_leased} ${t("memory.jobsRunning")} · ${status.jobs_failed} ${t("memory.jobsFailed")}`
    : "—";

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

      <h4 className="memory-section-title">{t("memory.status")}</h4>
      <div className="memory-status-grid" data-testid="memory-status">
        <div className="memory-status-item">
          <span>{t("memory.autoExtractState")}</span>
          <strong className={autoOn ? "memory-on" : "memory-off"}>
            {autoOn ? t("memory.on") : t("memory.off")}
          </strong>
        </div>
        <div className="memory-status-item">
          <span>{t("memory.idleWindow")}</span>
          <strong>
            {status
              ? t("memory.hoursValue").replace(
                  "{hours}",
                  String(status.min_idle_hours),
                )
              : "—"}
          </strong>
        </div>
        <div className="memory-status-item">
          <span>{t("memory.pendingCandidates")}</span>
          <strong>{status?.pending_candidates ?? "—"}</strong>
        </div>
        <div className="memory-status-item">
          <span>{t("memory.queue")}</span>
          <strong>{queueSummary}</strong>
        </div>
        <div className="memory-status-item">
          <span>{t("memory.nextCheck")}</span>
          <strong>{formatTimestamp(status?.next_job_at)}</strong>
        </div>
        <div className="memory-status-item">
          <span>{t("memory.lastConsolidated")}</span>
          <strong>{formatTimestamp(status?.last_consolidated_at)}</strong>
        </div>
      </div>
      {status && status.jobs_failed > 0 && status.last_job_error ? (
        <small className="memory-job-warning" data-testid="memory-job-warning">
          {t("memory.lastJobError")}: {status.last_job_error}
        </small>
      ) : null}
      <div className="memory-actions">
        <button
          type="button"
          className="primary"
          data-testid="memory-consolidate"
          onClick={() => void consolidate()}
          disabled={
            consolidating ||
            !status?.enabled ||
            status?.pending_candidates === 0
          }
        >
          {consolidating ? (
            <LoaderCircle size={12} className="spin" />
          ) : (
            <RefreshCcw size={12} />
          )}
          {consolidating ? t("memory.consolidating") : t("memory.consolidate")}
        </button>
        <button type="button" onClick={() => void load()}>
          <RefreshCcw size={12} />
          {t("memory.refreshStatus")}
        </button>
      </div>

      <h4 className="memory-section-title">{t("memory.files")}</h4>
      {!loading && entries.length === 0 ? (
        <p className="settings-empty">{t("memory.empty")}</p>
      ) : null}
      <ul className="memory-file-list">
        {views.map((view) => {
          const open = selectedView?.file_name === view.file_name;
          return (
            <li
              className="memory-file-row"
              key={view.file_name}
              data-testid="memory-view"
            >
              <button
                type="button"
                className="memory-file-row-main"
                data-testid={`memory-view-${view.file_name}`}
                onClick={() => void toggleView(view)}
                disabled={!view.exists}
              >
                <FileText size={14} className="memory-file-icon" />
                <span className="memory-file-name">{view.file_name}</span>
                <span className="memory-file-kind">{viewLabel(view.file_name)}</span>
                <span className="memory-badge">{t("memory.readOnly")}</span>
                <span className={`memory-badge ${view.exists ? "ok" : "muted"}`}>
                  {view.exists ? t("memory.generated") : t("memory.notGenerated")}
                </span>
                <span className="memory-file-time">
                  {formatTimestamp(view.updated_at)}
                </span>
                <ChevronDown
                  size={14}
                  className={`memory-chevron${open ? " open" : ""}`}
                />
              </button>
              {open ? (
                <div className="memory-file-body" data-testid="memory-view-content">
                  <pre className="memory-file-content">
                    {selectedView?.content ?? ""}
                  </pre>
                </div>
              ) : null}
            </li>
          );
        })}
        {entries.map((entry) => {
          const open = selectedEntry?.memory_id === entry.memory_id;
          const isEditing = editing?.memory_id === entry.memory_id;
          return (
            <li
              className="memory-file-row"
              key={entry.memory_id}
              data-testid="memory-entry"
            >
              <button
                type="button"
                className="memory-file-row-main"
                data-testid="memory-entry-open"
                onClick={() => void toggleEntry(entry)}
              >
                <FileText size={14} className="memory-file-icon" />
                <span className="memory-file-name">{entry.file_name}</span>
                <span className="memory-file-kind">{entry.topic_family}</span>
                <span className="memory-file-kind">{entry.kind}</span>
                {entry.user_edited ? (
                  <span className="memory-badge warn">{t("memory.userEdited")}</span>
                ) : null}
                <span className="memory-file-time">
                  {formatTimestamp(entry.updated_at)}
                </span>
                <ChevronDown
                  size={14}
                  className={`memory-chevron${open ? " open" : ""}`}
                />
              </button>
              {open && !isEditing ? (
                <div className="memory-file-body" data-testid="memory-file-content">
                  <pre className="memory-file-content">
                    {selectedEntry?.body ?? ""}
                  </pre>
                  {entry.origin_thread_id ? (
                    <small>
                      {t("memory.source")}: {entry.origin_thread_id}
                    </small>
                  ) : null}
                  <div className="memory-entry-actions">
                    <button type="button" onClick={() => startEdit(selectedEntry!)}>
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
              {isEditing ? (
                <div className="memory-file-body">
                  <div className="memory-editor" data-testid="memory-editor">
                    <textarea
                      value={editing?.body ?? ""}
                      onChange={(event) =>
                        setEditing({
                          ...editing!,
                          body: event.target.value,
                        })
                      }
                    />
                    <label className="clear-secret">
                      <input
                        type="checkbox"
                        checked={editing?.reenableAutoUpdate ?? false}
                        onChange={(event) =>
                          setEditing({
                            ...editing!,
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
                </div>
              ) : null}
            </li>
          );
        })}
      </ul>

      <details className="memory-maintenance" data-testid="memory-maintenance">
        <summary>
          <Wrench size={13} />
          {t("memory.maintenance")}
        </summary>
        <div className="memory-maintenance-body">
          <div className="memory-danger-zone">
            <strong>{t("memory.deleteBySourceTitle")}</strong>
            <p>{t("memory.deleteBySourceHint")}</p>
            <div className="memory-source-cleanup">
              <input
                value={source}
                onChange={(event) => setSource(event.target.value)}
                placeholder={t("memory.sourcePlaceholder")}
                aria-label={t("memory.sourcePlaceholder")}
              />
              <button
                type="button"
                className="danger"
                data-testid="memory-clean-source"
                onClick={() => void cleanSource()}
                disabled={!source.trim()}
              >
                <Trash2 size={12} />
                {t("memory.cleanSource")}
              </button>
            </div>
          </div>
          <details className="memory-families-help">
            <summary>{t("memory.familiesHelp")}</summary>
            <p>{TOPIC_FAMILIES.join(" / ")}</p>
          </details>
        </div>
      </details>
    </section>
  );
}
