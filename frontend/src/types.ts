export type JsonValue =
  | string
  | number
  | boolean
  | null
  | JsonValue[]
  | { [key: string]: JsonValue };

export interface HealthState {
  ok: boolean;
  ready: boolean;
  message: string;
  backend?: string;
  config_path?: string;
  workspace_path?: string;
  config_exists?: boolean;
  workspace_exists?: boolean;
}

export interface StateCheckResult {
  ok: boolean;
  ready?: boolean;
  message?: string;
  backend: string;
  backend_role?: "recommended" | "unsupported" | string;
  backend_label?: string;
  source_of_truth?: string;
  payload_format?: string;
  human_view?: string;
  safety_source?: string;
  runtime_switch_supported?: boolean;
  switching_model?: string;
  recommendation?: string;
  workspace_path: string;
  workspace_initialized: boolean;
  retrieval_enabled?: boolean;
  retrieval_max_chunks?: number;
  retrieval_max_chars_per_chunk?: number;
  audit_dir?: string;
  audit_export_writable?: boolean;
  sqlite_schema_complete?: boolean | null;
  sqlite_chunk_schema_complete?: boolean | null;
  sqlite_missing_tables?: string[];
  sqlite_missing_action_columns?: string[];
  sqlite_missing_memory_columns?: string[];
  sqlite_missing_upload_columns?: string[];
  sqlite_missing_chunk_columns?: string[];
}

export interface ExportAuditResponse {
  ok: boolean;
  message: string;
  backend?: string;
  workspace_path?: string;
  out_dir?: string;
  manifest?: string;
  result?: {
    backend?: string;
    workspace_path?: string;
    out_dir?: string;
    manifest?: string;
    [key: string]: unknown;
  };
}

export interface ActionItem {
  id: string;
  robot: string;
  capability: string;
  params?: Record<string, unknown>;
  reason?: string | null;
  depends_on?: string[];
  metadata?: ActionMetadata;
}

export interface ActionMetadata {
  source?: string;
  proposed_by?: string;
  original_task?: string;
  user_message?: string;
  draft_reason?: string;
  planner_reason?: string | null;
  draft_id?: string;
  expected?: ExpectedCheck[] | ExpectedCheck | unknown;
  approval?: ActionApproval;
  [key: string]: unknown;
}

export interface ExpectedCheck {
  path?: string;
  op?: "eq" | "ne" | "in" | "range" | string;
  value?: unknown;
  tolerance?: number;
  units?: string;
  description?: string;
  severity?: string;
  [key: string]: unknown;
}

export interface ActionApproval {
  required?: boolean;
  status?: "pending" | "approved" | "rejected" | "not_required" | string;
  by?: string;
  at?: string;
  reason?: string;
  approved_by?: string;
  approved_at?: string;
  rejected_by?: string;
  rejected_at?: string;
  [key: string]: unknown;
}

export interface ChatMessage {
  role: "user" | "assistant" | "system";
  content: string;
  created_at?: string | null;
  metadata?: Record<string, unknown>;
}

export interface MemoryChunk {
  id?: number;
  source_type?: string;
  source_id?: string;
  sha256?: string;
  chunk_index?: number;
  content?: string;
  tags?: string[];
  trust_level?: string;
  created_at?: string;
  score?: number;
}

export interface UploadMetadata {
  original_name?: string;
  stored_name?: string;
  sha256?: string;
  size_bytes?: number;
  content_type?: string;
  suffix?: string;
  status?: string;
  tags?: string[];
  importance?: number;
  error?: string;
}

export interface AgentState {
  ok: boolean;
  ready: boolean;
  message: string;
  backend?: string;
  config_path?: string;
  workspace_path?: string;
  task?: Record<string, unknown>;
  capabilities?: {
    robots?: Record<string, RobotInfo>;
    [key: string]: unknown;
  };
  world?: Record<string, unknown>;
  actions?: {
    pending?: ActionItem[];
    completed?: ActionItem[];
    cancelled?: ActionItem[];
  };
  feedback?: Record<string, unknown>;
  safety?: Record<string, unknown>;
  chat?: {
    messages?: ChatMessage[];
    running_summary?: string;
    [key: string]: unknown;
  };
  plan?: Record<string, unknown>;
  memory?: {
    notes?: Array<Record<string, unknown>>;
    [key: string]: unknown;
  };
  uploads?: {
    uploads?: UploadMetadata[];
    [key: string]: unknown;
  };
  chunks?: {
    chunks?: MemoryChunk[];
    [key: string]: unknown;
  };
}

