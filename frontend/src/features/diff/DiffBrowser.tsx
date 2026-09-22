import { useCallback, useEffect, useState } from "react";
import { ChevronDown, ChevronRight, GitPullRequest, RefreshCw, ShieldCheck, ShieldX, X } from "lucide-react";
import { getJson, postJson } from "../../lib/product-api";

export type PendingDiffRecord = {
  diff_id: string;
  run_id: string;
  thread_id: string;
  snapshot_commit?: string | null;
  head_commit?: string | null;
  commits: string[];
  files: string[];
  insertions: number;
  deletions: number;
  status: "pending" | "accepted" | "rejected";
  resolution?: string | null;
  created_at: string;
  resolved_at?: string | null;
  data?: Record<string, unknown>;
};

/** 代判（自动接受策略）的单元在历史区需要与人工判定区分开。 */
export function isAutoAccepted(diff: PendingDiffRecord): boolean {
  return diff.data?.resolved_by === "auto";
}

function dataText(diff: PendingDiffRecord, key: string): string {
  const value = diff.data?.[key];
  return typeof value === "string" ? value.trim() : "";
}

/**
 * 卡片主行：LLM 标题 → 发布时物化的确定性回退 → run id。
 * 回退标题由后端在发布时算好（提交 subject 要读 git，渲染时算不了）。
 */
export function unitTitle(diff: PendingDiffRecord): string {
  return dataText(diff, "unit_title") || dataText(diff, "unit_title_fallback") || diff.run_id;
}

/** 没有真名字（命名失败、无模型，或本功能上线前的历史单元）。 */
export function isUnnamed(diff: PendingDiffRecord): boolean {
  return !dataText(diff, "unit_title");
}

/**
 * 审批单元序号：`diff_<run_id>_<n>`。无后缀的旧行视为单元 1；
 * 无法识别的 id 返回 null（不展示徽章）。与后端 agent_runtime._unit_index 同步。
 */
export function approvalUnitIndex(diffId: string, runId: string): number | null {
  const prefix = `diff_${runId}_`;
  if (diffId.startsWith(prefix)) {
    const suffix = diffId.slice(prefix.length);
    return /^\d+$/.test(suffix) ? Number(suffix) : null;
  }
  if (diffId === `diff_${runId}`) return 1;
  return null;
}

// ---- patch 解析（纯函数，可单测）----
export type PatchLine = { kind: "add" | "del" | "ctx" | "hdr"; text: string; oldLine?: number; newLine?: number };
export type PatchHunk = { header: string; lines: PatchLine[] };
export type PatchFile = { path: string; hunks: PatchHunk[]; body?: string };

export function parsePatch(patch: string): PatchFile[] {
  const files: PatchFile[] = [];
  let current: PatchFile | null = null;
  let hunk: PatchHunk | null = null;
  let oldLine = 0;
  let newLine = 0;
  for (const line of patch.split("\n")) {
    if (line.startsWith("diff --git ")) {
      const match = line.match(/ b\/(.+)$/);
      current = { path: match ? match[1] : line, hunks: [] };
      files.push(current);
      hunk = null;
      continue;
    }
    if (!current) continue;
    const hunkMatch = line.match(/^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@/);
    if (hunkMatch) {
      hunk = { header: line, lines: [] };
      current.hunks.push(hunk);
      oldLine = Number(hunkMatch[1]);
      newLine = Number(hunkMatch[3]);
      continue;
    }
    if (!hunk) {
      // index / --- / +++ 等元数据跳过；其余（如 binary 差异）保留为正文占位
      if (line.startsWith("index ") || line.startsWith("--- ") || line.startsWith("+++ ")
        || line.startsWith("old mode ") || line.startsWith("new mode ")
        || line.startsWith("deleted file mode ") || line.startsWith("new file mode ")
        || line.startsWith("similarity index ") || line.startsWith("dissimilarity index ")
        || line.startsWith("rename from ") || line.startsWith("rename to ")
        || line.startsWith("copy from ") || line.startsWith("copy to ")
        || line === "GIT binary patch" || line === "") {
        continue;
      }
      current.body = current.body === undefined ? line : `${current.body}\n${line}`;
      continue;
    }
    if (line.startsWith("\\")) {
      hunk.lines.push({ kind: "hdr", text: line });
      continue;
    }
    const kind = line.startsWith("+") ? "add" : line.startsWith("-") ? "del" : "ctx";
    const entry: PatchLine = { kind, text: line };
    if (kind === "add") {
      entry.newLine = newLine;
      newLine += 1;
    } else if (kind === "del") {
      entry.oldLine = oldLine;
      oldLine += 1;
    } else {
      entry.oldLine = oldLine;
      entry.newLine = newLine;
      oldLine += 1;
      newLine += 1;
    }
    hunk.lines.push(entry);
  }
  return files;
}

