import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Box, Text, useApp } from "ink";
import { ApiClient } from "./api/client.js";
import { COMMAND_HELP, parseCommand } from "./commands/parser.js";
import { ActionsPanel } from "./components/ActionsPanel.js";
import { ChatPanel } from "./components/ChatPanel.js";
import { CommandInput } from "./components/CommandInput.js";
import { ConfigPanel } from "./components/ConfigPanel.js";
import { RobotDetailPanel } from "./components/RobotDetailPanel.js";
import { RobotsPanel } from "./components/RobotsPanel.js";
import { StatusBar } from "./components/StatusBar.js";
import { StatusPanel } from "./components/StatusPanel.js";
import { Transcript } from "./components/Transcript.js";
import { UploadsPanel } from "./components/UploadsPanel.js";
import type {
  AgentState,
  ApiEvent,
  ChatMessage,
  ConfigResponse,
  HealthState,
  LLMSettingsResponse,
  LlmRuntimeStatus,
  RegisterRobotPayload,
  RegisterRobotResponse,
  RuntimeStatus,
  TranscriptEntry,
  TuiView,
  UploadResponse,
  WatchStatus
} from "./types.js";

export interface TuiClient {
  health(): Promise<HealthState>;
  state(): Promise<AgentState>;
  config(): Promise<ConfigResponse>;
  llmSettings(): Promise<LLMSettingsResponse>;
  testLlmSettings(): Promise<LLMSettingsResponse>;
  submitTask(task: string): Promise<{ ok: boolean; message: string; state: AgentState }>;
  approveAction(actionId: string): Promise<{ ok: boolean; message: string; state: AgentState }>;
  rejectAction(actionId: string, reason: string): Promise<{ ok: boolean; message: string; state: AgentState }>;
  resetWorkspace(confirm: string): Promise<{ ok: boolean; message: string; state: AgentState }>;
  registerRobot(payload: RegisterRobotPayload): Promise<RegisterRobotResponse>;
  uploadFile(path: string): Promise<UploadResponse>;
  sendChatStream(message: string, onEvent: (event: ApiEvent) => void, signal?: AbortSignal): Promise<void>;
  events(onEvent: (event: ApiEvent) => void, signal?: AbortSignal): Promise<void>;
}

interface AppProps {
  apiBase: string;
  pollIntervalMs: number;
  useSse: boolean;
  client?: TuiClient;
}

