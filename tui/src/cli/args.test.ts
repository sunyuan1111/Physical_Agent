import assert from "node:assert/strict";
import { test } from "node:test";
import { DEFAULT_API_BASE, DEFAULT_POLL_INTERVAL_MS, parseArgs } from "./args.js";

test("parseArgs uses default API base", () => {
  assert.deepEqual(parseArgs([]), {
    apiBase: DEFAULT_API_BASE,
    pollIntervalMs: DEFAULT_POLL_INTERVAL_MS,
    sse: true,
    help: false
  });
});

test("parseArgs accepts API option forms and positional URL", () => {
  assert.equal(
    parseArgs(["--api", "http://127.0.0.1:8766/"]).apiBase,
    "http://127.0.0.1:8766"
  );
  assert.equal(
    parseArgs(["--api=http://127.0.0.1:8766"]).apiBase,
    "http://127.0.0.1:8766"
  );
  assert.equal(parseArgs(["http://127.0.0.1:8766"]).apiBase, "http://127.0.0.1:8766");
});

test("parseArgs still rejects non-url positional arguments", () => {
  assert.throws(() => parseArgs(["workspace"]), /Unknown option: workspace/);
});
