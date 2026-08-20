import assert from "node:assert/strict";
import test from "node:test";
import { parseCommand } from "./parser.js";

test("parses chat text", () => {
  assert.deepEqual(parseCommand("hello"), { type: "chat", text: "hello" });
});

test("parses task", () => {
  assert.deepEqual(parseCommand("/task pick block"), { type: "task", text: "pick block" });
});

test("parses approve", () => {
  assert.deepEqual(parseCommand("/approve act_001"), { type: "approve", actionId: "act_001" });
});

test("parses reject", () => {
  assert.deepEqual(parseCommand("/reject act_001 unsafe"), {
    type: "reject",
    actionId: "act_001",
    reason: "unsafe"
  });
});

test("parses reset refresh help quit", () => {
  assert.deepEqual(parseCommand("/reset true"), { type: "reset", confirm: "true" });
  assert.deepEqual(parseCommand("/refresh"), { type: "refresh" });
  assert.deepEqual(parseCommand("/help"), { type: "help" });
  assert.deepEqual(parseCommand("/quit"), { type: "quit" });
});

test("parses T3 view and robot commands", () => {
  assert.deepEqual(parseCommand("/config"), { type: "view", view: "config" });
  assert.deepEqual(parseCommand("/robots"), { type: "view", view: "robots" });
  assert.deepEqual(parseCommand("/view config"), { type: "view", view: "config" });
  assert.deepEqual(parseCommand("/view robots"), { type: "view", view: "robots" });
  assert.deepEqual(parseCommand("/view uploads"), { type: "view", view: "uploads" });
  assert.deepEqual(parseCommand("/robot arm_1"), { type: "robot", robotId: "arm_1" });
  assert.deepEqual(parseCommand("/capabilities arm_1"), { type: "capabilities", robotId: "arm_1" });
});

test("parses upload and ingest paths", () => {
  assert.deepEqual(parseCommand("/upload C:/tmp/manual.md"), {
    type: "upload",
    path: "C:/tmp/manual.md"
  });
  assert.deepEqual(parseCommand('/ingest "C:/tmp/my manual.md"'), {
    type: "upload",
    path: "C:/tmp/my manual.md"
  });
});

test("parses register robot JSON object", () => {
  assert.deepEqual(
    parseCommand('/register-robot {"robot_id":"arm_2","driver":"mock_arm","config":{"mode":"mock"}}'),
    {
      type: "registerRobot",
      payload: {
        robot_id: "arm_2",
        driver: "mock_arm",
        config: { mode: "mock" }
      }
    }
  );
});

test("rejects malformed JSON and unknown views", () => {
  const malformed = parseCommand('/register-robot {"robot_id":');
  assert.equal(malformed.type, "unknown");
  assert.match(malformed.message, /Malformed JSON/);

  const notObject = parseCommand("/register-robot []");
  assert.equal(notObject.type, "unknown");
  assert.match(notObject.message, /JSON object/);

  const unknownView = parseCommand("/view hardware");
  assert.equal(unknownView.type, "unknown");
  assert.match(unknownView.message, /Unknown view/);
});

test("rejects unknown and direct hardware commands", () => {
  assert.equal(parseCommand("/wat").type, "unknown");
  const command = parseCommand("/execute act_001");
  assert.equal(command.type, "unknown");
  assert.match(command.message, /watch remains the only executor/);
});
