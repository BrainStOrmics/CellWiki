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
import { createAgentEventScheduler, flushesChatImmediately } from "../features/agent/agent-event-scheduler";
import { QuestionCard } from "../features/agent/QuestionCard";
// 终态判定只有一份：unfinished 也是流终态（后端已关 SSE 停在预算上）。漏掉它会让
// 订阅侧无限重连、agentBusy 永不清零，"继续"按钮因此从不出现——看起来就是卡死。
import { terminalAgentStatuses } from "../features/agent/run-status";
import { composerActionFor } from "../features/agent/composer-action";
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
  AgentTimelineNode,
  AttachmentRecord,
  ChatMessage,
  Page,
  PageDetail,
  SearchResult,
} from "../types";

type ResizeSide = "left" | "right";

// SSE 订阅表：EventSource 只把注册过名字的事件派发给监听器，漏一个类型就等于
// 直播路径静默丢事件（回放路径读 /events 全量，不受这张表影响）。
// 与 types.ts 的 AgentEventType 联合由 AppShell.event-contract.test.ts 锁定一致。
export const agentEventTypes: AgentEventType[] = [
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
  "task_confirmation_required",
  "review_required",
  "changeset_ready",
  "verification",
  "usage_updated",
  "error",
];

/** 暂停态 run：恢复会话时必须把事件流渲染回聊天，否则刷新后回答与问题卡会一起消失。
 *  注意 unfinished 同时属于"暂停"和"终态"：终态指 SSE 已结束（不再自动重连、
 *  busy 清零），暂停指用户可点"继续"恢复——两者不矛盾。 */
const pausedAgentStatuses = new Set<AgentRunStatus>([
  "waiting_confirmation",
  "waiting_approval",
  "unfinished",
]);

/** 镜像后端 `CHECKPOINT_MISSING_CODE`：续跑被**永久**拒绝，载体里没有该 run 的图状态。
 *  同一个端点的门禁冲突 409 是可重试拒绝，两者必须分流——按文案分流会在文案本地化时
 *  静默失效，所以后端把码放进了 `detail`。 */
const checkpointMissingCode = "checkpoint_missing";
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

/**
 * "What was injected" detail for the timeline context node: the referenced
 * page (or the bare workspace), attachment names, and the selected-text size.
 * Pure so both the live composer state and a historical run record can feed it.
 */
