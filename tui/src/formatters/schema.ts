const SECRET_KEY_PATTERN = /(api[_-]?key|secret|token|password|credential|authorization|bearer)/i;

export function isSecretKey(key: string): boolean {
  return SECRET_KEY_PATTERN.test(key);
}

export function summarizeRecord(value: unknown, empty = "none"): string {
  if (!isRecord(value)) {
    return empty;
  }
  const entries = Object.entries(value).filter(([key]) => !isSecretKey(key));
  if (entries.length === 0) {
    return Object.keys(value).length > 0 ? "redacted settings" : empty;
  }
  return entries
    .slice(0, 6)
    .map(([key, item]) => `${key}: ${summarizeValue(item)}`)
    .join("; ");
}

export function summarizeSchema(schema: unknown): string {
  if (!isRecord(schema)) {
    return "no schema";
  }
  const type = String(schema.type ?? "object");
  const properties = isRecord(schema.properties) ? Object.keys(schema.properties).filter((key) => !isSecretKey(key)) : [];
  const required = Array.isArray(schema.required) ? schema.required.map(String).filter((key) => !isSecretKey(key)) : [];
  const parts = [`type ${type}`];
  if (properties.length) {
    parts.push(`props ${properties.slice(0, 6).join(", ")}${properties.length > 6 ? ", ..." : ""}`);
  }
  if (required.length) {
    parts.push(`required ${required.slice(0, 6).join(", ")}${required.length > 6 ? ", ..." : ""}`);
  }
  return parts.join("; ");
}

export function summarizeConstraints(constraints: unknown): string {
  if (!isRecord(constraints) || Object.keys(constraints).length === 0) {
    return "none";
  }
  if (isRecord(constraints.bounds)) {
    return `bounds ${summarizeRecord(constraints.bounds)}`;
  }
  return summarizeRecord(constraints);
}

export function summarizeEndpoint(config: unknown, worldInfo: unknown): string {
  const merged = { ...recordOrEmpty(config), ...recordOrEmpty(worldInfo) };
  const keys = ["endpoint", "url", "base_url", "transport", "port", "serial_port", "address", "host"];
  const values = keys
    .map((key) => valueAsShortString(merged[key]))
    .filter((value): value is string => Boolean(value));
  return values.length ? values.slice(0, 3).join(" / ") : "-";
}

export function summarizeMode(config: unknown, worldInfo: unknown): string {
  const merged = { ...recordOrEmpty(config), ...recordOrEmpty(worldInfo) };
  return valueAsShortString(merged.mode) ?? valueAsShortString(merged.transport) ?? "-";
}

export function compactJson(value: unknown, maxLength = 180): string {
  const redacted = redactSecretValues(value);
  const text = JSON.stringify(redacted);
  if (!text) {
    return "";
  }
  return text.length > maxLength ? `${text.slice(0, maxLength - 3)}...` : text;
}

export function redactSecretValues(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map((item) => redactSecretValues(item));
  }
  if (!isRecord(value)) {
    return value;
  }
  const result: Record<string, unknown> = {};
  for (const [key, item] of Object.entries(value)) {
    if (isSecretKey(key)) {
      continue;
    }
    result[key] = redactSecretValues(item);
  }
  return result;
}

export function valueAsShortString(value: unknown): string | null {
  if (typeof value === "string" && value.trim()) {
    return value.trim();
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return null;
}

export function recordOrEmpty(value: unknown): Record<string, unknown> {
  return isRecord(value) ? value : {};
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

function summarizeValue(value: unknown): string {
  const scalar = valueAsShortString(value);
  if (scalar !== null) {
    return scalar.length > 40 ? `${scalar.slice(0, 37)}...` : scalar;
  }
  if (Array.isArray(value)) {
    return `[${value.length}]`;
  }
  if (isRecord(value)) {
    const keys = Object.keys(value).filter((key) => !isSecretKey(key));
    return keys.length ? `{${keys.slice(0, 4).join(", ")}}` : "{redacted}";
  }
  if (value === null) {
    return "null";
  }
  return String(value);
}
