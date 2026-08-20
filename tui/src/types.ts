export interface HealthState {
  ok?: boolean;
  ready?: boolean;
  message?: string;
  backend?: string;
  workspace_path?: string;
  config_path?: string;
}

export interface AgentState extends HealthState {
  actions?: ActionBoardState;
  chat?: { messages?: ChatMessage[] };
  capabilities?: {
    robots?: Record<string, RobotInfo>;
    [key: string]: unknown;
  };
  world?: Record<string, unknown>;
  uploads?: {
    uploads?: UploadMetadata[];
    [key: string]: unknown;
  };
}

export interface ActionItem {
  id: string;
  robot: string;
  capability: string;
  params?: Record<string, unknown>;
  reason?: string | null;
  status?: string;
  metadata?: Record<string, unknown>;
}

export interface ActionBoardState {
  pending?: ActionItem[];
  completed?: ActionItem[];
  cancelled?: ActionItem[];
}

export interface ChatMessage {
  role: "user" | "assistant" | "system" | string;
  content: string;
  created_at?: string;
  metadata?: Record<string, unknown>;
}

export interface RobotCapability {
  name?: string;
  description?: string;
  params_schema?: Record<string, unknown>;
  returns_schema?: Record<string, unknown> | null;
  constraints?: Record<string, unknown>;
  requires_approval?: boolean;
  timeout_s?: number | null;
  [key: string]: unknown;
}

export interface RobotInfo {
  kind?: string;
  driver?: string;
  status?: string;
  requires_approval?: boolean;
  capabilities?: RobotCapability[];
  [key: string]: unknown;
}

export interface EffectiveRobotConfig {
  driver?: string;
  config?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface EffectiveConfig {
  project?: Record<string, unknown>;
  workspace?: { path?: string; backend?: string; [key: string]: unknown };
  watch?: Record<string, unknown>;
  agent?: Record<string, unknown>;
  memory?: Record<string, unknown>;
  robots?: Record<string, EffectiveRobotConfig>;
  [key: string]: unknown;
}

export interface ConfigResponse {
  ok: boolean;
  message: string;
  config_path?: string;
  config?: EffectiveConfig;
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
  memory_note_created?: boolean;
  truncated?: boolean;
  [key: string]: unknown;
}

export interface UploadResponse {
  ok: boolean;
  message: string;
  filename: string;
  size_bytes: number;
  result?: {
    metadata?: UploadMetadata;
    chunks_written?: number;
    memory_note?: Record<string, unknown> | null;
    [key: string]: unknown;
  };
  state: AgentState;
}

export type TuiView = "status" | "chat" | "actions" | "robots" | "config" | "uploads" | "robot" | "capabilities";

export interface TranscriptEntry {
  id: string;
  role: string;
  content: string;
  created_at?: string;
}

export interface ApiEvent {
  id?: number;
  type: string;
  ts?: string;
  payload?: Record<string, unknown>;
}

export interface RuntimeStatus {
  apiBase: string;
  connected: boolean;
  mode: "sse" | "polling" | "degraded";
  lastRefresh: string | null;
  backend: string;
  watch: WatchStatus;
  llm: LlmRuntimeStatus;
  message: string;
}

export type WatchStatus = "enabled" | "disabled" | "unknown";

export interface LLMSettingsSummary {
  base_url?: string;
  model?: string;
  api_mode?: string;
  has_api_key?: boolean;
  masked_api_key?: string;
  settings_path?: string;
}

export interface LLMSettingsResponse extends LLMSettingsSummary {
  ok: boolean;
  message?: string;
  result?: Record<string, unknown>;
  settings?: LLMSettingsSummary;
}

export interface LlmRuntimeStatus {
  state: "unknown" | "checking" | "ok" | "failed" | "unavailable";
  model: string;
  hasApiKey: boolean | null;
  message?: string;
}

export type ParsedCommand =
  | { type: "chat"; text: string }
  | { type: "task"; text: string }
  | { type: "approve"; actionId: string }
  | { type: "reject"; actionId: string; reason: string }
  | { type: "reset"; confirm: string }
  | { type: "refresh" }
  | { type: "view"; view: TuiView }
  | { type: "robot"; robotId: string }
  | { type: "capabilities"; robotId: string }
  | { type: "upload"; path: string }
  | { type: "registerRobot"; payload: RegisterRobotPayload }
  | { type: "help" }
  | { type: "quit" }
  | { type: "unknown"; input: string; message: string };
