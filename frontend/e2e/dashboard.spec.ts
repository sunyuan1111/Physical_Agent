import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import { promises as fs } from "node:fs";
import path from "node:path";

const TOUR_STORAGE_KEY = "physical-agent-tour-dismissed";
const LANGUAGE_STORAGE_KEY = "physical-agent-language";
const THEME_STORAGE_KEY = "physical-agent-theme";

function collectConsoleErrors(page: Page) {
  const consoleErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") {
      const location = message.location();
      if (
        message.text().includes("404") &&
        location.url.includes("/api/chat/stream")
      ) {
        return;
      }
      consoleErrors.push(message.text());
    }
  });
  page.on("pageerror", (error) => {
    consoleErrors.push(error.message);
  });
  return consoleErrors;
}

async function expectHealthyShell(page: Page) {
  await expect(page.getByTestId("dashboard-shell")).toBeVisible();
  await expect(page.getByTestId("status-bar")).toContainText("Physical Agent");
  await expect(page.locator("vite-error-overlay")).toHaveCount(0);
}

function expectNoConsoleErrors(consoleErrors: string[]) {
  expect(consoleErrors).toEqual([]);
}

test.beforeEach(async ({ page }, testInfo) => {
  await page.addInitScript(
    ({ languageKey, themeKey, tourKey, showTour }) => {
      localStorage.setItem(languageKey, "en");
      localStorage.setItem(themeKey, "light");
      if (showTour) {
        localStorage.removeItem(tourKey);
      } else {
        localStorage.setItem(tourKey, "1");
      }
    },
    {
      languageKey: LANGUAGE_STORAGE_KEY,
      themeKey: THEME_STORAGE_KEY,
      tourKey: TOUR_STORAGE_KEY,
      showTour: testInfo.title.includes("tour opens on first visit"),
    },
  );
});

test("desktop dashboard smoke still loads and core panels respond", async ({
  page,
  request,
}) => {
  const consoleErrors = collectConsoleErrors(page);

  const stateResponse = await request.get("/api/state");
  expect(stateResponse.ok()).toBeTruthy();
  const apiState = (await stateResponse.json()) as {
    ready: boolean;
    backend?: string;
  };
  expect(apiState.ready).toBe(true);
  expect(apiState.backend).toBeTruthy();
  await installMockChatStream(page, [
    sseEvent(3, "start", { stream_id: "desktop-smoke", request_id: "desktop-smoke" }),
    sseEvent(4, "delta", {
      stream_id: "desktop-smoke",
      request_id: "desktop-smoke",
      delta: "I will remember: c3.2 e2e smoke is safe",
    }),
    sseEvent(5, "done", {
      stream_id: "desktop-smoke",
      request_id: "desktop-smoke",
      reply: "I will remember: c3.2 e2e smoke is safe",
      mode: "rule_based",
    }),
  ]);

  await page.goto("/");
  await expectHealthyShell(page);
  await expect(page.getByTestId("status-bar")).toContainText(
    `backend ${apiState.backend}`,
  );

  const views = [
    { key: "overview", label: "Overview", panel: "chat-panel" },
    { key: "actions", label: "Actions", panel: "action-board" },
    { key: "memory", label: "Memory", panel: "upload-panel" },
    { key: "events", label: "Events", panel: "events-panel" },
    { key: "settings", label: "Settings", panel: "settings-panel" },
  ];

  for (const view of views) {
    await page.getByTestId(`nav-${view.key}`).click();
    await expect(page.getByTestId(`page-${view.key}`)).toBeVisible();
    await expect(page.getByTestId(view.panel)).toBeVisible();
    await expect(page.getByTestId("status-bar")).toContainText(view.label);
    await expect(page.locator("vite-error-overlay")).toHaveCount(0);
  }

  await page.getByTestId("nav-settings").click();
  await expect(page.getByTestId("state-backend-summary")).toContainText(
    "Recommended backend",
  );
  await expect(page.getByTestId("state-backend-summary")).toContainText(
    "state.db is source of truth",
  );
  await expect(page.getByTestId("state-backend-summary")).toContainText(
    "SAFETY.md remains file source",
  );

  await page.getByTestId("nav-overview").click();
  await page
    .getByPlaceholder("Message the agent")
    .fill("remember that c3.2 e2e smoke is safe");
  await page.getByPlaceholder("Message the agent").press("Enter");
  await expect(page.getByTestId("chat-panel")).toContainText(
    "I will remember: c3.2 e2e smoke is safe",
  );

  await page.getByTestId("nav-memory").click();
  await expect(page.getByTestId("upload-panel")).toContainText(
    "Drop text files here",
  );
  await expect(page.locator("vite-error-overlay")).toHaveCount(0);
  expectNoConsoleErrors(consoleErrors);
});

