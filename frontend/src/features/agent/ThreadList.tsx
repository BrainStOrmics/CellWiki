import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, History, MessageSquareText, Trash2 } from "lucide-react";
import { getJson } from "../../lib/product-api";
import type { AgentRun } from "../../types";
import { useI18n } from "../../i18n";

type ThreadSummary = {
  threadId: string;
  latestRun: AgentRun;
  runCount: number;
};

export function ThreadList({
  currentThreadId,
  onSelect,
  onDelete,
}: {
  currentThreadId: string | null;
  onSelect: (thread: ThreadSummary) => void;
  onDelete: (threadId: string) => Promise<void>;
}) {
  const { t } = useI18n();
  const [expanded, setExpanded] = useState(false);
  const runs = useQuery({
    queryKey: ["agent-threads"],
    queryFn: () => getJson<AgentRun[]>("/api/agent/runs?limit=200"),
    refetchInterval: expanded ? 3000 : false,
  });
  const threads = useMemo(() => {
    const grouped = new Map<string, ThreadSummary>();
    for (const run of runs.data ?? []) {
      const current = grouped.get(run.thread_id);
      if (!current) grouped.set(run.thread_id, { threadId: run.thread_id, latestRun: run, runCount: 1 });
      else current.runCount += 1;
    }
    return [...grouped.values()].slice(0, 20);
  }, [runs.data]);

  return (
    <div className="thread-list">
      <button className="thread-list-toggle" onClick={() => setExpanded((value) => !value)}>
        <History size={13} /><span>{t("threads.title")}</span><small>{threads.length}</small><ChevronDown size={12} className={expanded ? "open" : ""} />
      </button>
      {expanded && (
        <div className="thread-list-items">
          {runs.isLoading && <span>{t("threads.loading")}</span>}
          {threads.length === 0 && !runs.isLoading && <span>{t("threads.empty")}</span>}
          {threads.map((thread) => (
            <div
              key={thread.threadId}
              className={`thread-list-item ${thread.threadId === currentThreadId ? "active" : ""}`}
            >
              <button
                className="thread-list-select"
                onClick={() => { onSelect(thread); setExpanded(false); }}
              >
                <MessageSquareText size={13} />
                <span><strong>{thread.threadId.slice(-10)}</strong><small>{thread.latestRun.status} · {thread.runCount} {t("threads.runs")}</small></span>
              </button>
              <button
                className="thread-list-delete"
                title={t("threads.delete")}
                aria-label={t("threads.delete")}
                onClick={() => void onDelete(thread.threadId).then(() => runs.refetch())}
              >
                <Trash2 size={12} />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
