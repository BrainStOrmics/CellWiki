export type Page = { page_id: string; title?: string; path?: string };

export type PageDetail = {
  page_id: string;
  frontmatter: Record<string, unknown>;
  markdown: string;
};

export type Citation = {
  page_id?: string | null;
  source_id?: string | null;
  locator?: string | null;
  evidence_id?: string | null;
  attachment_id?: string | null;
  original_name?: string | null;
  section_locator?: string | null;
  type?: "thread_attachment" | null;
};

export type AgentAnswer = {
  answer: string;
  citations: Citation[];
  confidence: "low" | "medium" | "high";
  declared_confidence?: "low" | "medium" | "high" | null;
  missing_evidence: string[];
  verification_level?: "evidence" | "page" | "unvalidated";
  knowledge_scope?: "formal" | "general" | "attachment" | "unvalidated";
  knowledge_version?: string | null;
  validation_issues?: ValidationIssue[];
  validation_warnings?: string[];
};

export type ValidationIssue = {
  code:
    | "missing_citation"
    | "unread_page"
    | "version_mismatch"
    | "source_mismatch"
    | "locator_missing"
    | "unsupported_evidence_id";
  message: string;
  page_id?: string | null;
  source_id?: string | null;
  locator?: string | null;
};

export type AgentAttachmentReference = {
  attachment_id: string;
  original_name?: string;
  media_type?: string;
  content_hash?: string;
  size_bytes?: number;
};

export type AgentMessage = {
  message_id: string;
  thread_id: string;
  run_id: string;
  sequence: number;
  role: "user" | "assistant";
  content: string;
  data: Record<string, unknown>;
  created_at: string;
};

export type AgentProcessPhase = "running" | "completed" | "failed" | "cancelled";

export type AgentProcessStep = {
  event_id: string;
  run_id: string;
  thread_id: string;
  sequence: number;
  type: AgentEventType;
  message: string;
  progress?: number | null;
  data: Record<string, unknown>;
  created_at: string;
  phase: AgentProcessPhase;
};

export type ChatMessage = {
  role: "user" | "agent";
  text: string;
  attachments?: AgentAttachmentReference[];
  meta?: string;
  citations?: Citation[];
  confidence?: "low" | "medium" | "high";
  declaredConfidence?: "low" | "medium" | "high" | null;
  verificationLevel?: "evidence" | "page" | "unvalidated";
  knowledgeScope?: "formal" | "general" | "attachment" | "unvalidated";
  validationIssues?: ValidationIssue[];
  missingEvidence?: string[];
  process?: AgentProcessStep[];
  reasoning?: string;
  timeline?: AgentTimelineNode[];
  runId?: string;
  runStatus?: AgentRunStatus;
  streaming?: boolean;
  /** ADR-0010 决策 9：每段流的用量。只喂给 AgentRunDiagnostics，
   *  绝不进聊天气泡的 text / timeline。 */
  usageSegments?: AgentUsageSegment[];
};

export type AgentTimelineStatusTone = "info" | "success" | "warning" | "danger";

/** Bounded whitelisted tool-argument projection carried on tool_started events. */
export type AgentToolArgsDisplay = {
  title?: string;
  command?: string;
  path?: string;
  pattern?: string;
  args?: string[];
  [key: string]: unknown;
};

/** Head+tail bounded tool-output preview carried on tool_completed events. */
export type AgentToolResultPreview = {
  head: string;
  tail: string;
  total_chars: number;
  total_lines?: number;
  truncated: boolean;
  kind: "text" | "error" | "results";
  count?: number;
  /** lint_knowledge_base 的结论摘要：报告本体总被截断，结论单独摘出。 */
  summary?: {
    status: string;
    page_count: number;
    error_count: number;
    warning_count: number;
  };
};

export type AgentToolEditDiffLine = {
  kind: "context" | "removed" | "added" | "gap";
  text: string;
  old_no?: number | null;
  new_no?: number | null;
  count?: number;
};

/** 裁决 #11：edit_file 的真行级 diff，独立有界字段，带截断标记。 */
export type AgentToolEditDiff = {
  lines: AgentToolEditDiffLine[];
  removed: number;
  added: number;
  truncated: boolean;
};

export type AgentTimelineNode =
  | { kind: "context"; label: string; detail?: string }
  | { kind: "thinking"; text: string }
  | {
      kind: "tool";
      phase: AgentProcessPhase;
      toolName: string;
      summary: string;
      step: AgentProcessStep;
      argsDisplay?: AgentToolArgsDisplay;
      resultPreview?: AgentToolResultPreview;
      /** 裁决 #11：edit_file 的真行级 diff（独立有界字段，带截断标记）。 */
      editDiff?: AgentToolEditDiff;
    }
  | { kind: "status"; tone: AgentTimelineStatusTone; label: string; step?: AgentProcessStep }
  | { kind: "text"; text: string };

export type AgentRunStatus =
  | "queued"
  | "running"
  | "waiting_confirmation"
  | "waiting_approval"
  | "applying"
  | "verifying"
  | "succeeded"
  | "rejected"
  | "failed"
  | "retrying"
  | "cancelling"
  | "unfinished"
  | "cancelled";