test("mobile smoke opens proposal drawer and navigates secondary panels", async ({
  page,
}) => {
  const consoleErrors = collectConsoleErrors(page);
  await page.setViewportSize({ width: 390, height: 844 });

  await page.goto("/");
  await expectHealthyShell(page);
  await expect(page.getByTestId("open-proposal-drawer")).toBeVisible();
  await page.getByTestId("open-proposal-drawer").click();
  await expect(
    page.getByRole("dialog", { name: "Task / Action Proposal" }),
  ).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(
    page.getByRole("dialog", { name: "Task / Action Proposal" }),
  ).toBeHidden();

  for (const key of ["memory", "events", "settings"]) {
    await page.getByTestId(`nav-${key}`).click();
    await expect(page.getByTestId(`page-${key}`)).toBeVisible();
    await expect(page.getByTestId("status-bar")).toContainText(
      key.charAt(0).toUpperCase() + key.slice(1),
    );
    await expect(page.locator("vite-error-overlay")).toHaveCount(0);
  }

  expectNoConsoleErrors(consoleErrors);
});

test("browser upload of a markdown file succeeds and updates memory state", async ({
  page,
  request,
}, testInfo) => {
  const consoleErrors = collectConsoleErrors(page);
  const unique = `c3.2-upload-${Date.now()}`;
  const uploadPath = testInfo.outputPath(`${unique}.md`);
  await fs.mkdir(path.dirname(uploadPath), { recursive: true });
  await fs.writeFile(
    uploadPath,
    `# C3.2 Upload\n\nThis real browser upload contains ${unique}.`,
    "utf-8",
  );

  await page.goto("/");
  await page.getByTestId("nav-memory").click();
  await expect(page.getByTestId("upload-panel")).toBeVisible();
  await page
    .getByTestId("upload-panel")
    .locator('input[type="file"]')
    .setInputFiles(uploadPath);

  await expect(page.getByTestId("upload-feedback")).toContainText("uploaded");
  await expect(page.getByTestId("upload-feedback")).toContainText(
    "untrusted proposal context",
  );

  const searchResponse = await request.post("/api/search-memory", {
    data: { query: unique, limit: 5, source_type: "upload" },
  });
  expect(searchResponse.ok()).toBeTruthy();
  const search = (await searchResponse.json()) as {
    results: Array<{ content?: string; trust_level?: string }>;
  };
  expect(
    search.results.some((item) => item.content?.includes(unique)),
  ).toBeTruthy();
  expect(
    search.results.some((item) => item.trust_level === "untrusted"),
  ).toBeTruthy();
  expectNoConsoleErrors(consoleErrors);
});

test("unsupported upload type shows a visible panel error", async ({
  page,
}, testInfo) => {
  const consoleErrors = collectConsoleErrors(page);
  const pdfPath = testInfo.outputPath("unsupported.pdf");
  await fs.mkdir(path.dirname(pdfPath), { recursive: true });
  await fs.writeFile(pdfPath, "%PDF-1.7\nunsupported", "utf-8");

  await page.goto("/");
  await page.getByTestId("nav-memory").click();
  await page
    .getByTestId("upload-panel")
    .locator('input[type="file"]')
    .setInputFiles(pdfPath);

  await expect(page.getByTestId("upload-feedback")).toContainText(
    "Unsupported upload type",
  );
  await expect(page.getByTestId("upload-feedback")).toContainText(".md");
  expectNoConsoleErrors(consoleErrors);
});

test("oversized upload shows a visible panel error", async ({
  page,
}, testInfo) => {
  const consoleErrors = collectConsoleErrors(page);
  const oversizedPath = testInfo.outputPath("oversized.md");
  await fs.mkdir(path.dirname(oversizedPath), { recursive: true });
  await fs.writeFile(oversizedPath, "a".repeat(5 * 1024 * 1024 + 1), "utf-8");

  await page.goto("/");
  await page.getByTestId("nav-memory").click();
  await page
    .getByTestId("upload-panel")
    .locator('input[type="file"]')
    .setInputFiles(oversizedPath);

  await expect(page.getByTestId("upload-feedback")).toContainText(
    "exceeds the 5MB limit",
  );
  expectNoConsoleErrors(consoleErrors);
});

test("proposal params validation stays visible in the form", async ({
  page,
}) => {
  const consoleErrors = collectConsoleErrors(page);
  await mockReadyApiWithRobot(page);

  await page.goto("/");
  await expect(page.getByTestId("proposal-panel")).toBeVisible();
  await page.getByTestId("proposal-robot-select").click();
  await page
    .locator(
      ".ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option-content",
    )
    .filter({ hasText: /^arm_1 \(arm\)$/ })
    .click();
  await page.getByTestId("proposal-capability-select").click();
  await page
    .locator(
      ".ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option-content",
    )
    .filter({ hasText: /^observe$/ })
    .click();
  await page.getByTestId("proposal-params-input").fill("{not json");
  await page.getByTestId("propose-action-button").click();

  await expect(page.getByText("Params JSON is invalid")).toBeVisible();
  await expect(page.locator("vite-error-overlay")).toHaveCount(0);
  expectNoConsoleErrors(consoleErrors);
});

