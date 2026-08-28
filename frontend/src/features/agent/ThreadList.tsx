import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, History, MessageSquareText, Trash2 } from "lucide-react";
import { getJson } from "../../lib/product-api";
import type { AgentThreadEntry } from "../../types";
import { useI18n } from "../../i18n";

export type ThreadSelection = {
  threadId: string;
  latestRunId: string | null;
};

export function ThreadList({
  currentThreadId,
  onSelect,
  onDelete,
}: {
  currentThreadId: string | null;
  onSelect: (thread: ThreadSelection) => void;
  onDelete: (threadId: string) => Promise<void>;
}) {
  const { t } = useI18n();
  const [expanded, setExpanded] = useState(false);
  const threads = useQuery({
    queryKey: ["agent-threads"],
    queryFn: () => getJson<AgentThreadEntry[]>("/api/agent/threads?limit=200"),
    refetchInterval: expanded ? 3000 : false,
  });
  useEffect(() => {
    // 展开下拉时立即刷新一次，避免新会话要等 3s 轮询才出现
    if (expanded) void threads.refetch();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [expanded]);
  const items = (threads.data ?? []).slice(0, 20);

  return (
    <div className="thread-list">
      <button className="thread-list-toggle" onClick={() => setExpanded((value) => !value)}>
        <History size={13} /><span>{t("threads.title")}</span><small>{items.length}</small><ChevronDown size={12} className={expanded ? "open" : ""} />
      </button>
      {expanded && (
        <div className="thread-list-items">
          {threads.isLoading && <span>{t("threads.loading")}</span>}
          {items.length === 0 && !threads.isLoading && <span>{t("threads.empty")}</span>}
          {items.map((thread) => {
            // 标题优先级：会话标题（LLM 命名阶段的落点）> 会话 ID > 未开始占位
            const started = thread.run_count > 0;
            const label = thread.title?.trim()
              || (started ? thread.thread_id.slice(-10) : t("threads.untitled"));
            return (
              <div
                key={thread.thread_id}
                className={`thread-list-item ${thread.thread_id === currentThreadId ? "active" : ""}`}
              >
                <button
                  className="thread-list-select"
                  onClick={() => {
                    onSelect({ threadId: thread.thread_id, latestRunId: thread.latest_run_id });
                    setExpanded(false);
                  }}
                >
                  <MessageSquareText size={13} />
                  <span><strong>{label}</strong><small>{started ? `${thread.latest_status} · ${thread.run_count} ${t("threads.runs")}` : t("threads.notStarted")}</small></span>
                </button>
                <button
                  className="thread-list-delete"
                  title={t("threads.delete")}
                  aria-label={t("threads.delete")}
                  onClick={() => void onDelete(thread.thread_id).then(() => threads.refetch())}
                >
                  <Trash2 size={12} />
                </button>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