export type AgentRun = {
  run_id: string;
  thread_id: string;
  project_id: string;
  attachment_ids?: string[];
  source_id?: string | null;
  page_id?: string | null;
  selected_text?: string | null;
  task_kind?: string;
  task_payload?: Record<string, unknown>;
  model_role?: string;
  model_name?: string;
  status: AgentRunStatus;
  finished_at?: string | null;
  retry_count: number;
  retryable: boolean;
  cancellable: boolean;
  resumable: boolean;
  answer?: string;
  error_type?: string | null;
  error_message?: string | null;
  usage: {
    model_calls: number;
    input_tokens: number;
    output_tokens: number;
    cached_input_tokens?: number;
    cache_creation_input_tokens?: number;
    estimated_cost_usd: number;
    tool_calls: number;
    tool_calls_started?: number;
    tool_calls_completed?: number;
    tool_calls_failed?: number;
    tool_calls_cancelled?: number;
    elapsed_seconds: number;
  };
};

export type AttachmentRecord = {
  attachment_id: string;
  thread_id: string;
  original_name: string;
  media_type: string;
  size_bytes: number;
  content_hash: string;
  text_hash?: string | null;
  promoted_source_id?: string | null;
  created_at: string;
};

export type AgentEventType =
  | "run_status"
  | "message_delta"
  | "reasoning_delta"
  | "final_response"
  | "tool_started"
  | "tool_completed"
  | "tool_failed"
  | "subagent_started"
  | "subagent_completed"
  | "progress"
  | "task_confirmation_required"
  | "review_required"
  | "changeset_ready"
  | "verification"
  | "usage_updated"
  | "error";

export type AgentEvent = {
  event_id: string;
  run_id: string;
  thread_id: string;
  sequence: number;
  type: AgentEventType;
  message: string;
  progress?: number | null;
  data: Record<string, unknown>;
  created_at: string;
};

export type AgentSpan = {
  span_id: string;
  run_id: string;
  kind: string;
  name: string;
  status: string;
  started_at: string;
  finished_at?: string | null;
  duration_ms?: number | null;
  input_tokens: number;
  output_tokens: number;
  cached_input_tokens?: number;
  cache_creation_input_tokens?: number;
  data: Record<string, unknown>;
};

/** ADR-0010 决策 9：一段流结束时投递的用量（本段 + 累计）。 */
export type AgentUsageSegment = {
  event_id?: string;
  segment: AgentRun["usage"];
  cumulative: AgentRun["usage"];
};

export type AgentDiagnostics = {
  run_id: string;
  thread_id: string;
  status: AgentRunStatus;
  task_kind: string;
  model: string;
  model_role: string;
  error_type?: string | null;
  error_message?: string | null;
  usage: AgentRun["usage"];
  spans: AgentSpan[];
  thread_summary?: AgentThreadSummary;
  /** 决策 4/12：该 run 的 checkpoint 标识、载体类型与 checkpoints.sqlite 体积。 */
  checkpoint?: {
    id: string | null;
    backend: string;
    file_bytes: number;
  };
};

export type AgentThreadSummary = {
  run_count: number;
  total_input_tokens: number;
  total_output_tokens: number;
  total_cached_input_tokens: number;
  avg_cache_hit_rate: number;
};

export type AgentThreadEntry = {
  thread_id: string;
  title: string | null;
  created_at: string;
  updated_at: string;
  run_count: number;
  latest_run_id: string | null;
  latest_status: AgentRunStatus | null;
};

export type AppSettings = {
  openai_base_url: string;
  openai_model: string;
  openai_api_protocol: "chat_completions" | "responses";
  openai_api_key_configured: boolean;
  openai_api_key_hint?: string | null;
  secret_storage?: "system" | "env";
  log_level: "DEBUG" | "INFO" | "WARNING" | "ERROR" | "CRITICAL";
  app_language: "zh-CN" | "en";
  enable_agent_memory: boolean;
  enable_external_research: boolean;
  memory_recall_token_budget: number;
  restart_required?: boolean;
};

export type ProviderTestResult = {
  ok: boolean;
  message: string;
  model?: string;
  protocol?: "chat_completions" | "responses";
  structured_output?: boolean;
  latency_ms?: number;
};

export type SearchDocumentType = "page" | "entity" | "source" | "claim" | "evidence" | "lint";

export type SearchResult = {
  document_id: string;
  type: SearchDocumentType;
  title: string;
  snippet: string;
  score: number;
  page_id?: string | null;
  source_id?: string | null;
  locator?: string | null;
  metadata: Record<string, unknown>;
};

export type GraphNodeType = "cell_type" | "marker" | "tissue" | "species" | "source" | "claim";
export type GraphEdgeType = "expresses" | "does_not_express" | "located_in" | "supported_by" | "contradicts" | "related_to";

export type GraphNode = {
  node_id: string;
  type: GraphNodeType;
  label: string;
  page_id?: string | null;
  source_id?: string | null;
  metadata: Record<string, unknown>;
};

export type GraphEdge = {
  edge_id: string;
  type: GraphEdgeType;
  source: string;
  target: string;
  claim_id?: string | null;
  source_id?: string | null;
  confidence: string;
  evidence_count: number;
  metadata: Record<string, unknown>;
};

export type KnowledgeGraph = {
  nodes: GraphNode[];
  edges: GraphEdge[];
  scope: string;
  truncated: boolean;
};

export type MemoryRecord = {
  memory_id: string;
  project_id: string;
  kind: "episode" | "stable";
  content: string;
  key?: string | null;
  run_id?: string | null;
  confidence: number;
  tags: string[];
  status: "active" | "conflict" | "expired" | "deleted";
  conflicts_with: string[];
  expires_at?: string | null;
  created_at: string;
  updated_at: string;
};

export type ResearchCandidate = {
  candidate_id: string;
  project_id: string;
  query: string;
  source_id: string;
  title: string;
  url: string;
  status: "peer_reviewed" | "preprint" | "retracted" | "unknown";
  warnings: string[];
  accessed_at: string;
};