export function buildRunContextDetail(input: {
  page: { title: string; path?: string | null } | null;
  workspaceLabel: string;
  attachments: string[];
  attachmentsLabel: (count: number) => string;
  selectedText: string | null;
  selectedTextLabel: (chars: number) => string;
}): string {
  const parts: string[] = [];
  if (input.page) {
    parts.push(input.page.path ? `${input.page.title} (${input.page.path})` : input.page.title);
  } else {
    parts.push(input.workspaceLabel);
  }
  if (input.attachments.length > 0) {
    parts.push(`${input.attachmentsLabel(input.attachments.length)}: ${input.attachments.join("、")}`);
  }
  if (input.selectedText) {
    parts.push(input.selectedTextLabel(input.selectedText.length));
  }
  return parts.join(" · ");
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
  // Esc 停止要让位给命令面板的 Esc，所以这里需要读到开关状态本身，不只是 setter。
  const commandPaletteOpen = useUiStore((state) => state.commandPaletteOpen);
  const workbenchRef = useRef<HTMLDivElement>(null);
  const attachmentRef = useRef<HTMLInputElement>(null);
  const filterRef = useRef<HTMLInputElement>(null);
  const chatScrollRef = useRef<HTMLDivElement>(null);
  const agentThreadIdRef = useRef<string | null>(null);
  const agentEventSourceRef = useRef<EventSource | null>(null);
  const agentEventSequenceRef = useRef(0);
  const processedAgentEventsRef = useRef(new Set<string>());
  const streamGenerationRef = useRef(0);
  // 流式平滑层：delta 的聊天渲染按帧投放，进入稳定态前先 flush（agent-event-scheduler）。
  const agentChatScheduler = useMemo(() => createAgentEventScheduler(), []);
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
    // 页面卸载 / 进 bfcache：帧回调不再跑，积压得自己落地，否则回到页面时缺最后一段字。
    const flushChat = () => agentChatScheduler.flush();
    window.addEventListener("pagehide", flushChat);
    return () => {
      window.removeEventListener("pagehide", flushChat);
      agentChatScheduler.dispose();
    };
  }, [agentChatScheduler]);

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
    } else if (renderedThreadIdRef.current !== activeThreadId) {
      // 刷新/重启后持久化的会话身份回来了，但本地视图还是空的欢迎语。已完成的
      // run 不留 active_run_id 线索，所以这条分支必须自己拉历史，否则旧会话看起来
      // 被清空了。应用内切换与 `+` 新建都已经渲染过目标会话，不重复恢复。
      void restoreAgentThread(activeThreadId);
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
  // 发送/停止/继续共用 composer 里同一个槽位，判定收在纯函数里（composer-action.ts）。
  const composerAction = composerActionFor({
    agentBusy,
    waitingOnQuestion,
    resumableRunId: resumableAgentRunId,
    hasDraft: Boolean(draft.trim()),
  });

  // 这个 effect 必须排在 waitingOnQuestion 之后：依赖数组在渲染期求值，放前面会撞 TDZ。
  useEffect(() => {
    const stopRunOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      // 命令面板开着时让位：它的 Esc 关面板且不 stopPropagation，事件照样冒到 window。
      if (commandPaletteOpen) return;
      // 只在有请求在飞时响应。提问态下 Esc 不该顺手毁掉一个待答问题；中断态下也不绑
      // "放弃"——误触一下就把一个可续跑的 run 打成终态，代价太大。放弃走消息区那颗
      // 显式的键（见 chat.abandon）。
      if (!agentBusy || waitingOnQuestion) return;
      event.preventDefault();
      void cancelActiveAgentRun();
    };
    window.addEventListener("keydown", stopRunOnEscape);
    return () => window.removeEventListener("keydown", stopRunOnEscape);
  }, [agentBusy, waitingOnQuestion, commandPaletteOpen]);

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
    setResumableAgentRunId(null);
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

  /** 答题后的续跑：后端只登记答案与状态迁移就返回，进度必须切回直播订阅。 */
  async function resumeAfterAnswer(runId: string) {
    setActiveAgentRunId(runId);
    setResumableAgentRunId(null);
    setAgentBusy(true);
    setAgentActivity(t("chat.resuming"));
    if (agentThreadIdRef.current) {
      window.localStorage.setItem(agentRunStorageKey(agentThreadIdRef.current), runId);
    }
    try {
      await subscribeToAgentRun(runId);
    } catch {
      // 订阅起不来时不能把界面留在"忙"上：回滚，用户才还能重试或重发消息。
      setAgentBusy(false);
      setAgentActivity("");
    }
  }

  function applyAgentEvent(event: AgentEvent, options: { replayChat?: boolean } = {}) {
    if (event.thread_id !== agentThreadIdRef.current) return;
    const renderChat = options.replayChat ?? true;
    if (processedAgentEventsRef.current.has(event.event_id)) return;
    processedAgentEventsRef.current.add(event.event_id);
    agentEventSequenceRef.current = Math.max(agentEventSequenceRef.current, event.sequence);
    if (renderChat) {
      const eventThread = agentThreadIdRef.current;
      const render = () => {
        // 会话已切走：这条积压作废，不能被 reduce 进另一个会话的记录里。
        if (agentThreadIdRef.current !== eventThread) return;
        setMessages((current) => reduceAgentRunMessages(current, event, agentRunLabels()));
      };
      // 稳定态事件先投完积压再落地自己，否则终态画面会缺最后一段 delta。
      if (flushesChatImmediately(event)) {
        agentChatScheduler.flush();
        render();
      } else {
        agentChatScheduler.enqueue(render);
      }
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
      // 运行开始必须把活动条重置成中性态：它此前只被 tool/subagent/verification/
      // progress 与部分终态事件驱动，于是上一段甚至上一个 run 的终态文案会被带进
      // 新 run——实测三个 model_calls=0、tool_calls=0 的失败 run 全程显示"工具执行完成"。
      // 空串会落到渲染处的默认文案，所以这里不需要再造一个键。
      if (status === "running" || status === "queued") setAgentActivity("");
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
        // 主动停止与被动中断读起来不该是同一句话：前者是用户自己按的，说"已中断"
        // 像出了故障。判别来自后端 RUN_STATUS 事件 data 里的 reason。
        setAgentActivity(
          event.data.reason === "user_stopped"
            ? t("chat.runStopped")
            : t("chat.runUnfinished"),
        );
        setResumableAgentRunId(event.run_id);
        // 主动停止不再落 cancelled，所以横幅不会再由 cancel 那条路收尾，会一直卡在
        // "正在停止模型请求…"。暂停态有自己的文案，收敛到它。
        setWorkflow((current) => current.phase === "cancelling" || current.phase === "preparing"
          ? { phase: "unfinished", message: t("workflow.unfinished") }
          : current);
        // 后端 is_retryable_run 对 unfinished 同样返回真，而 retry 不依赖 checkpoint
        // （清状态 + 从有界 transcript 重放），所以图状态丢了它也走得通。两条出路一起
        // 给出来，用户不必先撞一次 409 才发现「继续」不可用。主动停止的 error_type 为
        // 空，retryable 因此是 false —— 那是有意的：按下停止的人要的是继续，不是重放。
        if (event.data.retryable === true) setRetryableAgentRunId(event.run_id);
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
        if (
          status !== "waiting_confirmation"
          && status !== "waiting_approval"
          // 可恢复的暂停仍算"挂在这个 run 上"：保留它，取消按钮才留着——
          // 那是 UI 里唯一能释放串行门禁（POST /cancel）的出口。
          && status !== "unfinished"
        ) {
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

  function contextDetailParts() {
    return {
      workspaceLabel: t("reader.workspace"),
      attachmentsLabel: (count: number) => t("chat.attachmentsAttached").replace("{count}", String(count)),
      selectedTextLabel: (chars: number) => t("chat.selectedTextInjected").replace("{n}", String(chars)),
    };
  }

  function buildTimelineContext(): { label: string; detail?: string } {
    const detail = buildRunContextDetail({
      page: composerPageRef ?? null,
      ...contextDetailParts(),
      attachments: activeAttachments.map((attachment) => attachment.original_name ?? attachment.attachment_id),
      selectedText: selectedText || null,
    });
    return { label: t("chat.contextInjection"), detail };
  }

  /**
   * Context node for a replayed run: describe what THAT run injected (its own
   * page_id / attachment_ids / selected_text), not today's composer state.
   */
  function runRecordContext(run: AgentRun): { label: string; detail?: string } {
    const page: Page | null = run.page_id
      ? pages.find((candidate) => candidate.page_id === run.page_id) ?? { page_id: run.page_id }
      : null;
    const attachmentNames = (run.attachment_ids ?? []).map(
      (attachmentId) =>
        attachments.find((attachment) => attachment.attachment_id === attachmentId)?.original_name
        ?? attachmentId,
    );
    return {
      label: t("chat.contextInjection"),
      detail: buildRunContextDetail({
        page: page
          ? { title: page.title ?? fileNameForPage(page), path: page.path ?? null }
          : null,
        ...contextDetailParts(),
        attachments: attachmentNames,
        selectedText: run.selected_text ?? null,
      }),
    };
  }

  function agentRunLabels(
    context?: { label: string; detail?: string },
  ): AgentRunReducerLabels {
    return {
      failed: t("chat.runFailed"),
      cancelled: t("chat.runCancelled"),
      unfinished: t("chat.runUnfinished"),
      // 十个码与后端 domain/runs.py 的 AgentErrorType 一一对应；漏译在 i18n 里是编译
      // 错误（en 表按 MessageKey 索引），漏一个码则回落到原始报错文本。
      errorTypes: {
        input: t("chat.error.input"),
        authentication: t("chat.error.authentication"),
        permission: t("chat.error.permission"),
        rate_limit: t("chat.error.rate_limit"),
        timeout: t("chat.error.timeout"),
        budget: t("chat.error.budget"),
        structured_output: t("chat.error.structured_output"),
        approval: t("chat.error.approval"),
        conflict: t("chat.error.conflict"),
        system: t("chat.error.system"),
      },
      maintenance: {
        lint: t("chat.maintenance.lint"),
        accept: t("chat.maintenance.accept"),
        reject: t("chat.maintenance.reject"),
        unfinished: t("chat.maintenance.unfinished"),
        failed: t("chat.maintenance.failed"),
      },
      timelineContext: context ?? buildTimelineContext(),
    };
  }

  function cacheCurrentThreadState(threadId: string | null) {
    // 切换线程前先投完积压：队列里是**离开的那个会话**的 delta，不能等到目标会话的
    // 视图装好之后才落地。回来时的文字由 /events 持久日志重建，不依赖这份缓存。
    agentChatScheduler.flush();
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
      // 上下文节点按该 run 自身的注入记录重建，而不是当前 composer 状态。
      const runLabels = agentRunLabels(runRecordContext(run));
      let transcript = rebuildAgentTranscript(
        options.base ?? messagesRef.current,
        runId,
        events,
        runLabels,
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
          runLabels,
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
        // 重启后端再回到会话正是"图状态在、字段为 NULL"的复现路径；retry 不依赖
        // checkpoint，所以它必须在这里就可见，而不是等「继续」撞一次 409。
        if (run.retryable) setRetryableAgentRunId(runId);
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
        setResumableAgentRunId(null);
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
    // 与忙碌指示器同时清活动条：否则新 run 的头几帧会显示上一个 run 留下的终态文案
    // （典型是"Agent 运行已取消"），读起来像这一次发送已经被取消了。
    setAgentActivity("");
    try {
      if (resumableAgentRunId) {
        // 中断的 run 仍占着串行门禁，直接发新消息必然 409。先放弃它——这是"打了字
        // 按钮就变回发送"那条判定的另一半。放弃不是无声的：那个 run 会在 transcript
        // 里落成一条已定的气泡。
        const released = await cancelActiveAgentRun();
        // 没放开就别发：请求出去只会再吃一个 409，错误还盖掉了真正的原因。
        if (!released) return;
        // cancelActiveAgentRun 收尾时把 busy 清零了（它以为这一轮到此结束），而新 run
        // 马上要起来：不重新置上，思考指示器与停止键整轮都不会出现。
        setAgentBusy(true);
        setAgentActivity("");
      }
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

  /**
   * 停止 / 放弃当前 run。同一个入口担两个角色，靠后端返回的状态区分：
   *
   * - **停止**一个正在跑的 run：后端返回 `cancelling`（协作式，等安全边界），真正的
   *   落点由 SSE 的 `unfinished` 事件带来 —— 主动停止是可续跑的暂停，不是终态。
   * - **放弃**一个已中断的 run：后端立刻返回 `cancelled`，串行门禁随之放开。
   *
   * 返回门禁是否**已经**放开：`cancelling` 意味着还在协作式停止途中，此时发新消息
   * 必然撞 409，调用方必须等 SSE 的落点而不是直接往下走。
   */
  async function cancelActiveAgentRun(): Promise<boolean> {
    if (!activeAgentRunId) return false;
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
        // 必须清：不清的话「继续」「重试」会残留在一个已经 cancelled 的 run 上，
        // 点下去必然 409（status 已不是 unfinished）——又一个死结。
        setResumableAgentRunId(null);
        setRetryableAgentRunId(null);
        setAgentActivity(t("chat.runCancelled"));
        if (agentThreadIdRef.current) window.localStorage.removeItem(agentRunStorageKey(agentThreadIdRef.current));
        // 让等待确认/未完成的气泡落定到 cancelled，并让问题卡停止轮询
        applyAgentEvent(legacyTerminalEvent(run, agentEventSequenceRef.current + 1));
        return true;
      }
      setAgentActivity(t("chat.cancelling"));
      return false;
    } catch (error) {
      setWorkflow((current) => current.phase === "cancelling"
        ? { phase: "failed", message: t("workflow.proposalFailed"), error: error instanceof Error ? error.message : t("source.failedTitle") }
        : current);
      setMessages((current) => [...current, {
        role: "agent",
        text: error instanceof Error ? error.message : t("chat.runFailed"),
        meta: "RUNTIME · CANCEL ERROR",
      }]);
      return false;
    }
  }

  async function resumeUnfinishedAgentRun() {
    if (!resumableAgentRunId || agentBusy) return;
    const resumedRunId = resumableAgentRunId;
    setResumableAgentRunId(null);
    setAgentBusy(true);
    setAgentActivity(t("chat.resuming"));
    try {
      await postJson<AgentRun>(`/api/agent/runs/${encodeURIComponent(resumedRunId)}/resume`, {});
      setActiveAgentRunId(resumedRunId);
      if (agentThreadIdRef.current) {
        window.localStorage.setItem(agentRunStorageKey(agentThreadIdRef.current), resumedRunId);
      }
      await subscribeToAgentRun(resumedRunId);
    } catch (error) {
      const failure = agentRequestFailure(
        error,
        isDesktopRuntime ? t("workflow.runtimeDesktop") : t("workflow.runtimeWeb"),
      );
      if (failure.code === checkpointMissingCode) {
        // 永久拒绝：载体里没有这个 run 的图状态，「继续」再点多少次都是 409。摘掉它，
        // 换成真正走得通的出路——retry 先清状态键、再从有界 transcript 重放后端持久化
        // 的原话（`input_message`），不依赖 checkpoint。修订前这里把「继续」还回去，
        // 于是成了死结：按钮点不动，而 UNFINISHED 仍占着串行门禁，重发同样是 409。
        setRetryableAgentRunId(resumedRunId);
      } else {
        // 可重试拒绝（典型是门禁冲突 409）必须把"继续"还回来：否则按钮已清空、
        // 思考指示器永远转下去，用户在这个会话里无路可走。
        setResumableAgentRunId(resumedRunId);
      }
      setMessages((current) => [...current, {
        role: "agent",
        text: failure.text,
        meta: failure.meta,
      }]);
    } finally {
      setAgentBusy(false);
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
      if (!response.ok) {
        // 服务端已应答并给出原因（如类型不支持）时不能报成"运行时没起来"。
        const reason = await response.json()
          .then((payload: unknown) => {
            const detail = (payload as { detail?: unknown } | null)?.detail;
            return typeof detail === "string" ? detail : "";
          })
          .catch(() => "");
        throw new ProductApiError(reason || "attachment upload failed", response.status);
      }
      const uploaded = await response.json() as AttachmentRecord[];
      mergeAttachmentRecords(uploaded);
      addActiveAttachmentIds(uploaded.map((item) => item.attachment_id));
    } catch (error) {
      attachmentUploadErrorRef.current = new Error("attachment upload failed; retry the upload before sending");
      const reason = error instanceof ProductApiError ? error.message : "";
      setMessages((current) => [...current, {
        role: "agent",
        text: reason
          ? t("chat.attachmentRejected").replace("{reason}", reason)
          : t("chat.attachmentUploadFailed"),
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
    // `+` 不得继承上一次会话选择留下的恢复线索，否则新会话会被旧 run 拉回去。
    threadRestorePrefRef.current = null;
    const leavingThreadId = agentThreadIdRef.current;
    cacheCurrentThreadState(leavingThreadId);
    renderedThreadIdRef.current = null;
    agentEventSourceRef.current?.close();
    streamGenerationRef.current += 1;
    agentThreadIdRef.current = null;
    setActiveThreadId(null);
    setActiveAgentRunId(null);
    setRetryableAgentRunId(null);
    setResumableAgentRunId(null);
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
      setComposerPageRef({ page_id: result.page_id, title: result.title });
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
      const page = pages.find((candidate) => candidate.page_id === pageId);
      setWorkspaceFile(null);
      setSelectedId(pageId);
      // Navigating the reader must keep the composer reference in sync; the
      // tree and workspace-file paths already do this via openWorkspaceFile.
      setComposerPageRef({
        page_id: pageId,
        title: page?.title ?? fileNameForPage({ page_id: pageId }),
        path: page?.path,
      });
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
    // 打开前把流式积压投完：DiffBrowser 接管视图后聊天不再重绘，积压留在队列里
    // 就会让关闭面板时看到的回答缺最后一段。
    agentChatScheduler.flush();
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
                <button className="icon-button" disabled={attachmentUploadBusy} onClick={startNewChat} title={t("chat.new")} aria-label={t("chat.new")}><CirclePlus size={16} /></button>
              </div>
            </div>
            <ThreadList
              currentThreadId={activeThreadId}
              onDelete={deleteAgentThread}
              onSelect={(thread) => {
                // 零 run 会话没有 latest_run_id；恢复线索回落到该线程的 localStorage 键。
                // 点当前会话时 activeThreadId 值不变、effect 不会重跑，滞留的线索会被
                // 下一次切换（典型是紧接着点 `+`）消费掉，把用户弹回旧会话，因此只在
                // 真的换会话时武装它。
                threadRestorePrefRef.current = thread.threadId === activeThreadId
                  ? null
                  : thread.latestRunId;
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
                  onQuestionAnswered={(runId) => { void resumeAfterAnswer(runId); }}
                />
              ))}
              {retryableAgentRunId && !agentBusy && (
                <button className="agent-retry" onClick={() => void retryAgentRun()}>
                  <RotateCcw size={12} />{t("chat.retry")}
                </button>
              )}
              {resumableAgentRunId && !agentBusy && (
                // 标题栏那颗停止键删掉之后，这里是"只放弃、不发新消息"的唯一出口。
                // 不能省：中断态的 run 占着串行门禁，而 delete_thread 有活动 run 守卫，
                // 没有放弃入口的话连会话都删不掉 —— 又一个死结。
                <button className="agent-retry" onClick={() => void cancelActiveAgentRun()}>
                  <X size={12} />{t("chat.abandon")}
                </button>
              )}
              {agentBusy && <div className="agent-thinking"><i /><i /><i /><span>{agentActivity || t("chat.reasoningLive")}</span></div>}
              {waitingOnQuestion && (
                <div className="composer-waiting-hint">{t("chat.waitingForConfirmation")}</div>
              )}
              {waitingOnQuestion
                && !messages.some((message) => message.role === "agent" && message.runId === activeAgentRunId)
                && <QuestionCard runId={activeAgentRunId} onAnswered={(runId) => { void resumeAfterAnswer(runId); }} />}
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
                  {composerAction.kind === "stop" && (
                    // 运行中把发送键**原位**换成停止键：同一个位置、同一个尺寸，只换
                    // 语义色与图标。中断入口必须在注意力焦点上，且要能被读屏与自动化
                    // 按 role+name 找到——实测标题栏那颗 13px 方块两者都做不到（像素
                    // 点击 4 次偏 3 次），所以它已经删了。Esc 是同一动作的键盘入口。
                    <button
                      type="button"
                      className="stop-run"
                      onClick={() => void cancelActiveAgentRun()}
                      title={t("chat.cancelHint")}
                      aria-label={t("chat.cancel")}
                    >
                      <Square size={15} />
                    </button>
                  )}
                  {composerAction.kind === "resume" && (
                    // 中断态且输入框空着：同一个槽位换成「继续」。沿用发送键的强调色
                    // 而不是停止键的危险色——它是"接着走"，不是"危险操作"。用户一旦
                    // 打字，composerActionFor 会把槽位让回发送键。
                    <button
                      type="button"
                      onClick={() => void resumeUnfinishedAgentRun()}
                      title={t("chat.resume")}
                      aria-label={t("chat.resume")}
                    >
                      <Play size={15} />
                    </button>
                  )}
                  {composerAction.kind === "send" && (
                    <button onClick={() => void sendMessage()} disabled={composerAction.disabled} aria-label={t("chat.send")}><Send size={15} /></button>
                  )}
                </div>
                <input
                  ref={attachmentRef}
                  type="file"
                  accept=".pdf,.md,.txt"
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
  const durable = base.filter((message) => message.role === "agent" && message.runId === runId);
  const transcript = events.reduce(
    (next, event) => reduceAgentRunMessages(next, event, labels),
    base.filter((message) => !(message.role === "agent" && message.runId === runId)),
  );
  // 事件日志不承载回答（无 final_response / message_delta）时，回放不能把
  // /messages 里已持久化的回答抹掉；回放有回答时仍以回放为准，避免重复文本。
  const answer = durable.map((message) => message.text).find((text) => text.trim().length > 0) ?? "";
  if (!answer) return transcript;
  const index = transcript.findIndex((message) => message.role === "agent" && message.runId === runId);
  if (index < 0) return [...transcript, ...durable];
  const rebuilt = transcript[index];
  if (rebuilt.text.trim()) return transcript;
  // 气泡在有时间线节点时只渲染时间线，回答必须同时成为其中的 text 节点。
  const timeline = rebuilt.timeline?.some((node) => node.kind === "text")
    ? rebuilt.timeline
    : [...(rebuilt.timeline ?? []), { kind: "text", text: answer } as AgentTimelineNode];
  return [
    ...transcript.slice(0, index),
    { ...rebuilt, text: answer, timeline },
    ...transcript.slice(index + 1),
  ];
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
      code: error.code ?? null,
    };
  }
  return { text: offlineMessage, meta: "RUNTIME OFFLINE", code: null };
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


