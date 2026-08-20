import type { AgentState, HealthState } from "../types";
import {
  CAPABILITY_KNOWN_KEYS,
  formatCapabilities,
  type CapabilityOverview
} from "./capability";
import {
  ENVIRONMENT_KNOWN_KEYS,
  formatEnvironment,
  readEnvironment,
  type EnvironmentOverview
} from "./environment";
import {
  ROBOT_KNOWN_KEYS,
  formatRobots,
  type RobotOverview
} from "./robot";
import {
  WORLD_OBJECT_KNOWN_KEYS,
  asRecord,
  formatPrimitive,
  formatWorldObjects,
  readWorldObjects,
  readWorldState,
  type WorldObjectOverview
} from "./world";

export interface SystemStatusOverview {
  ready: boolean;
  readyLabel: string;
  readyTag: {
    label: string;
    color: string;
  };
  backend: string;
  workspace: string;
  message: string;
}

export interface StateOverviewViewModel {
  system: SystemStatusOverview;
  robots: RobotOverview[];
  capabilities: CapabilityOverview[];
  environment: EnvironmentOverview;
  worldObjects: WorldObjectOverview[];
  rawDebug: Record<string, unknown>;
}

const STATE_KNOWN_KEYS = [
  "ok",
  "ready",
  "message",
  "backend",
  "config_path",
  "workspace_path",
  "config_exists",
  "workspace_exists",
  "task",
  "capabilities",
  "world",
  "actions",
  "feedback",
  "safety",
  "chat",
  "plan",
  "memory",
  "uploads",
  "chunks"
];

const WORLD_KNOWN_KEYS = [
  "summary",
  "state",
  "objects",
  "environment",
  "robots",
  "artifacts",
  "raw"
];

const WORLD_STATE_KNOWN_KEYS = ["objects", "environment", "robots", "artifacts", "raw"];

export function formatStateOverview(
  state: AgentState | null,
  health: HealthState | null
): StateOverviewViewModel {
  return {
    system: formatSystemStatus(state, health),
    robots: formatRobots(state),
    capabilities: formatCapabilities(state?.capabilities),
    environment: formatEnvironment(state?.world),
    worldObjects: formatWorldObjects(state?.world),
    rawDebug: formatRawDebugFields(state)
  };
}

export function formatSystemStatus(
  state: AgentState | null,
  health: HealthState | null
): SystemStatusOverview {
  const ready = Boolean(state?.ready ?? health?.ready);
  return {
    ready,
    readyLabel: ready ? "Ready" : "Not ready",
    readyTag: ready ? { label: "ready", color: "green" } : { label: "not ready", color: "red" },
    backend: formatPrimitive(state?.backend ?? health?.backend, "-"),
    workspace: formatPrimitive(state?.workspace_path ?? health?.workspace_path, "-"),
    message: formatPrimitive(state?.message ?? health?.message, "-")
  };
}

export function formatRawDebugFields(state: AgentState | null | undefined): Record<string, unknown> {
  const stateRecord = asRecord(state);
  const raw: Record<string, unknown> = {};

  putIfNonEmpty(raw, "unknown_state_fields", unknownFields(stateRecord, STATE_KNOWN_KEYS, true));
  putIfNonEmpty(raw, "backend_private_fields", privateFields(stateRecord));
  putIfNonEmpty(raw, "capabilities_raw", capabilitiesRaw(stateRecord.capabilities));
  putIfNonEmpty(raw, "world_raw", worldRaw(stateRecord.world));

  return raw;
}

function capabilitiesRaw(value: unknown): Record<string, unknown> {
  const capabilities = asRecord(value);
  const raw: Record<string, unknown> = {};
  putIfNonEmpty(raw, "unknown_capabilities_fields", unknownFields(capabilities, ["robots"]));

  const robotRaw = Object.fromEntries(
    Object.entries(asRecord(capabilities.robots))
      .map(([robotId, robot]) => [robotId, unknownFields(asRecord(robot), ROBOT_KNOWN_KEYS)])
      .filter(([, fields]) => Object.keys(asRecord(fields)).length)
  );
  putIfNonEmpty(raw, "robot_fields", robotRaw);

  const capabilityRaw = Object.fromEntries(
    Object.entries(asRecord(capabilities.robots))
      .map(([robotId, robot]) => {
        const entries = (asRecord(robot).capabilities as unknown[] | undefined) ?? [];
        const fields = Array.isArray(entries)
          ? entries
              .map((capability, index) => {
                const record = asRecord(capability);
                return [
                  formatPrimitive(record.name, `capability_${index + 1}`),
                  unknownFields(record, CAPABILITY_KNOWN_KEYS)
                ] as const;
              })
              .filter(([, item]) => Object.keys(item).length)
          : [];
        return [robotId, Object.fromEntries(fields)] as const;
      })
      .filter(([, fields]) => Object.keys(fields).length)
  );
  putIfNonEmpty(raw, "capability_fields", capabilityRaw);

  return raw;
}

function worldRaw(value: unknown): Record<string, unknown> {
  const root = asRecord(value);
  const state = readWorldState(root);
  const raw: Record<string, unknown> = {};

  putIfNonEmpty(raw, "unknown_world_fields", unknownFields(root, WORLD_KNOWN_KEYS));
  putIfNonEmpty(raw, "unknown_world_state_fields", unknownFields(state, WORLD_STATE_KNOWN_KEYS));
  putIfNonEmpty(raw, "world_raw_fields", asRecord(state.raw ?? root.raw));
  putIfNonEmpty(raw, "environment_fields", unknownFields(readEnvironment(root), ENVIRONMENT_KNOWN_KEYS));

  const objectRaw = Object.fromEntries(
    objectEntries(readWorldObjects(root))
      .map(([objectId, object]) => [
        objectId,
        unknownFields(asRecord(object), WORLD_OBJECT_KNOWN_KEYS)
      ])
      .filter(([, fields]) => Object.keys(fields).length)
  );
  putIfNonEmpty(raw, "object_fields", objectRaw);

  return raw;
}

function unknownFields(
  record: Record<string, unknown>,
  knownKeys: readonly string[],
  omitPrivate = false
): Record<string, unknown> {
  const known = new Set(knownKeys);
  return Object.fromEntries(
    Object.entries(record).filter(([key]) => !known.has(key) && !(omitPrivate && isPrivateField(key)))
  );
}

function privateFields(record: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(Object.entries(record).filter(([key]) => isPrivateField(key)));
}

function isPrivateField(key: string): boolean {
  return key.startsWith("_") || key.startsWith("backend_private");
}

function putIfNonEmpty(target: Record<string, unknown>, key: string, value: Record<string, unknown>) {
  if (Object.keys(value).length) {
    target[key] = value;
  }
}

function objectEntries(value: unknown): Array<[string, unknown]> {
  if (Array.isArray(value)) {
    return value.map((item, index) => [
      formatPrimitive(asRecord(item).id, `object_${index + 1}`),
      item
    ]);
  }
  return Object.entries(asRecord(value));
}
