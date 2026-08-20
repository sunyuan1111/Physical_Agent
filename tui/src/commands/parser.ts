import type { ParsedCommand, TuiView } from "../types.js";

const VIEW_NAMES = new Set<TuiView>(["status", "chat", "actions", "robots", "config", "uploads"]);

export function parseCommand(input: string): ParsedCommand {
  const trimmed = input.trim();
  if (!trimmed) {
    return { type: "unknown", input, message: "Enter a message or /help." };
  }
  if (!trimmed.startsWith("/")) {
    return { type: "chat", text: trimmed };
  }

  const [name, ...rest] = trimmed.split(/\s+/);
  const payload = trimmed.slice(name.length).trim();
  switch (name.toLowerCase()) {
    case "/task":
      return payload
        ? { type: "task", text: payload }
        : { type: "unknown", input, message: "/task requires text." };
    case "/approve":
      return rest[0]
        ? { type: "approve", actionId: rest[0] }
        : { type: "unknown", input, message: "/approve requires an action id." };
    case "/reject": {
      const actionId = rest[0];
      const reason = rest.slice(1).join(" ").trim();
      return actionId && reason
        ? { type: "reject", actionId, reason }
        : { type: "unknown", input, message: "/reject requires an action id and reason." };
    }
    case "/reset":
      return payload
        ? { type: "reset", confirm: payload }
        : { type: "unknown", input, message: "/reset requires confirmation text." };
    case "/refresh":
      return { type: "refresh" };
    case "/view":
      return parseViewCommand(payload, input);
    case "/config":
      return { type: "view", view: "config" };
    case "/robots":
      return { type: "view", view: "robots" };
    case "/robot":
      return payload
        ? { type: "robot", robotId: payload }
        : { type: "unknown", input, message: "/robot requires a robot id." };
    case "/capabilities":
      return payload
        ? { type: "capabilities", robotId: payload }
        : { type: "unknown", input, message: "/capabilities requires a robot id." };
    case "/upload":
    case "/ingest":
      return payload
        ? { type: "upload", path: stripSurroundingQuotes(payload) }
        : { type: "unknown", input, message: `${name} requires a file path.` };
    case "/register-robot":
      return parseRegisterRobotCommand(payload, input);
    case "/help":
      return { type: "help" };
    case "/quit":
    case "/exit":
      return { type: "quit" };
    case "/execute":
    case "/driver":
    case "/hardware-control":
      return {
        type: "unknown",
        input,
        message: `${name} is intentionally unavailable. Use Actions approval; watch remains the only executor.`
      };
    default:
      return { type: "unknown", input, message: `Unknown command: ${name}` };
  }
}

export const COMMAND_HELP = [
  "Commands:",
  "  <text>                     Send chat message",
  "  /task <text>               Submit task proposal",
  "  /approve <action_id>       Approve execution",
  "  /reject <action_id> <why>  Reject execution",
  "  /reset true                Reset workspace through API confirmation",
  "  /refresh                   Refresh snapshot",
  "  /view <name>               Show status/chat/actions/robots/config/uploads",
  "  /config                    Show effective config",
  "  /robots                    Show robot list",
  "  /robot <robot_id>          Show robot detail",
  "  /capabilities <robot_id>   Show robot capabilities",
  "  /upload <path>             Upload and ingest a local text file through API",
  "  /ingest <path>             Alias for /upload",
  "  /register-robot <json>     Register robot through existing config API",
  "  /help                      Show this help",
  "  /quit                      Exit"
].join("\n");

function parseViewCommand(payload: string, input: string): ParsedCommand {
  const view = payload.trim().toLowerCase() as TuiView;
  if (!view) {
    return { type: "unknown", input, message: "/view requires a view name." };
  }
  if (!VIEW_NAMES.has(view)) {
    return {
      type: "unknown",
      input,
      message: `Unknown view: ${payload}. Use status, chat, actions, robots, config, or uploads.`
    };
  }
  return { type: "view", view };
}

function parseRegisterRobotCommand(payload: string, input: string): ParsedCommand {
  if (!payload) {
    return { type: "unknown", input, message: "/register-robot requires a JSON object." };
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(payload);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return { type: "unknown", input, message: `Malformed JSON for /register-robot: ${message}` };
  }
  if (!isRecord(parsed) || Array.isArray(parsed)) {
    return { type: "unknown", input, message: "/register-robot payload must be a JSON object." };
  }
  const robotId = parsed.robot_id;
  const driver = parsed.driver;
  if (typeof robotId !== "string" || typeof driver !== "string") {
    return { type: "unknown", input, message: "/register-robot JSON requires string robot_id and driver." };
  }
  const config = isRecord(parsed.config) && !Array.isArray(parsed.config) ? parsed.config : {};
  return {
    type: "registerRobot",
    payload: {
      robot_id: robotId,
      driver,
      config
    }
  };
}

function stripSurroundingQuotes(value: string): string {
  const trimmed = value.trim();
  if (trimmed.length >= 2) {
    const first = trimmed[0];
    const last = trimmed[trimmed.length - 1];
    if ((first === '"' && last === '"') || (first === "'" && last === "'")) {
      return trimmed.slice(1, -1);
    }
  }
  return trimmed;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === "object");
}
