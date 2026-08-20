import assert from "node:assert/strict";
import test from "node:test";
import { parseSseBlock, readSseStream } from "./sse.js";

test("parseSseBlock handles event and data", () => {
  const event = parseSseBlock('event: delta\ndata: {"type":"delta","payload":{"delta":"hi"}}');
  assert.equal(event?.type, "delta");
  assert.deepEqual(event?.payload, { delta: "hi" });
});

test("parseSseBlock joins multiple data lines", () => {
  const event = parseSseBlock('event: message\ndata: {"type":"message",\ndata: "payload":{"text":"hi"}}');
  assert.equal(event?.type, "message");
  assert.deepEqual(event?.payload, { text: "hi" });
});

test("parseSseBlock ignores blank and comment-only blocks", () => {
  assert.equal(parseSseBlock(""), null);
  assert.equal(parseSseBlock(": keepalive\n"), null);
});

test("readSseStream carries incomplete blocks across chunks", async () => {
  const encoder = new TextEncoder();
  const response = new Response(
    new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode('event: delta\ndata: {"type"'));
        controller.enqueue(encoder.encode(':"delta","payload":{"delta":"hi"}}\n\n'));
        controller.close();
      }
    }),
    { headers: { "Content-Type": "text/event-stream" } }
  );
  const events: unknown[] = [];
  await readSseStream(response, (event) => events.push(event));
  assert.deepEqual(events, [{ type: "delta", payload: { delta: "hi" } }]);
});

test("parseSseBlock degrades malformed data into readable event", () => {
  const event = parseSseBlock("event: error\ndata: not-json");
  assert.equal(event?.type, "error");
  assert.equal(event?.payload?.malformed, true);
  assert.equal(event?.payload?.message, "not-json");
});
