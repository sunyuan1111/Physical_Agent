from __future__ import annotations

import json
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from physical_agent.config import DEFAULT_CONFIG_NAME
from physical_agent.gui.controller import GuiController, _json_safe


STATIC_DIR = Path(__file__).with_name("static")
STATIC_CONTENT_TYPES = {
    ".css": "text/css; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
}


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
                self._send_static("index.html")
                return
            if route.startswith("/static/"):
                self._send_static(unquote(route.removeprefix("/static/")))
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
                    llm = bool(payload.get("llm", False))
                    model = str(payload.get("model", "")).strip() or None
                    self._send_json(
                        controller.integrate_hardware(
                            source,
                            output=output,
                            name=name,
                            llm=llm,
                            model=model,
                        )
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

        def _send_static(self, relative_path: str) -> None:
            try:
                target = (STATIC_DIR / relative_path).resolve()
                target.relative_to(STATIC_DIR.resolve())
            except ValueError:
                self._send_json({"ok": False, "message": "Not found."}, HTTPStatus.NOT_FOUND)
                return
            if not target.is_file():
                self._send_json({"ok": False, "message": "Not found."}, HTTPStatus.NOT_FOUND)
                return

            payload = target.read_bytes()
            content_type = STATIC_CONTENT_TYPES.get(target.suffix.lower(), "application/octet-stream")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
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
