import { lazy, Suspense, useEffect, useMemo, useRef, useState, type MouseEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Bot,
  ChevronRight,
  FileText,
  GitPullRequest,
  Library,
  MessageSquareText,
  PanelLeft,
  Play,
  RefreshCw,
  RotateCcw,
  CirclePlus,
  Search,
  Send,
  Settings,
  Square,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import { ThemeToggle } from "../components/ThemeToggle";
import { ZoomController } from "../components/ZoomController";
import { useI18n } from "../i18n";
import { apiUrl, isDesktopRuntime, productFetch } from "../runtime";
import { deleteJson, getJson, postJson, ProductApiError } from "../lib/product-api";
import { MarkdownReader } from "../features/wiki/MarkdownReader";
import { useUiStore } from "../stores/ui-store";
import { appendAsyncTask, attachmentReferencesForIds } from "./attachment-upload-queue";
import { CommandPalette } from "../features/search/CommandPalette";
import { ThreadList } from "../features/agent/ThreadList";
import { AgentMessageBubble } from "../features/agent/AgentMessageBubble";
import { reduceAgentRunMessages, type AgentRunReducerLabels } from "../features/agent/agent-run-reducer";
import { QuestionCard } from "../features/agent/QuestionCard";
import { SearchWorkspace } from "../features/discovery/FeatureWorkspaces";
import { WorkspaceFileBrowser, type WorkspaceTreeEntry } from "../features/workspace/WorkspaceFileBrowser";
import { WorkspaceFileViewer } from "../features/workspace/WorkspaceFileViewer";
import { DiffBrowser } from "../features/diff/DiffBrowser";

const SettingsView = lazy(() => import("../components/SettingsView").then((module) => ({
  default: module.SettingsView,
})));
import type {
  AgentEvent,
  AgentEventType,
  AgentAnswer,
  AgentAttachmentReference,
  AgentMessage,
  AgentProcessStep,
  AgentRun,
  AgentRunStatus,
  AgentThreadEntry,
  AttachmentRecord,
  ChatMessage,
  Page,
  PageDetail,
  SearchResult,
} from "../types";

type ResizeSide = "left" | "right";

const agentEventTypes: AgentEventType[] = [
  "run_status",
  "message_delta",
  "reasoning_delta",
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

/** 暂停态 run：恢复会话时必须把事件流渲染回聊天，否则刷新后回答与问题卡会一起消失。 */
const pausedAgentStatuses = new Set<AgentRunStatus>([
  "waiting_confirmation",
  "waiting_approval",
  "unfinished",
]);
function agentRunStorageKey(contextKey: string) {
  return `cellwiki.agent.active_run_id.${contextKey}`;
}

function historyMessageToChatMessage(message: AgentMessage): ChatMessage {
  const data = message.data as Partial<AgentAnswer> & {
    process?: AgentProcessStep[];
    attachments?: unknown;
  };
  const attachments = Array.isArray(data.attachments)
    ? data.attachments.flatMap((item): AgentAttachmentReference[] => {
      if (!item || typeof item !== "object") return [];
      const candidate = item as Record<string, unknown>;
      if (typeof candidate.attachment_id !== "string") return [];
      return [{
        attachment_id: candidate.attachment_id,
        original_name: typeof candidate.original_name === "string" ? candidate.original_name : undefined,
        media_type: typeof candidate.media_type === "string" ? candidate.media_type : undefined,
        content_hash: typeof candidate.content_hash === "string" ? candidate.content_hash : undefined,
        size_bytes: typeof candidate.size_bytes === "number" ? candidate.size_bytes : undefined,
      }];
    })
    : [];
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
    attachments: attachments.length > 0 ? attachments : undefined,
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
};

async function loadWorkspaceData(): Promise<WorkspaceData> {
  const pages = await getJson<Page[]>("/api/projects/cellwiki/tree");
  return { pages };
}

export type CachedThreadState = {
  messages: ChatMessage[];
  draft: string;
  attachments: AttachmentRecord[];
  runId: string | null;
};

/**
 * 新建会话的乐观占位条目：服务端登记成功后会被同 `thread_id` 的真实条目替换，
 * 因此这里只保证"同一 tick 内可见且只有一条"。
 */
export function seedAgentThreadList(
  current: AgentThreadEntry[] | undefined,
  threadId: string,
  now: string,
): AgentThreadEntry[] {
  return [
    {
      thread_id: threadId,
      title: null,
      created_at: now,
      updated_at: now,
      run_count: 0,
      latest_run_id: null,
      latest_status: null,
    },
    ...(current ?? []).filter((thread) => thread.thread_id !== threadId),
  ];
}

/**
 * 空槽位回收判据。宁可少删不可多删：未知状态（没有本地缓存或注册表条目）一律保留，
 * 有草稿、附件或除欢迎语以外的消息也保留，尤其是首条消息因串行门禁 409 失败的会话。
 */
export function isDisposableEmptyThread(
  cached: CachedThreadState | undefined,
  entry: AgentThreadEntry | undefined,
): boolean {
  if (!cached || !entry) return false;
  if (entry.run_count > 0 || entry.latest_run_id) return false;
  return cached.draft.trim().length === 0
    && cached.attachments.length === 0
    && cached.messages.length <= 1;
}

function clamp(value: number, minimum: number, maximum: number) {
  return Math.min(Math.max(value, minimum), maximum);
}

function fileNameForPage(page: Page) {
  return page.path?.split("/").at(-1) ?? `${page.page_id}.md`;
}

export function resolveInitialPageId(
  pages: Page[],
  pageRef: { page_id: string } | null,
) {
  if (pageRef?.page_id && pages.some((page) => page.page_id === pageRef.page_id)) {
    return pageRef.page_id;
  }
  return pages[0]?.page_id ?? "";
}

export function AppShell() {
  const { language, t } = useI18n();
  const initialAgentMessage = useMemo<ChatMessage>(() => ({
    role: "agent",
    text: t("app.initialMessage"),
    meta: t("chat.queryMeta"),
  }), [t]);
  const [pages, setPages] = useState<Page[]>([]);
  const [selectedId, setSelectedId] = useState(
    () => useUiStore.getState().composerPageRef?.page_id ?? "",
  );
  const [detail, setDetail] = useState<PageDetail>(emptyPageDetail);
  const [filter, setFilter] = useState("");
  const [workspaceFile, setWorkspaceFile] = useState<WorkspaceTreeEntry | null>(null);
  const [diffPanelOpen, setDiffPanelOpen] = useState(false);
  // 记录打开 diff 审查前正在查看的页面/文件，关闭时恢复
  const diffReturnRef = useRef<{ workspaceFile: WorkspaceTreeEntry | null; selectedId: string }>({
    workspaceFile: null,
    selectedId: "",
  });
  const [pendingDiffCount, setPendingDiffCount] = useState(0);
  const [treeRefreshSignal, setTreeRefreshSignal] = useState(0);
  const [refreshing, setRefreshing] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([initialAgentMessage]);
  const [draft, setDraft] = useState("");
  const [agentBusy, setAgentBusy] = useState(false);
  const [activeAgentRunId, setActiveAgentRunId] = useState<string | null>(null);
  const [retryableAgentRunId, setRetryableAgentRunId] = useState<string | null>(null);
  const [resumableAgentRunId, setResumableAgentRunId] = useState<string | null>(null);
  const [agentActivity, setAgentActivity] = useState("");
  const [attachments, setAttachments] = useState<AttachmentRecord[]>([]);
  const [pendingInterrupt, setPendingInterrupt] = useState(null as { threadId: string; runId: string; changeSetId: string } | null);
  const [workflow, setWorkflow] = useState<{ phase: string; message: string; error?: string }>({ phase: "idle", message: t("workflow.ready") });
  const [attachmentUploadBusy, setAttachmentUploadBusy] = useState(false);
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
  const addActiveAttachmentIds = useUiStore((state) => state.addActiveAttachmentIds);
  const removeActiveAttachmentId = useUiStore((state) => state.removeActiveAttachmentId);
  const clearActiveAttachments = useUiStore((state) => state.clearActiveAttachments);
  const removeLastComposerReference = useUiStore((state) => state.removeLastComposerReference);
  const activeView = useUiStore((state) => state.activeView);
  const setActiveView = useUiStore((state) => state.setActiveView);
  const setCommandPaletteOpen = useUiStore((state) => state.setCommandPaletteOpen);
  const workbenchRef = useRef<HTMLDivElement>(null);
  const attachmentRef = useRef<HTMLInputElement>(null);
  const filterRef = useRef<HTMLInputElement>(null);
  const chatScrollRef = useRef<HTMLDivElement>(null);
  const agentThreadIdRef = useRef<string | null>(null);
  const agentEventSourceRef = useRef<EventSource | null>(null);
  const agentEventSequenceRef = useRef(0);
  const processedAgentEventsRef = useRef(new Set<string>());
  const streamGenerationRef = useRef(0);
  const messagesRef = useRef<ChatMessage[]>(messages);
  const attachmentRecordsRef = useRef<AttachmentRecord[]>([]);
  const attachmentUploadRef = useRef<Promise<void> | null>(null);
  const attachmentUploadErrorRef = useRef<Error | null>(null);
  const threadCreationRef = useRef<Promise<string> | null>(null);
  const queryClient = useQueryClient();
  // 每个会话保留一份本地聊天视图，离开会话时不丢正在流式输出的部分回答与草稿
  const threadStateCacheRef = useRef(new Map<string, CachedThreadState>());
  const threadRestorePrefRef = useRef<string | null>(null);
  const threadRestoreTokenRef = useRef(0);
  const renderedThreadIdRef = useRef<string | null>(null);

  function replaceAttachmentRecords(records: AttachmentRecord[]) {
    attachmentRecordsRef.current = records;
    setAttachments(records);
  }

  function mergeAttachmentRecords(uploaded: AttachmentRecord[]) {
    const next = [
      ...uploaded,
      ...attachmentRecordsRef.current.filter(
        (current) => !uploaded.some((record) => record.attachment_id === current.attachment_id),
      ),
    ];
    replaceAttachmentRecords(next);
  }

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
        unfinished: t("workflow.unfinished"),
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
    setApiOnline(true);
    if (workspaceQuery.data.pages.length === 0) {
      setSelectedId("");
      setDetail(emptyPageDetail);
    } else if (!workspaceQuery.data.pages.some((page) => page.page_id === selectedId)) {
      setSelectedId(resolveInitialPageId(workspaceQuery.data.pages, composerPageRef));
      if (composerPageRef && !workspaceQuery.data.pages.some((page) => page.page_id === composerPageRef.page_id)) {
        setComposerPageRef(null);
      }
    }
  }, [workspaceQuery.data, selectedId, composerPageRef, setComposerPageRef]);

  useEffect(() => {
    if (workspaceQuery.isError) setApiOnline(false);
  }, [workspaceQuery.isError]);

  async function refreshWorkspace() {
    const result = await workspaceQuery.refetch();
    if (!result.data) throw result.error ?? new Error("workspace unavailable");
    return result.data;
  }

  async function loadPendingDiffCount() {
    try {
      const data = await getJson<{ pending_diffs: { status: string }[] }>("/api/pending-diffs");
      setPendingDiffCount(data.pending_diffs.filter((item) => item.status === "pending").length);
    } catch {
      // 徽标保持当前值；DiffBrowser 打开时会自行刷新
    }
  }

  async function refreshWorkspaceState() {
    setRefreshing(true);
    try {
      await Promise.allSettled([
        workspaceQuery.refetch(),
        loadPendingDiffCount(),
        queryClient.invalidateQueries({ queryKey: ["agent-threads"] }),
      ]);
    } finally {
      setRefreshing(false);
    }
    setTreeRefreshSignal((current) => current + 1);
  }

  useEffect(() => {
    // 初始加载一次待审 Diff 徽标，避免 DiffBrowser 打开前恒为 0
    void loadPendingDiffCount();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!activeThreadId) {
      agentThreadIdRef.current = null;
      return () => {
        streamGenerationRef.current += 1;
        agentEventSourceRef.current?.close();
        agentEventSourceRef.current = null;
      };
    }
    // 会话切换统一走 restoreAgentThread：先缓存离开会话的本地视图，
    // 再结合历史与事件日志恢复目标会话（含仍在后台运行的 Agent）。
    const preferredRunId = threadRestorePrefRef.current
      ?? window.localStorage.getItem(agentRunStorageKey(activeThreadId))
      ?? undefined;
    threadRestorePrefRef.current = null;
    if (preferredRunId) {
      void restoreAgentThread(activeThreadId, preferredRunId);
    } else {
      agentThreadIdRef.current = activeThreadId;
    }
    return () => {
      streamGenerationRef.current += 1;
      agentEventSourceRef.current?.close();
      agentEventSourceRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeThreadId]);

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
  const selectedTitle = String(detail.frontmatter.display_name ?? selectedPage?.title ?? selectedId.replaceAll("_", " "));
  const selectedPath = selectedPage?.path ?? (selectedId ? `wiki/cell_types/${selectedId}.md` : "cellwiki");
  const contextTitle = selectedTitle || t("reader.workspace");
  const contextPath = selectedPath;
  const workspaceSelectedPath = workspaceFile?.path ?? (selectedPath.startsWith("wiki/") ? selectedPath : null);
  const references = Array.isArray(detail.frontmatter.references) ? detail.frontmatter.references : [];
  const activeAttachments = activeAttachmentIds
    .map((attachmentId) => attachments.find((attachment) => attachment.attachment_id === attachmentId))
    .filter((attachment): attachment is AttachmentRecord => Boolean(attachment));
  // 等待用户回答确认问题期间禁止发送新消息，并渲染问题卡/提示
  const waitingOnQuestion = activeAgentRunId != null
    && messages.some((message) => (
      message.role === "agent"
      && message.runId === activeAgentRunId
      && (message.runStatus === "waiting_confirmation" || message.runStatus === "waiting_approval")
    ));
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
    if (threadCreationRef.current) return threadCreationRef.current;
    const pending = postJson<{ thread_id: string }>("/api/agent/threads", {})
      .then((thread) => {
        agentThreadIdRef.current = thread.thread_id;
        setActiveThreadId(thread.thread_id);
        return thread.thread_id;
      });
    threadCreationRef.current = pending;
    try {
      return await pending;
    } finally {
      if (threadCreationRef.current === pending) threadCreationRef.current = null;
    }
  }

  async function waitForAgentAttachmentUploads() {
    // A file picker upload is asynchronous; bind the run only after every
    // upload started by the composer has committed its attachment record.
    while (attachmentUploadRef.current) {
      const pendingUpload = attachmentUploadRef.current;
      await pendingUpload;
    }
    if (attachmentUploadErrorRef.current) {
      const error = attachmentUploadErrorRef.current;
      attachmentUploadErrorRef.current = null;
      throw error;
    }
  }

  async function runAgent(
    text: string,
    options: {
      attachmentIds?: string[];
      clearPendingAttachments?: boolean;
      uploadsReady?: boolean;
      onAccepted?: () => void;
    } = {},
  ) {
    if (!options.uploadsReady) await waitForAgentAttachmentUploads();
    const threadId = await ensureAgentThread();
    const currentAttachmentIds = options.attachmentIds
      ?? useUiStore.getState().activeAttachmentIds;
    const run = await postJson<AgentRun>("/api/agent/runs", {
      thread_id: threadId,
      message: text,
      project_id: "cellwiki",
      page_id: composerPageRef?.page_id ?? null,
      source_id: null,
      attachment_ids: currentAttachmentIds,
      selected_text: selectedText || null,
    });
    queryClient.invalidateQueries({ queryKey: ["agent-threads"] });
    // The backend persists the user message while accepting the run. Only then
    // may the composer move its draft into the visible conversation history.
    options.onAccepted?.();
    if (options.clearPendingAttachments) clearActiveAttachments();
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
    if (event.thread_id !== agentThreadIdRef.current) return;
    const renderChat = options.replayChat ?? true;
    if (processedAgentEventsRef.current.has(event.event_id)) return;
    processedAgentEventsRef.current.add(event.event_id);
    agentEventSequenceRef.current = Math.max(agentEventSequenceRef.current, event.sequence);
    if (renderChat) {
      setMessages((current) => reduceAgentRunMessages(current, event, agentRunLabels()));
    }
    if (event.type === "error" && event.data.retryable === true) {
      setRetryableAgentRunId(event.run_id);
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
      if (status === "unfinished") {
        setAgentActivity(t("chat.runUnfinished"));
        setResumableAgentRunId(event.run_id);
      }
      if (status && terminalAgentStatuses.has(status)) {
        setAgentBusy(false);
        // Agent 运行结束（含 ingest 完成）后刷新文件树/页面/待审徽标
        void refreshWorkspaceState();
        queryClient.invalidateQueries({ queryKey: ["agent-threads"] });
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
          let event: AgentEvent;
          try {
            event = JSON.parse(message.data) as AgentEvent;
          } catch {
            // 畸形/空 payload 只丢弃当前事件，不再中断后续事件处理
            console.warn("[cellwiki] ignoring malformed agent event", message.data);
            return;
          }
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

  function buildTimelineContext(): { label: string; detail?: string } {
    const parts: string[] = [];
    parts.push(composerPageRef?.title ?? t("reader.workspace"));
    if (activeAttachments.length > 0) {
      parts.push(t("chat.attachmentsAttached").replace("{count}", String(activeAttachments.length)));
    }
    return { label: t("chat.contextInjection"), detail: parts.join(" · ") };
  }

  function agentRunLabels(): AgentRunReducerLabels {
    return {
      failed: t("chat.runFailed"),
      cancelled: t("chat.runCancelled"),
      unfinished: t("chat.runUnfinished"),
      timelineContext: buildTimelineContext(),
    };
  }

  function cacheCurrentThreadState(threadId: string | null) {
    if (!threadId || renderedThreadIdRef.current !== threadId) return;
    threadStateCacheRef.current.set(threadId, {
      messages: messagesRef.current,
      draft,
      attachments: attachmentRecordsRef.current,
      runId: activeAgentRunId,
    });
  }

  function seedThreadPlaceholder(threadId: string) {
    // 点 `+` 的那一刻就把占位条目写进会话列表缓存，用户不需要等 refetch
    // 就能在下拉里看到这个新会话，也不会被后续刷新挤出可回访位置。
    queryClient.setQueryData<AgentThreadEntry[]>(["agent-threads"], (current) => (
      seedAgentThreadList(current, threadId, new Date().toISOString())
    ));
  }

  async function disposeEmptyThread(threadId: string | null) {
    // 空槽位回收：从未产生 run、也没有草稿/附件/可见消息的新会话在离开后删除，
    // 避免会话登记表堆积无法解释的占位条目。任何本地内容都会保留会话，
    // 例如首条消息因串行门禁 409 失败的会话仍然可回访。
    if (!threadId || threadId === agentThreadIdRef.current) return;
    const listed = queryClient.getQueryData<AgentThreadEntry[]>(["agent-threads"]);
    const entry = listed?.find((thread) => thread.thread_id === threadId);
    if (!isDisposableEmptyThread(threadStateCacheRef.current.get(threadId), entry)) return;
    try {
      await deleteJson<{ thread_id: string; deleted_runs: number }>(
        `/api/agent/threads/${encodeURIComponent(threadId)}`,
      );
      threadStateCacheRef.current.delete(threadId);
      window.localStorage.removeItem(agentRunStorageKey(threadId));
      queryClient.invalidateQueries({ queryKey: ["agent-threads"] });
    } catch {
      // 回收失败不打断切换：占位条目留在列表里由用户手删。
    }
  }

  async function restoreAgentThread(threadId: string, preferredRunId?: string) {
    const token = ++threadRestoreTokenRef.current;
    // 离开当前会话前缓存其本地视图（含正在流式输出的部分回答与草稿）
    const leavingThreadId = agentThreadIdRef.current;
    cacheCurrentThreadState(leavingThreadId);
    agentThreadIdRef.current = threadId;
    void disposeEmptyThread(leavingThreadId);
    setActiveThreadId(threadId);
    // A thread switch must not carry review cards, streams, or attachment chips across conversations.
    agentEventSourceRef.current?.close();
    agentEventSourceRef.current = null;
    streamGenerationRef.current += 1;
    setActiveAgentRunId(null);
    setRetryableAgentRunId(null);
    setResumableAgentRunId(null);
    setAgentActivity("");
    setAgentBusy(false);
    setWorkflow({ phase: "idle", message: t("workflow.ready") });
    const cached = threadStateCacheRef.current.get(threadId);
    // 仅当缓存是“真实会话内容”（非欢迎语/空聊天）时使用，避免占位内容覆盖历史
    const cacheUsable = cached != null && (
      cached.messages.length > 1
      || (cached.messages.length === 1 && cached.messages[0]?.role === "user")
      || cached.messages.some((message) => message.runId)
    );
    const baseMessages = cacheUsable && cached ? cached.messages : [initialAgentMessage];
    messagesRef.current = baseMessages;
    renderedThreadIdRef.current = threadId;
    if (cacheUsable && cached) {
      setMessages(cached.messages);
    } else {
      setMessages([initialAgentMessage]);
    }
    setDraft(cached?.draft ?? "");
    replaceAttachmentRecords(cacheUsable && cached ? cached.attachments : []);
    clearActiveAttachments();
    try {
      const [history, runs] = await Promise.all([
        getJson<AgentMessage[]>(`/api/agent/threads/${encodeURIComponent(threadId)}/messages`),
        getJson<AgentRun[]>(`/api/agent/runs?thread_id=${encodeURIComponent(threadId)}&limit=1`),
      ]);
      if (token !== threadRestoreTokenRef.current) return;
      // 本地缓存仍是该会话的最新视图；仅在没有可用缓存时才用历史接口铺底
      if (!cacheUsable && history.length > 0) {
        const historyMessages = history.map(historyMessageToChatMessage);
        messagesRef.current = historyMessages;
        setMessages(historyMessages);
      }
      const threadAttachments = await getJson<AttachmentRecord[]>(
        `/api/agent/threads/${encodeURIComponent(threadId)}/attachments`,
      );
      if (token !== threadRestoreTokenRef.current) return;
      if (!cacheUsable) replaceAttachmentRecords(threadAttachments);
      const latestRun = runs[0];
      const runId = preferredRunId ?? latestRun?.run_id;
      if (runId) await restoreAgentRun(runId, { base: messagesRef.current, token });
    } catch {
      // A missing or deleted session must not prevent the user from starting a new one.
      if (token !== threadRestoreTokenRef.current) return;
      setMessages((current) => current.length > 0 ? current : [initialAgentMessage]);
    }
  }

  async function restoreAgentRun(
    runId: string,
    options: { base?: ChatMessage[]; token?: number } = {},
  ) {
    try {
      const [run, events] = await Promise.all([
        getJson<AgentRun>(`/api/agent/runs/${encodeURIComponent(runId)}`),
        getJson<AgentEvent[]>(`/api/agent/runs/${encodeURIComponent(runId)}/events`),
      ]);
      if (options.token !== undefined && options.token !== threadRestoreTokenRef.current) return;
      agentThreadIdRef.current = run.thread_id;
      setActiveThreadId(run.thread_id);
      // 活跃/暂停态的回答只存在于事件日志；已终态的 run 也从事件重建，
      // 避免“先取到的历史缺少回答、事件里才有完整回答”的竞态导致丢消息。
      // 重建前剔除本地/历史里同 run 的旧 agent 消息，防止文本被重复追加。
      let transcript = rebuildAgentTranscript(
        options.base ?? messagesRef.current,
        runId,
        events,
        agentRunLabels(),
      );
      if (
        terminalAgentStatuses.has(run.status)
        && !events.some(
          (event) => event.type === "run_status" && event.data.terminal === true,
        )
      ) {
        transcript = reduceAgentRunMessages(
          transcript,
          legacyTerminalEvent(run, (events.at(-1)?.sequence ?? 0) + 1),
          agentRunLabels(),
        );
      }
      messagesRef.current = transcript;
      setMessages(transcript);
      agentEventSequenceRef.current = events.at(-1)?.sequence ?? 0;
      renderedThreadIdRef.current = run.thread_id;
      const paused = pausedAgentStatuses.has(run.status);
      if (paused && run.status !== "unfinished") {
        // 等待用户确认/审批：停在问题卡，由用户操作后再续跑
        setActiveAgentRunId(runId);
        setAgentBusy(false);
      } else if (run.status === "unfinished") {
        setAgentActivity(t("chat.runUnfinished"));
        setResumableAgentRunId(runId);
        setActiveAgentRunId(runId);
        setAgentBusy(false);
      } else if (!terminalAgentStatuses.has(run.status)) {
        // 仍在后台运行：恢复流式订阅，切回后进度继续
        setActiveAgentRunId(runId);
        setAgentBusy(true);
        setAgentActivity(t("chat.reconnected"));
        await subscribeToAgentRun(runId);
      } else {
        if (run.status === "failed" && run.retryable) setRetryableAgentRunId(runId);
        window.localStorage.removeItem(agentRunStorageKey(run.thread_id));
        // 运行在离开期间结束：恢复时同步一次工作区/待审徽标
        void refreshWorkspaceState();
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
      threadStateCacheRef.current.delete(threadId);
      if (agentThreadIdRef.current === threadId) {
        agentEventSourceRef.current?.close();
        agentEventSourceRef.current = null;
        streamGenerationRef.current += 1;
        agentThreadIdRef.current = null;
        setActiveThreadId(null);
        replaceAttachmentRecords([]);
        clearActiveAttachments();
        setActiveAgentRunId(null);
        setRetryableAgentRunId(null);
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
    if (!text || agentBusy || waitingOnQuestion) return;
    setAgentBusy(true);
    try {
      await waitForAgentAttachmentUploads();
      const currentAttachmentIds = useUiStore.getState().activeAttachmentIds;
      const messageAttachments = attachmentReferencesForIds(
        attachmentRecordsRef.current,
        currentAttachmentIds,
      );
      await runAgent(text, {
        attachmentIds: currentAttachmentIds,
        clearPendingAttachments: true,
        uploadsReady: true,
        onAccepted: () => {
          setDraft("");
          setMessages((current) => [...current, {
            role: "user",
            text,
            attachments: messageAttachments.length > 0 ? messageAttachments : undefined,
          }]);
        },
      });
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
        setActiveAgentRunId(null);
        setAgentBusy(false);
        setAgentActivity(t("chat.runCancelled"));
        if (agentThreadIdRef.current) window.localStorage.removeItem(agentRunStorageKey(agentThreadIdRef.current));
        // 让等待确认/未完成的气泡落定到 cancelled，并让问题卡停止轮询
        applyAgentEvent(legacyTerminalEvent(run, agentEventSequenceRef.current + 1));
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

  async function resumeUnfinishedAgentRun() {
    if (!resumableAgentRunId || agentBusy) return;
    const resumedRunId = resumableAgentRunId;
    setResumableAgentRunId(null);
    setAgentBusy(true);
    setAgentActivity(t("chat.resuming"));
    await postJson<AgentRun>(`/api/agent/runs/${encodeURIComponent(resumedRunId)}/resume`, {});
    setActiveAgentRunId(resumedRunId);
    if (agentThreadIdRef.current) {
      window.localStorage.setItem(agentRunStorageKey(agentThreadIdRef.current), resumedRunId);
    }
    await subscribeToAgentRun(resumedRunId);
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

  async function uploadAgentAttachments(files: File[]) {
    if (files.length === 0) return;
    attachmentUploadErrorRef.current = null;
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
      mergeAttachmentRecords(uploaded);
      addActiveAttachmentIds(uploaded.map((item) => item.attachment_id));
    } catch {
      attachmentUploadErrorRef.current = new Error("attachment upload failed; retry the upload before sending");
      setMessages((current) => [...current, {
        role: "agent",
        text: t("chat.attachmentUploadFailed"),
        meta: t("chat.sourceErrorMeta"),
      }]);
    }
  }

  async function removeComposerAttachment(attachmentId: string) {
    const record = attachmentRecordsRef.current.find((item) => item.attachment_id === attachmentId);
    removeActiveAttachmentId(attachmentId);
    replaceAttachmentRecords(
      attachmentRecordsRef.current.filter((item) => item.attachment_id !== attachmentId),
    );
    if (!record || !agentThreadIdRef.current) return;

    try {
      await deleteJson<{ deleted: boolean }>(
        `/api/agent/threads/${encodeURIComponent(agentThreadIdRef.current)}/attachments/${encodeURIComponent(attachmentId)}`,
      );
    } catch (error) {
      mergeAttachmentRecords([record]);
      addActiveAttachmentIds([attachmentId]);
      setMessages((current) => [...current, {
        role: "agent",
        text: error instanceof ProductApiError && error.status === 409
          ? t("chat.attachmentAlreadySent")
          : t("chat.attachmentDeleteFailed"),
        meta: "ATTACHMENT · DELETE FAILED",
      }]);
    }
  }

  function queueAgentAttachmentUpload(fileList: FileList | null) {
    const files = Array.from(fileList ?? []);
    if (files.length === 0) return;
    setAttachmentUploadBusy(true);
    const pending = appendAsyncTask(
      attachmentUploadRef.current,
      () => uploadAgentAttachments(files),
    );
    attachmentUploadRef.current = pending;
    const settle = () => {
      if (attachmentUploadRef.current === pending) {
        attachmentUploadRef.current = null;
        setAttachmentUploadBusy(false);
      }
    };
    void pending.then(settle, settle);
  }

  async function startNewChat() {
    if (attachmentUploadBusy || attachmentUploadRef.current) return;
    const leavingThreadId = agentThreadIdRef.current;
    cacheCurrentThreadState(leavingThreadId);
    renderedThreadIdRef.current = null;
    agentEventSourceRef.current?.close();
    streamGenerationRef.current += 1;
    agentThreadIdRef.current = null;
    setActiveThreadId(null);
    setActiveAgentRunId(null);
    setRetryableAgentRunId(null);
    setAgentActivity("");
    agentEventSequenceRef.current = 0;
    processedAgentEventsRef.current.clear();
    replaceAttachmentRecords([]);
    clearActiveAttachments();
    setDraft("");
    try {
      const thread = await postJson<{ thread_id: string }>("/api/agent/threads", {});
      agentThreadIdRef.current = thread.thread_id;
      setActiveThreadId(thread.thread_id);
      seedThreadPlaceholder(thread.thread_id);
      queryClient.invalidateQueries({ queryKey: ["agent-threads"] });
      void disposeEmptyThread(leavingThreadId);
      setMessages([{
        ...initialAgentMessage,
        text: t("workflow.newConversation").replace(
          "{context}",
          composerPageRef?.title ?? t("reader.workspace"),
        ),
      }]);
      renderedThreadIdRef.current = thread.thread_id;
    } catch {
      setMessages([{ ...initialAgentMessage, text: t("workflow.newConversation").replace("{context}", contextTitle) }]);
    }
  }

  function openSearchResult(result: SearchResult) {
    if (result.page_id) {
      setSelectedId(result.page_id);
      setActiveView("wiki");
    }
  }

  // 工作区文件树打开：wiki 页面走现有阅读器，其余文件走工作区查看器
  function openWorkspaceFile(entry: WorkspaceTreeEntry) {
    setActiveView("wiki");
    if (entry.kind === "file" && entry.type === "md" && entry.path.startsWith("wiki/")) {
      const page = pages.find((candidate) => candidate.path === entry.path);
      if (page) {
        setWorkspaceFile(null);
        setSelectedId(page.page_id);
        setComposerPageRef({
          page_id: page.page_id,
          title: page.title ?? fileNameForPage(page),
          path: entry.path,
        });
        return;
      }
    }
    setWorkspaceFile(entry);
  }

  async function openWikiTarget(pageId: string) {
    // 优先按页面注册表跳转 Wiki 阅读器；找不到时在工作区树里按文件名解析并打开
    if (pages.some((page) => page.page_id === pageId)) {
      setWorkspaceFile(null);
      setSelectedId(pageId);
      return;
    }
    try {
      const tree = await getJson<WorkspaceTreeEntry[]>("/api/workspace/tree");
      const fileName = `${pageId}.md`;
      const match = tree.find(
        (entry) => entry.kind === "file"
          && (entry.path === fileName || entry.path.endsWith(`/${fileName}`)),
      );
      if (match) openWorkspaceFile(match);
    } catch {
      // 工作区树加载失败时保持当前视图
    }
  }

  function openDiffPanel() {
    // 打开前记录正在查看的页面/文件，关闭时恢复
    diffReturnRef.current = { workspaceFile, selectedId };
    setDiffPanelOpen(true);
    setActiveView("wiki");
    setWorkspaceFile(null);
  }

  function closeDiffPanel() {
    setDiffPanelOpen(false);
    const saved = diffReturnRef.current;
    setWorkspaceFile(saved.workspaceFile);
    setSelectedId(saved.selectedId);
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
          <button
            className="titlebar-refresh"
            onClick={() => void refreshWorkspaceState()}
            disabled={refreshing}
            title={t("app.refresh")}
            aria-label={t("app.refresh")}
          >
            <RefreshCw size={13} className={refreshing ? "spinning" : undefined} />
          </button>
          <ThemeToggle lightLabel={t("theme.switchLight")} darkLabel={t("theme.switchDark")} />
        </div>
      </header>

      <div className="app-body">
        <nav className="icon-rail" aria-label={t("nav.workspace")}>
          <div className="rail-main">
            <button className={activeView === "wiki" ? "rail-button active" : "rail-button"} onClick={() => setActiveView("wiki")} title={t("nav.wiki")} aria-label={t("nav.wiki")}><PanelLeft size={19} /></button>
            <button className="rail-button" onClick={() => document.querySelector<HTMLTextAreaElement>(".chat-compose textarea")?.focus()} title={t("nav.agent")} aria-label={t("nav.agent")}><MessageSquareText size={19} /></button>
            <button className={activeView === "search" ? "rail-button active" : "rail-button"} onClick={() => setActiveView("search")} title={t("nav.search")} aria-label={t("nav.search")}><Search size={19} /></button>
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
              <>
            <div className="panel-toolbar">
              <span>{t("explorer.title")}</span>
            </div>
            <div className="file-search">
              <Search size={14} />
              <input ref={filterRef} value={filter} onChange={(event) => setFilter(event.target.value)} placeholder={t("explorer.filter")} />
              <kbd>Ctrl K</kbd>
            </div>

            <div className="file-tree-scroll">
              <div className="tree-label">WORKSPACE</div>
              <div className="workspace-browser-section">
                <WorkspaceFileBrowser
                  filter={filter}
                  selectedPath={workspaceSelectedPath}
                  onOpenFile={openWorkspaceFile}
                  refreshSignal={treeRefreshSignal}
                />
              </div>
            </div>

            <div className="file-panel-footer">
              <span>{pages.length} {t("explorer.pages")}</span>
              <button
                className={diffPanelOpen ? "diff-entry active" : "diff-entry"}
                onClick={() => (diffPanelOpen ? closeDiffPanel() : openDiffPanel())}
                title="待确认 Diff"
              >
                <GitPullRequest size={13} /> 待审 Diff
                {pendingDiffCount > 0 && <b>{pendingDiffCount}</b>}
              </button>
            </div>
                        </>
          </aside>

          <div className="resize-handle" onMouseDown={(event) => beginResize("left", event)} role="separator" aria-label={t("explorer.resize")} />

          <section className="reader-panel">
            <div className="reader-toolbar">
              <div className="breadcrumb-path">
                <Library size={14} />
                {contextPath.split("/").map((part, index, parts) => (
                  <span key={`${part}-${index}`}>{part}{index < parts.length - 1 && <ChevronRight size={12} />}</span>
                ))}
              </div>
              <span className="published-state"><i />{t("reader.published")}</span>
            </div>

            <div className="reader-scroll">
              {workspaceQuery.isLoading ? (
                <div className="feature-state">{t("workspace.loading")}</div>
              ) : workspaceQuery.isError ? (
                <div className="feature-state error">{t("workspace.offline")}</div>
              ) : diffPanelOpen ? (
                <DiffBrowser onExit={closeDiffPanel} onCountChange={setPendingDiffCount} />
              ) : activeView === "search" ? (
                <SearchWorkspace onOpen={openSearchResult} />
              ) : workspaceFile ? (
                <div className="workspace-file-preview">
                  <div className="workspace-file-preview-bar">
                    <button onClick={() => setWorkspaceFile(null)} title="返回 wiki 阅读器"><X size={13} /> 返回</button>
                  </div>
                  <WorkspaceFileViewer entry={workspaceFile} onWikiLink={(pageId) => { void openWikiTarget(pageId); }} />
                </div>
              ) : !selectedId ? (
                <div className="feature-state onboarding-empty">
                  <Library size={28} />
                  <strong>{t("reader.emptyTitle")}</strong>
                  <span>{t("reader.emptyBody")}</span>
                  <button onClick={() => setActiveView("search")}><Search size={14} />{t("nav.search")}</button>
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
                  </div>
                  <MarkdownReader
                    markdown={detail.markdown}
                    onWikiLink={(pageId) => { void openWikiTarget(pageId); }}
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
              <div className="agent-title"><span className="agent-icon"><Bot size={16} /></span><div><strong>CewiPilot</strong><small>{t("chat.subtitle")}</small></div></div>
              <div className="agent-toolbar-actions">
                {activeAgentRunId && (
                  <button className="icon-button stop-run" onClick={() => void cancelActiveAgentRun()} title={t("chat.cancel")} aria-label={t("chat.cancel")}><Square size={13} /></button>
                )}
                <button className="icon-button" disabled={attachmentUploadBusy} onClick={startNewChat} title={t("chat.new")} aria-label={t("chat.new")}><CirclePlus size={16} /></button>
              </div>
            </div>
            <ThreadList
              currentThreadId={activeThreadId}
              onDelete={deleteAgentThread}
              onSelect={(thread) => {
                // 零 run 会话没有 latest_run_id；恢复线索回落到该线程的 localStorage 键
                threadRestorePrefRef.current = thread.latestRunId;
                setActiveThreadId(thread.threadId);
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

            <div className="chat-scroll" ref={chatScrollRef}>
              <div className="chat-day">{t("chat.session")}</div>
              {messages.map((message, index) => (
                <AgentMessageBubble
                  key={`${message.role}-${message.runId ?? "message"}-${index}`}
                  message={message}
                  agentLabel="CewiPilot"
                  userLabel={t("agent.you")}
                  reasoningTitle={t("chat.reasoning")}
                  reasoningLiveLabel={t("chat.reasoningLive")}
                  onQuestionAnswered={(runId) => { void restoreAgentRun(runId); }}
                />
              ))}
              {retryableAgentRunId && !agentBusy && (
                <button className="agent-retry" onClick={() => void retryAgentRun()}>
                  <RotateCcw size={12} />{t("chat.retry")}
                </button>
              )}
              {resumableAgentRunId && !agentBusy && (
                <button className="agent-retry" onClick={() => void resumeUnfinishedAgentRun()}>
                  <Play size={12} />{t("chat.resume")}
                </button>
              )}
              {agentBusy && <div className="agent-thinking"><i /><i /><i /><span>{agentActivity || t("chat.tracing")}</span></div>}
              {waitingOnQuestion && (
                <div className="composer-waiting-hint">{t("chat.waitingForConfirmation")}</div>
              )}
              {waitingOnQuestion
                && !messages.some((message) => message.role === "agent" && message.runId === activeAgentRunId)
                && <QuestionCard runId={activeAgentRunId} onAnswered={(runId) => { void restoreAgentRun(runId); }} />}
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
                        <button type="button" onClick={() => void removeComposerAttachment(attachment.attachment_id)} aria-label={t("chat.clearReference")}><X size={11} /></button>
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
                  <button onClick={() => void sendMessage()} disabled={!draft.trim() || agentBusy || waitingOnQuestion} aria-label={t("chat.send")}><Send size={15} /></button>
                </div>
                <input
                  ref={attachmentRef}
                  type="file"
                  accept=".pdf,.md,.txt,.csv,.json"
                  multiple
                  hidden
                 onChange={(event) => {
                    queueAgentAttachmentUpload(event.currentTarget.files);
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

/** 从完整事件日志重建单个 run 的聊天内容（剔除同 run 的旧 agent 消息，避免重复追加）。 */
export function rebuildAgentTranscript(
  base: ChatMessage[],
  runId: string,
  events: AgentEvent[],
  labels: AgentRunReducerLabels,
): ChatMessage[] {
  return events.reduce(
    (next, event) => reduceAgentRunMessages(next, event, labels),
    base.filter((message) => !(message.role === "agent" && message.runId === runId)),
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


