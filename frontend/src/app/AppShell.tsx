import { lazy, Suspense, useEffect, useMemo, useRef, useState, type MouseEvent, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Bot,
  ChevronDown,
  ChevronRight,
  CirclePlus,
  Database,
  FileText,
  Folder,
  FolderOpen,
  Library,
  MessageSquareText,
  Network,
  PanelLeft,
  RotateCcw,
  Search,
  Send,
  Settings,
  Square,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import { SourceReview } from "../components/SourceReview";
import { ThemeToggle } from "../components/ThemeToggle";
import { ZoomController } from "../components/ZoomController";
import { useI18n } from "../i18n";
import { apiUrl, isDesktopRuntime, productFetch } from "../runtime";
import { deleteJson, getJson, postJson, ProductApiError } from "../lib/product-api";
import { MarkdownReader } from "../features/wiki/MarkdownReader";
import { useUiStore } from "../stores/ui-store";
import { CommandPalette } from "../features/search/CommandPalette";
import { ThreadList } from "../features/agent/ThreadList";
import { AgentMessageBubble } from "../features/agent/AgentMessageBubble";
import { AgentReviewCard, type AgentReviewSummary } from "../features/agent/AgentReviewCard";
import { reduceAgentRunMessages } from "../features/agent/agent-run-reducer";
import {
  ReviewsWorkspace,
  SearchWorkspace,
} from "../features/discovery/FeatureWorkspaces";

const GraphWorkspace = lazy(() => import("../features/graph/GraphWorkspace").then((module) => ({
  default: module.GraphWorkspace,
})));
const SettingsView = lazy(() => import("../components/SettingsView").then((module) => ({
  default: module.SettingsView,
})));
import type {
  AgentEvent,
  AgentEventType,
  AgentAnswer,
  AgentMessage,
  AgentProcessStep,
  AgentRun,
  AgentRunStatus,
  AttachmentRecord,
  ChangeSetReview,
  Citation,
  ChatMessage,
  IngestWorkflow,
  Page,
  PageDetail,
  QualityReport,
  SearchResult,
  Source,
  TaskEvent,
} from "../types";

type ResizeSide = "left" | "right";
type PendingInterrupt = { threadId: string; runId: string; changeSetId: string };

const agentEventTypes: AgentEventType[] = [
  "run_status",
  "message_delta",
  "final_response",
  "tool_started",
  "tool_completed",
  "tool_failed",
  "subagent_started",
  "subagent_completed",
  "progress",
  "review_required",
  "changeset_ready",
  "verification",
  "error",
];

const terminalAgentStatuses = new Set<AgentRunStatus>([
  "waiting_confirmation",
  "waiting_approval",
  "succeeded",
  "rejected",
  "failed",
  "cancelled",
]);
function agentRunStorageKey(contextKey: string) {
  return `cellwiki.agent.active_run_id.${contextKey}`;
}

function historyMessageToChatMessage(message: AgentMessage): ChatMessage {
  const data = message.data as Partial<AgentAnswer> & { process?: AgentProcessStep[] };
  const verificationLevel = data.verification_level ?? "unvalidated";
  const knowledgeScope = data.knowledge_scope ?? "unvalidated";
  const confidence = knowledgeScope === "general"
    ? undefined
    : verificationLevel === "unvalidated"
      ? (data.confidence ? "low" : undefined)
      : data.confidence;
  return {
    role: message.role === "assistant" ? "agent" : "user",
    text: message.content,
    citations: data.citations ?? [],
    confidence,
    declaredConfidence: data.declared_confidence,
    verificationLevel,
    knowledgeScope,
    validationIssues: data.validation_issues ?? [],
    missingEvidence: data.missing_evidence ?? [],
    process: Array.isArray(data.process) ? data.process : undefined,
    runId: message.run_id,
  };
}

const emptyPageDetail: PageDetail = { page_id: "", frontmatter: {}, markdown: "" };

type WorkspaceData = {
  pages: Page[];
  sources: Source[];
  reviews: ChangeSetReview[];
  quality: QualityReport;
};

async function loadWorkspaceData(): Promise<WorkspaceData> {
  const [pages, sources, reviews, quality] = await Promise.all([
    getJson<Page[]>("/api/projects/cellwiki/tree"),
    getJson<Source[]>("/api/sources"),
    getJson<ChangeSetReview[]>("/api/changesets"),
    getJson<QualityReport>("/api/quality"),
  ]);
  return { pages, sources, reviews, quality };
}

function clamp(value: number, minimum: number, maximum: number) {
  return Math.min(Math.max(value, minimum), maximum);
}

function fileNameForPage(page: Page) {
  return page.path?.split("/").at(-1) ?? `${page.page_id}.md`;
}

export function AppShell() {
  const { language, t } = useI18n();
  const initialAgentMessage = useMemo<ChatMessage>(() => ({
    role: "agent",
    text: t("app.initialMessage"),
    meta: t("chat.queryMeta"),
  }), [t]);
  const [pages, setPages] = useState<Page[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [detail, setDetail] = useState<PageDetail>(emptyPageDetail);
  const [sources, setSources] = useState<Source[]>([]);
  const [reviews, setReviews] = useState<ChangeSetReview[]>([]);
  const [selectedChangeSetId, setSelectedChangeSetId] = useState<string | null>(null);
  const [quality, setQuality] = useState<QualityReport>();
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [taskEvents, setTaskEvents] = useState<TaskEvent[]>([]);
  const [selectedSourceId, setSelectedSourceId] = useState<string | null>(null);
  const [workflow, setWorkflow] = useState<IngestWorkflow>({ phase: "idle", message: t("workflow.ready") });
  const [filter, setFilter] = useState("");
  const [expanded, setExpanded] = useState(() => new Set(["root", "wiki", "cell-types", "sources"]));
  const [messages, setMessages] = useState<ChatMessage[]>([initialAgentMessage]);
  const [draft, setDraft] = useState("");
  const [agentBusy, setAgentBusy] = useState(false);
  const [activeAgentRunId, setActiveAgentRunId] = useState<string | null>(null);
  const [retryableAgentRunId, setRetryableAgentRunId] = useState<string | null>(null);
  const [agentActivity, setAgentActivity] = useState("");
  const [pendingInterrupt, setPendingInterrupt] = useState<PendingInterrupt | null>(null);
  const [attachments, setAttachments] = useState<AttachmentRecord[]>([]);
  const [apiOnline, setApiOnline] = useState(false);
  const leftWidth = useUiStore((state) => state.leftWidth);
  const rightWidth = useUiStore((state) => state.rightWidth);
  const selectedText = useUiStore((state) => state.selectedText);
  const setSelectedText = useUiStore((state) => state.setSelectedText);
  const setPanelWidth = useUiStore((state) => state.setPanelWidth);
  const activeThreadId = useUiStore((state) => state.activeThreadId);
  const setActiveThreadId = useUiStore((state) => state.setActiveThreadId);
  const composerPageRef = useUiStore((state) => state.composerPageRef);
  const setComposerPageRef = useUiStore((state) => state.setComposerPageRef);
  const activeAttachmentIds = useUiStore((state) => state.activeAttachmentIds);
  const setActiveAttachmentIds = useUiStore((state) => state.setActiveAttachmentIds);
  const addActiveAttachmentIds = useUiStore((state) => state.addActiveAttachmentIds);
  const removeActiveAttachmentId = useUiStore((state) => state.removeActiveAttachmentId);
  const clearActiveAttachments = useUiStore((state) => state.clearActiveAttachments);
  const removeLastComposerReference = useUiStore((state) => state.removeLastComposerReference);
  const activeView = useUiStore((state) => state.activeView);
  const setActiveView = useUiStore((state) => state.setActiveView);
  const setCommandPaletteOpen = useUiStore((state) => state.setCommandPaletteOpen);
  const workbenchRef = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const attachmentRef = useRef<HTMLInputElement>(null);
  const filterRef = useRef<HTMLInputElement>(null);
  const chatScrollRef = useRef<HTMLDivElement>(null);
  const agentThreadIdRef = useRef<string | null>(null);
  const agentEventSourceRef = useRef<EventSource | null>(null);
  const agentEventSequenceRef = useRef(0);
  const processedAgentEventsRef = useRef(new Set<string>());
  const streamGenerationRef = useRef(0);
  const messagesRef = useRef<ChatMessage[]>(messages);
  const workspaceQuery = useQuery({
    queryKey: ["workspace"],
    queryFn: loadWorkspaceData,
    refetchInterval: (query) => query.state.status === "error" ? 2_000 : 15_000,
  });
  const pageQuery = useQuery({
    queryKey: ["wiki-page", selectedId],
    queryFn: () => getJson<PageDetail>(`/api/pages/${selectedId}`),
    enabled: Boolean(selectedId),
  });

  messagesRef.current = messages;

  useEffect(() => {
    // Keep the untouched welcome state aligned with a language switch without rewriting an active chat.
    setMessages((current) => current.length === 1 && current[0]?.role === "agent" ? [initialAgentMessage] : current);
  }, [initialAgentMessage]);

  useEffect(() => {
    // Workflow phases are UI state, so their explanatory copy should follow the selected app language.
    setWorkflow((current) => {
      const message = {
        idle: t("workflow.ready"),
        preparing: t("workflow.preparing"),
        cancelling: t("workflow.cancelling"),
        cancelled: t("workflow.cancelled"),
        awaiting_review: t("workflow.review"),
        committing: t("workflow.committing"),
        committed: t("workflow.committed"),
        rejected: t("workflow.rejected"),
        rolled_back: t("workflow.rolledBack"),
        failed: t("source.failedTitle"),
      }[current.phase];
      return message ? { ...current, message } : current;
    });
  }, [t]);

  useEffect(() => {
    if (!workspaceQuery.data) return;
    setPages(workspaceQuery.data.pages);
    setSources(workspaceQuery.data.sources);
    setReviews(workspaceQuery.data.reviews);
    setQuality(workspaceQuery.data.quality);
    setApiOnline(true);
    if (workspaceQuery.data.pages.length === 0) {
      setSelectedId("");
      setDetail(emptyPageDetail);
    } else if (!workspaceQuery.data.pages.some((page) => page.page_id === selectedId)) {
      setSelectedId(workspaceQuery.data.pages[0].page_id);
    }
  }, [workspaceQuery.data, selectedId]);

  useEffect(() => {
    if (workspaceQuery.isError) setApiOnline(false);
  }, [workspaceQuery.isError]);

  async function refreshWorkspace() {
    const result = await workspaceQuery.refetch();
    if (!result.data) throw result.error ?? new Error("workspace unavailable");
    return result.data;
  }

  useEffect(() => {
    agentThreadIdRef.current = activeThreadId;
    const savedRunId = activeThreadId ? window.localStorage.getItem(agentRunStorageKey(activeThreadId)) : null;
    if (agentThreadIdRef.current) void restoreAgentThread(agentThreadIdRef.current, savedRunId ?? undefined);

    return () => {
      streamGenerationRef.current += 1;
      agentEventSourceRef.current?.close();
      agentEventSourceRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (pageQuery.data) setDetail(pageQuery.data);
    else if (pageQuery.isError || !selectedId) setDetail(emptyPageDetail);
  }, [pageQuery.data, pageQuery.isError, selectedId]);

  useEffect(() => {
    const openGlobalSearch = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setCommandPaletteOpen(true);
      }
    };
    window.addEventListener("keydown", openGlobalSearch);
    return () => window.removeEventListener("keydown", openGlobalSearch);
  }, []);

  useEffect(() => {
    // Only the message viewport moves; the Agent header and composer remain fixed.
    window.requestAnimationFrame(() => {
      if (chatScrollRef.current) chatScrollRef.current.scrollTop = chatScrollRef.current.scrollHeight;
    });
  }, [messages, agentBusy]);

  const selectedPage = pages.find((page) => page.page_id === selectedId);
  const selectedSource = sources.find((source) => source.source_id === selectedSourceId);
  const selectedReview = reviews.find((review) => review.change_set.change_set_id === selectedChangeSetId)
    ?? reviews.find((review) =>
      review.change_set.operations.some((operation) => operation.target_id === selectedSourceId),
    );
  const selectedTitle = String(detail.frontmatter.display_name ?? selectedPage?.title ?? selectedId.replaceAll("_", " "));
  const selectedPath = selectedPage?.path ?? (selectedId ? `wiki/cell_types/${selectedId}.md` : "cellwiki");
  const contextTitle = (selectedSource?.original_name ?? selectedTitle) || t("reader.workspace");
  const contextPath = selectedSource ? `sources/${selectedSource.source_id}` : selectedPath;
  const references = Array.isArray(detail.frontmatter.references) ? detail.frontmatter.references : [];
  const activeAttachments = activeAttachmentIds
    .map((attachmentId) => attachments.find((attachment) => attachment.attachment_id === attachmentId))
    .filter((attachment): attachment is AttachmentRecord => Boolean(attachment));
  const normalizedFilter = filter.trim().toLowerCase();
  const filteredPages = useMemo(() => {
    if (!normalizedFilter) return pages;
    return pages.filter((page) => {
      const searchable = `${page.page_id} ${page.title ?? ""} ${page.path ?? ""}`.toLowerCase();
      return searchable.includes(normalizedFilter);
    });
  }, [normalizedFilter, pages]);

  useEffect(() => {
    if (
      !selectedReview
      || workflow.phase === "preparing"
      || workflow.phase === "cancelling"
      || workflow.phase === "cancelled"
      || workflow.phase === "committing"
      || workflow.phase === "failed"
    ) return;
    const phase = selectedReview.status === "committed"
      ? "committed"
      : selectedReview.status === "rolled_back"
        ? "rolled_back"
      : selectedReview.status === "rejected"
        ? "rejected"
        : "awaiting_review";
    setWorkflow({
      phase,
      message: phase === "committed"
        ? t("workflow.committed")
        : phase === "rolled_back"
          ? t("workflow.rolledBack")
        : phase === "rejected"
          ? t("workflow.rejected")
          : t("workflow.review"),
    });
  }, [selectedReview?.change_set.change_set_id, selectedReview?.status]);

  useEffect(() => {
    if (selectedReview) {
      setActiveRunId(selectedReview.change_set.run_id);
      return;
    }
    if (workflow.phase !== "preparing" && workflow.phase !== "cancelling" && workflow.phase !== "cancelled") {
      setActiveRunId(null);
      setTaskEvents([]);
    }
  }, [selectedReview?.change_set.run_id, selectedSourceId, workflow.phase]);

  useEffect(() => {
    if (!activeRunId) return;
    let disposed = false;
    const loadTimeline = async () => {
      try {
        const result = await getJson<{ run_id: string; events: TaskEvent[] }>(`/api/tasks/${encodeURIComponent(activeRunId)}`);
        if (!disposed) setTaskEvents(result.events);
      } catch {
        // The Agent can take a moment to emit the first event after the run ID is allocated.
      }
    };

    void loadTimeline();
    const isActive = workflow.phase === "preparing" || workflow.phase === "cancelling" || workflow.phase === "committing";
    const timer = isActive ? window.setInterval(() => void loadTimeline(), 700) : undefined;
    return () => {
      disposed = true;
      if (timer !== undefined) window.clearInterval(timer);
    };
  }, [activeRunId, workflow.phase]);

  function toggleFolder(id: string) {
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function beginResize(side: ResizeSide, event: MouseEvent<HTMLDivElement>) {
    event.preventDefault();
    const workbench = workbenchRef.current;
    if (!workbench) return;

    // Width is derived from the pointer's distance to the relevant workbench edge.
    // Keeping resize state here avoids re-rendering the three independent scrollers.
    const onPointerMove = (moveEvent: globalThis.MouseEvent) => {
      const bounds = workbench.getBoundingClientRect();
      if (side === "left") {
        setPanelWidth("left", clamp(moveEvent.clientX - bounds.left, 190, 380));
      } else {
        const maximum = Math.min(560, bounds.width * 0.48);
        setPanelWidth("right", clamp(bounds.right - moveEvent.clientX, 310, maximum));
      }
    };
    const stopResize = () => {
      window.removeEventListener("mousemove", onPointerMove);
      window.removeEventListener("mouseup", stopResize);
      document.body.classList.remove("is-resizing");
    };

    document.body.classList.add("is-resizing");
    window.addEventListener("mousemove", onPointerMove);
    window.addEventListener("mouseup", stopResize);
  }

  async function ensureAgentThread() {
    if (agentThreadIdRef.current) return agentThreadIdRef.current;
    const thread = await postJson<{ thread_id: string }>("/api/agent/threads", {});
    agentThreadIdRef.current = thread.thread_id;
    setActiveThreadId(thread.thread_id);
    return thread.thread_id;
  }

  async function runAgent(text: string) {
    const threadId = await ensureAgentThread();
    const run = await postJson<AgentRun>("/api/agent/runs", {
      thread_id: threadId,
      message: text,
      project_id: "cellwiki",
      page_id: composerPageRef?.page_id ?? null,
      source_id: null,
      attachment_ids: activeAttachmentIds,
      selected_text: selectedText || null,
    });
    processedAgentEventsRef.current.clear();
    agentEventSequenceRef.current = 0;
    setActiveAgentRunId(run.run_id);
    setRetryableAgentRunId(null);
    window.localStorage.setItem(agentRunStorageKey(threadId), run.run_id);
    const status = await subscribeToAgentRun(run.run_id);
    return { threadId, runId: run.run_id, status };
  }

  async function resumeAgent(runId: string, decision: "approve" | "reject") {
    await postJson<AgentRun>(`/api/agent/runs/${encodeURIComponent(runId)}/resume`, { decision });
    setActiveAgentRunId(runId);
    if (agentThreadIdRef.current) window.localStorage.setItem(agentRunStorageKey(agentThreadIdRef.current), runId);
    return subscribeToAgentRun(runId);
  }

  function applyAgentEvent(event: AgentEvent, options: { replayChat?: boolean } = {}) {
    const renderChat = options.replayChat ?? true;
    if (processedAgentEventsRef.current.has(event.event_id)) return;
    processedAgentEventsRef.current.add(event.event_id);
    agentEventSequenceRef.current = Math.max(agentEventSequenceRef.current, event.sequence);
    if (renderChat) {
      setMessages((current) => reduceAgentRunMessages(current, event, {
        evidenceMeta: t("chat.evidenceMeta"),
        failed: t("chat.runFailed"),
        cancelled: t("chat.runCancelled"),
        formatConfidence: (confidence) => localizedConfidence(confidence, language),
      }));
    }
    if (event.type === "error" && event.data.retryable === true) {
      setRetryableAgentRunId(event.run_id);
    }
    if (event.type === "review_required") {
      const changeSetId = findNestedString(event.data, "change_set_id");
      if (changeSetId) {
        setPendingInterrupt({ threadId: event.thread_id, runId: event.run_id, changeSetId });
        setSelectedChangeSetId(changeSetId);
        setMessages((current) => current.some(
          (message) => message.runId === event.run_id && message.meta === t("chat.humanReviewMeta"),
        ) ? current : [...current, {
          role: "agent",
          text: t("workflow.approvalRequired").replace("{id}", changeSetId),
          meta: t("chat.humanReviewMeta"),
          runId: event.run_id,
        }]);
        void refreshWorkspace();
      }
    } else if (event.type === "changeset_ready") {
      const changeSetId = findNestedString(event.data, "change_set_id");
      if (changeSetId) {
        setSelectedChangeSetId(changeSetId);
        setPendingInterrupt({
          threadId: event.thread_id,
          runId: event.run_id,
          changeSetId,
        });
        void refreshWorkspace();
      }
      setAgentActivity(event.message || t("workflow.review"));
    }

    if (event.type === "tool_started") setAgentActivity(t("chat.toolRunning"));
    if (event.type === "tool_completed") setAgentActivity(t("chat.toolCompleted"));
    if (event.type === "subagent_completed") setAgentActivity(t("chat.subagentCompleted"));
    if (event.type === "verification") setAgentActivity(t("chat.verifying"));
    if (event.type === "progress" && event.message) setAgentActivity(event.message);
    if (event.type === "run_status") {
      const status = event.data.status as AgentRunStatus | undefined;
      if (status === "cancelling") setAgentActivity(t("chat.cancelling"));
      if (status === "retrying") setAgentActivity(t("chat.retrying"));
      if (status === "applying" || status === "verifying") setAgentActivity(t("chat.verifying"));
      if (status === "cancelled") {
        setAgentActivity(t("chat.runCancelled"));
        setWorkflow((current) => (
          current.phase === "preparing" || current.phase === "cancelling"
            ? { phase: "cancelled", message: t("workflow.cancelled") }
            : current
        ));
      }
      if (status && terminalAgentStatuses.has(status)) {
        setAgentBusy(false);
        if (status !== "waiting_approval") {
          setPendingInterrupt((current) => (
            current?.runId === event.run_id ? null : current
          ));
        }
        if (status !== "waiting_confirmation" && status !== "waiting_approval") {
          setActiveAgentRunId(null);
          window.localStorage.removeItem(agentRunStorageKey(event.thread_id));
        }
      }
    }
  }

  function subscribeToAgentRun(runId: string): Promise<AgentRunStatus> {
    agentEventSourceRef.current?.close();
    const generation = ++streamGenerationRef.current;
    return new Promise((resolve) => {
      const connect = () => {
        if (generation !== streamGenerationRef.current) return;
        const source = new EventSource(apiUrl(
          `/api/agent/runs/${encodeURIComponent(runId)}/stream?after=${agentEventSequenceRef.current}`,
        ));
        agentEventSourceRef.current = source;

        const handleEvent = (message: MessageEvent<string>) => {
          const event = JSON.parse(message.data) as AgentEvent;
          applyAgentEvent(event);
          if (event.type === "run_status") {
            const status = event.data.status as AgentRunStatus | undefined;
            if (status && terminalAgentStatuses.has(status)) {
              source.close();
              if (agentEventSourceRef.current === source) agentEventSourceRef.current = null;
              resolve(status);
            }
          }
        };
        agentEventTypes.forEach((eventType) => source.addEventListener(eventType, handleEvent as EventListener));
        source.onerror = () => {
          source.close();
          if (generation !== streamGenerationRef.current) return;
          // Read durable state before reconnecting so a dropped terminal event cannot
          // leave the desktop busy, and no already-executed side effect is replayed.
          void Promise.all([
            getJson<AgentRun>(`/api/agent/runs/${encodeURIComponent(runId)}`),
            getJson<AgentEvent[]>(
              `/api/agent/runs/${encodeURIComponent(runId)}/events?after=${agentEventSequenceRef.current}`,
            ),
          ])
            .then(([run, missedEvents]) => {
              missedEvents.forEach((event) => applyAgentEvent(event));
              if (terminalAgentStatuses.has(run.status)) {
                if (!missedEvents.some(
                  (event) => event.type === "run_status" && event.data.terminal === true,
                )) {
                  applyAgentEvent(legacyTerminalEvent(run, agentEventSequenceRef.current + 1));
                }
                resolve(run.status);
              } else {
                window.setTimeout(connect, 400);
              }
            })
            .catch(() => window.setTimeout(connect, 800));
        };
      };
      connect();
    });
  }

  async function restoreAgentThread(threadId: string, preferredRunId?: string) {
    try {
      const [history, runs] = await Promise.all([
        getJson<AgentMessage[]>(`/api/agent/threads/${encodeURIComponent(threadId)}/messages`),
        getJson<AgentRun[]>(`/api/agent/runs?thread_id=${encodeURIComponent(threadId)}&limit=1`),
      ]);
      if (history.length > 0) {
        setMessages(history.map(historyMessageToChatMessage));
      }
      const threadAttachments = await getJson<AttachmentRecord[]>(
        `/api/agent/threads/${encodeURIComponent(threadId)}/attachments`,
      );
      setAttachments(threadAttachments);
      setActiveAttachmentIds(threadAttachments.map((attachment) => attachment.attachment_id));
      const latestRun = runs[0];
      const runId = preferredRunId ?? latestRun?.run_id;
      if (runId) await restoreAgentRun(runId, { replayChat: false });
    } catch {
      // A missing or deleted session must not prevent the user from starting a new one.
      setMessages((current) => current.length > 0 ? current : [initialAgentMessage]);
    }
  }

  async function restoreAgentRun(runId: string, options: { replayChat?: boolean } = {}) {
    try {
      const [run, events] = await Promise.all([
        getJson<AgentRun>(`/api/agent/runs/${encodeURIComponent(runId)}`),
        getJson<AgentEvent[]>(`/api/agent/runs/${encodeURIComponent(runId)}/events`),
      ]);
      agentThreadIdRef.current = run.thread_id;
      setActiveThreadId(run.thread_id);
      events.forEach((event) => applyAgentEvent(event, options));
      if (
        terminalAgentStatuses.has(run.status)
        && !events.some(
          (event) => event.type === "run_status" && event.data.terminal === true,
        )
      ) {
        applyAgentEvent(
          legacyTerminalEvent(run, (events.at(-1)?.sequence ?? 0) + 1),
          options,
        );
      }
      if (run.status === "waiting_confirmation" || run.status === "waiting_approval") {
        setActiveAgentRunId(runId);
        setAgentBusy(false);
      } else if (!terminalAgentStatuses.has(run.status)) {
        setActiveAgentRunId(runId);
        setAgentBusy(true);
        setAgentActivity(t("chat.reconnected"));
        await subscribeToAgentRun(runId);
      } else {
        if (run.status === "failed" && run.retryable) setRetryableAgentRunId(runId);
        window.localStorage.removeItem(agentRunStorageKey(run.thread_id));
      }
    } catch {
      if (agentThreadIdRef.current) window.localStorage.removeItem(agentRunStorageKey(agentThreadIdRef.current));
    }
  }

  async function deleteAgentThread(threadId: string) {
    if (!window.confirm(t("threads.deleteConfirm"))) return;
    try {
      await deleteJson<{ thread_id: string; deleted_runs: number }>(
        `/api/agent/threads/${encodeURIComponent(threadId)}`,
      );
      window.localStorage.removeItem(agentRunStorageKey(threadId));
      if (agentThreadIdRef.current === threadId) {
        agentEventSourceRef.current?.close();
        agentEventSourceRef.current = null;
        streamGenerationRef.current += 1;
        agentThreadIdRef.current = null;
        setActiveThreadId(null);
        setAttachments([]);
        clearActiveAttachments();
        setActiveAgentRunId(null);
        setRetryableAgentRunId(null);
        setPendingInterrupt(null);
        setMessages([initialAgentMessage]);
      }
    } catch (error) {
      setMessages((current) => [...current, {
        role: "agent",
        text: error instanceof Error ? error.message : t("threads.deleteFailed"),
        meta: t("threads.deleteFailed"),
      }]);
    }
  }

  async function sendMessage() {
    const text = draft.trim();
    if (!text || agentBusy) return;
    setDraft("");
    setMessages((current) => [...current, { role: "user", text }]);
    setAgentBusy(true);
    try {
      await runAgent(text);
    } catch (error) {
      const failure = agentRequestFailure(
        error,
        isDesktopRuntime ? t("workflow.runtimeDesktop") : t("workflow.runtimeWeb"),
      );
      setMessages((current) => [...current, {
        role: "agent",
        text: failure.text,
        meta: failure.meta,
      }]);
    } finally {
      setAgentBusy(false);
    }
  }

  async function loadChangeSetReview(changeSetId: string) {
    const cached = reviews.find((review) => review.change_set.change_set_id === changeSetId);
    return cached ?? getJson<ChangeSetReview>(`/api/changesets/${encodeURIComponent(changeSetId)}/review`);
  }

  async function requestIngestRevision(comment: string) {
    const changeSetId = selectedReview?.change_set.change_set_id;
    if (!changeSetId) return;
    await requestIngestRevisionForChangeSet(changeSetId, comment);
  }

  async function requestIngestRevisionForChangeSet(changeSetId: string, comment: string) {
    if (agentBusy) return;
    setWorkflow({ phase: "preparing", message: t("workflow.preparing") });
    setAgentBusy(true);
    setMessages((current) => [
      ...current,
      { role: "user", text: `${t("source.requestRevision")}: ${comment}` },
    ]);
    try {
      if (pendingInterrupt?.changeSetId === changeSetId) {
        await resumeAgent(pendingInterrupt.runId, "reject");
        setPendingInterrupt(null);
      }
      await runAgent(
        `Revise ChangeSet ${changeSetId} using this reviewer feedback: ${comment}`,
      );
    } catch (error) {
      setWorkflow({
        phase: "failed",
        message: t("workflow.proposalFailed"),
        error: error instanceof Error ? error.message : "Unknown revision error",
      });
    } finally {
      setAgentBusy(false);
    }
  }

  async function approveChangeSet(requestedChangeSetId?: string) {
    const changeSetId = requestedChangeSetId ?? selectedReview?.change_set.change_set_id;
    if (!changeSetId || agentBusy) return;
    setWorkflow({ phase: "committing", message: t("workflow.committing") });
    setAgentBusy(true);
    try {
      const review = await loadChangeSetReview(changeSetId);
      setSelectedChangeSetId(changeSetId);
      setActiveRunId(review.change_set.run_id);
      if (pendingInterrupt?.changeSetId === changeSetId) {
        await resumeAgent(pendingInterrupt.runId, "approve");
        setPendingInterrupt(null);
      } else {
        await postJson<ChangeSetReview>(`/api/changesets/${changeSetId}/decision`, {
          approved: true,
          reason: "Reviewed and approved in the CellWiki desktop workspace.",
        });
      }
      const refreshed = await refreshWorkspace();
      const committed = refreshed.reviews.find((review) => review.change_set.change_set_id === changeSetId);
      if (committed?.status !== "committed") throw new Error("The commit did not reach a committed state.");
      setWorkflow({ phase: "committed", message: t("workflow.committed") });
      setMessages((current) => [...current, { role: "agent", text: `${changeSetId} was committed. The Wiki projection and quality report are refreshed.`, meta: t("chat.commitMeta") }]);
    } catch (error) {
      setWorkflow({ phase: "failed", message: t("workflow.commitFailed"), error: error instanceof Error ? error.message : "Unknown commit error" });
    } finally {
      setAgentBusy(false);
    }
  }

  async function rejectChangeSet(requestedChangeSetId?: string) {
    const changeSetId = requestedChangeSetId ?? selectedReview?.change_set.change_set_id;
    if (!changeSetId || agentBusy) return;
    setAgentBusy(true);
    try {
      const review = await loadChangeSetReview(changeSetId);
      setSelectedChangeSetId(changeSetId);
      setActiveRunId(review.change_set.run_id);
      if (pendingInterrupt?.changeSetId === changeSetId) {
        await resumeAgent(pendingInterrupt.runId, "reject");
        setPendingInterrupt(null);
      }
      await postJson<ChangeSetReview>(`/api/changesets/${changeSetId}/decision`, {
        approved: false,
        reason: "Rejected in the CellWiki desktop workspace.",
      });
      await refreshWorkspace();
      setWorkflow({ phase: "rejected", message: t("workflow.rejected") });
      setMessages((current) => [...current, { role: "agent", text: `${changeSetId} was rejected. No formal knowledge was changed.`, meta: t("chat.rejectedMeta") }]);
    } catch (error) {
      setWorkflow({ phase: "failed", message: t("workflow.rejectFailed"), error: error instanceof Error ? error.message : "Unknown review error" });
    } finally {
      setAgentBusy(false);
    }
  }

  async function rollbackChangeSet() {
    if (!selectedReview || selectedReview.status !== "committed" || agentBusy) return;
    if (!window.confirm(t("source.rollbackConfirm"))) return;
    const changeSetId = selectedReview.change_set.change_set_id;
    setWorkflow({ phase: "committing", message: t("workflow.rollback") });
    setAgentBusy(true);
    try {
      await postJson<ChangeSetReview>(`/api/changesets/${changeSetId}/rollback`, {
        reason: "Rolled back from the CellWiki desktop review workspace.",
      });
      await refreshWorkspace();
      setSelectedChangeSetId(changeSetId);
      setWorkflow({ phase: "rolled_back", message: t("workflow.rolledBack") });
    } catch (error) {
      setWorkflow({
        phase: "failed",
        message: t("workflow.rollbackFailed"),
        error: error instanceof Error ? error.message : t("workflow.rollbackFailed"),
      });
    } finally {
      setAgentBusy(false);
    }
  }

  async function cancelActiveAgentRun() {
    if (!activeAgentRunId) return;
    setWorkflow((current) => current.phase === "preparing"
      ? { phase: "cancelling", message: t("workflow.cancelling") }
      : current);
    try {
      const run = await postJson<AgentRun>(
        `/api/agent/runs/${encodeURIComponent(activeAgentRunId)}/cancel`,
        {},
      );
      if (run.status === "cancelled") {
        setWorkflow((current) => current.phase === "preparing" || current.phase === "cancelling"
          ? { phase: "cancelled", message: t("workflow.cancelled") }
          : current);
        setPendingInterrupt(null);
        setActiveAgentRunId(null);
        setAgentBusy(false);
        setAgentActivity(t("chat.runCancelled"));
        if (agentThreadIdRef.current) window.localStorage.removeItem(agentRunStorageKey(agentThreadIdRef.current));
      } else {
        setAgentActivity(t("chat.cancelling"));
      }
    } catch (error) {
      setWorkflow((current) => current.phase === "cancelling"
        ? { phase: "failed", message: t("workflow.proposalFailed"), error: error instanceof Error ? error.message : t("source.failedTitle") }
        : current);
      setMessages((current) => [...current, {
        role: "agent",
        text: error instanceof Error ? error.message : t("chat.runFailed"),
        meta: "RUNTIME · CANCEL ERROR",
      }]);
    }
  }

  async function retryAgentRun() {
    if (!retryableAgentRunId || agentBusy) return;
    const runId = retryableAgentRunId;
    setAgentBusy(true);
    setAgentActivity(t("chat.retrying"));
    setRetryableAgentRunId(null);
    setActiveAgentRunId(runId);
    if (agentThreadIdRef.current) window.localStorage.setItem(agentRunStorageKey(agentThreadIdRef.current), runId);
    try {
      await postJson<AgentRun>(`/api/agent/runs/${encodeURIComponent(runId)}/retry`, {});
      await subscribeToAgentRun(runId);
    } catch (error) {
      setAgentBusy(false);
      setMessages((current) => [...current, {
        role: "agent",
        text: error instanceof Error ? error.message : t("chat.runFailed"),
        meta: "RUNTIME · RETRY ERROR",
      }]);
    }
  }

  async function uploadSource(file: File) {
    const body = new FormData();
    body.append("file", file);
    try {
      const response = await productFetch("/api/sources", { method: "POST", body });
      if (!response.ok) throw new Error("upload failed");
      const source = await response.json() as Source;
      setSources((current) => [source, ...current.filter((item) => item.source_id !== source.source_id)]);
      setSelectedSourceId(source.source_id);
      setWorkflow({ phase: "idle", message: t("workflow.ready") });
      setMessages((current) => [...current, {
        role: "agent",
        text: t("workflow.sourceRegistered").replace("{name}", source.original_name),
        meta: t("chat.sourceReadyMeta"),
      }]);
    } catch {
      setMessages((current) => [...current, {
        role: "agent",
        text: t("workflow.sourceRegistrationFailed"),
        meta: t("chat.sourceErrorMeta"),
      }]);
    }
  }

  async function uploadAgentAttachments(fileList: FileList | null) {
    const files = Array.from(fileList ?? []);
    if (files.length === 0) return;
    try {
      const threadId = await ensureAgentThread();
      const body = new FormData();
      files.forEach((file) => body.append("files", file));
      const response = await productFetch(
        `/api/agent/threads/${encodeURIComponent(threadId)}/attachments`,
        { method: "POST", body },
      );
      if (!response.ok) throw new Error("attachment upload failed");
      const uploaded = await response.json() as AttachmentRecord[];
      setAttachments((current) => [
        ...uploaded,
        ...current.filter((item) => !uploaded.some((next) => next.attachment_id === item.attachment_id)),
      ]);
      setActiveAttachmentIds([...activeAttachmentIds, ...uploaded.map((item) => item.attachment_id)]);
    } catch {
      setMessages((current) => [...current, {
        role: "agent",
        text: t("chat.attachmentUploadFailed"),
        meta: t("chat.sourceErrorMeta"),
      }]);
    }
  }

  async function startNewChat() {
    if (agentBusy || pendingInterrupt) return;
    agentEventSourceRef.current?.close();
    streamGenerationRef.current += 1;
    agentThreadIdRef.current = null;
    setActiveThreadId(null);
    setActiveAgentRunId(null);
    setRetryableAgentRunId(null);
    setAgentActivity("");
    agentEventSequenceRef.current = 0;
    processedAgentEventsRef.current.clear();
    setPendingInterrupt(null);
    setAttachments([]);
    clearActiveAttachments();
    setDraft("");
    try {
      const thread = await postJson<{ thread_id: string }>("/api/agent/threads", {});
      agentThreadIdRef.current = thread.thread_id;
      setActiveThreadId(thread.thread_id);
      setMessages([{
        ...initialAgentMessage,
        text: t("workflow.newConversation").replace(
          "{context}",
          composerPageRef?.title ?? t("reader.workspace"),
        ),
      }]);
    } catch {
      setMessages([{ ...initialAgentMessage, text: t("workflow.newConversation").replace("{context}", contextTitle) }]);
    }
  }

  function openCitation(citation: Citation) {
    // A citation changes only the reader context; the conversation remains intact.
    setSelectedSourceId(null);
    setSelectedId(citation.page_id);
    setActiveView("wiki");
  }

  function openSearchResult(result: SearchResult) {
    if (result.source_id && result.type === "source") {
      setSelectedSourceId(result.source_id);
      setActiveView("sources");
      return;
    }
    if (result.page_id) {
      setSelectedId(result.page_id);
      setSelectedSourceId(null);
      setActiveView("wiki");
      return;
    }
    if (result.source_id) {
      setSelectedSourceId(result.source_id);
      setActiveView("sources");
    }
  }

  return (
    <main className="app-shell">
      <ZoomController
        zoomInLabel={t("zoom.in")}
        zoomOutLabel={t("zoom.out")}
        resetLabel={t("zoom.reset")}
      />
      <header className="app-titlebar">
        <div className="titlebar-brand">
          <span className="brand-glyph">CW</span>
          <strong>CellWiki</strong>
          <span className="titlebar-separator" />
          <span>cellwiki</span>
        </div>
        <div className="titlebar-status">
          <span className={apiOnline ? "connection online" : "connection"}><i />{apiOnline ? t("app.apiConnected") : t("app.localPreview")}</span>
          {isDesktopRuntime && <span>{t("app.desktop")}</span>}
          <ThemeToggle lightLabel={t("theme.switchLight")} darkLabel={t("theme.switchDark")} />
        </div>
      </header>

      <div className="app-body">
        <nav className="icon-rail" aria-label={t("nav.workspace")}>
          <div className="rail-main">
            <button className={activeView === "wiki" ? "rail-button active" : "rail-button"} onClick={() => { setActiveView("wiki"); setSelectedSourceId(null); setSelectedChangeSetId(null); }} title={t("nav.wiki")} aria-label={t("nav.wiki")}><PanelLeft size={19} /></button>
            <button className="rail-button" onClick={() => document.querySelector<HTMLTextAreaElement>(".chat-compose textarea")?.focus()} title={t("nav.agent")} aria-label={t("nav.agent")}><MessageSquareText size={19} /></button>
            <button className={activeView === "search" ? "rail-button active" : "rail-button"} onClick={() => setActiveView("search")} title={t("nav.search")} aria-label={t("nav.search")}><Search size={19} /></button>
            <button className={activeView === "sources" ? "rail-button active" : "rail-button"} onClick={() => { setActiveView("sources"); if (sources[0] && !selectedSourceId) setSelectedSourceId(sources[0].source_id); else if (!sources[0]) fileRef.current?.click(); }} title={t("nav.sources")} aria-label={t("nav.sources")}><Database size={19} /></button>
          </div>
          <div className="rail-bottom">
            <span className={apiOnline ? "rail-health online" : "rail-health"} title={apiOnline ? t("runtime.online") : t("runtime.offline")} />
            <button className={activeView === "settings" ? "rail-button active" : "rail-button"} onClick={() => setActiveView("settings")} title={t("nav.settings")} aria-label={t("nav.settings")}><Settings size={18} /></button>
          </div>
        </nav>

        {activeView === "settings" ? (
          <Suspense fallback={<div className="feature-state">{t("workspace.loading")}</div>}>
            <SettingsView onClose={() => setActiveView("wiki")} />
          </Suspense>
        ) : (
        <div className="workbench" ref={workbenchRef}>
          <aside className="file-panel" style={{ width: leftWidth }}>
            <div className="panel-toolbar">
              <span>{t("explorer.title")}</span>
              <button className="icon-button" onClick={() => fileRef.current?.click()} title={t("explorer.register")} aria-label={t("explorer.register")}><Upload size={14} /></button>
            </div>
            <div className="file-search">
              <Search size={14} />
              <input ref={filterRef} value={filter} onChange={(event) => setFilter(event.target.value)} placeholder={t("explorer.filter")} />
              <kbd>Ctrl K</kbd>
            </div>

            <div className="file-tree-scroll">
              <div className="tree-label">CELLWIKI</div>
              <TreeFolder label="CellWiki" depth={0} open={expanded.has("root")} onToggle={() => toggleFolder("root")}>
                <TreeFolder label="wiki" depth={1} open={expanded.has("wiki")} onToggle={() => toggleFolder("wiki")}>
                  <TreeFolder label="cell_types" depth={2} open={expanded.has("cell-types")} onToggle={() => toggleFolder("cell-types")} count={filteredPages.length}>
                    {filteredPages.map((page) => (
                      <button
                        className={page.page_id === selectedId ? "tree-file selected" : "tree-file"}
                        style={{ paddingLeft: 18 + 16 * 3 }}
                        key={page.page_id}
                        onClick={() => {
                          setActiveView("wiki");
                          setSelectedId(page.page_id);
                          setComposerPageRef({
                            page_id: page.page_id,
                            title: page.title ?? fileNameForPage(page),
                            path: page.path,
                          });
                          setSelectedSourceId(null);
                          setSelectedChangeSetId(null);
                        }}
                        title={page.path}
                      >
                        <FileText size={14} />
                        <span>{fileNameForPage(page)}</span>
                      </button>
                    ))}
                    {filteredPages.length === 0 && <div className="tree-empty">{t("explorer.noMatches")}</div>}
                  </TreeFolder>
                </TreeFolder>
                <TreeFolder label="sources" depth={1} open={expanded.has("sources")} onToggle={() => toggleFolder("sources")} count={sources.length}>
                  {sources.map((source) => (
                    <button className={source.source_id === selectedSourceId ? "tree-source selected" : "tree-source"} style={{ paddingLeft: 18 + 16 * 2 }} key={source.source_id} title={source.content_hash} onClick={() => { setActiveView("sources"); setSelectedSourceId(source.source_id); setSelectedChangeSetId(null); }}>
                      <FileText size={14} />
                      <span>{source.original_name}</span>
                      <i className={source.status === "analyzed" ? "source-state analyzed" : "source-state ready"} />
                    </button>
                  ))}
                  {sources.length === 0 && <div className="tree-empty source-empty">{t("explorer.noSources")}</div>}
                </TreeFolder>
              </TreeFolder>
            </div>

            <div className="file-panel-footer">
              <button onClick={() => fileRef.current?.click()}><CirclePlus size={14} />{t("explorer.register")}</button>
              <span>{pages.length} {t("explorer.pages")}</span>
              <input
                ref={fileRef}
                type="file"
                accept=".pdf,.md,.txt"
                hidden
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file) void uploadSource(file);
                  event.currentTarget.value = "";
                }}
              />
            </div>
          </aside>

          <div className="resize-handle" onMouseDown={(event) => beginResize("left", event)} role="separator" aria-label={t("explorer.resize")} />

          <section className="reader-panel">
            <div className="reader-toolbar">
              <div className="breadcrumb-path">
                {selectedSource ? <Database size={14} /> : <Library size={14} />}
                {contextPath.split("/").map((part, index, parts) => (
                  <span key={`${part}-${index}`}>{part}{index < parts.length - 1 && <ChevronRight size={12} />}</span>
                ))}
              </div>
              <span className={selectedSource ? "published-state review" : "published-state"}><i />{selectedSource ? t("reader.review") : t("reader.published")}</span>
            </div>

            <div className="reader-scroll">
              {workspaceQuery.isLoading ? (
                <div className="feature-state">{t("workspace.loading")}</div>
              ) : workspaceQuery.isError ? (
                <div className="feature-state error">{t("workspace.offline")}</div>
              ) : activeView === "graph" ? (
                <Suspense fallback={<div className="feature-state">{t("workspace.graphLoading")}</div>}>
                  <GraphWorkspace
                    focus={`cell_type:${selectedId}`}
                    onOpenPage={(pageId) => { setSelectedId(pageId); setSelectedSourceId(null); setActiveView("wiki"); }}
                    onOpenSource={(sourceId) => { setSelectedSourceId(sourceId); setActiveView("sources"); }}
                  />
                </Suspense>
              ) : activeView === "search" ? (
                <SearchWorkspace onOpen={openSearchResult} />
              ) : activeView === "reviews" ? (
                <ReviewsWorkspace
                  reviews={reviews}
                  onOpen={(review) => {
                    setSelectedChangeSetId(review.change_set.change_set_id);
                    const target = review.change_set.operations[0]?.target_id;
                    if (target && sources.some((source) => source.source_id === target)) setSelectedSourceId(target);
                    setActiveView("sources");
                  }}
                />
              ) : selectedSource ? (
                <SourceReview
                  source={selectedSource}
                  review={selectedReview}
                  workflow={workflow}
                  quality={quality}
                  taskEvents={taskEvents}
                  onApprove={() => void approveChangeSet()}
                  onReject={() => void rejectChangeSet()}
                  onRollback={() => void rollbackChangeSet()}
                  onRequestRevision={(comment) => void requestIngestRevision(comment)}
                />
              ) : !selectedId ? (
                <div className="feature-state onboarding-empty">
                  <Library size={28} />
                  <strong>{t("reader.emptyTitle")}</strong>
                  <span>{t("reader.emptyBody")}</span>
                  <button onClick={() => fileRef.current?.click()}><Upload size={14} />{t("reader.addSource")}</button>
                </div>
              ) : pageQuery.isLoading ? (
                <div className="feature-state">{t("reader.pageLoading")}</div>
              ) : pageQuery.isError ? (
                <div className="feature-state error">{t("reader.pageError")}</div>
              ) : (
                <article className="wiki-document">
                  <div className="document-kicker">{t("reader.cellType").toUpperCase()} · {String(detail.frontmatter.cl_id ?? t("reader.unmapped").toUpperCase())}</div>
                  <h1>{selectedTitle}</h1>
                  <div className="document-meta">
                    <span>{references.length} {t("reader.references")}</span>
                    <span>{t("reader.stable")}</span>
                    <span>{t("reader.verified")}</span>
                    <button
                      className="document-graph-action"
                      onClick={() => setActiveView("graph")}
                      title={t("reader.viewGraph")}
                    >
                      <Network size={13} />
                      {t("reader.viewGraph")}
                    </button>
                  </div>
                  <MarkdownReader
                    markdown={detail.markdown}
                    onWikiLink={(pageId) => {
                      if (pages.some((page) => page.page_id === pageId)) {
                        setSelectedId(pageId);
                        setSelectedSourceId(null);
                      }
                    }}
                    onAskSelection={(text) => {
                      setSelectedText(text);
                      setDraft(text);
                    }}
                    onCheckEvidence={(text) => {
                      setSelectedText(text);
                      setDraft(`${t("selection.evidence")}: ${text}`);
                    }}
                    onProposeRevision={(text) => {
                      setSelectedText(text);
                      setDraft(`${t("selection.revise")}: ${text}`);
                    }}
                  />
                  <footer className="document-footer">
                    <div>
                      <b>{t("reader.sourceLedger")}</b>
                      <div className="reference-list">
                        {references.length > 0
                          ? references.slice(0, 6).map((reference, index) => <span key={`${String(reference)}-${index}`}>{formatReference(reference)}</span>)
                          : <span>{t("reader.noReferences")}</span>}
                      </div>
                    </div>
                    <span>{t("reader.projectionStable")}</span>
                  </footer>
                </article>
              )}
            </div>
          </section>

          <div className="resize-handle" onMouseDown={(event) => beginResize("right", event)} role="separator" aria-label={t("chat.resize")} />

          <aside className="agent-panel" style={{ width: rightWidth }}>
            <div className="agent-toolbar">
              <div className="agent-title"><span className="agent-icon"><Bot size={16} /></span><div><strong>WikiAgent</strong><small>{t("chat.subtitle")}</small></div></div>
              <div className="agent-toolbar-actions">
                {activeAgentRunId && (
                  <button className="icon-button stop-run" onClick={() => void cancelActiveAgentRun()} title={t("chat.cancel")} aria-label={t("chat.cancel")}><Square size={13} /></button>
                )}
                <button className="icon-button" disabled={agentBusy || pendingInterrupt !== null} onClick={startNewChat} title={t("chat.new")} aria-label={t("chat.new")}><CirclePlus size={16} /></button>
              </div>
            </div>
            <ThreadList
              currentThreadId={activeThreadId}
              onDelete={deleteAgentThread}
              onSelect={(thread) => {
                agentThreadIdRef.current = thread.threadId;
                setActiveThreadId(thread.threadId);
                void restoreAgentThread(thread.threadId, thread.latestRun.run_id);
              }}
            />
            <div className="agent-context">
              <span><i />{t("chat.agentContext")}</span>
              {composerPageRef && (
                <>
                  <strong>{composerPageRef.title}</strong>
                  <small>{composerPageRef.path ?? composerPageRef.page_id}</small>
                </>
              )}
              {activeAttachments.length > 0 && (
                <small>{t("chat.attachmentsAttached").replace("{count}", String(activeAttachments.length))}</small>
              )}
              {selectedText && <blockquote>{selectedText}</blockquote>}
            </div>

            {pendingInterrupt && (
              <AgentReviewCard
                changeSetId={pendingInterrupt.changeSetId}
                summary={(() => {
                  const review = reviews.find((item) => item.change_set.change_set_id === pendingInterrupt.changeSetId);
                  if (!review) return undefined;
                  return {
                    reason: review.change_set.reason,
                    risk: review.change_set.risk,
                    operationCount: review.change_set.operations.length,
                    evidenceCount: review.change_set.evidence.length,
                  } satisfies AgentReviewSummary;
                })()}
                allowRevision={(() => {
                  const review = reviews.find((item) => item.change_set.change_set_id === pendingInterrupt.changeSetId);
                  return !review?.change_set.operations.some((operation) => operation.type === "apply_lint_fix");
                })()}
                disabled={agentBusy}
                onApprove={() => void approveChangeSet(pendingInterrupt.changeSetId)}
                onReject={() => void rejectChangeSet(pendingInterrupt.changeSetId)}
                onRequestRevision={(comment) => void requestIngestRevisionForChangeSet(pendingInterrupt.changeSetId, comment)}
              />
            )}

            <div className="chat-scroll" ref={chatScrollRef}>
              <div className="chat-day">{t("chat.session")}</div>
              {messages.map((message, index) => (
                <AgentMessageBubble
                  key={`${message.role}-${message.runId ?? "message"}-${index}`}
                  message={message}
                  agentLabel="WikiAgent"
                  userLabel={t("agent.you")}
                  missingEvidenceLabel={t("chat.missingEvidence")}
                  processTitle={t("chat.process")}
                  processLiveLabel={t("chat.processLive")}
                  processCompletedLabel={t("chat.processCompleted")}
                  processEmptyLabel={t("chat.processEmpty")}
                  diagnosticsLabel={t("chat.runDetails")}
                  onCitationOpen={openCitation}
                />
              ))}
              {retryableAgentRunId && !agentBusy && (
                <button className="agent-retry" onClick={() => void retryAgentRun()}>
                  <RotateCcw size={12} />{t("chat.retry")}
                </button>
              )}
              {agentBusy && <div className="agent-thinking"><i /><i /><i /><span>{agentActivity || t("chat.tracing")}</span></div>}
            </div>

            <div className="composer-wrap">
              <div className="chat-compose">
                {(composerPageRef || activeAttachments.length > 0) && (
                  <div className="composer-reference-row">
                    {composerPageRef && (
                      <span className="composer-chip page-chip">
                        <FileText size={12} />
                        <span>{composerPageRef.title}</span>
                        <button type="button" onClick={() => setComposerPageRef(null)} aria-label={t("chat.clearReference")}><X size={11} /></button>
                      </span>
                    )}
                    {activeAttachments.map((attachment) => (
                      <span className="composer-chip attachment-chip" key={attachment.attachment_id}>
                        <Upload size={12} />
                        <span>{attachment.original_name}</span>
                        <button type="button" onClick={() => removeActiveAttachmentId(attachment.attachment_id)} aria-label={t("chat.clearReference")}><X size={11} /></button>
                      </span>
                    ))}
                  </div>
                )}
                <textarea
                  value={draft}
                  onChange={(event) => setDraft(event.target.value)}
                  onKeyDown={(event) => {
                    if (
                      event.key === "Backspace"
                      && !draft
                      && event.currentTarget.selectionStart === 0
                      && event.currentTarget.selectionEnd === 0
                      && (composerPageRef || activeAttachmentIds.length > 0)
                    ) {
                      event.preventDefault();
                      removeLastComposerReference();
                      return;
                    }
                    if (event.key === "Enter" && !event.shiftKey) {
                      event.preventDefault();
                      void sendMessage();
                    }
                  }}
                  placeholder={t("chat.composerPlaceholder")}
                  rows={3}
                />
                <div className="compose-actions">
                  <div className="compose-left">
                    <button
                      type="button"
                      className="compose-tool-button"
                      onClick={() => attachmentRef.current?.click()}
                      title={t("chat.addAttachment")}
                      aria-label={t("chat.addAttachment")}
                    >
                      <CirclePlus size={14} />
                    </button>
                    <span>{activeAttachments.length > 0 ? t("chat.attachmentsAttached").replace("{count}", String(activeAttachments.length)) : t("chat.agentContext")}</span>
                  </div>
                  <button onClick={() => void sendMessage()} disabled={!draft.trim() || agentBusy} aria-label={t("chat.send")}><Send size={15} /></button>
                </div>
                <input
                  ref={attachmentRef}
                  type="file"
                  accept=".pdf,.md,.txt,.csv,.json"
                  multiple
                  hidden
                  onChange={(event) => {
                    void uploadAgentAttachments(event.currentTarget.files);
                    event.currentTarget.value = "";
                  }}
                />
              </div>
            </div>
          </aside>
        </div>
        )}
      </div>
      <CommandPalette onOpen={openSearchResult} />
    </main>
  );
}

