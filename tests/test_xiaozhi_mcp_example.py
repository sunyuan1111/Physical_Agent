from pathlib import Path
from shutil import copytree

import asyncio

from physical_agent.drivers import xiaozhi_mcp as xiaozhi_mcp_module
from physical_agent.watch.runtime import WatchRuntime


def test_xiaozhi_example_files_exist():
    base = Path("examples/xiaozhi_mcp_hardware")
    assert (base / "physical-agent.yaml").exists()
    assert (base / ".env.example").exists()
    assert (base / "README.md").exists()
    assert (base / "README.zh-CN.md").exists()
    assert (base / "physical_driver.yaml").exists()
    assert (base / "driver.py").exists()


def test_xiaozhi_example_watch_runtime_setup(monkeypatch, tmp_path):
    class FakeWsClient:
        def __init__(self, url, *, connect_timeout_s, timeout_s, **_kwargs):
            self.url = url
            self.is_connected = False
            self._next_id = 1

        def connect(self):
            self.is_connected = True

        def close(self):
            self.is_connected = False

        def send_tool_call(self, name, arguments=None):
            request_id = self._next_id
            self._next_id += 1
            return request_id

    monkeypatch.setattr(xiaozhi_mcp_module, "XiaozhiMcpWebSocketClient", FakeWsClient)
    monkeypatch.setenv("XIAOZHI_MCP_URL", "ws://127.0.0.1:8080/ws")

    example_dir = Path("examples/xiaozhi_mcp_hardware").resolve()
    copied_dir = tmp_path / "xiaozhi_mcp_hardware"
    copytree(example_dir, copied_dir)
    config_path = copied_dir / "physical-agent.yaml"
    runtime = WatchRuntime(config_path)
    asyncio.run(runtime.setup())
    assert "xiaozhi_1" in runtime.loaded_drivers
    assert runtime.workspace is not None
    capabilities = runtime.workspace.read_capabilities()
    assert "xiaozhi_1" in capabilities["robots"]
    assert any(cap["name"] == "otto_action" for cap in capabilities["robots"]["xiaozhi_1"]["capabilities"])
