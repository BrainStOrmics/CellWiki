import {
  Brain,
  Check,
  ChevronRight,
  CircleAlert,
  CircleCheck,
  Copy,
  FileCode2,
  FileText,
  GitBranch,
  LoaderCircle,
  Search,
  Terminal,
} from "lucide-react";
import { useState, type ComponentType } from "react";
import { Highlight, Prism, type PrismTheme } from "prism-react-renderer";
import { MarkdownContent } from "../../components/MarkdownContent";
import { useI18n } from "../../i18n";
import { getText } from "../../lib/product-api";
import { AgentRunDiagnostics } from "./AgentRunDiagnostics";
import { QuestionCard } from "./QuestionCard";
import type {
  AgentProcessStep,
  AgentRunStatus,
  AgentTimelineNode,
  AgentToolArgsDisplay,
  AgentToolEditDiff,
  AgentToolResultPreview,
  ChatMessage,
} from "../../types";

type AgentMessageBubbleProps = {
  message: ChatMessage;
  agentLabel: string;
  userLabel: string;
  reasoningTitle: string;
  reasoningLiveLabel: string;
  onQuestionAnswered?: (runId: string) => void;
};

/** One agent message rendered as a flat, chronological timeline of lightweight nodes. */
export function AgentMessageBubble({
  message,
  agentLabel,
  userLabel,
  reasoningTitle,
  reasoningLiveLabel,
  onQuestionAnswered,
}: AgentMessageBubbleProps) {
  const isAgent = message.role === "agent";
  const nodes = timelineNodes(message);

  return (
    <div className={`message ${message.role} ${message.streaming ? "is-streaming" : ""}`}>
      <div className="message-author">
        {isAgent ? <><Brain size={13} />{agentLabel}</> : userLabel}
      </div>
      {!isAgent && message.attachments && message.attachments.length > 0 && (
        <div className="message-attachments">
          {message.attachments.map((attachment) => (
            <span
              className="message-attachment"
              key={attachment.attachment_id}
              title={attachment.attachment_id}
            >
              <FileText size={12} />
              <span>{attachment.original_name ?? attachment.attachment_id}</span>
            </span>
          ))}
        </div>
      )}
      <div className="message-bubble">
        {isAgent && nodes.length > 0 ? (
          <div className="agent-timeline">
            {nodes.map((node, index) => (
              <TimelineNode
                key={`${node.kind}-${index}`}
                node={node}
                streaming={Boolean(message.streaming)}
                reasoningTitle={reasoningTitle}
                reasoningLiveLabel={reasoningLiveLabel}
              />
            ))}
          </div>
        ) : isAgent ? (
          <MarkdownContent content={message.text} />
        ) : (
          <p>{message.text}</p>
        )}
      </div>
      {message.meta && <small className="message-meta">{message.meta}</small>}
      {isAgent && message.runId && (
        <>
          {!message.streaming && (
            <AgentRunDiagnostics runId={message.runId} usageSegments={message.usageSegments} />
          )}
          {isAwaitingUserAnswer(message.runStatus) && (
            <QuestionCard runId={message.runId} onAnswered={onQuestionAnswered} />
          )}
        </>
      )}
    </div>
  );
}

/** 只有等待用户回应的 run 才需要问题卡；历史消息不挂载，避免每个气泡都轮询 /question。 */
function isAwaitingUserAnswer(status: AgentRunStatus | undefined): boolean {
  return status === "waiting_confirmation" || status === "waiting_approval";
}

function timelineNodes(message: ChatMessage): AgentTimelineNode[] {
  if (message.timeline && message.timeline.length > 0) return message.timeline;
  // Legacy fallback: rebuild nodes from persisted process steps, reusing the
  // bounded display projections when the durable events carry them.
  const nodes: AgentTimelineNode[] = [];
  for (const step of message.process ?? []) {
    if (step.type === "tool_started" || step.type === "tool_completed" || step.type === "tool_failed") {
      nodes.push({
        kind: "tool",
        phase: step.phase,
        toolName: String((step.data as Record<string, unknown>).tool_name ?? "tool"),
        summary: step.message,
        step,
        argsDisplay: readArgsDisplay(step.data),
        resultPreview: readResultPreview(step.data),
        editDiff: readEditDiff(step.data),
      });
    } else {
      nodes.push({
        kind: "status",
        tone: step.phase === "failed" || step.phase === "cancelled" ? "danger" : "info",
        label: step.message || step.type.replaceAll("_", " "),
        step,
      });
    }
  }
  if (message.reasoning) nodes.push({ kind: "thinking", text: message.reasoning });
  if (message.text) nodes.push({ kind: "text", text: message.text });
  return nodes;
}