test("F2 readable context shows feedback world and capabilities without raw debug", async ({
  page,
}) => {
  const consoleErrors = collectConsoleErrors(page);
  await mockReadyApiWithRobot(page, {
    capabilities: {
      robots: {
        arm_1: {
          kind: "arm",
          driver: "mock_arm",
          status: "connected",
          capabilities: [
            {
              name: "pick",
              description: "Pick up a known object.",
              params_schema: {
                type: "object",
                properties: { object_id: { type: "string" } },
                required: ["object_id"],
              },
              constraints: { object_must_exist: true },
              requires_approval: true,
            },
          ],
        },
      },
    },
    world: {
      summary: "The arm is idle. Visible objects: red_block, tray.",
      state: {
        objects: {
          red_block: {
            type: "block",
            location: "table",
            pose: { x: 0.2, y: 0.1, z: 0.0 },
            status: "available",
            container: "workspace",
            color: "red",
          },
          tray: {
            type: "tray",
            location: "bench",
            pose: { x: 0.5, y: 0.2, z: 0.0 },
          },
        },
        environment: {
          bounds: { x_min: 0, x_max: 1, y_min: 0, y_max: 1 },
        },
        raw: { driver_note: "mock-arm snapshot" },
      },
    },
    actions: {
      pending: [
        {
          id: "act_pick_1",
          robot: "arm_1",
          capability: "pick",
          params: { object_id: "red_block" },
          reason: "Pick the red block.",
          metadata: {
            source: "chat_draft",
            user_message: "pick the red block",
            approval: {
              required: true,
              status: "approved",
              by: "gui",
              at: "2026-07-07T00:00:00Z",
              reason: "Approved from Actions board.",
            },
          },
        },
      ],
      completed: [],
      cancelled: [],
    },
    feedback: {
      latest: {
        action_id: "act_pick_1",
        status: "failed",
        robot: "arm_1",
        capability: "pick",
        message: "SafetyGate rejected the action: object is outside bounds.",
        result: { error_type: "SafetyViolation", error_message: "outside bounds" },
      },
      history: [
        {
          action_id: "act_pick_1",
          status: "failed",
          robot: "arm_1",
          capability: "pick",
          message: "SafetyGate rejected the action: object is outside bounds.",
          result: { error_type: "SafetyViolation", error_message: "outside bounds" },
        },
      ],
    },
    chat: {
      messages: [
        {
          role: "assistant",
          content: "I cannot draft that action.",
          created_at: "2026-07-07T00:01:00Z",
          metadata: {
            refusal_reason: "No listed capability can pour coffee.",
          },
        },
      ],
    },
  });

  await page.goto("/");
  await expectHealthyShell(page);
  await expect(page.getByTestId("action-board")).toContainText("Params: object_id=red_block");
  await expect(page.getByTestId("action-board").locator(".raw-json-collapse")).toHaveCount(0);
  await expect(page.getByTestId("context-tabs")).toContainText("red_block");
  await expect(page.getByTestId("context-tabs")).toContainText("x=0.2");
  await expect(page.getByTestId("context-tabs")).toContainText("workspace");

  await page.getByRole("tab", { name: /Feedback/ }).click();
  await expect(page.getByTestId("context-tabs")).toContainText(
    "SafetyGate rejected the action",
  );
  await expect(page.getByTestId("context-tabs")).toContainText(
    "Execution approved",
  );
  await expect(page.getByTestId("context-tabs")).toContainText(
    "No listed capability can pour coffee",
  );
  await expect(page.getByTestId("context-tabs")).toContainText("Raw:");
  await expect(page.getByTestId("context-tabs").locator(".raw-json-collapse")).toHaveCount(0);
  await page.getByRole("button", { name: /action act_pick_1/ }).first().click();
  await expect(page.getByTestId("page-actions")).toBeVisible();

  await page.getByRole("tab", { name: /Capabilities/ }).click();
  await expect(page.getByTestId("context-tabs")).toContainText("pick");
  await expect(page.getByTestId("context-tabs")).toContainText("Params: object_id*: string");
  await expect(page.getByTestId("context-tabs")).toContainText("approval required");
  await expect(page.getByTestId("context-tabs").locator(".raw-json-collapse")).toHaveCount(0);
  expectNoConsoleErrors(consoleErrors);
});

