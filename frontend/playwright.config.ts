import { defineConfig, devices } from "@playwright/test";

const isCI = Boolean(process.env.CI);
const isWindows = process.platform === "win32";
const e2eConfig = isWindows
  ? "..\\.tmp\\e2e\\physical-agent.yaml"
  : "../.tmp/e2e/physical-agent.yaml";
const apiCommand =
  process.env.PA_E2E_API_COMMAND ??
  (isWindows
    ? `cmd.exe /c ..\\.venv\\Scripts\\physical-agent.exe init --config ${e2eConfig} --force && ..\\.venv\\Scripts\\physical-agent.exe api --config ${e2eConfig} --host 127.0.0.1 --port 8766`
    : `physical-agent init --config ${e2eConfig} --force && physical-agent api --config ${e2eConfig} --host 127.0.0.1 --port 8766`);
const devCommand =
  process.env.PA_E2E_DEV_COMMAND ??
  (isWindows
    ? "cmd.exe /c npm.cmd run dev -- --port 5173"
    : "npm run dev -- --port 5173");

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  expect: {
    timeout: 10_000
  },
  reporter: [["list"]],
  use: {
    baseURL: "http://127.0.0.1:5173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure"
  },
  webServer: [
    {
      command: apiCommand,
      url: "http://127.0.0.1:8766/api/health",
      reuseExistingServer: !isCI,
      timeout: 30_000
    },
    {
      command: devCommand,
      url: "http://127.0.0.1:5173/",
      reuseExistingServer: !isCI,
      timeout: 30_000
    }
  ],
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] }
    }
  ]
});