type TimelineNodeProps = {
  node: AgentTimelineNode;
  streaming: boolean;
  reasoningTitle: string;
  reasoningLiveLabel: string;
};

function TimelineNode({ node, streaming, reasoningTitle, reasoningLiveLabel }: TimelineNodeProps) {
  switch (node.kind) {
    case "context":
      return (
        <div className="agent-timeline-node context">
          <FileText size={12} />
          <span className="at-label">{node.label}{node.detail ? ` · ${node.detail}` : ""}</span>
        </div>
      );
    case "thinking":
      return (
        <ThinkingNode
          text={node.text}
          streaming={streaming}
          title={reasoningTitle}
          live={reasoningLiveLabel}
        />
      );
    case "tool":
      return <ToolCard node={node} />;
    case "status":
      return (
        <div className={`agent-timeline-node tone-${node.tone}`}>
          <span className="at-dot" />
          <span className="at-label">{node.label}</span>
        </div>
      );
    case "text":
      return (
        <div className="agent-timeline-text">
          <MarkdownContent content={node.text} />
        </div>
      );
  }
}

/**
 * Reasoning renders as one quiet, truncated line so streaming thoughts never
 * flood the transcript; the full text opens on demand.
 */
function ThinkingNode({
  text,
  streaming,
  title,
  live,
}: {
  text: string;
  streaming: boolean;
  title: string;
  live: string;
}) {
  const preview = thinkingPreview(text, streaming);
  return (
    <details className={`agent-timeline-think ${streaming ? "is-live" : ""}`}>
      <summary>
        <ChevronRight size={12} className="at-chevron" />
        <span>{title}</span>
        {preview && <span className="at-think-preview">{preview}</span>}
        {streaming && <small>{live}</small>}
      </summary>
      <div className="agent-timeline-think-body">{text}</div>
    </details>
  );
}

function thinkingPreview(text: string, streaming: boolean): string {
  const lines = text.split("\n").map((line) => line.trim()).filter(Boolean);
  if (lines.length === 0) return "";
  // While streaming, the newest line is the useful signal; after the run the
  // first line summarizes the thought.
  const source = streaming ? lines[lines.length - 1] : lines[0];
  return source.length > 100 ? `${source.slice(0, 100)}…` : source;
}

type ToolCardBodyProps = {
  node: Extract<AgentTimelineNode, { kind: "tool" }>;
  args?: AgentToolArgsDisplay;
  preview?: AgentToolResultPreview;
  legacy: string | null;
};

/** One card = one entry: label, icon and body come from the same place, so
 *  adding a card type cannot leave the three lookups disagreeing. */
type ToolCardSpec = {
  label: string;
  icon: ComponentType<{ size: number }>;
  Body: ComponentType<ToolCardBodyProps>;
};

const TOOL_CARDS: Record<string, ToolCardSpec> = {
  run_powershell: { label: "Pwsh", icon: Terminal, Body: PwshCard },
  read_file: { label: "Read", icon: FileCode2, Body: ReadCard },
  read_wiki_page: { label: "Read", icon: FileCode2, Body: ReadCard },
  grep: { label: "Grep", icon: Search, Body: SearchCard },
  glob: { label: "Glob", icon: Search, Body: SearchCard },
  ls: { label: "LS", icon: Search, Body: SearchCard },
  search_wiki: { label: "Search", icon: Search, Body: SearchCard },
  write_file: { label: "Write", icon: FileText, Body: GenericCard },
  edit_file: { label: "Edit", icon: FileCode2, Body: EditCard },
  delete_file: { label: "Delete", icon: FileText, Body: GenericCard },
  rename_file: { label: "Rename", icon: FileText, Body: GenericCard },
  git: { label: "Git", icon: GitBranch, Body: GitCard },
  lint_knowledge_base: { label: "Lint", icon: CircleCheck, Body: LintCard },
  read_attachment: { label: "Attachment", icon: FileText, Body: AttachmentCard },
  promote_attachment: { label: "Promote", icon: FileText, Body: AttachmentCard },
  ingest_sources: { label: "Ingest", icon: FileText, Body: GenericCard },
  ask_user_question: { label: "Ask", icon: FileText, Body: GenericCard },
  get_project_status: { label: "Status", icon: FileText, Body: GenericCard },
};

