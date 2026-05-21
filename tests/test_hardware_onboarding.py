import asyncio
from pathlib import Path

from typer.testing import CliRunner

from physical_agent.agent.chat_runtime import ChatRuntime
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
    return sdk


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
