import asyncio
from pathlib import Path

from typer.testing import CliRunner

from physical_agent.agent.chat_runtime import ChatRuntime
from physical_agent.agent.driver_coder import DriverCodingAgent
from physical_agent.agent.onboarding import HardwareIntegrationAssistant
from physical_agent.cli import app
from physical_agent.drivers.loader import load_driver
from physical_agent.protocol.schemas import Action
from physical_agent.protocol.workspace import Workspace
from physical_agent.quickstart import setup_project


def _make_vendor_sdk(tmp_path: Path) -> Path:
    sdk = tmp_path / "vendor_sdk"
    sdk.mkdir()
    (sdk / "README.md").write_text(
        "\n".join(
            [
                "# Demo Serial Arm SDK",
                "",
                "Python SDK for a serial robot arm over COM3 or /dev/ttyUSB0.",
                "The device can move, pick, grasp, place, drop, and release objects.",
            ]
        ),
        encoding="utf-8",
    )
    (sdk / "pyproject.toml").write_text(
        '[project]\nname = "demo-serial-arm-sdk"\ndescription = "Serial arm SDK."\n',
        encoding="utf-8",
    )
    (sdk / "demo_sdk.py").write_text(
        "\n".join(
            [
                "class DemoArmClient:",
                "    def connect(self): ...",
                "    def move_to(self, x, y, z): ...",
                "    def pick(self, object_id): ...",
                "    def place(self, target): ...",
            ]
        ),
        encoding="utf-8",
    )
    return sdk


