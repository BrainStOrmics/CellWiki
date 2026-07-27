export type Page = { page_id: string; title?: string; path?: string };

export type PageDetail = {
  page_id: string;
  frontmatter: Record<string, unknown>;
  markdown: string;
};

export type Source = {
  source_id: string;
  source_type: string;
  original_name: string;
  status: string;
  content_hash: string;
  parser_name?: string | null;
  parser_version?: string | null;
  parse_hash?: string | null;
  text_hash?: string | null;
  error_reason?: string | null;
  metadata?: Record<string, unknown>;
  created_at?: string;
};

export type EvidenceReference = {
  evidence_id?: string;
  source_id: string;
  locator: string;
  excerpt: string;
  page_start?: number | null;
  page_end?: number | null;
  section?: string;
  block_id?: string | null;
  evidence_type?: string;
  confidence?: string;
};

export type ReviewItem = {
  review_item_id: string;
  type: string;
  target_id: string;
  description: string;
  severity: "low" | "medium" | "high";
  claim_ids: string[];
};

export type ChangeOperation = {
  type: string;
  target_id: string;
  payload: Record<string, unknown>;
  expected_version?: string | null;
};

export type ChangeSet = {
  change_set_id: string;
  run_id: string;
  project_id: string;
  operations: ChangeOperation[];
  evidence: EvidenceReference[];
  review_items: ReviewItem[];
  risk: "low" | "medium" | "high";
  reason: string;
  schema_version?: string;
  snapshot_id?: string | null;
  base_knowledge_version?: string | null;
  revision_id?: string | null;
  parent_change_set_id?: string | null;
  created_at: string;
};

export type ChangeSetReview = {
  change_set: ChangeSet;
  status: "awaiting_review" | "approved" | "rejected" | "committed" | "rolled_back";
  decision?: { approved: boolean; decided_by: string; reason: string; decided_at: string } | null;
  commit?: {
    commit_id: string;
    changed_targets: string[];
    snapshot_id: string;
    committed_at: string;
  } | null;
  rollback?: {
    commit_id: string;
    changed_targets: string[];
    snapshot_id: string;
    committed_at: string;
  } | null;
  preview: {
    operations: Array<{
      type: string;
      target_id: string;
      entity_count: number;
      entities: Array<{ name: string; standard_name?: string | null; marker_count: number }>;
      field_diffs: Array<{
        path: string;
        change_type: "added" | "removed" | "changed";
        before: unknown;
        after: unknown;
      }>;
      diff_truncated: boolean;
    }>;
    summary: Record<"added" | "removed" | "changed", number>;
  };
};

export type QualityReport = {
  status: "passed" | "passed_with_warnings" | "failed";
  page_count: number;
  issue_count: number;
  error_count: number;
  warning_count: number;
  levels: Record<"L0" | "L1" | "L2", {
    status: "passed" | "warning" | "failed" | "not_run";
    issue_count: number;
    description: string;
  }>;
  issues: Array<{
    finding_id: string;
    page_id: string;
    type: string;
    level: "L0" | "L1" | "L2";
    category: string;
    severity: "error" | "warning" | "info";
    detail: string;
    locator: string;
    auto_fixable: boolean;
    blocking: boolean;
    status: "open" | "resolved" | "ignored";
  }>;
};

export type TaskEvent = {
  event_id: string;
  run_id: string;
  source_id: string;
  stage: string;
  status: "running" | "awaiting_review" | "committing" | "committed" | "rejected" | "failed" | "cancelled";
  message: string;
  progress: number;
  change_set_id?: string | null;
  detail: Record<string, unknown>;
  created_at: string;
};

export type Citation = {
  page_id: string;
  source_id?: string | null;
  locator?: string | null;
};

export type AgentAnswer = {
  answer: string;
  citations: Citation[];
  confidence: string;
  missing_evidence: string[];
  knowledge_scope?: string;
  knowledge_version?: string | null;
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

export type AgentProcessPhase = "running" | "completed" | "failed";

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
  meta?: string;
  citations?: Citation[];
  confidence?: string;
  missingEvidence?: string[];
  process?: AgentProcessStep[];
  runId?: string;
  streaming?: boolean;
};

export type AgentRunStatus =
  | "queued"
  | "running"
  | "waiting_approval"
  | "applying"
  | "verifying"
  | "succeeded"
  | "rejected"
  | "failed"
  | "retrying"
  | "cancelling"
  | "cancelled";

export type AgentRun = {
  run_id: string;
  thread_id: string;
  project_id: string;
  source_id?: string | null;
  page_id?: string | null;
  status: AgentRunStatus;
  retry_count: number;
  retryable: boolean;
  cancellable: boolean;
  error_type?: string | null;
  error_message?: string | null;
  usage: {
    model_calls: number;
    input_tokens: number;
    output_tokens: number;
    estimated_cost_usd: number;
    tool_calls: number;
    elapsed_seconds: number;
  };
};

export type AgentEventType =
  | "run_status"
  | "message_delta"
  | "final_response"
  | "tool_started"
  | "tool_completed"
  | "tool_failed"
  | "subagent_started"
  | "subagent_completed"
  | "progress"
  | "review_required"
  | "changeset_ready"
  | "verification"
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

export type PipelineStatus = {
  project_id: string;
  knowledge_version: string;
  approval_policy: "manual" | "auto_all";
  default_reviewer: string;
  active_task: {
    run_id: string;
    task_type: string;
    snapshot_id: string;
    started_at: string;
  } | null;
};

export type ProviderTestResult = {
  ok: boolean;
  message: string;
  model?: string;
  protocol?: "chat_completions" | "responses";
  structured_output?: boolean;
  latency_ms?: number;
};

export type IngestPhase =
  | "idle"
  | "preparing"
  | "cancelling"
  | "cancelled"
  | "awaiting_review"
  | "committing"
  | "committed"
  | "rolled_back"
  | "rejected"
  | "failed";

export type IngestWorkflow = {
  phase: IngestPhase;
  message: string;
  error?: string;
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
