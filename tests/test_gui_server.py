import json
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from physical_agent.gui import make_server
from physical_agent.quickstart import setup_project


def _driver_coding_payload() -> str:
    driver_py = '''
from physical_agent.drivers import (
    Action,
    ActionResult,
    Capability,
    DriverContext,
    HealthStatus,
    Observation,
    PhysicalDriver,
)


class GuiDriver(PhysicalDriver):
    def __init__(self, context: DriverContext):
        super().__init__(context)
        self.connected = False

    async def connect(self) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.connected = False

    async def health(self) -> HealthStatus:
        return HealthStatus(ok=self.connected, message="connected")

    async def observe(self) -> Observation:
        return Observation(summary="GUI LLM generated driver is connected.", robots={self.context.robot_id: {"status": "idle"}})

    def capabilities(self) -> list[Capability]:
        return [
            Capability(
                name="observe",
                description="Observe the device.",
                params_schema={"type": "object", "properties": {}, "additionalProperties": False},
            )
        ]

    async def execute(self, action: Action) -> ActionResult:
        if action.capability == "observe":
            observation = await self.observe()
            return ActionResult(status="completed", message="Observed.", result={"observation": observation.model_dump(mode="json")})
        return ActionResult(status="failed", message=f"Unsupported capability: {action.capability}")
'''
    return json.dumps(
        {
            "summary": "Generated a GUI mock-safe driver.",
            "files": [{"path": "driver.py", "content": driver_py}],
            "next_steps": ["Wire the real SDK in hardware mode."],
            "tests": ["Load the generated driver and execute observe."],
        }
    )