export function App({ apiBase, pollIntervalMs, useSse, client: injectedClient }: AppProps) {
  const client = useMemo<TuiClient>(() => injectedClient ?? new ApiClient(apiBase), [apiBase, injectedClient]);
  const { exit } = useApp();
  const [health, setHealth] = useState<HealthState | null>(null);
  const [state, setState] = useState<AgentState | null>(null);
  const [configResponse, setConfigResponse] = useState<ConfigResponse | null>(null);
  const [configError, setConfigError] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [streamingText, setStreamingText] = useState("");
  const [transcriptEntries, setTranscriptEntries] = useState<TranscriptEntry[]>([]);
  const [activeView, setActiveView] = useState<TuiView>("chat");
  const [selectedRobotId, setSelectedRobotId] = useState<string | null>(null);
  const [lastUpload, setLastUpload] = useState<UploadResponse | null>(null);
  const [mode, setMode] = useState<RuntimeStatus["mode"]>(useSse ? "sse" : "polling");
  const [connected, setConnected] = useState(false);
  const [lastRefresh, setLastRefresh] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>("Type /help for commands. Enter text to chat.");
  const [error, setError] = useState<string | null>(null);
  const [watchStatus, setWatchStatus] = useState<WatchStatus>("unknown");
  const [llmStatus, setLlmStatus] = useState<LlmRuntimeStatus>({
    state: "unknown",
    model: "-",
    hasApiKey: null
  });
  const pollingRef = useRef<NodeJS.Timeout | null>(null);
  const transcriptCounterRef = useRef(0);
  const seenChatKeysRef = useRef<Set<string>>(new Set());
  const pendingLocalChatRef = useRef<Array<{ role: string; content: string }>>([]);
  const messages: ChatMessage[] = state?.chat?.messages ?? [];

  const appendLocalChat = useCallback((role: string, content: string) => {
    const normalized = normalizeChatContent(content);
    if (!normalized) {
      return;
    }
    pendingLocalChatRef.current.push({ role, content: normalized });
    const id = `local-${Date.now()}-${transcriptCounterRef.current++}`;
    setTranscriptEntries((previous) => [
      ...previous,
      {
        id,
        role,
        content: normalized
      }
    ]);
  }, []);

  const refresh = useCallback(async () => {
    try {
      const [nextHealth, nextState] = await Promise.all([client.health(), client.state()]);
      setHealth(nextHealth);
      setState(nextState);
      setConnected(true);
      setError(null);
      setLastRefresh(new Date().toLocaleTimeString());
    } catch (err) {
      setConnected(false);
      setError(readError(err));
    }
  }, [client]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const refreshConfig = useCallback(async () => {
    try {
      const nextConfig = await client.config();
      setConfigResponse(nextConfig);
      setConfigError(null);
    } catch (err) {
      setConfigError(readError(err));
    }
  }, [client]);

  useEffect(() => {
    void refreshConfig();
  }, [refreshConfig]);

  useEffect(() => {
    const additions: TranscriptEntry[] = [];
    messages.forEach((message, index) => {
      const content = normalizeChatContent(message.content);
      if (!content) {
        return;
      }
      const key = chatMessageKey(message, index);
      if (seenChatKeysRef.current.has(key)) {
        return;
      }
      seenChatKeysRef.current.add(key);

      const pendingIndex = pendingLocalChatRef.current.findIndex(
        (pending) => pending.role === message.role && pending.content === content
      );
      if (pendingIndex >= 0) {
        pendingLocalChatRef.current.splice(pendingIndex, 1);
        return;
      }

      additions.push({
        id: key,
        role: message.role,
        content,
        created_at: message.created_at
      });
    });
    if (additions.length > 0) {
      setTranscriptEntries((previous) => [...previous, ...additions]);
    }
  }, [messages]);

  const refreshLlmStatus = useCallback(async () => {
    setLlmStatus((previous) => ({ ...previous, state: "checking", message: undefined }));
    try {
      const settingsResponse = await client.llmSettings();
      const settings = settingsResponse.settings ?? settingsResponse;
      const baseStatus = llmRuntimeStatusFromSettings(settings);
      setLlmStatus(baseStatus);

      const testResponse = await client.testLlmSettings();
      const testedSettings = testResponse.settings ?? testResponse;
      setLlmStatus({
        ...llmRuntimeStatusFromSettings(testedSettings),
        state: testResponse.ok ? "ok" : "failed",
        message: testResponse.message
      });
    } catch (err) {
      setLlmStatus((previous) => ({
        ...previous,
        state: "unavailable",
        message: readError(err)
      }));
    }
  }, [client]);

  useEffect(() => {
    void refreshLlmStatus();
  }, [refreshLlmStatus]);

  useEffect(() => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current);
    }
    if (!useSse || mode !== "sse") {
      pollingRef.current = setInterval(() => void refresh(), pollIntervalMs);
    }
    return () => {
      if (pollingRef.current) {
        clearInterval(pollingRef.current);
      }
    };
  }, [mode, pollIntervalMs, refresh, useSse]);

  useEffect(() => {
    if (!useSse) {
      setMode("polling");
      return;
    }
    const controller = new AbortController();
    const enterPollingFallback = (reason: string) => {
      setMode("degraded");
      setConnected(false);
      setError(reason);
    };
    client
      .events((event) => {
        setConnected(true);
        setMode("sse");
        const nextWatchStatus = watchStatusFromEvent(event);
        if (nextWatchStatus) {
          setWatchStatus(nextWatchStatus);
        }
        const applyResult = applyEvent(event, setState);
        if (applyResult === "summary" && shouldRefreshFullStateFromEvent(event)) {
          void refresh();
        }
        if (shouldUpdateLastRefreshFromEvent(event)) {
          setLastRefresh(new Date().toLocaleTimeString());
        }
      }, controller.signal)
      .then(() => {
        if (shouldFallbackAfterSseClose(controller.signal)) {
          enterPollingFallback(sseClosedFallbackMessage());
        }
      })
      .catch((err) => {
        if (shouldFallbackAfterSseClose(controller.signal)) {
          enterPollingFallback(sseErrorFallbackMessage(err));
        }
      });
    return () => controller.abort();
  }, [client, refresh, useSse]);

  const status: RuntimeStatus = {
    apiBase,
    connected,
    mode,
    lastRefresh,
    backend: state?.backend ?? health?.backend ?? "-",
    watch: watchStatus,
    llm: llmStatus,
    message: state?.message ?? health?.message ?? (error ? "API unavailable" : "Loading")
  };

  async function handleSubmit(value: string) {
    const command = parseCommand(value);
    setInput("");
    setNotice(null);
    if (command.type === "unknown") {
      setNotice(command.message);
      return;
    }
    if (command.type === "help") {
      setNotice(COMMAND_HELP);
      return;
    }
    if (command.type === "quit") {
      exit();
      return;
    }
    setBusy(true);
    try {
      if (command.type === "refresh") {
        await Promise.all([refresh(), refreshLlmStatus(), refreshConfig()]);
        setNotice("Snapshot refreshed.");
      } else if (command.type === "view") {
        setActiveView(command.view);
        if (["config", "robots", "uploads", "status", "actions"].includes(command.view)) {
          await Promise.all([refresh(), refreshConfig()]);
        }
        setNotice(`View: ${command.view}`);
      } else if (command.type === "robot") {
        setSelectedRobotId(command.robotId);
        setActiveView("robot");
        await Promise.all([refresh(), refreshConfig()]);
        setNotice(`Robot: ${command.robotId}`);
      } else if (command.type === "capabilities") {
        setSelectedRobotId(command.robotId);
        setActiveView("capabilities");
        await Promise.all([refresh(), refreshConfig()]);
        setNotice(`Capabilities: ${command.robotId}`);
      } else if (command.type === "upload") {
        setActiveView("uploads");
        const response = await client.uploadFile(command.path);
        setLastUpload(response);
        setState(response.state);
        setNotice(response.message);
      } else if (command.type === "registerRobot") {
        const response = await client.registerRobot(command.payload);
        if (response.config) {
          setConfigResponse({
            ok: response.ok,
            message: response.message,
            config_path: response.config_path,
            config: response.config
          });
        } else {
          await refreshConfig();
        }
        setSelectedRobotId(response.robot_id ?? command.payload.robot_id);
        setActiveView("config");
        setNotice(response.message);
      } else if (command.type === "task") {
        const response = await client.submitTask(command.text);
        setState(response.state);
        setNotice(response.message);
      } else if (command.type === "approve") {
        const response = await client.approveAction(command.actionId);
        setState(response.state);
        setNotice(response.message);
      } else if (command.type === "reject") {
        const response = await client.rejectAction(command.actionId, command.reason);
        setState(response.state);
        setNotice(response.message);
      } else if (command.type === "reset") {
        const response = await client.resetWorkspace(command.confirm);
        setState(response.state);
        setNotice(response.message);
      } else if (command.type === "chat") {
        await runChat(command.text);
      }
    } catch (err) {
      setNotice(readError(err));
    } finally {
      setBusy(false);
    }
  }

  async function runChat(text: string) {
    appendLocalChat("user", text);
    await runTuiChatStream(client, text, {
      setStreaming,
      setStreamingText,
      setState,
      setNotice,
      appendTranscript: (role, content) => appendLocalChat(role, content)
    });
  }

  return (
    <>
      {activeView === "chat" ? <Transcript entries={transcriptEntries} /> : null}
      <Box flexDirection="column" gap={1}>
        <StatusBar status={status} busy={busy || streaming} />
        {renderActiveView({
          activeView,
          status,
          health,
          state,
          configResponse,
          configError,
          selectedRobotId,
          lastUpload,
          transcriptEntries,
          streamingText,
          streaming,
          error
        })}
        {notice ? <Box paddingX={1}><Text color="gray">{notice}</Text></Box> : null}
        <CommandInput value={input} onChange={setInput} onSubmit={handleSubmit} disabled={busy} />
      </Box>
    </>
  );
}