export interface RobotInfo {
  kind?: string;
  driver?: string;
  status?: string;
  capabilities?: Array<{
    name?: string;
    description?: string;
    params_schema?: Record<string, unknown>;
    requires_approval?: boolean;
  }>;
}

export interface ApiEvent {
  id: number;
  type: "hello" | "state" | "watch_step" | "error" | string;
  ts: string;
  payload: Record<string, unknown>;
}

export interface ActionMutationResponse {
  ok: boolean;
  message: string;
  action: ActionItem;
  changed?: boolean;
  state: AgentState;
}

export interface SearchResponse {
  ok: boolean;
  query: string;
  results: MemoryChunk[];
}

export interface UploadResponse {
  ok: boolean;
  message: string;
  filename: string;
  size_bytes: number;
  result: Record<string, unknown>;
  state: AgentState;
}

export interface LLMSettingsSummary {
  base_url: string;
  model: string;
  api_mode: string;
  has_api_key: boolean;
  masked_api_key: string;
  settings_path?: string;
}

export interface LLMSettingsResponse extends LLMSettingsSummary {
  ok: boolean;
  message?: string;
  result?: Record<string, unknown>;
  settings?: LLMSettingsSummary;
}

export interface LLMSettingsPayload {
  base_url?: string;
  api_key?: string;
  model?: string;
  api_mode?: string;
}

export interface WorkspaceResetResponse {
  ok: boolean;
  message: string;
  workspace_path?: string;
  backend?: string;
  state: AgentState;
}

export interface SchemaProperty {
  type?: string;
  default?: unknown;
  description?: string;
  enum?: unknown[];
  [key: string]: unknown;
}

export interface IntegrationSourceProfile {
  source?: string;
  resolved_path?: string;
  source_kind?: string;
  name?: string;
  title?: string;
  description?: string;
  robot_kind?: string;
  transport?: string;
  supports_simulation?: boolean;
  capabilities?: Array<Record<string, unknown>>;
  config_schema?: {
    type?: string;
    properties?: Record<string, SchemaProperty>;
    required?: string[];
    [key: string]: unknown;
  };
  evidence?: string[];
  next_steps?: string[];
  [key: string]: unknown;
}

export interface IntegrateResult {
  output_path?: string;
  generated_files?: string[];
  report_path?: string | null;
  source?: IntegrationSourceProfile;
  integration?: {
    source?: IntegrationSourceProfile;
    output_path?: string;
    generated_files?: string[];
    report_path?: string | null;
    [key: string]: unknown;
  };
  llm_used?: boolean;
  llm_error?: string | null;
  summary?: string;
  next_steps?: string[];
  validation?: {
    ok?: boolean;
    errors?: string[];
    checks?: string[];
    [key: string]: unknown;
  };
  attempts?: number;
  [key: string]: unknown;
}

export interface IntegrateResponse {
  ok: boolean;
  message: string;
  result: IntegrateResult;
  state: AgentState;
}

export interface IntegratePayload {
  source: string;
  name?: string;
  output?: string;
  llm?: boolean;
  model?: string;
}

export interface EffectiveRobotConfig {
  driver: string;
  config: Record<string, unknown>;
}

export interface EffectiveConfig {
  project?: { name?: string };
  workspace?: { path?: string; backend?: string };
  watch?: Record<string, unknown>;
  agent?: Record<string, unknown>;
  memory?: Record<string, unknown>;
  robots?: Record<string, EffectiveRobotConfig>;
}

export interface ConfigResponse {
  ok: boolean;
  message: string;
  config_path: string;
  config: EffectiveConfig;
}

export interface RegisterRobotPayload {
  robot_id: string;
  driver: string;
  config?: Record<string, unknown>;
}

export interface RegisterRobotResponse {
  ok: boolean;
  message: string;
  requires_watch_restart?: boolean;
  robot_id?: string;
  config_path?: string;
  config?: EffectiveConfig;
}