class _FakeDriverCodingClient:
    def __init__(self, *, class_name: str = "DemoDriver"):
        self.class_name = class_name
        self.requests = []

    def chat(self, messages, *, temperature=0.0, max_tokens=1024):
        self.requests.append(
            {
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )
        return _driver_coding_payload(class_name=self.class_name)


class _FakeDriverCodingClientFactory:
    def __init__(self):
        self.requests = []

    def __call__(self, settings):
        client = _FakeDriverCodingClient(class_name="DemoSerialArmSdkDriver")
        self.requests.append(client.requests)
        return client


def _driver_coding_payload(*, class_name: str = "DemoDriver") -> str:
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


class __CLASS_NAME__(PhysicalDriver):
    def __init__(self, context: DriverContext):
        super().__init__(context)
        self.mode = context.config.get("mode", "mock")
        self.connected = False
        self.pose = {"x": 0.0, "y": 0.0, "z": 0.0}
        self.holding = None

    async def connect(self) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.connected = False

    async def health(self) -> HealthStatus:
        return HealthStatus(ok=self.connected, message="connected")

    async def observe(self) -> Observation:
        return Observation(
            summary="LLM generated demo driver is connected.",
            robots={self.context.robot_id: {"status": "idle", "pose": self.pose, "holding": self.holding}},
        )

    def capabilities(self) -> list[Capability]:
        return [
            Capability(
                name="observe",
                description="Observe the arm.",
                params_schema={"type": "object", "properties": {}, "additionalProperties": False},
            ),
            Capability(
                name="move_to",
                description="Move the arm.",
                params_schema={
                    "type": "object",
                    "required": ["x", "y", "z"],
                    "properties": {"x": {"type": "number"}, "y": {"type": "number"}, "z": {"type": "number"}},
                    "additionalProperties": False,
                },
            ),
        ]

    async def execute(self, action: Action) -> ActionResult:
        if action.capability == "observe":
            observation = await self.observe()
            return ActionResult(status="completed", message="Observed.", result={"observation": observation.model_dump(mode="json")})
        if action.capability == "move_to":
            self.pose = {"x": action.params["x"], "y": action.params["y"], "z": action.params["z"]}
            return ActionResult(status="completed", message="Moved by LLM generated driver.", result={"pose": self.pose})
        return ActionResult(status="failed", message=f"Unsupported capability: {action.capability}")
'''.replace("__CLASS_NAME__", class_name)
    return __import__("json").dumps(
        {
            "summary": "Generated a mock-safe driver that maps the SDK move API.",
            "files": [{"path": "driver.py", "content": driver_py}],
            "next_steps": ["Replace mock move_to with DemoArmClient.move_to in hardware mode."],
            "tests": ["Run load_driver and observe action validation."],
        }
    )


def test_hardware_integration_assistant_analyzes_local_sdk(tmp_path):
    sdk = _make_vendor_sdk(tmp_path)

    profile = HardwareIntegrationAssistant(sdk, base_dir=tmp_path).analyze()

    assert profile.source_kind == "local_path"
    assert profile.transport == "serial"
    assert profile.robot_kind == "arm"
    assert [cap.name for cap in profile.capabilities] == ["observe", "move_to", "pick", "place"]
    assert "port" in profile.config_schema["properties"]


def test_hardware_integration_assistant_generates_loadable_driver(tmp_path):
    sdk = _make_vendor_sdk(tmp_path)
    result = HardwareIntegrationAssistant(
        sdk,
        output_dir=tmp_path / "demo_driver",
        name="demo_driver",
        base_dir=tmp_path,
    ).generate()

    workspace = Workspace(tmp_path / "workspace")
    workspace.initialize()
    loaded = load_driver(
        robot_id="demo_1",
        driver_ref=str(result.output_path),
        config={"mode": "mock", "port": "COM3", "baudrate": 115200},
        workspace_path=workspace.path,
        artifacts_path=workspace.artifacts_path,
    )
    asyncio.run(loaded.driver.connect())

    assert loaded.manifest.name == "demo_driver"
    assert (result.output_path / "README.zh-CN.md").exists()
    assert [cap.name for cap in loaded.driver.capabilities()] == [
        "observe",
        "move_to",
        "pick",
        "place",
    ]

    pick = asyncio.run(
        loaded.driver.execute(
            Action(
                id="act_001",
                robot="demo_1",
                capability="pick",
                params={"object_id": "red_block"},
            )
        )
    )
    place = asyncio.run(
        loaded.driver.execute(
            Action(
                id="act_002",
                robot="demo_1",
                capability="place",
                params={"target": "tray"},
                depends_on=["act_001"],
            )
        )
    )

    assert pick.status == "completed"
    assert place.status == "completed"
    assert place.result["target"] == "tray"


def test_cli_integrate_creates_named_scaffold(tmp_path):
    sdk = _make_vendor_sdk(tmp_path)
    config_path = tmp_path / "physical-agent.yaml"
    setup_project(config_path, publish=False)
    output = tmp_path / "drivers" / "demo_driver"

    result = CliRunner().invoke(
        app,
        [
            "integrate",
            str(sdk),
            "--config",
            str(config_path),
            "--output",
            str(output),
            "--name",
            "demo_driver",
        ],
    )

    assert result.exit_code == 0, result.output
    assert (output / "physical_driver.yaml").exists()
    assert (output / "driver.py").exists()
    assert (output / "integration-report.md").exists()


def test_chat_runtime_integration_request_generates_scaffold(tmp_path):
    sdk = _make_vendor_sdk(tmp_path)
    config_path = tmp_path / "physical-agent.yaml"
    setup_project(config_path, publish=True)

    result = ChatRuntime(config_path, planner_name="rule_based").respond(
        f"帮我接入这个硬件 SDK {sdk}"
    )

    output_path = Path(result["integration"]["output_path"])
    workspace = Workspace(tmp_path / "workspace")

    assert result["mode"] == "integration"
    assert workspace.read_plan()["plan"].intent == "integrate"
    assert output_path.exists()
    assert output_path.parent == tmp_path / "physical-agent-integration"
    assert (output_path / "README.zh-CN.md").read_text(encoding="utf-8").startswith("#")


def test_chat_runtime_llm_planner_integration_codes_driver(tmp_path, monkeypatch):
    _clear_llm_env(monkeypatch)
    sdk = _make_vendor_sdk(tmp_path)
    config_path = tmp_path / "physical-agent.yaml"
    setup_project(config_path, publish=True)

    fake_factory = _FakeDriverCodingClientFactory()
    monkeypatch.setattr("physical_agent.agent.driver_coder.OpenAICompatibleClient", fake_factory)
    (tmp_path / ".env").write_text(
        "GPT_URL=http://example.test/v1\n"
        "GPT_KEY=test-key\n"
        "GPT_MODEL=test-model\n",
        encoding="utf-8",
    )

    result = ChatRuntime(config_path, planner_name="llm").respond(
        f"帮我接入这个硬件 SDK {sdk}"
    )
    output_path = Path(result["integration"]["output_path"])

    assert result["mode"] == "integration"
    assert result["integration"]["llm_used"] is True
    assert fake_factory.requests
    assert "LLM generated demo driver" in (output_path / "driver.py").read_text(encoding="utf-8")
    assert (output_path / "llm-coding-report.md").exists()


def test_driver_coding_agent_uses_llm_to_update_driver(tmp_path):
    sdk = _make_vendor_sdk(tmp_path)
    fake_client = _FakeDriverCodingClient()

    result = DriverCodingAgent(
        sdk,
        output_dir=tmp_path / "coded_driver",
        name="demo_driver",
        base_dir=tmp_path,
        client=fake_client,
    ).generate()

    driver_text = (result.output_path / "driver.py").read_text(encoding="utf-8")

    assert result.llm_used is True
    assert result.validation["ok"] is True
    assert fake_client.requests
    assert "LLM generated demo driver" in driver_text
    assert (result.output_path / "llm-coding-report.md").exists()

    workspace = Workspace(tmp_path / "workspace-coded")
    workspace.initialize()
    loaded = load_driver(
        robot_id="coded_1",
        driver_ref=str(result.output_path),
        config={"mode": "mock", "port": "COM3", "baudrate": 115200},
        workspace_path=workspace.path,
        artifacts_path=workspace.artifacts_path,
    )
    asyncio.run(loaded.driver.connect())
    move = asyncio.run(
        loaded.driver.execute(
            Action(
                id="act_001",
                robot="coded_1",
                capability="move_to",
                params={"x": 1, "y": 2, "z": 3},
            )
        )
    )
    assert move.status == "completed"
    assert move.result["pose"] == {"x": 1, "y": 2, "z": 3}


def test_cli_integrate_llm_uses_openai_compatible_endpoint(tmp_path):
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Handler(BaseHTTPRequestHandler):
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

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        import os

        previous_env = {key: os.environ.get(key) for key in _LLM_ENV_KEYS}
        for key in _LLM_ENV_KEYS:
            os.environ.pop(key, None)
        sdk = _make_vendor_sdk(tmp_path)
        config_path = tmp_path / "physical-agent.yaml"
        setup_project(config_path, publish=False)
        (tmp_path / ".env").write_text(
            f"GPT_URL=http://127.0.0.1:{server.server_address[1]}/v1\n"
            "GPT_KEY=test-key\n"
            "GPT_MODEL=test-model\n",
            encoding="utf-8",
        )
        output = tmp_path / "drivers" / "coded_driver"

        result = CliRunner().invoke(
            app,
            [
                "integrate",
                str(sdk),
                "--config",
                str(config_path),
                "--output",
                str(output),
                "--name",
                "demo_driver",
                "--llm",
            ],
        )

        assert result.exit_code == 0, result.output
        assert "LLM used: True" in result.output
        assert Handler.requests[0]["model"] == "test-model"
        assert "LLM generated demo driver" in (output / "driver.py").read_text(encoding="utf-8")
    finally:
        for key, value in previous_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        server.shutdown()
        server.server_close()


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


def _clear_llm_env(monkeypatch):
    for key in _LLM_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
