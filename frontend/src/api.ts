import type {
  ActionItem,
  ActionMutationResponse,
  AgentState,
  ApiEvent,
  ConfigResponse,
  ExportAuditResponse,
  HealthState,
  IntegratePayload,
  IntegrateResponse,
  LLMSettingsPayload,
  LLMSettingsResponse,
  RegisterRobotPayload,
  RegisterRobotResponse,
  SearchResponse,
  StateCheckResult,
  UploadResponse,
  WorkspaceResetResponse,
} from "./types";

interface ApiJsonOptions {
  allowNotReadyBody?: boolean;
}

async function apiJson<T>(
  path: string,
  init: RequestInit = {},
  options: ApiJsonOptions = {},
): Promise<T> {
  const response = await fetch(path, {
    headers: {
      "Content-Type": "application/json",
      ...(init.headers ?? {}),
    },
    ...init,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok || (!options.allowNotReadyBody && data.ok === false)) {
    throw new Error(data.message || `Request failed: ${response.status}`);
  }
  return data as T;
}

export function fetchHealth(): Promise<HealthState> {
  return apiJson<HealthState>("/api/health", {}, { allowNotReadyBody: true });
}

export function fetchState(): Promise<AgentState> {
  return apiJson<AgentState>("/api/state", {}, { allowNotReadyBody: true });
}

export function fetchStateCheck(): Promise<StateCheckResult> {
  return apiJson<StateCheckResult>(
    "/api/state-check",
    {},
    { allowNotReadyBody: true },
  );
}

export function exportAudit(): Promise<ExportAuditResponse> {
  return apiJson<ExportAuditResponse>("/api/export-audit", {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export function sendChat(message: string): Promise<{
  ok: boolean;
  mode?: string;
  reply: string;
  executed: number;
  state: AgentState;
}> {
  return apiJson("/api/chat", {
    method: "POST",
    body: JSON.stringify({ message }),
  });
}

export function resetChat(): Promise<{
  ok: boolean;
  message: string;
  state: AgentState;
}> {
  return apiJson("/api/chat/reset", {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export function resetWorkspace(): Promise<WorkspaceResetResponse> {
  return apiJson<WorkspaceResetResponse>("/api/workspace/reset", {
    method: "POST",
    body: JSON.stringify({ confirm: true }),
  });
}

export function integrateHardware(
  payload: IntegratePayload,
): Promise<IntegrateResponse> {
  return apiJson<IntegrateResponse>("/api/integrate", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function fetchConfig(): Promise<ConfigResponse> {
  return apiJson<ConfigResponse>("/api/config");
}

export function registerRobot(
  payload: RegisterRobotPayload,
): Promise<RegisterRobotResponse> {
  return apiJson<RegisterRobotResponse>("/api/config/robots", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export interface ChatStreamCallbacks {
  signal?: AbortSignal;
  requestId?: string;
  streamId?: string;
  onEvent: (event: ApiEvent) => void;
}

export async function sendChatStream(
  message: string,
  { signal, requestId, streamId, onEvent }: ChatStreamCallbacks,
): Promise<void> {
  const id = streamId ?? `chat-${Date.now()}`;
  const response = await fetch("/api/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message,
      request_id: requestId ?? id,
      stream_id: id,
    }),
    signal,
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(
      data.message || `Streaming chat failed: ${response.status}`,
    );
  }
  if (!response.body) {
    throw new Error("Streaming chat response did not include a readable body.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }
    buffer += decoder.decode(value, { stream: true });
    const blocks = buffer.split(/\r?\n\r?\n/);
    buffer = blocks.pop() ?? "";
    for (const block of blocks) {
      const event = parseSseBlock(block);
      if (event) {
        onEvent(event);
      }
    }
  }

  const tail = buffer + decoder.decode();
  const event = parseSseBlock(tail);
  if (event) {
    onEvent(event);
  }
}

export function abortChatStream(streamId: string): Promise<{
  ok: boolean;
  stream_id: string;
  aborted: boolean;
}> {
  return apiJson(`/api/chat/abort/${encodeURIComponent(streamId)}`, {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export function fetchLLMSettings(): Promise<LLMSettingsResponse> {
  return apiJson<LLMSettingsResponse>("/api/settings/llm");
}

export function saveLLMSettings(
  payload: LLMSettingsPayload,
): Promise<LLMSettingsResponse> {
  return apiJson<LLMSettingsResponse>("/api/settings/llm", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function testLLMSettings(): Promise<LLMSettingsResponse> {
  return apiJson<LLMSettingsResponse>(
    "/api/settings/llm/test",
    { method: "POST", body: JSON.stringify({}) },
    { allowNotReadyBody: true },
  );
}

export function submitTask(task: string): Promise<{
  ok: boolean;
  message: string;
  actions: ActionItem[];
  state: AgentState;
}> {
  return apiJson("/api/tasks/submit", {
    method: "POST",
    body: JSON.stringify({ task }),
  });
}

export function proposeAction(action: ActionItem): Promise<{
  ok: boolean;
  message: string;
  action: ActionItem;
  state: AgentState;
}> {
  return apiJson("/api/actions/propose", {
    method: "POST",
    body: JSON.stringify(action),
  });
}

export function approveAction(
  actionId: string,
  reason?: string,
): Promise<ActionMutationResponse> {
  return apiJson<ActionMutationResponse>(
    `/api/actions/${encodeURIComponent(actionId)}/approve`,
    {
      method: "POST",
      body: JSON.stringify({ actor: "gui", reason: reason ?? null }),
    },
  );
}

export function rejectAction(
  actionId: string,
  reason: string,
): Promise<ActionMutationResponse> {
  return apiJson<ActionMutationResponse>(
    `/api/actions/${encodeURIComponent(actionId)}/reject`,
    {
      method: "POST",
      body: JSON.stringify({ actor: "gui", reason }),
    },
  );
}

export function searchMemory(
  query: string,
  limit: number,
  tags?: string,
  sourceType?: string,
): Promise<SearchResponse> {
  return apiJson("/api/search-memory", {
    method: "POST",
    body: JSON.stringify({
      query,
      limit,
      tags: tags
        ? tags
            .split(",")
            .map((item) => item.trim())
            .filter(Boolean)
        : null,
      source_type: sourceType || null,
    }),
  });
}

export async function uploadBrowserFile(
  file: File,
  tags: string,
  importance: number,
): Promise<UploadResponse> {
  const form = new FormData();
  form.append("file", file);
  if (tags.trim()) {
    form.append("tags", tags);
  }
  form.append("importance", String(importance));

  const response = await fetch("/api/upload", {
    method: "POST",
    body: form,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data.ok === false) {
    throw new Error(data.message || `Upload failed: ${response.status}`);
  }
  return data as UploadResponse;
}

function parseSseBlock(block: string): ApiEvent | null {
  const lines = block.split(/\r?\n/);
  const dataLines = lines
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice(5).trimStart());
  if (!dataLines.length) {
    return null;
  }
  try {
    return JSON.parse(dataLines.join("\n")) as ApiEvent;
  } catch {
    return null;
  }
}