test("F2.5 state overview uses productized schema components with collapsed raw debug", async ({
  page,
}) => {
  const consoleErrors = collectConsoleErrors(page);
  await mockReadyApiWithRobot(page, {
    backend_private_snapshot: { revision: 7 },
    capabilities: {
      robots: {
        arm_1: {
          kind: "arm",
          driver: "mock_arm",
          mode: "simulation",
          status: "connected",
          custom_driver_note: "hidden in raw debug",
          capabilities: [
            {
              name: "pick",
              description: "Pick up a known object.",
              params_schema: {
                type: "object",
                properties: { object_id: { type: "string" } },
                required: ["object_id"],
              },
              requires_approval: true,
            },
            {
              name: "place",
              description: "Place a held object at a named target.",
              params_schema: {
                type: "object",
                properties: { target_id: { type: "string" } },
                required: ["target_id"],
              },
              requires_approval: false,
            },
          ],
        },
      },
    },
    world: {
      summary: "The arm is idle. Visible objects: red_block, tray.",
      state: {
        robots: {
          arm_1: { health: "ok", mode: "simulation" },
        },
        objects: {
          red_block: {
            type: "block",
            location: "table",
            pose: { x: 0.2, y: 0.1, z: 0.0 },
            status: "available",
            color: "red",
          },
          tray: {
            type: "tray",
            location: "bench",
            pose: { x: 0.5, y: 0.2, z: 0.0 },
            status: "ready",
          },
        },
        environment: {
          bounds: { x_min: -1, x_max: 1, y_min: -0.5, y_max: 0.5, z_min: 0, z_max: 1 },
          calibration_note: "hidden in raw debug",
        },
        raw: { driver_note: "mock-arm snapshot" },
      },
    },
  });

  await page.goto("/");
  await expectHealthyShell(page);

  await expect(page.getByTestId("system-status-card")).toContainText("Ready");
  await expect(page.getByTestId("system-status-card")).toContainText("sqlite");
  await expect(page.getByTestId("system-status-card")).toContainText(
    "C:/tmp/physical-agent-workspace",
  );
  await expect(page.getByTestId("robots-table")).toContainText("arm_1");
  await expect(page.getByTestId("robots-table")).toContainText("mock_arm");
  await expect(page.getByTestId("robots-table")).toContainText("simulation");
  await expect(page.getByTestId("robots-table")).toContainText("2");
  await expect(page.getByTestId("capability-cards")).toContainText("pick");
  await expect(page.getByTestId("capability-cards")).toContainText("place");
  await expect(page.getByTestId("capability-cards")).toContainText("object_id*: string");
  await expect(page.getByTestId("capability-cards")).toContainText("approval required");
  await expect(page.getByTestId("environment-descriptions")).toContainText("x bounds");
  await expect(page.getByTestId("environment-descriptions")).toContainText("-1 to 1");
  await expect(page.getByTestId("environment-descriptions")).toContainText("-0.5 to 0.5");
  await expect(page.getByTestId("world-objects-table")).toContainText("red_block");
  await expect(page.getByTestId("world-objects-table")).toContainText("tray");
  await expect(page.getByTestId("world-objects-table")).toContainText("available");
  await expect(page.getByTestId("raw-debug-panel")).toContainText("Unknown/raw fields");
  await expect(page.getByTestId("raw-debug-collapse").locator(".ant-collapse-content-active"))
    .toHaveCount(0);
  await expect(page.getByTestId("raw-debug-panel").locator(".ant-tree")).toHaveCount(0);
  await expect(page.getByTestId("raw-debug-panel").locator(".json-tree")).toHaveCount(0);
  await expect(page.getByTestId("raw-debug-panel")).not.toContainText("driver_note");
  await page.getByTestId("raw-debug-collapse").getByText("Unknown/raw fields").click();
  await expect(page.getByTestId("raw-debug-panel").locator(".ant-tree")).toBeVisible();
  await expect(page.getByTestId("raw-debug-panel")).toContainText("world_raw");
  await expect(page.getByTestId("raw-debug-panel")).toContainText("driver_note");
  await expect(page.getByText("Full state JSON")).toHaveCount(0);
  expectNoConsoleErrors(consoleErrors);
});

test("settings panel saves and tests LLM settings with mocked API", async ({
  page,
}) => {
  const consoleErrors = collectConsoleErrors(page);
  await mockReadyApiWithRobot(page);

  await page.goto("/");
  await page.getByTestId("nav-settings").click();
  await expect(page.getByTestId("state-backend-summary")).toContainText(
    "Recommended backend",
  );
  await expect(page.getByTestId("state-backend-summary")).toContainText(
    "state.db is source of truth",
  );
  await expect(page.getByTestId("state-backend-summary")).toContainText(
    "SAFETY.md remains file source",
  );
  await expect(page.getByTestId("settings-panel")).toContainText(
    "key ****7890",
  );

  await page.getByLabel("Base URL").fill("http://local-llm.test/v1");
  await page.getByLabel("API key").fill("sk-local-00007890");
  await page.getByLabel("Model").fill("local-model");
  await page.getByTestId("save-llm-settings").click();

  await expect(page.getByTestId("llm-settings-feedback")).toContainText(
    "LLM settings saved",
  );
  await expect(page.getByTestId("settings-panel")).toContainText(
    "key ****7890",
  );

  await page.getByTestId("test-llm-settings").click();
  await expect(page.getByTestId("llm-settings-feedback")).toContainText(
    "LLM connection test passed",
  );

  await page.getByTestId("export-audit-button").click();
  await expect(page.getByTestId("export-audit-feedback")).toContainText(
    "Exported audit view",
  );
  expectNoConsoleErrors(consoleErrors);
});

test("settings panel explains sqlite backend without live switching", async ({
  page,
}) => {
  const consoleErrors = collectConsoleErrors(page);
  await mockReadyApiWithRobot(page, {
    backend: "sqlite",
    workspace_path: "C:/tmp/physical-agent-sqlite-workspace",
  });

  await page.goto("/");
  await page.getByTestId("nav-settings").click();

  await expect(page.getByTestId("state-backend-summary")).toContainText(
    "Recommended backend",
  );
  await expect(page.getByTestId("state-backend-summary")).toContainText(
    "state.db is source of truth",
  );
  await expect(page.getByTestId("state-backend-summary")).toContainText(
    "no GUI live backend switch",
  );
  await expect(page.getByTestId("state-backend-summary")).not.toContainText(
    "JSON backend",
  );
  expectNoConsoleErrors(consoleErrors);
});

