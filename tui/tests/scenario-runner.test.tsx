import assert from "node:assert/strict";
import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { EventEmitter } from "node:events";
import React from "react";
import { render as inkRender } from "ink";
import { App, type TuiClient } from "../src/App.js";
import type {
  AgentState,
  ApiEvent,
  ConfigResponse,
  HealthState,
  LLMSettingsResponse,
  RegisterRobotPayload,
  RegisterRobotResponse,
  UploadResponse
} from "../src/types.js";

type EventBehavior = "idle" | "clean-eof" | "error";

interface ScenarioFile {
  name: string;
  cases: ScenarioCase[];
}

interface ScenarioCase {
  name: string;
  useSse?: boolean;
  initialState?: string;
  initialConfig?: string;
  initialExpectOutput?: string[];
  fail?: Partial<Record<CallName, string>>;
  events?: {
    behavior?: EventBehavior;
    error?: string;
    items?: ScenarioEvent[];
  };
  responses?: Partial<Record<QueuedCallName, ScenarioResponse[]>>;
  steps: ScenarioStep[];
}

interface ScenarioStep {
  input: string;
  covers?: string[];
  expectOutput?: string[];
  rejectOutput?: string[];
  expectCalls?: Partial<Record<CallName, number>>;
  expectState?: Record<string, unknown>;
  expectConfig?: Record<string, unknown>;
}

interface ScenarioEvent {
  type: string;
  payload?: Record<string, unknown>;
  state?: string;
}

type ScenarioResponse =
  | {
      error: string;
    }
  | {
      message?: string;
      state?: string;
      config?: string;
      robot_id?: string;
      filename?: string;
      size_bytes?: number;
      sha256?: string;
      chunks_written?: number;
      events?: ApiEvent[];
    };

type CallName =
  | "health"
  | "state"
  | "config"
  | "llmSettings"
  | "testLlmSettings"
  | "submitTask"
  | "approveAction"
  | "rejectAction"
  | "resetWorkspace"
  | "registerRobot"
  | "uploadFile"
  | "sendChatStream"
  | "events";

type QueuedCallName =
  | "submitTask"
  | "approveAction"
  | "rejectAction"
  | "resetWorkspace"
  | "registerRobot"
  | "uploadFile"
  | "sendChatStream";

interface ScenarioCaseContext {
  scenario: ScenarioFile;
  scenarioCase: ScenarioCase;
  client: ScenarioClient;
  view: TestInkInstance;
}

interface TestInkInstance {
  stdin: TestStdin;
  frames: string[];
  lastFrame(): string | undefined;
  unmount(): void;
  cleanup(): void;
}

const scenarioRoot = path.resolve("tests", "scenarios");

const requiredCoverage = [
  "/help",
  "/view status",
  "/view chat",
  "/view actions",
  "/view config",
  "/view robots",
  "/view uploads",
  "/task",
  "/approve",
  "/reject",
  "/reset",
  "/config",
  "/robots",
  "/robot",
  "/capabilities",
  "/upload",
  "/refresh",
  "/quit",
  "API offline",
  "SSE error",
  "SSE clean EOF",
  "polling fallback",
  "missing arguments",
  "invalid command",
  "upload failure",
  "reset confirmation failure"
];

const scenarioFiles = await loadScenarios();

for (const scenario of scenarioFiles) {
  for (const scenarioCase of scenario.cases) {
    test(`${scenario.name}: ${scenarioCase.name}`, async () => {
      const context = renderScenarioCase(scenario, scenarioCase);
      try {
        if (scenarioCase.initialExpectOutput?.length) {
          await waitForOutput(context.view, scenarioCase.initialExpectOutput);
        } else {
          await waitForOutput(context.view, ["Physical Agent TUI"]);
        }

        for (const step of scenarioCase.steps) {
          await submitCommand(context.view, step.input);
          await assertStep(context, step);
        }
      } finally {
        context.view.unmount();
      }
    });
  }
}

