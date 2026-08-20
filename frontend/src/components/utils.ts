export function compactJson(value: unknown, fallback = "-"): string {
  if (value === undefined || value === null || value === "") {
    return fallback;
  }
  if (typeof value === "string") {
    return value;
  }
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

export function oneLine(value: unknown, fallback = "-"): string {
  const text = compactJson(value, fallback).replace(/\s+/g, " ").trim();
  return text || fallback;
}

export function countOf(items: unknown[] | undefined): number {
  return Array.isArray(items) ? items.length : 0;
}