class _FakeOpenAIHandler(BaseHTTPRequestHandler):
    requests = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        self.__class__.requests.append(payload)
        body = json.dumps(
            {"choices": [{"message": {"role": "assistant", "content": _driver_coding_payload()}}]}
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return


def _request(url: str, *, method: str = "GET", payload: dict | None = None) -> dict:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def _read_text(url: str) -> str:
    with urllib.request.urlopen(url, timeout=10) as response:
        return response.read().decode("utf-8")


def test_gui_homepage_has_language_toggle(tmp_path):
    server = make_server(tmp_path / "physical-agent.yaml", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        html = _read_text(f"{base_url}/")
        assert "Physical Agent" in html
        assert 'data-lang="en"' in html
        assert 'data-lang="zh"' in html
        assert "中文" in html
        assert "Chat" in html
    finally:
        server.shutdown()
        server.server_close()


def test_gui_http_demo_endpoint(tmp_path):
    server = make_server(tmp_path / "physical-agent.yaml", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        setup = _request(f"{base_url}/api/setup", method="POST", payload={})
        assert setup["ok"] is True

        demo = _request(f"{base_url}/api/demo", method="POST", payload={})
        assert demo["ok"] is True
        assert demo["executed"] == 2
        assert demo["state"]["world"]["state"]["objects"]["red_block"]["location"] == "tray"

        state = _request(f"{base_url}/api/state")
        assert state["ready"] is True
        assert state["actions"]["completed"][-1]["capability"] == "place"
    finally:
        server.shutdown()
        server.server_close()


def test_gui_http_chat_endpoint(tmp_path):
    server = make_server(tmp_path / "physical-agent.yaml", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        _request(f"{base_url}/api/setup", method="POST", payload={})
        chat = _request(
            f"{base_url}/api/chat",
            method="POST",
            payload={
                "message": "pick the red block and place it on the tray",
                "planner": "rule_based",
                "auto_step": True,
            },
        )
        assert chat["ok"] is True
        assert chat["executed"] == 2
        assert chat["state"]["chat"]["messages"][-1]["role"] == "assistant"
        assert chat["state"]["world"]["state"]["objects"]["red_block"]["location"] == "tray"
    finally:
        server.shutdown()
        server.server_close()


def test_gui_http_chat_endpoint_exposes_code_result(tmp_path, monkeypatch):
    from physical_agent.agent.chat_runtime import ChatRuntime
    from physical_agent.agent.code_runtime import CodeSkillRuntime
    from physical_agent.protocol.schemas import CodeTaskIntent, CodeTaskResult

    class FakeCodeRuntime:
        def detect(self, message: str):
            return CodeTaskIntent(
                kind="code_edit",
                confidence=1.0,
                reason="test",
                requested_files=[],
            )

        def run(self, message: str):
            return CodeTaskResult(
                summary="Updated via GUI chat.",
                changed_files=["README.md"],
                tests_run=["pytest", "-q"],
                test_output="ok",
                lessons_written=["GUI code lesson"],
                rounds=1,
                ok=True,
                intent_kind="code_edit",
            )

    server = make_server(tmp_path / "physical-agent.yaml", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        _request(f"{base_url}/api/setup", method="POST", payload={})
        original = ChatRuntime._code_runtime
        monkeypatch.setattr(ChatRuntime, "_code_runtime", lambda self: FakeCodeRuntime())
        try:
            chat = _request(
                f"{base_url}/api/chat",
                method="POST",
                payload={"message": "please modify files and write tests", "planner": "rule_based"},
            )
        finally:
            monkeypatch.setattr(ChatRuntime, "_code_runtime", original)

        assert chat["ok"] is True
        assert chat["code_result"]["summary"] == "Updated via GUI chat."
        assert chat["state"]["code_result"]["summary"] == "Updated via GUI chat."
    finally:
        server.shutdown()
        server.server_close()


def test_gui_http_integrate_endpoint(tmp_path):
    sdk = tmp_path / "vendor_sdk"
    sdk.mkdir()
    (sdk / "README.md").write_text(
        "# Demo Voice Device\n\nHTTP SDK with voice, speak, tts, light and RGB support.",
        encoding="utf-8",
    )
    server = make_server(tmp_path / "physical-agent.yaml", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        result = _request(
            f"{base_url}/api/integrate",
            method="POST",
            payload={"source": str(sdk), "name": "voice_light_driver"},
        )
        output_path = result["result"]["output_path"]
        assert result["ok"] is True
        assert "physical-agent-integration" in output_path
        assert result["result"]["source"]["transport"] == "http"
        assert result["result"]["source"]["robot_kind"] == "audio_device"
        assert result["state"]["ready"] is True
    finally:
        server.shutdown()
        server.server_close()


def test_gui_http_integrate_endpoint_can_use_llm(tmp_path):
    import os

    sdk = tmp_path / "vendor_sdk"
    sdk.mkdir()
    (sdk / "README.md").write_text(
        "# Demo GUI Device\n\nPython SDK with observe support.",
        encoding="utf-8",
    )
    _FakeOpenAIHandler.requests = []
    previous_env = {key: os.environ.get(key) for key in _LLM_ENV_KEYS}
    for key in _LLM_ENV_KEYS:
        os.environ.pop(key, None)
    fake_llm = ThreadingHTTPServer(("127.0.0.1", 0), _FakeOpenAIHandler)
    fake_thread = threading.Thread(target=fake_llm.serve_forever, daemon=True)
    fake_thread.start()
    config_path = tmp_path / "physical-agent.yaml"
    setup_project(config_path, publish=False)
    (tmp_path / ".env").write_text(
        f"GPT_URL=http://127.0.0.1:{fake_llm.server_address[1]}/v1\n"
        "GPT_KEY=test-key\n"
        "GPT_MODEL=test-model\n",
        encoding="utf-8",
    )
    server = make_server(config_path, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        result = _request(
            f"{base_url}/api/integrate",
            method="POST",
            payload={
                "source": str(sdk),
                "name": "gui_driver",
                "llm": True,
                "model": "override-model",
            },
        )
        output_path = result["result"]["output_path"]

        assert result["ok"] is True
        assert result["result"]["llm_used"] is True
        assert _FakeOpenAIHandler.requests[-1]["model"] == "override-model"
        assert "GUI LLM generated driver" in (Path(output_path) / "driver.py").read_text(
            encoding="utf-8"
        )
    finally:
        for key, value in previous_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        server.shutdown()
        server.server_close()
        fake_llm.shutdown()
        fake_llm.server_close()


_LLM_ENV_KEYS = (
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENAI_MODEL",
    "GPT_KEY",
    "GPT_URL",
    "GPT_MODEL",
    "API_KEY",
    "BASE_URL",
    "MODEL",
)
