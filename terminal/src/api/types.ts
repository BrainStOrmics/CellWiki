export interface ThreadRecord {
  thread_id: string;
  title?: string | null;
  latest_status?: string | null;
  latest_run_id?: string | null;
  run_count?: number;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface MessageRecord {
  role?: string;
  content?: string;
}

export interface AgentEvent {
  event_id?: string;
  run_id: string;
  thread_id?: string;
  sequence: number;
  type: string;
  message?: string;
  progress?: number | null;
  data?: Record<string, unknown>;
  created_at?: string;
}

export interface RunUsage {
  model_calls?: number;
  input_tokens?: number;
  output_tokens?: number;
  cached_input_tokens?: number;
  cache_creation_input_tokens?: number;
  estimated_cost_usd?: number;
  tool_calls?: number;
  elapsed_seconds?: number;
}

export interface AgentRun {
  run_id: string;
  thread_id: string;
  status: string;
  pending_diff_id?: string | null;
  error_message?: string | null;
  retryable?: boolean;
  resumable?: boolean;
  cancellable?: boolean;
  usage?: RunUsage;
  answer?: string;
}

export interface QuestionOption {
  label?: string;
  description?: string;
  recommended?: boolean;
}

export interface PendingQuestion {
  question_id?: string;
  run_id: string;
  thread_id?: string;
  question?: string;
  options?: QuestionOption[];
  required?: boolean;
}

export interface PendingDiffSummary {
  diff_id: string;
  run_id?: string;
  status?: string;
  title?: string;
}

export interface ModelSelection {
  provider_id?: string;
  model_id?: string;
}

export interface ProviderModelRecord {
  id: string;
  display_name?: string | null;
  enabled?: boolean;
}

export interface ModelProviderRecord {
  id: string;
  name?: string | null;
  enabled?: boolean;
  api_key_configured?: boolean;
  models?: ProviderModelRecord[];
}

export interface ModelCatalog {
  default_selection?: ModelSelection | null;
  providers?: ModelProviderRecord[];
}

export interface ContextUsage {
  thread_id: string;
  used_tokens?: number;
  last_input_tokens?: number;
  last_output_tokens?: number;
  estimated_tokens?: number;
}