test("settings danger zone keeps explicit reset confirmation path", async ({
  page,
  request,
}) => {
  const consoleErrors = collectConsoleErrors(page);
  await mockReadyApiWithRobot(page);

  const wrongConfirm = await request.post("/api/workspace/reset", {
    data: {},
  });
  expect(wrongConfirm.status()).toBe(400);
  expect((await wrongConfirm.json()).message).toContain("confirm");

  await page.goto("/");
  await page.getByTestId("nav-settings").click();
  await expect(page.getByTestId("reset-workspace-button")).toBeVisible();
  await page.getByTestId("reset-workspace-button").click();
  await page.getByRole("button", { name: "Reset workspace", exact: true }).last().click();
  await expect(page.getByTestId("reset-workspace-feedback")).toContainText(
    "Workspace reset",
  );
  expectNoConsoleErrors(consoleErrors);
});

test("hardware scaffold can register a robot and config panel refreshes", async ({
  page,
}) => {
  const consoleErrors = collectConsoleErrors(page);
  await mockReadyApiWithRobot(page);

  await page.goto("/");
  await page.getByTestId("nav-hardware").click();
  await page.getByTestId("integrate-source-input").fill("C:/tmp/mock-sdk");
  await page.getByTestId("integrate-name-input").fill("bench_arm");
  await page.getByTestId("integrate-submit-button").click();
  await expect(page.getByTestId("integrate-result")).toContainText("bench_arm");

  await page.getByTestId("register-robot-id").fill("bench_arm_1");
  await page.getByTestId("register-robot-button").click();
  await expect(page.getByTestId("register-robot-feedback")).toContainText(
    "Registered bench_arm_1",
  );
  await expect(page.getByTestId("config-panel")).toContainText("bench_arm_1");
  expectNoConsoleErrors(consoleErrors);
});

test("language and dark mode switches persist", async ({ page }) => {
  const consoleErrors = collectConsoleErrors(page);
  await mockReadyApiWithRobot(page);

  await page.goto("/");
  await page.getByTestId("nav-settings").click();
  await page.getByTestId("language-switch").getByText("中文").click();
  await expect(page.getByTestId("status-bar")).toContainText("工作台");
  await expect(page.evaluate(() => localStorage.getItem("physical-agent-language"))).resolves.toBe("zh");

  await page.getByTestId("theme-switch").getByText("深色").click();
  await expect(page.locator("body")).toHaveAttribute("data-theme", "dark");
  await expect(page.evaluate(() => localStorage.getItem("physical-agent-theme"))).resolves.toBe("dark");
  expectNoConsoleErrors(consoleErrors);
});

test("tour opens on first visit closes and can be reopened from settings", async ({
  page,
}) => {
  const consoleErrors = collectConsoleErrors(page);
  await page.addInitScript(() => {
    localStorage.setItem("physical-agent-language", "en");
    localStorage.setItem("physical-agent-theme", "light");
    localStorage.removeItem("physical-agent-tour-dismissed");
  });
  await mockReadyApiWithRobot(page);

  await page.goto("/");
  await expect(page.getByText("Set up first")).toBeVisible();
  await page.getByRole("button", { name: "Close" }).click();
  await expect(page.evaluate(() => localStorage.getItem("physical-agent-tour-dismissed"))).resolves.toBe("1");

  await page.getByTestId("nav-settings").click();
  await page.getByTestId("show-tour-button").click();
  await expect(page.getByText("Set up first")).toBeVisible();
  expectNoConsoleErrors(consoleErrors);
});

test("chat panel streams text incrementally and can stop", async ({ page }) => {
  const consoleErrors = collectConsoleErrors(page);
  const snapshot = await mockReadyApiWithRobot(page);
  const finalState = {
    ...snapshot,
    chat: {
      messages: [
        {
          role: "user",
          content: "stream a greeting",
          created_at: "2026-07-01T00:00:00Z",
        },
        {
          role: "assistant",
          content: "Hello stream",
          created_at: "2026-07-01T00:00:01Z",
        },
      ],
    },
  };
  await installControlledChatStream(
    page,
    [
      sseEvent(10, "start", { stream_id: "stream-e2e", request_id: "req-e2e" }),
      sseEvent(11, "delta", {
        stream_id: "stream-e2e",
        request_id: "req-e2e",
        delta: "Hello",
      }),
      sseEvent(12, "delta", {
        stream_id: "stream-e2e",
        request_id: "req-e2e",
        delta: " stream",
      }),
      sseEvent(13, "done", {
        stream_id: "stream-e2e",
        request_id: "req-e2e",
        reply: "Hello stream",
        mode: "llm",
        state: finalState,
      }),
    ],
    2,
  );

  await page.goto("/");
  await page.getByPlaceholder("Message the agent").fill("stream a greeting");
  await page.getByPlaceholder("Message the agent").press("Enter");
  await expect(page.getByTestId("stop-chat-stream")).toBeEnabled();
  await expect(page.getByTestId("chat-panel")).toContainText("Hello");
  await expect(page.getByTestId("chat-panel")).not.toContainText(
    "Hello stream",
    { timeout: 150 },
  );
  await page.evaluate(() => {
    (
      window as typeof window & { __releaseChatStream?: () => void }
    ).__releaseChatStream?.();
  });
  await expect(page.getByTestId("chat-panel")).toContainText("Hello stream");
  await expect(page.getByTestId("stop-chat-stream")).toBeDisabled();
  await expect(page.locator("vite-error-overlay")).toHaveCount(0);
  expectNoConsoleErrors(consoleErrors);
});