/** 未登记的工具 fail-open：报出自己的名字，走通用卡身，绝不因为不认识而消失。 */
function toolCardSpec(toolName: string): ToolCardSpec {
  return TOOL_CARDS[toolName] ?? { label: toolName, icon: FileText, Body: GenericCard };
}

/** Tool node as a collapsible card: header line + type-specific body. */
function ToolCard({ node }: { node: Extract<AgentTimelineNode, { kind: "tool" }> }) {
  const [open, setOpen] = useState(false);
  const args = node.argsDisplay;
  const preview = node.resultPreview;
  const { label, icon: Icon, Body } = toolCardSpec(node.toolName);
  const title = args?.title || toolLabel(node.summary, node.toolName);
  const legacyDetail = !args && !preview ? toolDetail(node.step) : null;

  return (
    <div className={`agent-timeline-card tool ${node.phase}`}>
      <button
        className="at-card-head"
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <ChevronRight size={12} className={`at-chevron ${open ? "is-open" : ""}`} />
        <Icon size={12} />
        <span className="at-kind">{label}</span>
        {title && <span className="at-label">{title}</span>}
        <span className="at-status">
          {node.phase === "failed"
            ? <CircleAlert size={12} />
            : node.phase === "completed"
              ? <CircleCheck size={12} />
              : <LoaderCircle size={12} className="spin" />}
        </span>
      </button>
      {open && (
        <div className="at-card-body">
          <Body node={node} args={args} preview={preview} legacy={legacyDetail} />
        </div>
      )}
    </div>
  );
}

function PwshCard({ args, preview, legacy }: ToolCardBodyProps) {
  return <PwshBody args={args} preview={preview} legacy={legacy} />;
}

function ReadCard({ args, preview, legacy }: ToolCardBodyProps) {
  return <ReadBody args={args} preview={preview} legacy={legacy} />;
}

function GenericCard({ node, preview, legacy }: ToolCardBodyProps) {
  return (
    <GenericBody
      preview={preview}
      legacy={legacy}
      summary={node.summary}
      toolName={node.toolName}
    />
  );
}

/** 搜索类工具在通用卡身之外多一行命中数。 */
function SearchCard({ node, preview, legacy }: ToolCardBodyProps) {
  const { t } = useI18n();
  const count = preview && typeof preview.count === "number" ? preview.count : null;
  return (
    <>
      <GenericBody
        preview={preview}
        legacy={legacy}
        summary={node.summary}
        toolName={node.toolName}
      />
      {count !== null && (
        <div className="at-preview-meta">
          {t("chat.toolResultCount").replace("{count}", String(count))}
        </div>
      )}
    </>
  );
}

/** edit_file：真行级 diff（裁决 #11 的有界投影），旧/新行号 + +/- 标记。 */
function EditCard({ node, preview, legacy }: ToolCardBodyProps) {
  const { t } = useI18n();
  const diff = node.editDiff;
  if (!diff) {
    return (
      <GenericBody
        preview={preview}
        legacy={legacy}
        summary={node.summary}
        toolName={node.toolName}
      />
    );
  }
  const path = typeof node.argsDisplay?.path === "string" ? node.argsDisplay.path : null;
  return (
    <>
      <div className="at-code-frame">
        {path && (
          <div className="at-file-head">
            <span className="at-file-path">{path}</span>
            <span className="at-file-lang">−{diff.removed} / +{diff.added}</span>
          </div>
        )}
        <div className="at-diff">
          {diff.lines.map((line, index) => (
            <div className={`at-diff-line ${line.kind}`} key={`${line.kind}-${index}`}>
              <span className="at-diff-no">{line.old_no ?? ""}</span>
              <span className="at-diff-no">{line.new_no ?? ""}</span>
              <span className="at-diff-mark">{DIFF_MARKS[line.kind]}</span>
              <span className="at-diff-text">
                {line.kind === "gap"
                  ? t("chat.toolRestLines").replace("{count}", String(line.count ?? 0))
                  : line.text}
              </span>
            </div>
          ))}
        </div>
        {diff.truncated && (
          <div className="at-preview-meta">{t("chat.toolDiffTruncated")}</div>
        )}
      </div>
      {preview && <PreviewBlock preview={preview} language="plaintext" />}
    </>
  );
}