test("scenario coverage includes every documented TUI command and failure mode", () => {
  const covered = new Set<string>();
  for (const scenario of scenarioFiles) {
    for (const scenarioCase of scenario.cases) {
      for (const step of scenarioCase.steps) {
        for (const item of step.covers ?? []) {
          covered.add(item);
        }
      }
    }
  }

  for (const command of requiredCoverage) {
    assert.equal(covered.has(command), true, `${command} is not covered by tui/tests/scenarios`);
  }
});

async function loadScenarios(): Promise<ScenarioFile[]> {
  const files = (await readdir(scenarioRoot))
    .filter((file) => file.endsWith(".scenario"))
    .sort();
  assert.deepEqual(files, [
    "actions.scenario",
    "basic.scenario",
    "chat.scenario",
    "config.scenario",
    "error.scenario",
    "robots.scenario",
    "upload.scenario"
  ]);

  const parsed: ScenarioFile[] = [];
  for (const file of files) {
    const fullPath = path.join(scenarioRoot, file);
    parsed.push(JSON.parse(await readFile(fullPath, "utf8")) as ScenarioFile);
  }
  return parsed;
}

function renderScenarioCase(scenario: ScenarioFile, scenarioCase: ScenarioCase): ScenarioCaseContext {
  const client = new ScenarioClient(scenarioCase);
  const view = renderTui(
    <App
      apiBase="http://mock.local"
      pollIntervalMs={60_000}
      useSse={scenarioCase.useSse ?? true}
      client={client}
    />
  );
  return { scenario, scenarioCase, client, view };
}

async function submitCommand(view: TestInkInstance, input: string): Promise<void> {
  view.stdin.write(input);
  await delay(100);
  view.stdin.write("\r");
  await delay(0);
}

async function assertStep(context: ScenarioCaseContext, step: ScenarioStep): Promise<void> {
  if (step.expectOutput?.length) {
    await waitForOutput(context.view, step.expectOutput);
  } else {
    await delay(0);
  }

  const output = terminalOutput(context.view);
  for (const expected of step.rejectOutput ?? []) {
    assert.equal(output.includes(expected), false, `${context.scenario.name}/${step.input} unexpectedly rendered ${expected}`);
  }

  for (const [name, expectedCount] of Object.entries(step.expectCalls ?? {})) {
    assert.equal(
      context.client.callCount(name as CallName) >= expectedCount,
      true,
      `${context.scenario.name}/${step.input} expected ${name} >= ${expectedCount}, got ${context.client.callCount(name as CallName)}`
    );
  }

  for (const [pathExpression, expected] of Object.entries(step.expectState ?? {})) {
    assert.deepEqual(
      readPath(context.client.currentState, pathExpression),
      expected,
      `${context.scenario.name}/${step.input} state ${pathExpression}`
    );
  }

  for (const [pathExpression, expected] of Object.entries(step.expectConfig ?? {})) {
    assert.deepEqual(
      readPath(context.client.currentConfig, pathExpression),
      expected,
      `${context.scenario.name}/${step.input} config ${pathExpression}`
    );
  }
}

async function waitForOutput(view: TestInkInstance, expected: string[], timeoutMs = 2500): Promise<void> {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const output = terminalOutput(view);
    if (expected.every((item) => output.includes(item))) {
      return;
    }
    await delay(10);
  }
  assert.fail(`Timed out waiting for ${expected.join(", ")}.\n\nOutput:\n${terminalOutput(view)}`);
}

function terminalOutput(view: TestInkInstance): string {
  return normalizeOutput([...view.frames, view.lastFrame() ?? ""].join("\n"));
}

