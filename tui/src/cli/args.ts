export interface CliOptions {
  apiBase: string;
  pollIntervalMs: number;
  sse: boolean;
  help: boolean;
}

export const DEFAULT_API_BASE = "http://127.0.0.1:8766";
export const DEFAULT_POLL_INTERVAL_MS = 2000;

export function parseArgs(argv: string[]): CliOptions {
  const options: CliOptions = {
    apiBase: DEFAULT_API_BASE,
    pollIntervalMs: DEFAULT_POLL_INTERVAL_MS,
    sse: true,
    help: false
  };

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === "--help" || arg === "-h") {
      options.help = true;
      continue;
    }
    if (arg === "--no-sse") {
      options.sse = false;
      continue;
    }
    if (arg === "--api") {
      options.apiBase = requireValue(argv, index, "--api");
      index += 1;
      continue;
    }
    if (arg.startsWith("--api=")) {
      options.apiBase = arg.slice("--api=".length);
      continue;
    }
    if (arg === "--poll-interval-ms") {
      options.pollIntervalMs = parsePositiveInt(
        requireValue(argv, index, "--poll-interval-ms"),
        "--poll-interval-ms"
      );
      index += 1;
      continue;
    }
    if (arg.startsWith("--poll-interval-ms=")) {
      options.pollIntervalMs = parsePositiveInt(
        arg.slice("--poll-interval-ms=".length),
        "--poll-interval-ms"
      );
      continue;
    }
    if (looksLikeApiBase(arg)) {
      options.apiBase = arg;
      continue;
    }
    throw new Error(`Unknown option: ${arg}`);
  }

  options.apiBase = options.apiBase.replace(/\/+$/, "");
  return options;
}

export function helpText(): string {
  return [
    "Physical Agent Ink TUI",
    "",
    "Usage:",
    "  npm start -- --api http://127.0.0.1:8766",
    "  npm start -- http://127.0.0.1:8766",
    "",
    "Options:",
    "  --api <url>                API base URL (default: http://127.0.0.1:8766)",
    "  --poll-interval-ms <ms>    Polling interval (default: 2000)",
    "  --no-sse                   Disable SSE and use polling only",
    "  --help                     Show this help",
    "",
    "Commands:",
    "  <text>                     Send chat message",
    "  /task <text>               Submit task proposal",
    "  /approve <action_id>       Approve execution",
    "  /reject <action_id> <why>  Reject execution",
  "  /reset <CONFIRM_TEXT>      Reset workspace; backend currently requires true",
  "  /refresh                   Refresh snapshot",
  "  /view <name>               Show status/chat/actions/robots/config/uploads",
  "  /config                    Show effective config",
  "  /robots                    Show robot list",
  "  /robot <robot_id>          Show robot detail",
  "  /capabilities <robot_id>   Show robot capabilities",
  "  /upload <path>             Upload and ingest a local text file through API",
  "  /ingest <path>             Alias for /upload",
  "  /register-robot <json>     Register robot through existing config API",
  "  /help                      Show commands",
  "  /quit                      Exit"
  ].join("\n");
}

function requireValue(argv: string[], index: number, name: string): string {
  const value = argv[index + 1];
  if (!value || value.startsWith("--")) {
    throw new Error(`${name} requires a value`);
  }
  return value;
}

function parsePositiveInt(value: string, name: string): number {
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed <= 0) {
    throw new Error(`${name} must be a positive integer`);
  }
  return parsed;
}

function looksLikeApiBase(value: string): boolean {
  return /^https?:\/\//i.test(value);
}
