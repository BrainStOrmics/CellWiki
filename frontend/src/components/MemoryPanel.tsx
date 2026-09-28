import { useEffect, useState } from "react";
import { LoaderCircle, Pencil, RefreshCcw, Trash2, XCircle } from "lucide-react";

import { useI18n } from "../i18n";
import { deleteJson, getJson, putJson } from "../lib/product-api";

type MemoryPanelEntry = {
  memory_id: string;
  kind: string;
  topic_family: string;
  title: string;
  file_name: string;
  user_edited: boolean;
  auto_update: boolean;
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
  const [entries, setEntries] = useState<MemoryPanelEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<EntryDraft>();

  async function load() {
    setLoading(true);
    try {
      const payload = await getJson<{ entries: MemoryPanelEntry[] }>("/api/memory");
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

  async function startEdit(entry: MemoryPanelEntry) {
    try {
      const detail = await getJson<MemoryPanelEntry>(`/api/memory/${entry.memory_id}`);
      setEditing({
        memory_id: detail.memory_id,
        body: detail.body ?? "",
        reenableAutoUpdate: false,
      });
    } catch (editError) {
      setError(editError instanceof Error ? editError.message : t("memory.readError"));
    }
  }

  async function saveEdit() {
    if (!editing) return;
    try {
      await putJson(`/api/memory/${editing.memory_id}`, {
        body: editing.body,
        reenable_auto_update: editing.reenableAutoUpdate,
      });
      setEditing(undefined);
      await load();
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : t("memory.saveError"));
    }
  }

  async function remove(memoryId: string) {
    try {
      await deleteJson(`/api/memory/${memoryId}`);
      await load();
    } catch (deleteError) {
      setError(deleteError instanceof Error ? deleteError.message : t("memory.deleteError"));
    }
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
      {!loading && entries.length === 0 ? (
        <p className="settings-empty">{t("memory.empty")}</p>
      ) : null}
      <ul className="memory-list">
        {entries.map((entry) => (
          <li key={entry.memory_id} data-testid="memory-entry">
            <div className="memory-entry-head">
              <strong>{entry.title}</strong>
              <span>{entry.topic_family}</span>
            </div>
            <small>
              {entry.kind}
              {entry.user_edited ? ` · ${t("memory.userEdited")}` : ""}
            </small>
            <div className="memory-entry-actions">
              <button type="button" onClick={() => void startEdit(entry)}>
                <Pencil size={12} />
                {t("memory.edit")}
              </button>
              <button type="button" onClick={() => void remove(entry.memory_id)}>
                <Trash2 size={12} />
                {t("memory.delete")}
              </button>
            </div>
          </li>
        ))}
      </ul>
      {editing ? (
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
                setEditing({ ...editing, reenableAutoUpdate: event.target.checked })
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
      <small className="memory-families">
        {t("memory.families")}: {TOPIC_FAMILIES.join(" / ")}
      </small>
    </section>
  );
}