const DIFF_MARKS: Record<string, string> = {
  added: "+",
  removed: "−",
  context: " ",
  gap: "⋯",
};

/** git：把子命令与路径参数还原成一行可读命令，输出仍走有界预览。 */
function GitCard({ args, preview, legacy }: ToolCardBodyProps) {
  const tokens = Array.isArray(args?.args) ? args?.args ?? [] : [];
  const command = tokens.length > 0 ? `git ${tokens.join(" ")}` : null;
  return (
    <>
      {command && (
        <div className="at-code-frame">
          <CodeBlock code={command} language="plaintext" numbered={false} />
          <CopyButton text={command} />
        </div>
      )}
      {preview && <PreviewBlock preview={preview} language="plaintext" />}
      {!preview && legacy && <pre className="at-detail">{legacy}</pre>}
    </>
  );
}

/** lint_knowledge_base：报告本体总是被截断，所以结论走后端单独摘出的 summary。 */
function LintCard({ preview, legacy }: ToolCardBodyProps) {
  const summary = preview?.summary;
  return (
    <>
      {summary && (
        <div className="at-lint-summary">
          <span className={`at-lint-status is-${summary.status}`}>{summary.status}</span>
          <span className="at-preview-meta">
            {summary.page_count} pages · {summary.error_count} errors ·{" "}
            {summary.warning_count} warnings
          </span>
        </div>
      )}
      {preview && <PreviewBlock preview={preview} language={summary ? "json" : "plaintext"} />}
      {!preview && legacy && <pre className="at-detail">{legacy}</pre>}
    </>
  );
}

/** 附件读写：报出附件标识与晋升目标，正文走有界预览。 */
function AttachmentCard({ node, args, preview, legacy }: ToolCardBodyProps) {
  const attachmentId = typeof args?.attachment_id === "string" ? args.attachment_id : null;
  const sourceType = typeof args?.source_type === "string" ? args.source_type : null;
  return (
    <>
      {(attachmentId || sourceType) && (
        <div className="at-file-head">
          <span className="at-file-path">{attachmentId ?? node.toolName}</span>
          {sourceType && <span className="at-file-lang">{sourceType}</span>}
        </div>
      )}
      {preview && <PreviewBlock preview={preview} language="plaintext" />}
      {!preview && legacy && <pre className="at-detail">{legacy}</pre>}
    </>
  );
}

function PwshBody({
  args,
  preview,
  legacy,
}: {
  args?: AgentToolArgsDisplay;
  preview?: AgentToolResultPreview;
  legacy: string | null;
}) {
  const command = typeof args?.command === "string" ? args.command : null;
  return (
    <>
      {command && (
        <div className="at-code-frame">
          <CodeBlock code={command} language="plaintext" numbered={false} />
          <CopyButton text={command} />
        </div>
      )}
      {preview && <PreviewBlock preview={preview} language="plaintext" />}
      {!preview && legacy && <pre className="at-detail">{legacy}</pre>}
    </>
  );
}

const EXT_LANG: Record<string, string> = {
  md: "markdown",
  markdown: "markdown",
  json: "json",
  yml: "yaml",
  yaml: "yaml",
  py: "python",
  ts: "typescript",
  tsx: "tsx",
  js: "javascript",
  jsx: "jsx",
  css: "css",
  html: "markup",
  xml: "markup",
  sql: "sql",
  go: "go",
  rs: "rust",
};

