from __future__ import annotations

import asyncio
import json
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from physical_agent.agent.chat_runtime import ChatRuntime
from physical_agent.agent.onboarding import HardwareIntegrationAssistant
from physical_agent.agent.runtime import AgentRuntime
from physical_agent.config import DEFAULT_CONFIG_NAME, load_config, write_default_config
from physical_agent.doctor import doctor_ok, run_doctor
from physical_agent.protocol.schemas import Action
from physical_agent.protocol.workspace import Workspace
from physical_agent.quickstart import setup_project
from physical_agent.watch.runtime import WatchRuntime


class GuiController:
    def __init__(self, config_path: str | Path = DEFAULT_CONFIG_NAME):
        self.config_path = Path(config_path).resolve()
        self.lock = threading.Lock()
        self.watch_runtime: WatchRuntime | None = None

    def state(self) -> dict[str, Any]:
        if not self.config_path.exists():
            return {
                "ready": False,
                "watch_started": False,
                "message": "Project is not initialized. Click Setup Project.",
                "doctor": [check.as_dict() for check in run_doctor(self.config_path)],
            }

        config = load_config(self.config_path)
        workspace = Workspace(config.workspace_path(self.config_path.parent))
        if not workspace.exists():
            return {
                "ready": False,
                "watch_started": self._watch_started,
                "message": "Workspace is missing. Click Setup Project.",
                "doctor": [check.as_dict() for check in run_doctor(self.config_path)],
            }

        actions = workspace.read_actions()
        feedback = workspace.read_feedback()
        return {
            "ready": True,
            "watch_started": self._watch_started,
            "message": "Ready.",
            "config_path": str(self.config_path),
            "workspace_path": str(workspace.path),
            "task": workspace.read_task(),
            "capabilities": workspace.read_capabilities(),
            "world": workspace.read_world(),
            "actions": {
                "pending": _dump_actions(actions["pending"]),
                "completed": _dump_actions(actions["completed"]),
                "cancelled": _dump_actions(actions["cancelled"]),
            },
            "feedback": feedback,
            "chat": workspace.read_chat(),
            "plan": workspace.read_plan(),
            "memory": workspace.read_memory(),
            "doctor": [check.as_dict() for check in run_doctor(self.config_path)],
        }

    def setup(self, *, force: bool = False) -> dict[str, Any]:
        with self.lock:
            if self.watch_runtime is not None and self.watch_runtime.started:
                asyncio.run(self.watch_runtime.shutdown())
            self.watch_runtime = None
            result = setup_project(self.config_path, force=force, publish=True, smoke_test=False)
            self.watch_runtime = WatchRuntime(self.config_path)
            asyncio.run(self.watch_runtime.setup())
            return {"ok": True, "result": result, "state": self.state()}

    def start_watch(self) -> dict[str, Any]:
        with self.lock:
            self._ensure_watch_started()
            return {"ok": True, "message": "Watch runtime is connected.", "state": self.state()}

    def stop_watch(self) -> dict[str, Any]:
        with self.lock:
            if self.watch_runtime is not None and self.watch_runtime.started:
                asyncio.run(self.watch_runtime.shutdown())
            self.watch_runtime = None
            return {"ok": True, "message": "Watch runtime stopped.", "state": self.state()}

    def step_watch(self) -> dict[str, Any]:
        with self.lock:
            self._ensure_watch_started()
            assert self.watch_runtime is not None
            executed = asyncio.run(self.watch_runtime.step(setup=False))
            return {
                "ok": True,
                "message": f"Executed {executed} action(s).",
                "executed": executed,
                "state": self.state(),
            }

    def submit_task(self, task: str) -> dict[str, Any]:
        with self.lock:
            self._ensure_watch_started()
            result = asyncio.run(AgentRuntime(self.config_path).run_task(task, wait_for_feedback=False))
            return {"ok": bool(result["ok"]), "result": _json_safe(result), "state": self.state()}

    def chat_message(self, message: str, *, planner: str = "auto", auto_step: bool = False) -> dict[str, Any]:
        with self.lock:
            self._ensure_watch_started()
            result = ChatRuntime(self.config_path, planner_name=planner).respond(
                message,
                auto_step=False,
            )
            executed = 0
            if auto_step and result["actions"]:
                assert self.watch_runtime is not None
                executed = asyncio.run(self.watch_runtime.step(setup=False))
                result["executed"] = executed
            return {
                "ok": True,
                "message": result["reply"],
                "result": _json_safe(result),
                "executed": executed,
                "state": self.state(),
            }

    def integrate_hardware(
        self,
        source: str,
        *,
        output: str | None = None,
        name: str | None = None,
    ) -> dict[str, Any]:
        with self.lock:
            if not self.config_path.exists():
                write_default_config(self.config_path)
            config = load_config(self.config_path)
            Workspace(config.workspace_path(self.config_path.parent)).initialize()
            assistant = HardwareIntegrationAssistant(
                source,
                output_dir=output or None,
                name=name or None,
                base_dir=self.config_path.parent,
            )
            result = assistant.generate()
            return {
                "ok": True,
                "message": f"Generated driver scaffold at {result.output_path}.",
                "result": _json_safe(result.model_dump(mode="json")),
                "state": self.state(),
            }

    def run_demo(self) -> dict[str, Any]:
        with self.lock:
            self._ensure_watch_started()
            task = "pick the red block and place it on the tray"
            result = asyncio.run(AgentRuntime(self.config_path).run_task(task, wait_for_feedback=False))
            assert self.watch_runtime is not None
            executed = asyncio.run(self.watch_runtime.step(setup=False))
            return {
                "ok": bool(result["ok"] and executed == 2),
                "message": "Demo completed.",
                "executed": executed,
                "result": _json_safe(result),
                "state": self.state(),
            }

    def doctor(self) -> dict[str, Any]:
        checks = run_doctor(self.config_path)
        return {"ok": doctor_ok(checks), "checks": [check.as_dict() for check in checks]}

    @property
    def _watch_started(self) -> bool:
        return bool(self.watch_runtime is not None and self.watch_runtime.started)

    def _ensure_watch_started(self) -> None:
        if not self.config_path.exists():
            write_default_config(self.config_path)
        config = load_config(self.config_path)
        Workspace(config.workspace_path(self.config_path.parent)).initialize()
        if self.watch_runtime is None or not self.watch_runtime.started:
            self.watch_runtime = WatchRuntime(self.config_path)
            asyncio.run(self.watch_runtime.setup())