interface ActiveViewProps {
  activeView: TuiView;
  status: RuntimeStatus;
  health: HealthState | null;
  state: AgentState | null;
  configResponse: ConfigResponse | null;
  configError: string | null;
  selectedRobotId: string | null;
  lastUpload: UploadResponse | null;
  transcriptEntries: TranscriptEntry[];
  streamingText: string;
  streaming: boolean;
  error: string | null;
}

function renderActiveView(props: ActiveViewProps) {
  switch (props.activeView) {
    case "status":
      return <StatusPanel status={props.status} health={props.health} state={props.state} config={props.configResponse} />;
    case "actions":
      return <ActionsPanel state={props.state} error={props.error} force />;
    case "robots":
      return <RobotsPanel state={props.state} config={props.configResponse} error={props.configError} />;
    case "config":
      return <ConfigPanel state={props.state} config={props.configResponse} error={props.configError} />;
    case "uploads":
      return <UploadsPanel state={props.state} lastUpload={props.lastUpload} />;
    case "robot":
      return (
        <RobotDetailPanel
          state={props.state}
          config={props.configResponse}
          robotId={props.selectedRobotId}
          mode="detail"
        />
      );
    case "capabilities":
      return (
        <RobotDetailPanel
          state={props.state}
          config={props.configResponse}
          robotId={props.selectedRobotId}
          mode="capabilities"
        />
      );
    case "chat":
    default:
      return (
        <>
          <ChatPanel
            hasTranscript={props.transcriptEntries.length > 0}
            streamingText={props.streamingText}
            streaming={props.streaming}
            error={props.error}
          />
          <ActionsPanel state={props.state} error={props.error} />
        </>
      );
  }
}

