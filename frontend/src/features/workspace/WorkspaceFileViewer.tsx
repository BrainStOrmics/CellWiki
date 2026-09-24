import { useEffect, useState } from "react";
import { ExternalLink, Pencil, Save, X } from "lucide-react";
import { getText, postJson } from "../../lib/product-api";
import { apiUrl } from "../../runtime";
import { useI18n } from "../../i18n";
import { MarkdownReader } from "../wiki/MarkdownReader";
import type { WorkspaceTreeEntry } from "./WorkspaceFileBrowser";

type Props = {
  entry: WorkspaceTreeEntry;
  onStagedEdit?: (diffId: string) => void;
  onWikiLink?: (pageId: string) => void;
};

/**
 * 工作区文件查看器：md 用 MarkdownReader 渲染、txt 等宽文本、PDF 内嵌 + 降级、
 * 二进制外部打开；md/txt 支持受控编辑（提交后走 pending diff 审批）。
 */
export function WorkspaceFileViewer({ entry, onStagedEdit, onWikiLink }: Props) {
  const { t } = useI18n();
  const [content, setContent] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    setContent(null);
    setEditing(false);
    setNotice(null);
    if (entry.type === "pdf" || entry.type === "binary") return;
    getText(`/api/workspace/file?path=${encodeURIComponent(entry.path)}`)
      .then(setContent)
      .catch((cause) => setNotice(`${t("viewer.readFailed")}: ${String(cause)}`));
  }, [entry]);

  async function saveEdit() {
    setBusy(true);
    setNotice(null);
    try {
      const result = await postJson<{ pending_diff_id?: string }>("/api/workspace/edit", {
        path: entry.path,
        content: draft,
      });
      setEditing(false);
      setContent(draft);
      setNotice(result.pending_diff_id ? `${t("viewer.editSubmitted")} (${result.pending_diff_id})` : t("viewer.editSubmitted"));
      onStagedEdit?.(result.pending_diff_id ?? "");
    } catch (cause) {
      setNotice(`${t("viewer.editFailed")}: ${String(cause)}`);
    } finally {
      setBusy(false);
    }
  }

  const fileUrl = apiUrl(`/api/workspace/file?path=${encodeURIComponent(entry.path)}`);

  return (
    <div className="workspace-viewer">
      <div className="workspace-viewer-toolbar">
        <strong>{entry.path}</strong>
        <span className="workspace-viewer-type">{entry.type.toUpperCase()}</span>
        {(entry.type === "md" || entry.type === "txt") && !editing && (
          <button onClick={() => { setDraft(content ?? ""); setEditing(true); }} title={t("viewer.edit")}>
            <Pencil size={13} /> {t("viewer.edit")}
          </button>
        )}
      </div>
      {notice && <div className="workspace-notice">{notice}</div>}
      {entry.type === "pdf" && (
        <div className="workspace-pdf-wrap">
          <object data={fileUrl} type="application/pdf" className="workspace-pdf-object">
            <p>{t("viewer.pdfNotEmbeddable")}</p>
            <a href={fileUrl} target="_blank" rel="noreferrer"><ExternalLink size={13} /> {t("viewer.openExternally")}</a>
          </object>
        </div>
      )}
      {entry.type === "binary" && (
        <div className="workspace-binary">
          <p>{t("viewer.binaryNotPreviewable")}</p>
          <a href={fileUrl} target="_blank" rel="noreferrer"><ExternalLink size={13} /> {t("viewer.openExternally")}</a>
        </div>
      )}
      {(entry.type === "md" || entry.type === "txt") && (
        editing ? (
          <>
            <textarea
              className="workspace-editor"
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              rows={18}
            />
            <div className="workspace-editor-actions">
              <button onClick={() => void saveEdit()} disabled={busy}><Save size={13} /> {busy ? t("viewer.submitting") : t("viewer.saveAndSubmit")}</button>
              <button onClick={() => setEditing(false)}><X size={13} /> {t("viewer.cancel")}</button>
            </div>
          </>
        ) : content !== null ? (
          entry.type === "md"
            ? <MarkdownReader markdown={content} onWikiLink={onWikiLink} />
            : <pre className="workspace-text">{content}</pre>
        ) : null
      )}
    </div>
  );
}