test("chat stop aborts the active stream and leaves a visible status", async ({
  page,
}) => {
  const consoleErrors = collectConsoleErrors(page);
  await mockReadyApiWithRobot(page);
  await installMockChatStream(
    page,
    [
      sseEvent(20, "start", {
        stream_id: "stream-stop",
        request_id: "req-stop",
      }),
      sseEvent(21, "delta", {
        stream_id: "stream-stop",
        request_id: "req-stop",
        delta: "Partial",
      }),
      sseEvent(22, "delta", {
        stream_id: "stream-stop",
        request_id: "req-stop",
        delta: " ignored",
      }),
    ],
    900,
  );

  await page.goto("/");
  await page.getByPlaceholder("Message the agent").fill("stream slowly");
  await page.getByPlaceholder("Message the agent").press("Enter");
  await expect(page.getByTestId("chat-panel")).toContainText("Partial");
  await page.getByTestId("stop-chat-stream").click();
  await expect(page.getByTestId("chat-stream-error")).toContainText("stopped");
  await expect(page.getByTestId("stop-chat-stream")).toBeDisabled();
  await expect(page.locator("vite-error-overlay")).toHaveCount(0);
  expectNoConsoleErrors(consoleErrors);
});

test("chat stream unavailable falls back to regular chat", async ({ page }) => {
  const consoleErrors = collectConsoleErrors(page);
  await mockReadyApiWithRobot(page);
  await installUnavailableChatStream(page);

  await page.goto("/");
  await page.getByPlaceholder("Message the agent").fill("fallback please");
  await page.getByPlaceholder("Message the agent").press("Enter");
  await expect(page.getByTestId("chat-panel")).toContainText(
    "Fallback reply: fallback please",
  );
  await expect(page.locator("vite-error-overlay")).toHaveCount(0);
  expectNoConsoleErrors(consoleErrors);
});

async function mockReadyApiWithRobot(
  page: Page,
  overrides: Record<string, unknown> = {},
) {
  const snapshot = {
    ok: true,
    ready: true,
    message: "Ready.",
    backend: "sqlite",
    config_path: "C:/tmp/physical-agent.yaml",
    workspace_path: "C:/tmp/physical-agent-workspace",
    capabilities: {
      robots: {
        arm_1: {
          kind: "arm",
          driver: "mock_arm",
          status: "connected",
          capabilities: [
            { name: "observe", description: "Inspect the workspace." },
          ],
        },
      },
    },
    world: { summary: "Mock world", state: {}, environment: {} },
    actions: { pending: [], completed: [], cancelled: [] },
    feedback: {},
    safety: {},
    chat: { messages: [] },
    plan: {},
    memory: { notes: [] },
    uploads: { uploads: [] },
    chunks: { chunks: [] },
    ...overrides,
  };

  await mockApiSnapshot(page, snapshot);
  return snapshot;
}

test("config missing state renders a clear nonblank dashboard", async ({
  page,
}) => {
  const consoleErrors = collectConsoleErrors(page);
  await mockNotReadyApi(page, "Config file is missing.", {
    config_exists: false,
    workspace_exists: false,
  });

  await page.goto("/");
  await expectHealthyShell(page);
  await expect(page.getByTestId("workspace-notice")).toContainText(
    "Workspace is not ready",
  );
  await expect(page.getByTestId("workspace-notice")).toContainText(
    "Config file is missing.",
  );
  await expect(page.getByTestId("sse-status")).toContainText(
    "SSE disconnected",
  );
  await expect(page.getByTestId("action-board")).toBeVisible();
  expectNoConsoleErrors(consoleErrors);
});

test("workspace not initialized state renders a clear nonblank dashboard", async ({
  page,
}) => {
  const consoleErrors = collectConsoleErrors(page);
  await mockNotReadyApi(page, "Workspace is not initialized.", {
    config_exists: true,
    workspace_exists: false,
    backend: "sqlite",
    workspace_path: "C:/tmp/physical-agent-empty-workspace",
  });

  await page.goto("/");
  await expectHealthyShell(page);
  await expect(page.getByTestId("workspace-notice")).toContainText(
    "Workspace is not ready",
  );
  await expect(page.getByTestId("workspace-notice")).toContainText(
    "Workspace is not initialized.",
  );
  await page.getByTestId("nav-settings").click();
  await expect(page.getByTestId("settings-panel")).toContainText("not ready");
  expectNoConsoleErrors(consoleErrors);
});

async function mockNotReadyApi(
  page: Page,
  message: string,
  extras: Record<string, unknown>,
) {
  const snapshot = {
    ok: false,
    ready: false,
    message,
    config_path: "C:/tmp/missing-physical-agent.yaml",
    ...extras,
  };

  await mockApiSnapshot(page, snapshot);
}