function fileLanguage(path: string): string {
  const ext = path.split(".").pop()?.toLowerCase() ?? "";
  return EXT_LANG[ext] ?? "plaintext";
}

function ReadBody({
  args,
  preview,
  legacy,
}: {
  args?: AgentToolArgsDisplay;
  preview?: AgentToolResultPreview;
  legacy: string | null;
}) {
  const { t } = useI18n();
  const path = typeof args?.path === "string" ? args.path : null;
  const language = path ? fileLanguage(path) : "plaintext";
  const [full, setFull] = useState<{ status: "idle" | "loading" | "ready" | "error"; text: string }>({
    status: "idle",
    text: "",
  });

  async function loadFull() {
    if (!path) return;
    setFull({ status: "loading", text: "" });
    try {
      const text = await getText(`/api/workspace/file?path=${encodeURIComponent(path)}`);
      setFull({ status: "ready", text });
    } catch {
      setFull({ status: "error", text: "" });
    }
  }

  const hiddenLines = preview
    ? Math.max(0, (preview.total_lines ?? 0) - countPreviewLines(preview))
    : 0;

  return (
    <>
      {preview && full.status !== "ready" && (
        <div className="at-code-frame">
          {path && (
            <div className="at-file-head">
              <span className="at-file-path">{path}</span>
              <span className="at-file-lang">{path.split(".").pop() ?? "txt"}</span>
              <CopyButton text={preview.head + (preview.tail ? `\n…\n${preview.tail}` : "")} />
            </div>
          )}
          <PreviewBlock preview={preview} language={language} numbered />
          {preview.truncated && hiddenLines > 0 && (
            <button className="at-more" type="button" onClick={() => void loadFull()} disabled={full.status === "loading"}>
              {full.status === "loading" ? t("chat.toolLoading") : t("chat.toolRestLines").replace("{count}", String(hiddenLines))}
            </button>
          )}
          {full.status === "error" && <div className="at-preview-meta">{t("chat.toolLoadFailed")}</div>}
        </div>
      )}
      {preview && full.status === "ready" && (
        <div className="at-code-frame">
          {path && (
            <div className="at-file-head">
              <span className="at-file-path">{path}</span>
              <span className="at-file-lang">{path.split(".").pop() ?? "txt"}</span>
              <CopyButton text={full.text} />
            </div>
          )}
          <CodeBlock code={capFullText(full.text)} language={language} numbered />
        </div>
      )}
      {!preview && legacy && <pre className="at-detail">{legacy}</pre>}
    </>
  );
}

function capFullText(text: string): string {
  const lines = text.split("\n");
  if (lines.length <= 4_000) return text;
  return `${lines.slice(0, 4_000).join("\n")}\n…`;
}

function GenericBody({
  preview,
  legacy,
  summary,
  toolName,
}: {
  preview?: AgentToolResultPreview;
  legacy: string | null;
  summary: string;
  toolName: string;
}) {
  return (
    <>
      {legacy && <pre className="at-detail">{legacy}</pre>}
      {preview && <PreviewBlock preview={preview} language="plaintext" />}
      {!preview && !legacy && <pre className="at-detail">{toolLabel(summary, toolName)}</pre>}
    </>
  );
}

function countPreviewLines(preview: AgentToolResultPreview): number {
  const head = preview.head ? preview.head.split("\n").length : 0;
  const tail = preview.tail ? preview.tail.split("\n").length : 0;
  return head + tail;
}

function PreviewBlock({
  preview,
  language,
  numbered = false,
}: {
  preview: AgentToolResultPreview;
  language: string;
  numbered?: boolean;
}) {
  const { t } = useI18n();
  const tailStart = Math.max(1, (preview.total_lines ?? 0) - (preview.tail ? preview.tail.split("\n").length : 0) + 1);
  return (
    <div className={`at-preview ${preview.kind === "error" ? "is-error" : ""}`}>
      {preview.head && <CodeBlock code={preview.head} language={language} numbered={numbered} />}
      {preview.truncated && (
        <div className="at-preview-gap">{numbered ? t("chat.toolRestLines").replace("{count}", "…") : "…"}</div>
      )}
      {preview.tail && (
        <CodeBlock code={preview.tail} language={language} numbered={numbered} startLine={tailStart} />
      )}
    </div>
  );
}