function findNestedString(value: unknown, key: string): string | null {
  if (Array.isArray(value)) {
    for (const item of value) {
      const found = findNestedString(item, key);
      if (found) return found;
    }
  } else if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    if (typeof record[key] === "string") return record[key];
    for (const item of Object.values(record)) {
      const found = findNestedString(item, key);
      if (found) return found;
    }
  }
  return null;
}

export function agentRequestFailure(error: unknown, offlineMessage: string) {
  if (error instanceof ProductApiError) {
    return {
      text: error.message,
      meta: `AGENT REQUEST FAILED · HTTP ${error.status}`,
    };
  }
  return { text: offlineMessage, meta: "RUNTIME OFFLINE" };
}

function legacyTerminalEvent(run: AgentRun, sequence: number): AgentEvent {
  return {
    event_id: `legacy-terminal-${run.run_id}-${run.status}`,
    run_id: run.run_id,
    thread_id: run.thread_id,
    sequence,
    type: "run_status",
    message: run.error_message ?? `Run ${run.status}.`,
    data: {
      status: run.status,
      terminal: true,
      error_type: run.error_type ?? null,
      error_message: run.error_message ?? null,
      retryable: run.retryable,
      finished_at: run.finished_at ?? null,
    },
    created_at: run.finished_at ?? new Date().toISOString(),
  };
}

function formatReference(reference: unknown) {
  if (typeof reference === "string") return reference;
  if (reference && typeof reference === "object") {
    const value = reference as { paper_id?: string; title?: string; locator?: string };
    return value.paper_id ?? value.title ?? value.locator ?? "Evidence reference";
  }
  return String(reference);
}

function localizedConfidence(value: string, language: "zh-CN" | "en") {
  if (language === "en") return `${value.toUpperCase()} CONFIDENCE`;
  return `${({ high: "高", medium: "中", low: "低" }[value.toLowerCase()] ?? value)}置信度`;
}

function TreeFolder({ label, depth, open, onToggle, count, children }: {
  label: string;
  depth: number;
  open: boolean;
  onToggle: () => void;
  count?: number;
  children: ReactNode;
}) {
  return (
    <div className="tree-folder">
      <button className="tree-folder-row" style={{ paddingLeft: 8 + depth * 16 }} onClick={onToggle}>
        {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
        {open ? <FolderOpen size={14} /> : <Folder size={14} />}
        <span>{label}</span>
        {count !== undefined && <small>{count}</small>}
      </button>
      {open && children}
    </div>
  );
}