async function mockApiSnapshot(page: Page, snapshot: Record<string, unknown>) {
  let llmSettings = {
    base_url: "http://mock-llm.test/v1",
    model: "mock-model",
    api_mode: "chat_completions",
    has_api_key: true,
    masked_api_key: "****7890",
    settings_path: "C:/tmp/workspace/.llm.json",
  };
  const configRobots: Record<string, { driver: string; config: Record<string, unknown> }> = {};

  await page.route("**/api/health", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(snapshot),
    });
  });
  await page.route("**/api/state", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(snapshot),
    });
  });
  await page.route("**/api/state-check", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(stateCheckForSnapshot(snapshot)),
    });
  });
  await page.route("**/api/export-audit", async (route) => {
    const backend = String(snapshot.backend ?? "sqlite");
    const workspacePath = String(
      snapshot.workspace_path ?? "C:/tmp/physical-agent-workspace",
    );
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        ok: true,
        message: "Exported audit view.",
        backend,
        workspace_path: workspacePath,
        out_dir: `${workspacePath}/audit`,
        manifest: `${workspacePath}/audit/manifest.json`,
        result: {
          backend,
          workspace_path: workspacePath,
          out_dir: `${workspacePath}/audit`,
          manifest: `${workspacePath}/audit/manifest.json`,
        },
      }),
    });
  });
  await page.route("**/api/workspace/reset", async (route) => {
    const body = route.request().postDataJSON() as { confirm?: boolean };
    if (!body.confirm) {
      await route.fulfill({
        status: 400,
        contentType: "application/json",
        body: JSON.stringify({
          ok: false,
          message: "Workspace reset requires explicit confirmation.",
        }),
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        ok: true,
        message: "Workspace reset complete.",
        state: {
          ...snapshot,
          actions: { pending: [], completed: [], cancelled: [] },
          chat: { messages: [] },
          memory: { notes: [] },
        },
      }),
    });
  });
  await page.route("**/api/integrate", async (route) => {
    const body = route.request().postDataJSON() as { name?: string; output?: string };
    const name = body.name || "mock_driver";
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        ok: true,
        message: `Generated ${name}.`,
        state: snapshot,
        result: {
          output_path: body.output || `my_hardware/${name}`,
          generated_files: ["driver.py", "physical_driver.yaml"],
          llm_used: false,
          source: {
            name,
            title: name,
            robot_kind: "arm",
            transport: "mock",
            config_schema: {
              type: "object",
              properties: {
                port: { type: "string", default: "COM1" },
              },
            },
            capabilities: [
              {
                name: "observe",
                description: "Inspect workspace.",
                params_schema: { type: "object", properties: {} },
              },
            ],
          },
          validation: { ok: true, checks: ["scaffold"], errors: [] },
          next_steps: ["Register robot"],
        },
      }),
    });
  });
  await page.route("**/api/config/robots", async (route) => {
    const body = route.request().postDataJSON() as {
      robot_id: string;
      driver: string;
      config?: Record<string, unknown>;
    };
    configRobots[body.robot_id] = {
      driver: body.driver,
      config: body.config ?? {},
    };
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        ok: true,
        message: `Registered ${body.robot_id}.`,
      }),
    });
  });
  await page.route("**/api/config", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        ok: true,
        config_path: "C:/tmp/physical-agent.yaml",
        config: {
          workspace: { path: "C:/tmp/physical-agent-workspace", backend: "sqlite" },
          watch: { tick_ms: 500, require_human_approval: true },
          robots: configRobots,
        },
      }),
    });
  });
  await page.route("**/api/events", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body: [
        sseEvent(1, "hello", { version: "0.1.0", watch_enabled: false }),
        sseEvent(2, "state", { reason: "connect", state: snapshot }),
      ].join(""),
    });
  });
  await page.route("**/api/settings/llm", async (route) => {
    if (route.request().method() === "POST") {
      const body = route.request().postDataJSON() as {
        base_url?: string;
        api_key?: string;
        model?: string;
        api_mode?: string;
      };
      llmSettings = {
        ...llmSettings,
        base_url: body.base_url ?? llmSettings.base_url,
        model: body.model ?? llmSettings.model,
        api_mode: body.api_mode ?? llmSettings.api_mode,
        has_api_key: Boolean(body.api_key) || llmSettings.has_api_key,
        masked_api_key: body.api_key
          ? `****${body.api_key.slice(-4)}`
          : llmSettings.masked_api_key,
      };
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          ok: true,
          message: "LLM settings saved.",
          ...llmSettings,
          settings: llmSettings,
        }),
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ ok: true, ...llmSettings, settings: llmSettings }),
    });
  });
  await page.route("**/api/settings/llm/test", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        ok: true,
        message: "LLM connection test passed.",
        ...llmSettings,
        settings: llmSettings,
      }),
    });
  });
  await page.route("**/api/chat", async (route) => {
    const body = route.request().postDataJSON() as { message?: string };
    const nextSnapshot = {
      ...snapshot,
      chat: {
        messages: [
          {
            role: "user",
            content: body.message ?? "",
            created_at: "2026-07-01T00:00:00Z",
          },
          {
            role: "assistant",
            content: `Fallback reply: ${body.message ?? ""}`,
            created_at: "2026-07-01T00:00:01Z",
          },
        ],
      },
    };
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        ok: true,
        mode: "rule_based",
        reply: `Fallback reply: ${body.message ?? ""}`,
        executed: 0,
        state: nextSnapshot,
      }),
    });
  });
  await page.route("**/api/chat/abort/**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        ok: true,
        stream_id: "mock-stream",
        aborted: true,
      }),
    });
  });
}