type Props = {
  onExit?: () => void;
  onCountChange?: (count: number) => void;
};

export function DiffBrowser({ onExit, onCountChange }: Props) {
  const [diffs, setDiffs] = useState<PendingDiffRecord[] | null>(null);
  const [selected, setSelected] = useState<PendingDiffRecord | null>(null);
  const [patch, setPatch] = useState<string | null>(null);
  // 默认全部折叠：展开集合为空，点击文件头才展开对应文件
  const [expandedFiles, setExpandedFiles] = useState<ReadonlySet<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const data = await getJson<{ pending_diffs: PendingDiffRecord[] }>("/api/pending-diffs");
      setDiffs(data.pending_diffs);
      onCountChange?.(data.pending_diffs.filter((item) => item.status === "pending").length);
    } catch (cause) {
      setError(String(cause));
    }
  }, [onCountChange]);

  useEffect(() => {
    void load();
  }, [load]);

  async function open(diff: PendingDiffRecord) {
    setSelected(diff);
    setPatch(null);
    setError(null);
    try {
      // /patch 接口返回 { diff_id, patch } JSON 包壳，需取出 patch 字段后再解析
      const payload = await getJson<{ patch: string }>(`/api/pending-diffs/${encodeURIComponent(diff.diff_id)}/patch`);
      setPatch(payload.patch);
    } catch (cause) {
      setError(String(cause));
    }
  }

  function toggleFile(path: string) {
    setExpandedFiles((current) => {
      const next = new Set(current);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  }

  async function resolve(diffId: string, action: "accept" | "reject") {
    setBusy(true);
    setError(null);
    try {
      await postJson<{ status: string }>(`/api/pending-diffs/${encodeURIComponent(diffId)}/${action}`, {});
      setSelected(null);
      setPatch(null);
      await load();
    } catch (cause) {
      setError(String(cause));
    } finally {
      setBusy(false);
    }
  }

  async function regenerate(diffId: string) {
    setBusy(true);
    setError(null);
    try {
      await postJson<{ status: string }>(`/api/pending-diffs/${encodeURIComponent(diffId)}/rename`, {});
      const updated = await getJson<PendingDiffRecord>(`/api/pending-diffs/${encodeURIComponent(diffId)}`);
      setSelected((current) => (current?.diff_id === diffId ? updated : current));
      await load();
    } catch (cause) {
      setError(String(cause));
    } finally {
      setBusy(false);
    }
  }

  const files = patch ? parsePatch(patch) : [];
  const pending = diffs?.filter((d) => d.status === "pending") ?? [];
  const pendingCount = pending.length;
  const resolved = diffs?.filter((d) => d.status !== "pending") ?? [];
  const [historyOpen, setHistoryOpen] = useState(false);

  function unitBadge(d: PendingDiffRecord) {
    const unit = approvalUnitIndex(d.diff_id, d.run_id);
    return unit === null ? null : <span className="diff-unit-badge">单元 {unit}</span>;
  }

  return (
    <div className="diff-browser">
      <div className="diff-browser-toolbar">
        <strong><GitPullRequest size={14} /> 待确认 Diff</strong>
        <span className="diff-pending-count">{pendingCount} 待审</span>
        <button onClick={() => void load()} title="刷新"><RefreshCw size={13} /> 刷新</button>
        <button onClick={onExit} title="关闭" className="diff-toolbar-close"><X size={13} /> 关闭</button>
      </div>
      {error && <div className="workspace-notice">{error}</div>}
      {!diffs ? (
        <div className="feature-state">加载中…</div>
      ) : diffs.length === 0 ? (
        <div className="tree-empty diff-empty">暂无待确认 diff。Agent 或工作区编辑提交后会出现在这里。</div>
      ) : (
        <>
          <div className="diff-list">
            {pending.length === 0 ? (
              <div className="tree-empty diff-empty">当前没有待判定单元；已判定单元见下方历史。</div>
            ) : pending.map((d) => (
              <button key={d.diff_id} className={selected?.diff_id === d.diff_id ? "diff-card selected" : "diff-card"} onClick={() => void open(d)}>
                <span className="diff-card-top">
                  <span className={`diff-status ${d.status}`}>{d.status}</span>
                  {unitBadge(d)}
                  {isUnnamed(d) && <span className="diff-unnamed-badge" title={dataText(d, "unit_title_error") || "尚未命名"}>未命名</span>}
                </span>
                <span className="diff-card-main">
                  <strong>{unitTitle(d)}</strong>
                  <small>{d.run_id} · +{d.insertions} −{d.deletions} · {d.files.length} 文件 · {d.commits.length} 提交</small>
                </span>
              </button>
            ))}
          </div>
          {resolved.length > 0 && (
            <div className="diff-history">
              <button type="button" className="diff-history-toggle" onClick={() => setHistoryOpen((open) => !open)}>
                {historyOpen ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                历史判定单元（{resolved.length}）
              </button>
              {historyOpen && (
                <div className="diff-list diff-history-list">
                  {resolved.map((d) => (
                    <button key={d.diff_id} className={selected?.diff_id === d.diff_id ? "diff-card selected readonly" : "diff-card readonly"} onClick={() => void open(d)}>
                      <span className="diff-card-top">
                        <span className={`diff-status ${d.status}`}>{d.status}</span>
                        {unitBadge(d)}
                        {isAutoAccepted(d) && <span className="diff-auto-badge">自动接受</span>}
                        {isUnnamed(d) && <span className="diff-unnamed-badge" title={dataText(d, "unit_title_error") || "尚未命名"}>未命名</span>}
                      </span>
                      <span className="diff-card-main">
                        <strong>{unitTitle(d)}</strong>
                        <small>{d.run_id} · +{d.insertions} −{d.deletions} · {d.files.length} 文件</small>
                      </span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
          {selected && (
            <div className="diff-detail">
              <div className="diff-detail-toolbar">
                <div className="diff-detail-heading">
                  <strong>{unitTitle(selected)}</strong>
                  <small>{selected.run_id}</small>
                  {dataText(selected, "unit_summary") && <small>{dataText(selected, "unit_summary")}</small>}
                  {isUnnamed(selected) && (
                    <small className="diff-unnamed-reason">
                      未命名{dataText(selected, "unit_title_error") ? ` · ${dataText(selected, "unit_title_error")}` : ""}
                    </small>
                  )}
                </div>
                {unitBadge(selected)}
                {selected.status !== "pending" && (
                  <span className="diff-history-notice">已判定 · 只读</span>
                )}
                <div className="diff-detail-actions">
                  <button
                    className="diff-rename"
                    onClick={() => void regenerate(selected.diff_id)}
                    disabled={busy}
                    title="让模型重新总结这个单元并起名"
                  ><RefreshCw size={13} /> 重新生成标题</button>
                  {selected.status === "pending" && (
                    <div className="diff-actions">
                      <button
                        onClick={() => void resolve(selected.diff_id, "reject")}
                        disabled={busy}
                        title={`仅回滚本单元的 ${selected.commits.length} 个提交，不影响此前已判定的内容`}
                      ><ShieldX size={13} /> 拒绝本单元（{selected.commits.length} 提交）</button>
                      <button onClick={() => void resolve(selected.diff_id, "accept")} disabled={busy}><ShieldCheck size={13} /> 接受</button>
                    </div>
                  )}
                </div>
              </div>
              {patch === null ? (
                <div className="feature-state">加载中…</div>
              ) : files.length === 0 ? (
                <pre className="workspace-text">{patch}</pre>
              ) : (
                <div className="diff-patch">
                  {files.map((file) => (
                    <div key={file.path} className="diff-file">
                      <button
                        type="button"
                        className="diff-file-header"
                        onClick={() => toggleFile(file.path)}
                        aria-expanded={expandedFiles.has(file.path)}
                        title={file.path}
                      >
                        {expandedFiles.has(file.path) ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                        <span>{file.path}</span>
                      </button>
                      {expandedFiles.has(file.path) && (
                        file.hunks.length === 0 && file.body ? (
                          <div className="diff-file-body">
                            <div className="diff-line binary">{file.body}</div>
                          </div>
                        ) : (
                          file.hunks.map((hunk, index) => (
                            <div className="diff-file-body" key={index}>
                              <div className="diff-hunk-header">{hunk.header}</div>
                              {hunk.lines.map((line, lineIndex) => (
                                <div key={lineIndex} className={`diff-line ${line.kind}`}>
                                  {line.kind === "hdr" ? (
                                    <span className="diff-line-note">{line.text}</span>
                                  ) : (
                                    <>
                                      <span className="diff-line-num old">{line.oldLine ?? ""}</span>
                                      <span className="diff-line-num new">{line.newLine ?? ""}</span>
                                      <span className="diff-line-marker">{line.kind === "add" ? "+" : line.kind === "del" ? "−" : ""}</span>
                                      <span className="diff-line-content">{line.text.slice(1)}</span>
                                    </>
                                  )}
                                </div>
                              ))}
                            </div>
                          ))
                        )
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
