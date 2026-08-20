import type { AgentState } from "../types";

export interface WorldObjectOverview {
  key: string;
  id: string;
  type: string;
  location: string;
  pose: string;
  status: string;
  raw: Record<string, unknown>;
}

export const WORLD_OBJECT_KNOWN_KEYS = [
  "id",
  "type",
  "location",
  "pose",
  "position",
  "status",
  "state",
  "availability"
];

export function formatWorldObjects(world: AgentState["world"] | undefined): WorldObjectOverview[] {
  return objectEntries(readWorldObjects(world)).map(([id, value], index) => {
    const record = asRecord(value);
    const resolvedId = formatPrimitive(record.id, id || `object_${index + 1}`);
    return {
      key: resolvedId,
      id: resolvedId,
      type: formatPrimitive(record.type, "object"),
      location: formatObjectValue(record.location ?? record.position, "-"),
      pose: formatObjectValue(record.pose, "-"),
      status: formatPrimitive(record.status ?? record.state ?? record.availability, "unknown"),
      raw: omitKeys(record, WORLD_OBJECT_KNOWN_KEYS)
    };
  });
}

export function readWorldState(world: AgentState["world"] | undefined): Record<string, unknown> {
  const root = asRecord(world);
  const nested = asRecord(root.state);
  return Object.keys(nested).length ? nested : root;
}

export function readWorldObjects(world: AgentState["world"] | undefined): unknown {
  const root = asRecord(world);
  const state = readWorldState(world);
  return state.objects ?? root.objects ?? {};
}

export function formatObjectValue(value: unknown, fallback = "-"): string {
  if (value === undefined || value === null || value === "") {
    return fallback;
  }
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (Array.isArray(value)) {
    if (!value.length) {
      return "[]";
    }
    return `[${value.map((item) => formatObjectValue(item, fallback)).join(", ")}]`;
  }

  const record = asRecord(value);
  const preferredKeys = ["x", "y", "z", "theta", "yaw", "pitch", "roll", "location", "id"];
  const preferred = preferredKeys
    .filter((key) => record[key] !== undefined && record[key] !== null && record[key] !== "")
    .map((key) => `${key}=${formatObjectValue(record[key], fallback)}`);
  if (preferred.length) {
    return preferred.join(", ");
  }

  const entries = Object.entries(record).slice(0, 4);
  if (!entries.length) {
    return "{}";
  }
  return entries.map(([key, item]) => `${key}=${formatObjectValue(item, fallback)}`).join(", ");
}

export function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

export function formatPrimitive(value: unknown, fallback = "-"): string {
  if (value === undefined || value === null || value === "") {
    return fallback;
  }
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return fallback;
}

export function omitKeys(
  record: Record<string, unknown>,
  keys: readonly string[]
): Record<string, unknown> {
  const known = new Set(keys);
  return Object.fromEntries(Object.entries(record).filter(([key]) => !known.has(key)));
}

function objectEntries(value: unknown): Array<[string, unknown]> {
  if (Array.isArray(value)) {
    return value.map((item, index) => {
      const id = formatPrimitive(asRecord(item).id, `object_${index + 1}`);
      return [id, item];
    });
  }
  return Object.entries(asRecord(value));
}