export type EventStateApplyResult = "full" | "summary" | "ignored";

export function applyEvent(event: ApiEvent, setState: (state: AgentState) => void): EventStateApplyResult {
  const payload = event.payload ?? {};
  const nestedState = payload.state;
  if (isFullAgentState(nestedState)) {
    setState(nestedState);
    return "full";
  }
  if (isAgentStateSummary(nestedState)) {
    return "summary";
  }
  return "ignored";
}

export function watchStatusFromEvent(event: ApiEvent): WatchStatus | null {
  const value = event.payload?.watch_enabled;
  if (value === true) {
    return "enabled";
  }
  if (value === false) {
    return "disabled";
  }
  return null;
}

export function shouldRefreshFullStateFromEvent(event: ApiEvent): boolean {
  if (event.type === "state") {
    return true;
  }
  if (event.type === "watch_step") {
    return Number(event.payload?.executed ?? 0) > 0;
  }
  return false;
}

export function shouldUpdateLastRefreshFromEvent(event: ApiEvent): boolean {
  return event.type !== "watch_step" || Number(event.payload?.executed ?? 0) > 0;
}

export function shouldFallbackAfterSseClose(signal: AbortSignal): boolean {
  return !signal.aborted;
}

export function sseClosedFallbackMessage(): string {
  return "SSE stream closed; using polling fallback.";
}

export function sseErrorFallbackMessage(error: unknown): string {
  return `SSE disconnected; polling fallback active. ${readError(error)}`;
}

interface ChatStreamHandlers {
  setStreaming: (value: boolean) => void;
  setStreamingText: (value: string) => void;
  setState: (state: AgentState) => void;
  setNotice: (message: string) => void;
  appendTranscript?: (role: string, content: string) => void;
}

export async function runTuiChatStream(
  client: Pick<TuiClient, "sendChatStream">,
  text: string,
  handlers: ChatStreamHandlers
): Promise<void> {
  handlers.setStreaming(true);
  handlers.setStreamingText("");
  let content = "";
  try {
    await client.sendChatStream(text, (event) => {
      const payload = event.payload ?? {};
      if (event.type === "delta") {
        content += String(payload.delta ?? "");
        handlers.setStreamingText(content);
      }
      if (event.type === "done") {
        if (isFullAgentState(payload.state)) {
          handlers.setState(payload.state);
          handlers.setStreamingText("");
        } else {
          const reply = String(payload.reply ?? content);
          if (handlers.appendTranscript) {
            handlers.appendTranscript("assistant", reply);
            handlers.setStreamingText("");
          } else {
            handlers.setStreamingText(reply);
          }
        }
      }
      if (event.type === "error") {
        handlers.setNotice(String(payload.message ?? "Streaming chat failed."));
      }
    });
  } catch (err) {
    if (!isAbortError(err)) {
      handlers.setNotice(`Streaming chat failed. ${readError(err)}`);
    }
  } finally {
    handlers.setStreaming(false);
  }
}

function isFullAgentState(value: unknown): value is AgentState {
  return isRecord(value) && "ready" in value && (
    "actions" in value ||
    "chat" in value ||
    "world" in value ||
    "capabilities" in value ||
    "feedback" in value
  );
}

function isAgentStateSummary(value: unknown): boolean {
  return isRecord(value) && "ready" in value && (
    "chat_messages" in value ||
    "pending_actions" in value ||
    "completed_count" in value ||
    "cancelled_count" in value ||
    "memory_notes" in value
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === "object");
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException
    ? error.name === "AbortError"
    : error instanceof Error && error.name === "AbortError";
}

function readError(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function llmRuntimeStatusFromSettings(settings: { model?: string; has_api_key?: boolean }): LlmRuntimeStatus {
  return {
    state: "checking",
    model: settings.model?.trim() || "-",
    hasApiKey: typeof settings.has_api_key === "boolean" ? settings.has_api_key : null
  };
}

function chatMessageKey(message: ChatMessage, index: number): string {
  return `chat-${message.created_at ?? index}-${message.role}-${stableTextHash(message.content)}`;
}

function normalizeChatContent(content: string): string {
  return content.replace(/\r\n/g, "\n").replace(/\r/g, "\n").trim();
}

function stableTextHash(value: string): string {
  let hash = 0;
  for (let index = 0; index < value.length; index += 1) {
    hash = (hash * 31 + value.charCodeAt(index)) >>> 0;
  }
  return hash.toString(36);
}
