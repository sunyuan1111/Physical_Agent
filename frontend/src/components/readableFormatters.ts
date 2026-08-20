import type { ActionItem } from "../types";

export type UnknownRecord = Record<string, unknown>;

const SUCCESS_STATUSES = new Set([
  "accepted",
  "approved",
  "completed",
  "connected",
  "ok",
  "ready",
  "verified"
]);

const DANGER_STATUSES = new Set([
  "cancelled",
  "error",
  "failed",
  "halted",
  "rejected",
  "violated"
]);

const PROCESSING_STATUSES = new Set(["in_progress", "pending", "running", "thinking"]);

const SKIPPED_STATUSES = new Set(["skipped", "not_required", "disabled"]);

export function asRecord(value: unknown): UnknownRecord {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as UnknownRecord)
    : {};
}

export function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

export function isNonEmptyRecord(value: unknown): value is UnknownRecord {
  return Object.keys(asRecord(value)).length > 0;
}

export function statusColor(status: unknown): string {
  const normalized = normalizeStatus(status);
  if (SUCCESS_STATUSES.has(normalized)) {
    return "green";
  }
  if (DANGER_STATUSES.has(normalized)) {
    return "red";
  }
  if (PROCESSING_STATUSES.has(normalized)) {
    return "gold";
  }
  if (SKIPPED_STATUSES.has(normalized)) {
    return "default";
  }
  return normalized ? "blue" : "default";
}

export function statusText(status: unknown, fallback = "unknown"): string {
  const normalized = normalizeStatus(status);
  return normalized || fallback;
}

export function normalizeStatus(status: unknown): string {
  return typeof status === "string" ? status.trim().toLowerCase() : "";
}

export function readableDate(value: unknown): string {
  if (typeof value !== "string" || !value.trim()) {
    return "";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleString();
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
  const preferredKeys = [
    "x",
    "y",
    "z",
    "theta",
    "yaw",
    "pitch",
    "roll",
    "lat",
    "lon",
    "location",
    "zone",
    "id",
    "name"
  ];
  const selected = preferredKeys
    .filter((key) => record[key] !== undefined && record[key] !== null && record[key] !== "")
    .map((key) => `${key}=${formatObjectValue(record[key], fallback)}`);
  if (selected.length) {
    return selected.join(", ");
  }
  const entries = Object.entries(record).slice(0, 4);
  if (!entries.length) {
    return "{}";
  }
  return entries.map(([key, item]) => `${key}=${formatObjectValue(item, fallback)}`).join(", ");
}

export function expectedSummary(value: unknown, limit = 2): string {
  const checks = expectedChecks(value);
  if (!checks.length) {
    return "";
  }
  const rendered = checks.slice(0, limit).map((check) => {
    const description = formatPrimitive(check.description, "");
    const path = formatPrimitive(check.path, "path?");
    const op = formatPrimitive(check.op, "op?");
    const expected = check.value !== undefined ? formatObjectValue(check.value) : "value?";
    return description || `${path} ${op} ${expected}`;
  });
  const suffix = checks.length > limit ? ` +${checks.length - limit} more` : "";
  return `${rendered.join(" · ")}${suffix}`;
}

export function expectedChecks(value: unknown): UnknownRecord[] {
  if (Array.isArray(value)) {
    return value.map(asRecord).filter(isNonEmptyRecord);
  }
  const record = asRecord(value);
  return isNonEmptyRecord(record) ? [record] : [];
}

export function compactSchemaSummary(schema: unknown): string {
  const record = asRecord(schema);
  const properties = asRecord(record.properties);
  const required = asArray(record.required).map(String);
  const propertyNames = Object.keys(properties);
  if (!propertyNames.length) {
    return formatObjectValue(schema, "No params");
  }
  return propertyNames
    .slice(0, 6)
    .map((name) => {
      const property = asRecord(properties[name]);
      const type = formatPrimitive(property.type, "value");
      return `${name}${required.includes(name) ? "*" : ""}: ${type}`;
    })
    .join(" · ");
}

export function pickFirstString(record: UnknownRecord, keys: string[]): string {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === "string" && value.trim()) {
      return value;
    }
    if (typeof value === "number" || typeof value === "boolean") {
      return String(value);
    }
  }
  return "";
}

export function omitKeys(record: UnknownRecord, keys: string[]): UnknownRecord {
  const blocked = new Set(keys);
  return Object.fromEntries(Object.entries(record).filter(([key]) => !blocked.has(key)));
}

export function allActions(actions: {
  pending?: ActionItem[];
  completed?: ActionItem[];
  cancelled?: ActionItem[];
} | undefined): ActionItem[] {
  return [
    ...(actions?.pending ?? []),
    ...(actions?.completed ?? []),
    ...(actions?.cancelled ?? [])
  ];
}
