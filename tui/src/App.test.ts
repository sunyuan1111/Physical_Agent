import assert from "node:assert/strict";
import test from "node:test";
import {
  applyEvent,
  runTuiChatStream,
  shouldRefreshFullStateFromEvent,
  shouldUpdateLastRefreshFromEvent,
  shouldFallbackAfterSseClose,
  sseClosedFallbackMessage,
  sseErrorFallbackMessage,
  watchStatusFromEvent
} from "./App.js";
import type { AgentState } from "./types.js";

test("chat stream rejection clears streaming state and reports readable error", async () => {
  const calls = createChatCalls();
  await runTuiChatStream(
    {
      sendChatStream: async () => {
        throw new Error("network gone");
      }
    },
    "hello",
    calls.handlers
  );

  assert.deepEqual(calls.streaming, [true, false]);
  assert.deepEqual(calls.streamingText, [""]);
  assert.equal(calls.notices.length, 1);
  assert.match(calls.notices[0], /Streaming chat failed/);
  assert.match(calls.notices[0], /network gone/);
});

test("chat stream abort clears streaming state without noisy failure", async () => {
  const calls = createChatCalls();
  const abortError = new Error("The operation was aborted");
  abortError.name = "AbortError";

  await runTuiChatStream(
    {
      sendChatStream: async () => {
        throw abortError;
      }
    },
    "hello",
    calls.handlers
  );

  assert.deepEqual(calls.streaming, [true, false]);
  assert.deepEqual(calls.notices, []);
});

test("chat stream done updates state and clears streaming", async () => {
  const calls = createChatCalls();
  const readyState = createReadyState();

  await runTuiChatStream(
    {
      sendChatStream: async (_message, onEvent) => {
        onEvent({ type: "delta", payload: { delta: "hi" } });
        onEvent({ type: "done", payload: { state: readyState } });
      }
    },
    "hello",
    calls.handlers
  );

  assert.deepEqual(calls.streaming, [true, false]);
  assert.deepEqual(calls.streamingText, ["", "hi", ""]);
  assert.deepEqual(calls.states, [readyState]);
});

test("chat stream done with summary state keeps visible reply text", async () => {
  const calls = createChatCalls();

  await runTuiChatStream(
    {
      sendChatStream: async (_message, onEvent) => {
        onEvent({ type: "delta", payload: { delta: "hello" } });
        onEvent({
          type: "done",
          payload: {
            reply: "hello",
            state: {
              ok: true,
              ready: true,
              backend: "sqlite",
              chat_messages: 2,
              pending_actions: []
            }
          }
        });
      }
    },
    "hello",
    calls.handlers
  );

  assert.deepEqual(calls.streaming, [true, false]);
  assert.equal(calls.streamingText.at(-1), "hello");
  assert.deepEqual(calls.states, []);
});

test("chat stream done with summary state can append reply to transcript", async () => {
  const calls = createChatCalls({ includeTranscript: true });

  await runTuiChatStream(
    {
      sendChatStream: async (_message, onEvent) => {
        onEvent({ type: "delta", payload: { delta: "hello" } });
        onEvent({
          type: "done",
          payload: {
            reply: "hello",
            state: {
              ok: true,
              ready: true,
              chat_messages: 2
            }
          }
        });
      }
    },
    "hello",
    calls.handlers
  );

  assert.deepEqual(calls.streamingText, ["", "hello", ""]);
  assert.deepEqual(calls.transcript, [{ role: "assistant", content: "hello" }]);
  assert.deepEqual(calls.states, []);
});

test("SSE summary state does not overwrite full TUI state", () => {
  const states: AgentState[] = [];
  const result = applyEvent(
    {
      type: "state",
      payload: {
        state: {
          ok: true,
          ready: true,
          backend: "sqlite",
          chat_messages: 4,
          pending_actions: ["act_001"],
          completed_count: 0,
          cancelled_count: 0
        }
      }
    },
    (state) => states.push(state)
  );

  assert.equal(result, "summary");
  assert.deepEqual(states, []);
});

test("full SSE state applies normally", () => {
  const states: AgentState[] = [];
  const readyState = createReadyState();
  const result = applyEvent(
    {
      type: "state",
      payload: {
        state: readyState
      }
    },
    (state) => states.push(state)
  );

  assert.equal(result, "full");
  assert.deepEqual(states, [readyState]);
});

test("idle watch_step summary does not force live refresh churn", () => {
  assert.equal(
    shouldRefreshFullStateFromEvent({
      type: "watch_step",
      payload: { executed: 0, state: { ok: true, ready: true, chat_messages: 2 } }
    }),
    false
  );
  assert.equal(
    shouldUpdateLastRefreshFromEvent({
      type: "watch_step",
      payload: { executed: 0 }
    }),
    false
  );
  assert.equal(
    shouldRefreshFullStateFromEvent({
      type: "watch_step",
      payload: { executed: 1, state: { ok: true, ready: true, chat_messages: 2 } }
    }),
    true
  );
  assert.equal(
    shouldUpdateLastRefreshFromEvent({
      type: "state",
      payload: { state: { ok: true, ready: true, chat_messages: 2 } }
    }),
    true
  );
});

test("SSE clean EOF fallback ignores only intentional abort", () => {
  const controller = new AbortController();
  assert.equal(shouldFallbackAfterSseClose(controller.signal), true);
  assert.equal(sseClosedFallbackMessage(), "SSE stream closed; using polling fallback.");

  controller.abort();
  assert.equal(shouldFallbackAfterSseClose(controller.signal), false);
});

test("SSE thrown error fallback is readable", () => {
  assert.equal(
    sseErrorFallbackMessage(new Error("socket broke")),
    "SSE disconnected; polling fallback active. socket broke"
  );
});

test("watch_enabled hello event maps to real watch status", () => {
  assert.equal(watchStatusFromEvent({ type: "hello", payload: { watch_enabled: true } }), "enabled");
  assert.equal(watchStatusFromEvent({ type: "hello", payload: { watch_enabled: false } }), "disabled");
  assert.equal(watchStatusFromEvent({ type: "hello", payload: { watch_enabled: "true" } }), null);
  assert.equal(watchStatusFromEvent({ type: "state", payload: {} }), null);
});

function createChatCalls(options: { includeTranscript?: boolean } = {}) {
  const streaming: boolean[] = [];
  const streamingText: string[] = [];
  const states: AgentState[] = [];
  const notices: string[] = [];
  const transcript: Array<{ role: string; content: string }> = [];
  const result = {
    streaming,
    streamingText,
    states,
    notices,
    transcript,
    handlers: {
      setStreaming(value: boolean) {
        streaming.push(value);
      },
      setStreamingText(value: string) {
        streamingText.push(value);
      },
      setState(state: AgentState) {
        states.push(state);
      },
      setNotice(message: string) {
        notices.push(message);
      }
    } as {
      setStreaming(value: boolean): void;
      setStreamingText(value: string): void;
      setState(state: AgentState): void;
      setNotice(message: string): void;
      appendTranscript?: (role: string, content: string) => void;
    }
  };
  if (options.includeTranscript) {
    result.handlers.appendTranscript = (role: string, content: string) => {
      transcript.push({ role, content });
    };
  }
  return result;
}

function createReadyState(): AgentState {
  return {
    ready: true,
    backend: "sqlite",
    message: "Ready.",
    actions: { pending: [], completed: [], cancelled: [] },
    chat: { messages: [] }
  };
}
