import { readFile, stat } from "node:fs/promises";
import { basename, extname } from "node:path";
import type { UploadResponse } from "../types.js";

export const MAX_UPLOAD_BYTES = 5 * 1024 * 1024;
export const ALLOWED_UPLOAD_SUFFIXES = [
  ".txt",
  ".md",
  ".markdown",
  ".py",
  ".json",
  ".yaml",
  ".yml",
  ".toml",
  ".csv",
  ".log"
];

const CONTENT_TYPES: Record<string, string> = {
  ".txt": "text/plain",
  ".md": "text/markdown",
  ".markdown": "text/markdown",
  ".py": "text/x-python",
  ".json": "application/json",
  ".yaml": "application/yaml",
  ".yml": "application/yaml",
  ".toml": "application/toml",
  ".csv": "text/csv",
  ".log": "text/plain"
};

export interface UploadOptions {
  tags?: string;
  importance?: number;
  fetchImpl?: typeof fetch;
}

interface UploadFileSource {
  file: Blob;
  filename: string;
  path: string;
  size: number;
}

export async function uploadLocalFile(
  apiBase: string,
  path: string,
  options: UploadOptions = {}
): Promise<UploadResponse> {
  const source = await prepareUploadFile(path);
  const form = new FormData();
  form.append("file", source.file, source.filename);
  if (options.tags?.trim()) {
    form.append("tags", options.tags.trim());
  }
  form.append("importance", String(options.importance ?? 0));

  const fetchImpl = options.fetchImpl ?? fetch;
  const response = await fetchImpl(`${apiBase.replace(/\/+$/, "")}/api/upload`, {
    method: "POST",
    body: form
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data?.ok === false) {
    throw new Error(data?.message || `Upload failed: ${response.status}`);
  }
  return data as UploadResponse;
}

export async function prepareUploadFile(path: string): Promise<UploadFileSource> {
  const normalizedPath = stripSurroundingQuotes(path.trim());
  if (!normalizedPath) {
    throw new Error("/upload requires a file path.");
  }

  let fileStat;
  try {
    fileStat = await stat(normalizedPath);
  } catch {
    throw new Error(`File does not exist: ${normalizedPath}`);
  }
  if (!fileStat.isFile()) {
    throw new Error(`Upload path must be a regular file: ${normalizedPath}`);
  }
  if (fileStat.size > MAX_UPLOAD_BYTES) {
    throw new Error("Uploaded file exceeds the 5MB limit.");
  }

  const suffix = extname(normalizedPath).toLowerCase();
  if (!ALLOWED_UPLOAD_SUFFIXES.includes(suffix)) {
    throw new Error(
      `Unsupported upload type: ${suffix || "<none>"}. ` +
        `Supported text suffixes: ${ALLOWED_UPLOAD_SUFFIXES.join(", ")}.`
    );
  }

  const data = await readFile(normalizedPath);
  if (looksBinary(data)) {
    throw new Error("Binary or non-UTF-8 content is not supported.");
  }

  return {
    path: normalizedPath,
    size: fileStat.size,
    filename: basename(normalizedPath),
    file: new Blob([new Uint8Array(data)], {
      type: CONTENT_TYPES[suffix] ?? "text/plain"
    })
  };
}

export function looksBinary(data: Uint8Array): boolean {
  if (data.length === 0) {
    return false;
  }
  if (data.includes(0)) {
    return true;
  }
  try {
    new TextDecoder("utf-8", { fatal: true }).decode(data);
  } catch {
    return true;
  }

  const sample = data.subarray(0, Math.min(data.length, 2048));
  let control = 0;
  for (const byte of sample) {
    const allowedWhitespace = byte === 9 || byte === 10 || byte === 12 || byte === 13;
    if (byte < 32 && !allowedWhitespace) {
      control += 1;
    }
  }
  return control / sample.length > 0.1;
}

function stripSurroundingQuotes(value: string): string {
  if (value.length >= 2) {
    const first = value[0];
    const last = value[value.length - 1];
    if ((first === '"' && last === '"') || (first === "'" && last === "'")) {
      return value.slice(1, -1);
    }
  }
  return value;
}