/** CSS-variable prism theme so token colors follow the app theme in styles.css. */
const CARD_THEME: PrismTheme = {
  plain: { color: "var(--code-plain)", backgroundColor: "transparent" },
  styles: [
    { types: ["comment", "prolog", "doctype", "cdata"], style: { color: "var(--code-comment)" } },
    { types: ["punctuation"], style: { color: "var(--code-punctuation)" } },
    { types: ["property", "tag", "boolean", "number", "constant", "symbol"], style: { color: "var(--code-number)" } },
    { types: ["selector"], style: { color: "var(--code-keyword)" } },
    { types: ["attr-name"], style: { color: "var(--code-function)" } },
    { types: ["string", "char", "builtin", "inserted"], style: { color: "var(--code-string)" } },
    { types: ["operator", "entity", "url"], style: { color: "var(--code-punctuation)" } },
    { types: ["keyword"], style: { color: "var(--code-keyword)" } },
    { types: ["atrule", "function", "class-name"], style: { color: "var(--code-function)" } },
    { types: ["regex", "important"], style: { color: "var(--code-string)" } },
    { types: ["deleted"], style: { color: "var(--code-keyword)" } },
  ],
};

function CodeBlock({
  code,
  language,
  numbered,
  startLine = 1,
}: {
  code: string;
  language: string;
  numbered: boolean;
  startLine?: number;
}) {
  const safeLanguage = Prism.languages[language] ? language : "plaintext";
  return (
    <Highlight code={code} language={safeLanguage} theme={CARD_THEME}>
      {({ className, style, tokens, getLineProps, getTokenProps }) => (
        <pre className={`at-code ${className}`} style={style}>
          {tokens.map((line, index) => {
            const lineProps = getLineProps({ line });
            return (
              <div key={index} {...lineProps} className={`at-code-line ${lineProps.className ?? ""}`}>
                {numbered && <span className="at-code-no">{startLine + index}</span>}
                <span className="at-code-text">
                  {line.map((token, key) => <span key={key} {...getTokenProps({ token })} />)}
                </span>
              </div>
            );
          })}
        </pre>
      )}
    </Highlight>
  );
}

function CopyButton({ text }: { text: string }) {
  const { t } = useI18n();
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1_500);
    } catch {
      // Clipboard may be unavailable (insecure context / jsdom); stay silent.
    }
  }

  return (
    <button className="at-copy" type="button" onClick={() => void copy()}>
      {copied ? <Check size={11} /> : <Copy size={11} />}
      <span>{copied ? t("chat.copied") : t("chat.copy")}</span>
    </button>
  );
}

function toolLabel(summary: string, toolName: string): string {
  const escaped = escapeRegExp(toolName);
  return summary.replace(new RegExp(`^${escaped}\\s*(?:·|→|-)?\\s*`), "") || summary;
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function readArgsDisplay(data: Record<string, unknown>): AgentToolArgsDisplay | undefined {
  const value = (data as { args_display?: unknown }).args_display;
  return value && typeof value === "object" ? value as AgentToolArgsDisplay : undefined;
}

function readResultPreview(data: Record<string, unknown>): AgentToolResultPreview | undefined {
  const value = (data as { result_preview?: unknown }).result_preview;
  return value && typeof value === "object" ? value as AgentToolResultPreview : undefined;
}

function readEditDiff(data: Record<string, unknown>): AgentToolEditDiff | undefined {
  const value = (data as { edit_diff_display?: unknown }).edit_diff_display;
  return value && typeof value === "object" ? value as AgentToolEditDiff : undefined;
}

function toolDetail(step: AgentProcessStep): string | null {
  const lines: string[] = [];
  const labelArgs = (step.data as Record<string, unknown>).label_args;
  if (labelArgs && typeof labelArgs === "object") {
    for (const [key, value] of Object.entries(labelArgs as Record<string, unknown>)) {
      lines.push(`${key}: ${String(value)}`);
    }
  }
  if (step.message) lines.push(step.message);
  return lines.length > 0 ? lines.join("\n") : null;
}
