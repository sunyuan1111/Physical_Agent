import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import test, { type TestContext } from "node:test";
import { MAX_UPLOAD_BYTES, prepareUploadFile, uploadLocalFile } from "./upload.js";

test("uploadLocalFile posts multipart data and returns backend success", async (t) => {
  const root = await makeTempDir(t);
  const file = join(root, "note.md");
  await writeFile(file, "# note\n\nupload safely", "utf8");
  let calledUrl = "";

  const response = await uploadLocalFile("http://127.0.0.1:8766", file, {
    fetchImpl: async (url, init) => {
      calledUrl = String(url);
      assert.equal(init?.method, "POST");
      assert.ok(init?.body instanceof FormData);
      return jsonResponse({
        ok: true,
        message: "File uploaded.",
        filename: "note.md",
        size_bytes: 20,
        result: { chunks_written: 1, metadata: { sha256: "abc123" } },
        state: { ready: true }
      });
    }
  });

  assert.equal(calledUrl, "http://127.0.0.1:8766/api/upload");
  assert.equal(response.filename, "note.md");
  assert.equal(response.result?.chunks_written, 1);
});

test("uploadLocalFile reports backend error", async (t) => {
  const root = await makeTempDir(t);
  const file = join(root, "note.txt");
  await writeFile(file, "hello", "utf8");

  await assert.rejects(
    uploadLocalFile("http://127.0.0.1:8766", file, {
      fetchImpl: async () => jsonResponse({ ok: false, message: "backend rejected it" }, 400)
    }),
    /backend rejected it/
  );
});

test("prepareUploadFile rejects missing files and directories", async (t) => {
  const root = await makeTempDir(t);
  await assert.rejects(prepareUploadFile(join(root, "missing.txt")), /File does not exist/);
  await assert.rejects(prepareUploadFile(root), /regular file/);
});

test("prepareUploadFile rejects oversized files", async (t) => {
  const root = await makeTempDir(t);
  const file = join(root, "huge.txt");
  await writeFile(file, Buffer.alloc(MAX_UPLOAD_BYTES + 1, 97));

  await assert.rejects(prepareUploadFile(file), /5MB limit/);
});

test("prepareUploadFile rejects binary files", async (t) => {
  const root = await makeTempDir(t);
  const file = join(root, "binary.txt");
  await writeFile(file, Buffer.from([0, 1, 2, 3]));

  await assert.rejects(prepareUploadFile(file), /Binary or non-UTF-8/);
});

test("prepareUploadFile rejects unsupported suffixes", async (t) => {
  const root = await makeTempDir(t);
  const file = join(root, "manual.pdf");
  await writeFile(file, "%PDF-1.7\n", "utf8");

  await assert.rejects(prepareUploadFile(file), /Unsupported upload type/);
});

async function makeTempDir(t: TestContext): Promise<string> {
  const root = await mkdtemp(join(tmpdir(), "physical-agent-tui-upload-"));
  t.after(async () => {
    await rm(root, { recursive: true, force: true });
  });
  return root;
}

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" }
  });
}