def make_server(
    config_path: str | Path = DEFAULT_CONFIG_NAME,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> ThreadingHTTPServer:
    controller = GuiController(config_path)

    class Handler(BaseHTTPRequestHandler):
        server_version = "PhysicalAgentGUI/0.1"

        def do_GET(self) -> None:
            route = urlparse(self.path).path
            if route == "/":
                self._send_html(INDEX_HTML)
                return
            if route == "/api/state":
                self._send_json(controller.state())
                return
            if route == "/api/doctor":
                self._send_json(controller.doctor())
                return
            self._send_json({"ok": False, "message": "Not found."}, HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:
            route = urlparse(self.path).path
            try:
                if route == "/api/setup":
                    payload = self._read_json()
                    self._send_json(controller.setup(force=bool(payload.get("force", False))))
                    return
                if route == "/api/watch/start":
                    self._send_json(controller.start_watch())
                    return
                if route == "/api/watch/stop":
                    self._send_json(controller.stop_watch())
                    return
                if route == "/api/watch/step":
                    self._send_json(controller.step_watch())
                    return
                if route == "/api/task":
                    payload = self._read_json()
                    task = str(payload.get("task", "")).strip()
                    if not task:
                        self._send_json(
                            {"ok": False, "message": "Task cannot be empty."},
                            HTTPStatus.BAD_REQUEST,
                        )
                        return
                    self._send_json(controller.submit_task(task))
                    return
                if route == "/api/chat":
                    payload = self._read_json()
                    message = str(payload.get("message", "")).strip()
                    if not message:
                        self._send_json(
                            {"ok": False, "message": "Chat message cannot be empty."},
                            HTTPStatus.BAD_REQUEST,
                        )
                        return
                    planner = str(payload.get("planner", "auto"))
                    auto_step = bool(payload.get("auto_step", False))
                    self._send_json(
                        controller.chat_message(message, planner=planner, auto_step=auto_step)
                    )
                    return
                if route == "/api/integrate":
                    payload = self._read_json()
                    source = str(payload.get("source", "")).strip()
                    if not source:
                        self._send_json(
                            {"ok": False, "message": "Source cannot be empty."},
                            HTTPStatus.BAD_REQUEST,
                        )
                        return
                    output = str(payload.get("output", "")).strip() or None
                    name = str(payload.get("name", "")).strip() or None
                    self._send_json(
                        controller.integrate_hardware(source, output=output, name=name)
                    )
                    return
                if route == "/api/demo":
                    self._send_json(controller.run_demo())
                    return
            except Exception as exc:
                self._send_json({"ok": False, "message": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
                return
            self._send_json({"ok": False, "message": "Not found."}, HTTPStatus.NOT_FOUND)

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            if length == 0:
                return {}
            return json.loads(self.rfile.read(length).decode("utf-8"))

        def _send_html(self, html: str) -> None:
            payload = html.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _send_json(self, data: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
            payload = json.dumps(_json_safe(data), indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    server = ThreadingHTTPServer((host, port), Handler)
    server.controller = controller  # type: ignore[attr-defined]
    return server


def run_gui(
    config_path: str | Path = DEFAULT_CONFIG_NAME,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
) -> None:
    server = make_server(config_path, host=host, port=port)
    url = f"http://{host}:{server.server_address[1]}"
    if open_browser:
        webbrowser.open(url)
    print(f"Physical Agent GUI running at {url}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        controller: GuiController = server.controller  # type: ignore[attr-defined]
        controller.stop_watch()
        server.server_close()


def _dump_actions(actions: list[Action]) -> list[dict[str, Any]]:
    return [action.model_dump(mode="json") for action in actions]


def _json_safe(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Physical Agent</title>
  <style>
    :root {
      --bg: #f5f7fb;
      --panel: #ffffff;
      --line: #d8deea;
      --text: #1d2635;
      --muted: #607086;
      --blue: #2563eb;
      --green: #15803d;
      --red: #b42318;
      --amber: #a16207;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      letter-spacing: 0;
    }
    header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 16px 20px;
      background: var(--panel);
      border-bottom: 1px solid var(--line);
    }
    h1 { margin: 0; font-size: 20px; line-height: 1.2; }
    h2 { margin: 0 0 12px; font-size: 16px; }
    p { margin: 0; color: var(--muted); line-height: 1.45; }
    main {
      display: grid;
      grid-template-columns: minmax(320px, 1.15fr) minmax(300px, 0.85fr);
      gap: 14px;
      padding: 14px;
    }
    section {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
    }
    .stack { display: grid; gap: 12px; }
    .row { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
    .top-actions { justify-content: flex-end; }
    .grid-2 { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
    button, select {
      min-height: 36px;
      border: 1px solid #b8c1d1;
      border-radius: 6px;
      background: #fff;
      color: var(--text);
      font: inherit;
    }
    button { padding: 0 12px; font-weight: 650; cursor: pointer; }
    button.primary { background: var(--blue); border-color: var(--blue); color: #fff; }
    button.success { background: var(--green); border-color: var(--green); color: #fff; }
    select { padding: 0 8px; min-width: 136px; }
    input[type="text"] {
      width: 100%;
      min-height: 36px;
      border: 1px solid #b8c1d1;
      border-radius: 6px;
      padding: 8px 10px;
      font: inherit;
    }
    textarea {
      width: 100%;
      min-height: 96px;
      resize: vertical;
      border: 1px solid #b8c1d1;
      border-radius: 6px;
      padding: 10px;
      font: inherit;
      line-height: 1.45;
    }
    label {
      display: inline-flex;
      align-items: center;
      gap: 7px;
      color: var(--muted);
      font-size: 13px;
    }
    .badge {
      display: inline-flex;
      align-items: center;
      min-height: 28px;
      padding: 4px 10px;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: #fff;
      color: var(--muted);
      font-size: 12px;
      font-weight: 650;
    }
    .badge.ok { border-color: #86efac; color: var(--green); background: #f0fdf4; }
    .badge.warn { border-color: #fcd34d; color: var(--amber); background: #fffbeb; }
    .badge.fail { border-color: #fca5a5; color: var(--red); background: #fef2f2; }
    .lang button {
      min-height: 30px;
      padding: 0 10px;
      border-radius: 999px;
      font-size: 12px;
    }
    .lang button.active { background: var(--text); border-color: var(--text); color: #fff; }
    .chat-log {
      display: grid;
      gap: 8px;
      min-height: 160px;
      max-height: 360px;
      overflow: auto;
      padding: 8px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fbfcfe;
    }
    .message {
      max-width: 92%;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 9px 10px;
      background: #fff;
      white-space: pre-wrap;
      line-height: 1.45;
    }
    .message.user { justify-self: end; border-color: #bfdbfe; background: #eff6ff; }
    .message.assistant { justify-self: start; border-color: #bbf7d0; background: #f0fdf4; }
    .list { display: grid; gap: 8px; }
    .item {
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 10px;
      background: #fff;
      min-width: 0;
      white-space: pre-wrap;
    }
    .item strong { display: block; margin-bottom: 3px; }
    .item span { color: var(--muted); line-height: 1.45; overflow-wrap: anywhere; }
    details {
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 10px;
      background: #fbfcfe;
    }
    summary { cursor: pointer; font-weight: 650; }
    pre {
      max-height: 240px;
      overflow: auto;
      margin: 10px 0 0;
      font-family: "SFMono-Regular", Consolas, "Liberation Mono", monospace;
      font-size: 12px;
      line-height: 1.4;
      color: #243044;
    }
    @media (max-width: 900px) {
      main { grid-template-columns: 1fr; }
      header { align-items: flex-start; flex-direction: column; }
      .top-actions { justify-content: flex-start; }
      .grid-2 { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>Physical Agent</h1>
      <p data-i18n="subtitle">Chat, observe, and safely propose physical actions.</p>
    </div>
    <div class="row top-actions">
      <div id="status" class="badge warn" data-i18n="loading">Loading</div>
      <div class="row lang" aria-label="Language">
        <button type="button" data-lang="en">English</button>
        <button type="button" data-lang="zh">中文</button>
      </div>
    </div>
  </header>

  <main>
    <div class="stack">
      <section class="stack">
        <div class="row" style="justify-content: space-between;">
          <h2 data-i18n="chatTitle">Chat</h2>
          <select id="chat-planner" aria-label="Planner">
            <option value="auto" data-i18n="autoChat">Auto</option>
            <option value="llm" data-i18n="llmChat">LLM</option>
            <option value="rule_based" data-i18n="ruleChat">Rules</option>
          </select>
        </div>
        <div id="chat-log" class="chat-log"></div>
        <textarea id="chat-input" data-i18n-placeholder="chatPlaceholder" placeholder="Ask what the agent sees, or request a safe action."></textarea>
        <div class="row">
          <button id="send-chat" class="primary" data-i18n="send">Send</button>
          <label><input id="chat-auto-step" type="checkbox"> <span data-i18n="autoStep">Run one watch step</span></label>
        </div>
      </section>

      <section class="stack">
        <h2 data-i18n="quickTitle">Quick actions</h2>
        <div class="grid-2">
          <button id="setup" class="primary" data-i18n="setup">Setup</button>
          <button id="reset" data-i18n="reset">Reset</button>
          <button id="start-watch" data-i18n="startWatch">Start watch</button>
          <button id="step-watch" data-i18n="stepWatch">Run step</button>
          <button id="demo" class="success" data-i18n="demo">Pick/place demo</button>
          <button id="refresh" data-i18n="refresh">Refresh</button>
        </div>
        <p id="last-message"></p>
      </section>

      <section class="stack">
        <h2 data-i18n="integrateTitle">Hardware integration</h2>
        <input id="integrate-source" type="text" data-i18n-placeholder="integrateSourcePlaceholder" placeholder="./vendor_sdk or https://github.com/org/repo">
        <div class="grid-2">
          <input id="integrate-name" type="text" data-i18n-placeholder="integrateNamePlaceholder" placeholder="optional_driver_name">
          <button id="integrate" data-i18n="integrateButton">Generate driver</button>
        </div>
        <p data-i18n="integrateHint">Generates a watch-side driver scaffold; it does not execute hardware.</p>
      </section>
    </div>

    <div class="stack">
      <section>
        <h2 data-i18n="worldTitle">World</h2>
        <p id="world-summary" data-i18n="noWorld">No world state yet.</p>
        <div id="robots" class="list" style="margin-top: 10px;"></div>
      </section>

      <section>
        <h2 data-i18n="actionsTitle">Actions</h2>
        <div id="actions" class="list"></div>
      </section>

      <section>
        <h2 data-i18n="feedbackTitle">Feedback</h2>
        <div id="feedback-card" class="list"></div>
      </section>

      <section>
        <h2 data-i18n="systemTitle">System</h2>
        <div id="project" class="list"></div>
        <details style="margin-top: 8px;">
          <summary data-i18n="details">Details</summary>
          <pre id="details-json">{}</pre>
        </details>
      </section>
    </div>
  </main>

  <script>
    const I18N = {
      en: {
        subtitle: "Chat, observe, and safely propose physical actions.",
        loading: "Loading",
        setupNeeded: "Setup needed",
        readyWatch: "Ready · watch connected",
        readyStopped: "Ready · watch stopped",
        chatTitle: "Chat",
        autoChat: "Auto",
        llmChat: "LLM",
        ruleChat: "Rules",
        chatPlaceholder: "Ask what the agent sees, or request a safe action.",
        send: "Send",
        autoStep: "Run one watch step",
        quickTitle: "Quick actions",
        setup: "Setup",
        reset: "Reset",
        startWatch: "Start watch",
        stepWatch: "Run step",
        demo: "Pick/place demo",
        refresh: "Refresh",
        worldTitle: "World",
        noWorld: "No world state yet.",
        actionsTitle: "Actions",
        feedbackTitle: "Feedback",
        systemTitle: "System",
        details: "Details",
        noChat: "No chat messages yet.",
        config: "Config",
        workspace: "Workspace",
        message: "Message",
        notCreated: "Not created",
        noRobots: "No robots yet",
        startWatchHint: "Click Setup or Start watch.",
        pending: "Pending",
        completed: "Completed",
        cancelled: "Cancelled",
        none: "none",
        latest: "Latest",
        noFeedback: "No feedback yet.",
        settingUp: "Setting up",
        resetting: "Resetting",
        startingWatch: "Starting watch",
        runningStep: "Running step",
        runningDemo: "Running demo",
        refreshing: "Refreshing",
        sendingChat: "Sending",
        integrateTitle: "Hardware integration",
        integrateSourcePlaceholder: "./vendor_sdk or https://github.com/org/repo",
        integrateNamePlaceholder: "optional_driver_name",
        integrateButton: "Generate driver",
        integrateHint: "Generates a watch-side driver scaffold; it does not execute hardware.",
        integrating: "Generating driver",
        done: "Done"
      },
      zh: {
        subtitle: "聊天、观察，并安全地提出物理动作。",
        loading: "加载中",
        setupNeeded: "需要初始化",
        readyWatch: "就绪 · watch 已连接",
        readyStopped: "就绪 · watch 已停止",
        chatTitle: "对话",
        autoChat: "自动",
        llmChat: "LLM",
        ruleChat: "规则",
        chatPlaceholder: "询问 agent 看到了什么，或请求一个安全动作。",
        send: "发送",
        autoStep: "执行一次 watch step",
        quickTitle: "常用操作",
        setup: "初始化",
        reset: "重置",
        startWatch: "启动 watch",
        stepWatch: "执行一步",
        demo: "抓取演示",
        refresh: "刷新",
        worldTitle: "世界状态",
        noWorld: "还没有世界状态。",
        actionsTitle: "动作",
        feedbackTitle: "反馈",
        systemTitle: "系统",
        details: "详情",
        noChat: "还没有聊天消息。",
        config: "配置",
        workspace: "工作区",
        message: "消息",
        notCreated: "未创建",
        noRobots: "还没有机器人",
        startWatchHint: "点击初始化或启动 watch。",
        pending: "待执行",
        completed: "已完成",
        cancelled: "已取消",
        none: "无",
        latest: "最新",
        noFeedback: "还没有反馈。",
        settingUp: "正在初始化",
        resetting: "正在重置",
        startingWatch: "正在启动 watch",
        runningStep: "正在执行一步",
        runningDemo: "正在运行演示",
        refreshing: "正在刷新",
        sendingChat: "正在发送",
        integrateTitle: "硬件接入",
        integrateSourcePlaceholder: "./vendor_sdk 或 https://github.com/org/repo",
        integrateNamePlaceholder: "可选驱动名",
        integrateButton: "生成驱动",
        integrateHint: "只生成 watch 侧 driver 脚手架，不会执行硬件动作。",
        integrating: "正在生成驱动",
        done: "完成"
      }
    };

    const els = {
      status: document.querySelector("#status"),
      setup: document.querySelector("#setup"),
      reset: document.querySelector("#reset"),
      startWatch: document.querySelector("#start-watch"),
      stepWatch: document.querySelector("#step-watch"),
      demo: document.querySelector("#demo"),
      refresh: document.querySelector("#refresh"),
      lastMessage: document.querySelector("#last-message"),
      project: document.querySelector("#project"),
      detailsJson: document.querySelector("#details-json"),
      worldSummary: document.querySelector("#world-summary"),
      feedbackCard: document.querySelector("#feedback-card"),
      robots: document.querySelector("#robots"),
      actions: document.querySelector("#actions"),
      chatLog: document.querySelector("#chat-log"),
      chatInput: document.querySelector("#chat-input"),
      chatPlanner: document.querySelector("#chat-planner"),
      chatAutoStep: document.querySelector("#chat-auto-step"),
      sendChat: document.querySelector("#send-chat"),
      integrateSource: document.querySelector("#integrate-source"),
      integrateName: document.querySelector("#integrate-name"),
      integrate: document.querySelector("#integrate")
    };

    const savedLang = localStorage.getItem("physical-agent-lang");
    let lang = savedLang || ((navigator.language || "").toLowerCase().startsWith("zh") ? "zh" : "en");
    let lastState = null;

    function t(key) { return (I18N[lang] || I18N.en)[key] || I18N.en[key] || key; }

    function setLanguage(next) {
      lang = next;
      localStorage.setItem("physical-agent-lang", lang);
      document.documentElement.lang = lang === "zh" ? "zh-CN" : "en";
      document.querySelectorAll("[data-i18n]").forEach(node => { node.textContent = t(node.dataset.i18n); });
      document.querySelectorAll("[data-i18n-placeholder]").forEach(node => { node.placeholder = t(node.dataset.i18nPlaceholder); });
      document.querySelectorAll("[data-lang]").forEach(node => node.classList.toggle("active", node.dataset.lang === lang));
      if (lastState) render(lastState);
    }

    document.querySelectorAll("[data-lang]").forEach(node => {
      node.addEventListener("click", () => setLanguage(node.dataset.lang));
    });
    els.chatInput.addEventListener("input", () => { els.chatInput.dataset.touched = "true"; });

    async function api(path, options = {}) {
      const response = await fetch(path, {
        headers: {"Content-Type": "application/json"},
        ...options
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.message || "Request failed");
      return data;
    }

    async function post(path, payload = {}) {
      return api(path, { method: "POST", body: JSON.stringify(payload) });
    }

    function escapeHtml(text) {
      return String(text).replace(/[&<>"']/g, char => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;"
      }[char]));
    }

    function item(title, body) {
      const div = document.createElement("div");
      div.className = "item";
      div.innerHTML = `<strong>${escapeHtml(title)}</strong><span>${escapeHtml(body || "")}</span>`;
      return div;
    }

    function render(state) {
      lastState = state;
      const ready = Boolean(state.ready);
      els.status.className = ready ? "badge ok" : "badge warn";
      els.status.textContent = ready ? (state.watch_started ? t("readyWatch") : t("readyStopped")) : t("setupNeeded");

      renderChat(state);
      renderWorld(state);
      renderActions(state);
      renderFeedback(state);
      renderSystem(state);
    }

    function renderChat(state) {
      els.chatLog.innerHTML = "";
      const messages = ((state.chat || {}).messages) || [];
      if (messages.length === 0) {
        const empty = document.createElement("div");
        empty.className = "message";
        empty.textContent = t("noChat");
        els.chatLog.appendChild(empty);
        return;
      }
      for (const message of messages.slice(-16)) {
        const div = document.createElement("div");
        div.className = `message ${message.role}`;
        div.textContent = `${message.role}: ${message.content}`;
        els.chatLog.appendChild(div);
      }
      els.chatLog.scrollTop = els.chatLog.scrollHeight;
    }

    function renderWorld(state) {
      const world = state.world || {};
      els.worldSummary.textContent = world.summary || t("noWorld");
      els.robots.innerHTML = "";
      const robots = ((state.capabilities || {}).robots) || {};
      if (Object.keys(robots).length === 0) {
        els.robots.appendChild(item(t("noRobots"), t("startWatchHint")));
        return;
      }
      for (const [id, robot] of Object.entries(robots)) {
        const caps = (robot.capabilities || []).map(cap => cap.name).join(", ");
        els.robots.appendChild(item(id, `${robot.kind || ""} · ${robot.driver || ""}\n${caps}`));
      }
    }

    function renderActions(state) {
      els.actions.innerHTML = "";
      const board = state.actions || { pending: [], completed: [], cancelled: [] };
      const labels = [["pending", t("pending")], ["completed", t("completed")], ["cancelled", t("cancelled")]];
      for (const [name, label] of labels) {
        const rows = board[name] || [];
        const body = rows.length ? rows.map(row => `${row.id}: ${row.robot}.${row.capability}`).join("\n") : t("none");
        els.actions.appendChild(item(label, body));
      }
    }

    function renderFeedback(state) {
      els.feedbackCard.innerHTML = "";
      const latest = ((state.feedback || {}).latest) || {};
      if (!Object.keys(latest).length) {
        els.feedbackCard.appendChild(item(t("latest"), t("noFeedback")));
        return;
      }
      els.feedbackCard.appendChild(item(
        t("latest"),
        `${latest.action_id || ""} · ${latest.status || ""}\n${latest.message || ""}`
      ));
    }

    function renderSystem(state) {
      els.project.innerHTML = "";
      els.project.appendChild(item(t("config"), state.config_path || t("notCreated")));
      els.project.appendChild(item(t("workspace"), state.workspace_path || t("notCreated")));
      els.project.appendChild(item(t("message"), state.message || ""));
      els.detailsJson.textContent = JSON.stringify({
        plan: state.plan,
        memory: state.memory,
        doctor: state.doctor
      }, null, 2);
    }

    async function refresh() {
      try {
        render(await api("/api/state"));
      } catch (error) {
        els.lastMessage.textContent = error.message;
      }
    }

    async function run(labelKey, fn) {
      els.lastMessage.textContent = `${t(labelKey)}...`;
      try {
        const result = await fn();
        els.lastMessage.textContent = result.message || t("done");
        render(result.state || await api("/api/state"));
      } catch (error) {
        els.lastMessage.textContent = error.message;
      }
    }

    els.setup.addEventListener("click", () => run("settingUp", () => post("/api/setup")));
    els.reset.addEventListener("click", () => run("resetting", () => post("/api/setup", { force: true })));
    els.startWatch.addEventListener("click", () => run("startingWatch", () => post("/api/watch/start")));
    els.stepWatch.addEventListener("click", () => run("runningStep", () => post("/api/watch/step")));
    els.demo.addEventListener("click", () => run("runningDemo", () => post("/api/demo")));
    els.refresh.addEventListener("click", () => run("refreshing", () => api("/api/state")));
    els.sendChat.addEventListener("click", () => run("sendingChat", () => post("/api/chat", {
      message: els.chatInput.value,
      planner: els.chatPlanner.value,
      auto_step: els.chatAutoStep.checked
    })));
    els.integrate.addEventListener("click", () => run("integrating", () => post("/api/integrate", {
      source: els.integrateSource.value,
      name: els.integrateName.value
    })));

    setLanguage(lang);
    refresh();
  </script>
</body>
</html>
"""
