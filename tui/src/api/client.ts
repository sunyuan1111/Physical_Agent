import { readSseStream } from "./sse.js";
import { uploadLocalFile } from "./upload.js";
import type {
  ActionItem,
  AgentState,
  ApiEvent,
  ConfigResponse,
  HealthState,
  LLMSettingsResponse,
  RegisterRobotPayload,
  RegisterRobotResponse,
  UploadResponse
} from "../types.js";

export class ApiClient {
  readonly apiBase: string;

  constructor(apiBase: string) {
    this.apiBase = apiBase.replace(/\/+$/, "");
  }

  health(): Promise<HealthState> {
    return this.json("/api/health", undefined, true);
  }

  state(): Promise<AgentState> {
    return this.json("/api/state", undefined, true);
  }

  config(): Promise<ConfigResponse> {
    return this.json("/api/config", undefined, true);
  }

  llmSettings(): Promise<LLMSettingsResponse> {
    return this.json("/api/settings/llm", undefined, true);
  }

  testLlmSettings(): Promise<LLMSettingsResponse> {
    return this.json("/api/settings/llm/test", { method: "POST" }, true);
  }

  submitTask(task: string): Promise<{ ok: boolean; message: string; state: AgentState }> {
    return this.json("/api/tasks/submit", {
      method: "POST",
      body: JSON.stringify({ task })
    });
  }

  approveAction(actionId: string): Promise<{ ok: boolean; message: string; state: AgentState }> {
    return this.json(`/api/actions/${encodeURIComponent(actionId)}/approve`, {
      method: "POST",
      body: JSON.stringify({ actor: "tui", reason: "Approved from Ink TUI." })
    });
  }

  rejectAction(actionId: string, reason: string): Promise<{ ok: boolean; message: string; state: AgentState }> {
    return this.json(`/api/actions/${encodeURIComponent(actionId)}/reject`, {
      method: "POST",
      body: JSON.stringify({ actor: "tui", reason })
    });
  }

  resetWorkspace(confirm: string): Promise<{ ok: boolean; message: string; state: AgentState }> {
    return this.json("/api/workspace/reset", {
      method: "POST",
      body: JSON.stringify({ confirm: normalizeResetConfirm(confirm) })
    });
  }

  registerRobot(payload: RegisterRobotPayload): Promise<RegisterRobotResponse> {
    return this.json("/api/config/robots", {
      method: "POST",
      body: JSON.stringify(payload)
    });
  }

  uploadFile(path: string): Promise<UploadResponse> {
    return uploadLocalFile(this.apiBase, path);
  }

  async sendChatStream(
    message: string,
    onEvent: (event: ApiEvent) => void,
    signal?: AbortSignal
  ): Promise<void> {
    const streamId = `tui-${Date.now()}`;
    const response = await fetch(this.url("/api/chat/stream"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message,
        request_id: streamId,
        stream_id: streamId
      }),
      signal
    });
    if (!response.ok) {
      await throwReadableError(response, "Streaming chat failed");
    }
    await readSseStream(response, onEvent, signal);
  }

  async events(onEvent: (event: ApiEvent) => void, signal?: AbortSignal): Promise<void> {
    const response = await fetch(this.url("/api/events"), {
      headers: { Accept: "text/event-stream" },
      signal
    });
    if (!response.ok) {
      await throwReadableError(response, "Event stream failed");
    }
    await readSseStream(response, onEvent, signal);
  }

  private async json<T>(path: string, init?: RequestInit, allowNotReadyBody = false): Promise<T> {
    const response = await fetch(this.url(path), {
      headers: {
        "Content-Type": "application/json",
        ...(init?.headers ?? {})
      },
      ...init
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || (!allowNotReadyBody && data?.ok === false)) {
      throw new Error(data?.message || `Request failed: ${response.status}`);
    }
    return data as T;
  }

  private url(path: string): string {
    return `${this.apiBase}${path}`;
  }
}

export function flattenActions(state: AgentState | null): ActionItem[] {
  if (!state?.actions) {
    return [];
  }
  return [
    ...(state.actions.pending ?? []).map((action) => ({ ...action, status: action.status ?? "pending" })),
    ...(state.actions.completed ?? []).map((action) => ({ ...action, status: action.status ?? "completed" })),
    ...(state.actions.cancelled ?? []).map((action) => ({ ...action, status: action.status ?? "cancelled" }))
  ];
}

function normalizeResetConfirm(confirm: string): boolean {
  return confirm.trim().toLowerCase() === "true";
}

async function throwReadableError(response: Response, prefix: string): Promise<never> {
  const data = await response.json().catch(() => ({}));
  throw new Error(data?.message || `${prefix}: ${response.status}`);
}