function stateCheckForSnapshot(snapshot: Record<string, unknown>) {
  const workspacePath = String(
    snapshot.workspace_path ?? "C:/tmp/physical-agent-workspace",
  );
  return {
    ok: true,
    ready: Boolean(snapshot.ready ?? true),
    message: "State backend is ready.",
    backend: "sqlite",
    backend_role: "recommended",
    backend_label: "SQLite recommended backend",
    source_of_truth: `${workspacePath}/state.db`,
    payload_format: "JSON payloads inside SQLite tables",
    human_view: "export-audit creates a read-only audit view",
    safety_source: `${workspacePath}/SAFETY.md`,
    runtime_switch_supported: false,
    switching_model:
      "Change workspace.backend in config and restart the process; there is no GUI live backend switch.",
    recommendation:
      "Use workspace/state.db as the state source of truth; SAFETY.md remains the file source for safety rules.",
    workspace_path: workspacePath,
    workspace_initialized: Boolean(snapshot.ready ?? true),
    audit_dir: `${workspacePath}/audit`,
    audit_export_writable: true,
    sqlite_schema_complete: true,
    sqlite_chunk_schema_complete: true,
    sqlite_missing_tables: [],
    sqlite_missing_action_columns: [],
    sqlite_missing_memory_columns: [],
    sqlite_missing_upload_columns: [],
    sqlite_missing_chunk_columns: [],
  };
}

function sseEvent(id: number, type: string, payload: Record<string, unknown>) {
  return `event: ${type}\ndata: ${JSON.stringify({
    id,
    type,
    ts: "2026-07-01T00:00:00Z",
    payload,
  })}\n\n`;
}

async function installMockChatStream(
  page: Page,
  chunks: string[],
  delayMs = 250,
) {
  await page.addInitScript(
    ({ chunks, delayMs }) => {
      const originalFetch = window.fetch.bind(window);
      window.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
        const url =
          typeof input === "string"
            ? input
            : input instanceof URL
              ? input.href
              : input.url;
        if (!url.includes("/api/chat/stream")) {
          return originalFetch(input, init);
        }
        const encoder = new TextEncoder();
        const signal = init?.signal;
        const stream = new ReadableStream<Uint8Array>({
          start(controller) {
            let aborted = false;
            signal?.addEventListener("abort", () => {
              aborted = true;
              controller.error(new DOMException("Aborted", "AbortError"));
            });
            const push = (index: number) => {
              if (aborted) {
                return;
              }
              if (index >= chunks.length) {
                controller.close();
                return;
              }
              controller.enqueue(encoder.encode(chunks[index]));
              window.setTimeout(() => push(index + 1), delayMs);
            };
            push(0);
          },
        });
        return Promise.resolve(
          new Response(stream, {
            status: 200,
            headers: { "Content-Type": "text/event-stream" },
          }),
        );
      };
    },
    { chunks, delayMs },
  );
}

async function installControlledChatStream(
  page: Page,
  chunks: string[],
  releaseAfter: number,
) {
  await page.addInitScript(
    ({ chunks, releaseAfter }) => {
      const originalFetch = window.fetch.bind(window);
      window.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
        const url =
          typeof input === "string"
            ? input
            : input instanceof URL
              ? input.href
              : input.url;
        if (!url.includes("/api/chat/stream")) {
          return originalFetch(input, init);
        }
        const encoder = new TextEncoder();
        let release: (() => void) | null = null;
        const releasePromise = new Promise<void>((resolve) => {
          release = resolve;
        });
        (
          window as typeof window & { __releaseChatStream?: () => void }
        ).__releaseChatStream = () => release?.();
        const stream = new ReadableStream<Uint8Array>({
          async start(controller) {
            init?.signal?.addEventListener("abort", () => {
              controller.error(new DOMException("Aborted", "AbortError"));
            });
            for (let index = 0; index < chunks.length; index += 1) {
              if (index === releaseAfter) {
                await releasePromise;
              }
              controller.enqueue(encoder.encode(chunks[index]));
            }
            controller.close();
          },
        });
        return Promise.resolve(
          new Response(stream, {
            status: 200,
            headers: { "Content-Type": "text/event-stream" },
          }),
        );
      };
    },
    { chunks, releaseAfter },
  );
}

async function installUnavailableChatStream(page: Page) {
  await page.addInitScript(() => {
    const originalFetch = window.fetch.bind(window);
    window.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
      const url =
        typeof input === "string"
          ? input
          : input instanceof URL
            ? input.href
            : input.url;
      if (url.includes("/api/chat/stream")) {
        return Promise.resolve(new Response("{}", { status: 404 }));
      }
      return originalFetch(input, init);
    };
  });
}