function normalizeOutput(value: string): string {
  return value
    .replace(/\u001B\[[0-?]*[ -/]*[@-~]/g, "")
    .replace(/\r\n/g, "\n")
    .replace(/\r/g, "\n");
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function readPath(value: unknown, pathExpression: string): unknown {
  const parts = pathExpression.split(".");
  let current: unknown = value;
  for (const part of parts) {
    if (part === "length") {
      return Array.isArray(current) || typeof current === "string" ? current.length : undefined;
    }
    if (Array.isArray(current) && /^\d+$/.test(part)) {
      current = current[Number(part)];
      continue;
    }
    if (current && typeof current === "object") {
      current = (current as Record<string, unknown>)[part];
      continue;
    }
    return undefined;
  }
  return current;
}

class ScenarioClient implements TuiClient {
  readonly calls: Record<CallName, unknown[][]> = {
    health: [],
    state: [],
    config: [],
    llmSettings: [],
    testLlmSettings: [],
    submitTask: [],
    approveAction: [],
    rejectAction: [],
    resetWorkspace: [],
    registerRobot: [],
    uploadFile: [],
    sendChatStream: [],
    events: []
  };

  currentState: AgentState;
  currentConfig: ConfigResponse;

  private readonly fail: Partial<Record<CallName, string>>;
  private readonly responses: Partial<Record<QueuedCallName, ScenarioResponse[]>>;
  private readonly eventBehavior: EventBehavior;
  private readonly eventError: string;
  private readonly eventItems: ScenarioEvent[];

  constructor(private readonly scenarioCase: ScenarioCase) {
    this.currentState = clone(stateFixtures[scenarioCase.initialState ?? "ready"]);
    this.currentConfig = clone(configFixtures[scenarioCase.initialConfig ?? "default"]);
    this.fail = scenarioCase.fail ?? {};
    this.responses = clone(scenarioCase.responses ?? {});
    this.eventBehavior = scenarioCase.events?.behavior ?? "idle";
    this.eventError = scenarioCase.events?.error ?? "SSE failed";
    this.eventItems = scenarioCase.events?.items ?? [];
  }

  callCount(name: CallName): number {
    return this.calls[name].length;
  }

  async health(): Promise<HealthState> {
    this.record("health");
    this.throwIfFailed("health");
    return {
      ok: true,
      ready: this.currentState.ready,
      backend: this.currentState.backend,
      message: this.currentState.message,
      workspace_path: this.currentState.workspace_path,
      config_path: this.currentState.config_path
    };
  }

  async state(): Promise<AgentState> {
    this.record("state");
    this.throwIfFailed("state");
    return clone(this.currentState);
  }

  async config(): Promise<ConfigResponse> {
    this.record("config");
    this.throwIfFailed("config");
    return clone(this.currentConfig);
  }

  async llmSettings(): Promise<LLMSettingsResponse> {
    this.record("llmSettings");
    this.throwIfFailed("llmSettings");
    return clone(llmOk);
  }

  async testLlmSettings(): Promise<LLMSettingsResponse> {
    this.record("testLlmSettings");
    this.throwIfFailed("testLlmSettings");
    return { ...clone(llmOk), message: "LLM connection test passed." };
  }

  async submitTask(task: string): Promise<{ ok: boolean; message: string; state: AgentState }> {
    this.record("submitTask", task);
    const response = this.nextResponse("submitTask");
    const state = this.applyState(response.state ?? "afterTask");
    return { ok: true, message: response.message ?? "Task submitted.", state };
  }

  async approveAction(actionId: string): Promise<{ ok: boolean; message: string; state: AgentState }> {
    this.record("approveAction", actionId);
    const response = this.nextResponse("approveAction");
    const state = this.applyState(response.state ?? "afterApprove");
    return { ok: true, message: response.message ?? `Action ${actionId} approved.`, state };
  }

  async rejectAction(actionId: string, reason: string): Promise<{ ok: boolean; message: string; state: AgentState }> {
    this.record("rejectAction", actionId, reason);
    const response = this.nextResponse("rejectAction");
    const state = this.applyState(response.state ?? "afterReject");
    return { ok: true, message: response.message ?? `Action ${actionId} rejected.`, state };
  }

  async resetWorkspace(confirm: string): Promise<{ ok: boolean; message: string; state: AgentState }> {
    this.record("resetWorkspace", confirm);
    const response = this.nextResponse("resetWorkspace");
    const state = this.applyState(response.state ?? "afterReset");
    return { ok: true, message: response.message ?? "Workspace reset.", state };
  }

  async registerRobot(payload: RegisterRobotPayload): Promise<RegisterRobotResponse> {
    this.record("registerRobot", payload);
    const response = this.nextResponse("registerRobot");
    if (response.config) {
      this.currentConfig = clone(configFixtures[response.config]);
    }
    return {
      ok: true,
      message: response.message ?? "Robot registered.",
      robot_id: response.robot_id ?? payload.robot_id,
      config_path: this.currentConfig.config_path,
      config: clone(this.currentConfig.config)
    };
  }

  async uploadFile(filePath: string): Promise<UploadResponse> {
    this.record("uploadFile", filePath);
    const response = this.nextResponse("uploadFile");
    const state = this.applyState(response.state ?? "afterUpload");
    return {
      ok: true,
      message: response.message ?? "Uploaded.",
      filename: response.filename ?? path.basename(filePath),
      size_bytes: response.size_bytes ?? 0,
      result: {
        chunks_written: response.chunks_written ?? 1,
        metadata: {
          original_name: response.filename ?? path.basename(filePath),
          sha256: response.sha256 ?? "upload-sha"
        }
      },
      state
    };
  }

  async sendChatStream(
    message: string,
    onEvent: (event: ApiEvent) => void,
    _signal?: AbortSignal
  ): Promise<void> {
    this.record("sendChatStream", message);
    const response = this.nextResponse("sendChatStream");
    for (const event of response.events ?? []) {
      onEvent(expandApiEvent(event));
    }
    if (response.state) {
      this.currentState = clone(stateFixtures[response.state]);
    }
  }

  async events(onEvent: (event: ApiEvent) => void, signal?: AbortSignal): Promise<void> {
    this.record("events");
    for (const event of this.eventItems) {
      onEvent(expandScenarioEvent(event));
    }

    if (this.eventBehavior === "error") {
      throw new Error(this.eventError);
    }
    if (this.eventBehavior === "clean-eof") {
      return;
    }
    await waitForAbort(signal);
  }

  private record(name: CallName, ...args: unknown[]): void {
    this.calls[name].push(args);
  }

  private throwIfFailed(name: CallName): void {
    const message = this.fail[name];
    if (message) {
      throw new Error(message);
    }
  }

  private nextResponse(name: QueuedCallName): Exclude<ScenarioResponse, { error: string }> {
    const queue = this.responses[name] ?? [];
    const response = queue.shift() ?? {};
    if ("error" in response) {
      throw new Error(response.error);
    }
    return response;
  }

  private applyState(name: string): AgentState {
    this.currentState = clone(stateFixtures[name]);
    return clone(this.currentState);
  }
}

function expandScenarioEvent(event: ScenarioEvent): ApiEvent {
  const payload = { ...(event.payload ?? {}) };
  if (event.state) {
    payload.state = clone(stateFixtures[event.state]);
  }
  return { type: event.type, payload };
}

function expandApiEvent(event: ApiEvent): ApiEvent {
  const payload = { ...(event.payload ?? {}) };
  if (typeof payload.state === "string") {
    payload.state = clone(stateFixtures[payload.state]);
  }
  return { ...event, payload };
}

async function waitForAbort(signal?: AbortSignal): Promise<void> {
  if (signal?.aborted) {
    return;
  }
  await new Promise<void>((resolve) => {
    signal?.addEventListener("abort", () => resolve(), { once: true });
  });
}

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function renderTui(tree: React.ReactElement): TestInkInstance {
  const stdout = new TestStdout();
  const stderr = new TestStdout();
  const stdin = new TestStdin();
  const instance = inkRender(tree, {
    stdout: stdout as NodeJS.WriteStream,
    stderr: stderr as NodeJS.WriteStream,
    stdin: stdin as NodeJS.ReadStream,
    debug: true,
    exitOnCtrlC: false,
    patchConsole: false
  });

  return {
    stdin,
    frames: stdout.frames,
    lastFrame: () => stdout.lastFrame(),
    unmount: () => instance.unmount(),
    cleanup: () => instance.cleanup()
  };
}

class TestStdout extends EventEmitter {
  readonly frames: string[] = [];
  private frame: string | undefined;

  get columns(): number {
    return 100;
  }

  write = (value: string): boolean => {
    this.frames.push(value);
    this.frame = value;
    return true;
  };

  lastFrame(): string | undefined {
    return this.frame;
  }
}

class TestStdin extends EventEmitter {
  isTTY = true;
  private readonly chunks: string[] = [];

  write = (value: string): boolean => {
    this.chunks.push(value);
    this.emit("readable");
    return true;
  };

  read(): string | null {
    return this.chunks.shift() ?? null;
  }

  setEncoding(): void {
    // Ink expects terminal stream methods; the test stream only emits data.
  }

  setRawMode(): void {
    // Ink expects terminal stream methods; the test stream only emits data.
  }

  resume(): void {
    // Ink expects terminal stream methods; the test stream only emits data.
  }

  pause(): void {
    // Ink expects terminal stream methods; the test stream only emits data.
  }

  ref(): void {
    // Keep Node's test runner free to exit.
  }

  unref(): void {
    // Keep Node's test runner free to exit.
  }
}

const llmOk: LLMSettingsResponse = {
  ok: true,
  settings: {
    model: "mock-llm",
    has_api_key: true
  }
};

const configFixtures: Record<string, ConfigResponse> = {
  default: {
    ok: true,
    message: "ok",
    config_path: "physical-agent.yaml",
    config: {
      workspace: { path: "./workspace", backend: "sqlite" },
      watch: { tick_ms: 500, require_human_approval: false },
      agent: { planner: "llm", model: "mock-llm", api_key: "super-secret" },
      robots: {
        arm_1: {
          driver: "mock_arm",
          config: {
            mode: "mock",
            endpoint: "loopback",
            token: "super-secret-token",
            bounds: { x: [-1, 1], y: [-1, 1], z: [0, 1] }
          }
        }
      }
    }
  },
  registeredRobot: {
    ok: true,
    message: "ok",
    config_path: "physical-agent.yaml",
    config: {
      workspace: { path: "./workspace", backend: "sqlite" },
      watch: { tick_ms: 500, require_human_approval: false },
      agent: { planner: "llm", model: "mock-llm", api_key: "super-secret" },
      robots: {
        arm_1: {
          driver: "mock_arm",
          config: { mode: "mock", endpoint: "loopback", token: "super-secret-token" }
        },
        sim_1: {
          driver: "mock_arm",
          config: { mode: "sim" }
        }
      }
    }
  }
};

const baseActionState: AgentState = {
  ready: true,
  backend: "sqlite",
  message: "Ready.",
  workspace_path: "C:/workspace",
  config_path: "physical-agent.yaml",
  chat: { messages: [] },
  world: {
    robots: {
      arm_1: { status: "idle", endpoint: "loopback", mode: "mock" }
    }
  },
  capabilities: {
    robots: {
      arm_1: {
        kind: "arm",
        driver: "mock_arm",
        status: "idle",
        capabilities: [
          {
            name: "pick",
            description: "Pick an object by object_id.",
            requires_approval: true,
            params_schema: {
              type: "object",
              properties: { object_id: { type: "string" } },
              required: ["object_id"]
            },
            constraints: { bounds: { x: [-1, 1] } }
          },
          {
            name: "observe",
            description: "Observe the workspace.",
            requires_approval: false,
            params_schema: { type: "object", properties: {} },
            constraints: {}
          }
        ]
      }
    }
  },
  actions: {
    pending: [
      {
        id: "act_001",
        robot: "arm_1",
        capability: "pick",
        reason: "Pick the red block.",
        metadata: { approval: { required: true, status: "pending" } }
      },
      {
        id: "act_002",
        robot: "arm_1",
        capability: "observe",
        reason: "Observe before moving.",
        metadata: { approval: { required: true, status: "pending" } }
      }
    ],
    completed: [],
    cancelled: []
  },
  uploads: { uploads: [] }
};

const stateFixtures: Record<string, AgentState> = {
  ready: {
    ...baseActionState,
    actions: { pending: [], completed: [], cancelled: [] }
  },
  chatReady: baseActionState,
  chatAfterReply: {
    ...baseActionState,
    chat: {
      messages: [
        { role: "assistant", content: "Previous context", created_at: "2026-07-08T00:00:00Z" },
        { role: "user", content: "hello robot", created_at: "2026-07-08T00:01:00Z" },
        { role: "assistant", content: "Hello from agent", created_at: "2026-07-08T00:01:01Z" }
      ]
    }
  },
  actionsReady: baseActionState,
  afterTask: {
    ...baseActionState,
    actions: {
      pending: [
        ...(baseActionState.actions?.pending ?? []),
        {
          id: "act_task",
          robot: "arm_1",
          capability: "pick",
          reason: "Task-created action.",
          metadata: {}
        }
      ],
      completed: [],
      cancelled: []
    }
  },
  afterApprove: {
    ...baseActionState,
    actions: {
      pending: [
        {
          id: "act_001",
          robot: "arm_1",
          capability: "pick",
          reason: "Pick the red block.",
          metadata: { approval: { required: true, status: "approved" } }
        },
        ...(baseActionState.actions?.pending ?? []).slice(1),
        {
          id: "act_task",
          robot: "arm_1",
          capability: "pick",
          reason: "Task-created action.",
          metadata: {}
        }
      ],
      completed: [],
      cancelled: []
    }
  },
  afterReject: {
    ...baseActionState,
    actions: {
      pending: [
        {
          id: "act_001",
          robot: "arm_1",
          capability: "pick",
          reason: "Pick the red block.",
          metadata: { approval: { required: true, status: "approved" } }
        },
        {
          id: "act_task",
          robot: "arm_1",
          capability: "pick",
          reason: "Task-created action.",
          metadata: {}
        }
      ],
      completed: [],
      cancelled: [
        {
          id: "act_002",
          robot: "arm_1",
          capability: "observe",
          reason: "Observe before moving.",
          status: "cancelled",
          metadata: { approval: { required: true, status: "rejected" } }
        }
      ]
    }
  },
  afterReset: {
    ...baseActionState,
    actions: { pending: [], completed: [], cancelled: [] },
    chat: { messages: [] },
    uploads: { uploads: [] }
  },
  robotsReady: baseActionState,
  uploadReady: {
    ...baseActionState,
    actions: { pending: [], completed: [], cancelled: [] },
    uploads: { uploads: [] }
  },
  afterUpload: {
    ...baseActionState,
    actions: { pending: [], completed: [], cancelled: [] },
    uploads: {
      uploads: [
        {
          original_name: "manual.md",
          stored_name: "abc-manual.md",
          sha256: "abc123def4567890",
          size_bytes: 128,
          suffix: ".md",
          status: "stored",
          memory_note_created: true
        }
      ]
    }
  },
  afterIngest: {
    ...baseActionState,
    actions: { pending: [], completed: [], cancelled: [] },
    uploads: {
      uploads: [
        {
          original_name: "manual.md",
          stored_name: "abc-manual.md",
          sha256: "abc123def4567890",
          size_bytes: 128,
          suffix: ".md",
          status: "stored",
          memory_note_created: true
        },
        {
          original_name: "notes.txt",
          stored_name: "def-notes.txt",
          sha256: "def456abc1237890",
          size_bytes: 64,
          suffix: ".txt",
          status: "stored",
          memory_note_created: true
        }
      ]
    }
  }
};
