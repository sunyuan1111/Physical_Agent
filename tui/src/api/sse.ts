import type { ApiEvent } from "../types.js";

export function parseSseBlock(block: string): ApiEvent | null {
  const eventLines: string[] = [];
  const dataLines: string[] = [];

  for (const line of block.split(/\r?\n/)) {
    if (!line.trim() || line.startsWith(":")) {
      continue;
    }
    if (line.startsWith("event:")) {
      eventLines.push(line.slice(6).trimStart());
      continue;
    }
    if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trimStart());
    }
  }

  if (!dataLines.length) {
    return null;
  }

  try {
    const parsed = JSON.parse(dataLines.join("\n")) as ApiEvent;
    if (!parsed.type && eventLines.length) {
      parsed.type = eventLines[eventLines.length - 1];
    }
    return parsed;
  } catch {
    return {
      type: eventLines[eventLines.length - 1] ?? "message",
      payload: { message: dataLines.join("\n"), malformed: true }
    };
  }
}

export async function readSseStream(
  response: Response,
  onEvent: (event: ApiEvent) => void,
  signal?: AbortSignal
): Promise<void> {
  if (!response.body) {
    throw new Error("SSE response did not include a readable body.");
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (!signal?.aborted) {
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
