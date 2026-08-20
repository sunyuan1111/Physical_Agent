from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from physical_agent.api import watch_service
from physical_agent.api.server import create_app
from physical_agent.config import write_default_config
from physical_agent.protocol.schemas import Observation
from physical_agent.state import open_state_store


def _client_or_skip():
    pytest.importorskip("fastapi")
    try:
        from fastapi.testclient import TestClient
    except (ImportError, RuntimeError) as exc:
        pytest.skip(f"fastapi.testclient is unavailable; install .[dev,server]: {exc}")
    return TestClient


def _prepare_store(config_path: Path):
    store = open_state_store(config_path=config_path)
    store.initialize()
    store.write_capabilities(
        {
            "arm_1": {
                "kind": "arm",
                "driver": "mock_arm",
                "status": "connected",
                "capabilities": [
                    {
                        "name": "observe",
                        "description": "Inspect the workspace.",
                        "params_schema": {"type": "object"},
                    },
                    {
                        "name": "pick",
                        "description": "Pick an object.",
                        "params_schema": {"type": "object"},
                    },
                    {
                        "name": "place",
                        "description": "Place an object.",
                        "params_schema": {"type": "object"},
                    },
                ],
            }
        }
    )
    store.write_world(
        Observation(
            summary="API watch events test world",
            robots={"arm_1": {"status": "idle"}},
            objects={
                "red_block": {"type": "block", "color": "red", "location": "table"},
                "tray": {"type": "tray", "location": "table"},
            },
        )
    )
    return store


def _read_sse_events(client, *, limit: int, wanted: set[str] | None = None):
    events = []
    current: dict[str, str] = {}
    response = client.get(f"/api/events?limit={limit}")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    for line in response.text.splitlines():
        if line == "":
            if current:
                events.append(
                    {
                        "event": current["event"],
                        "data": json.loads(current["data"]),
                    }
                )
                current = {}
                names = {item["event"] for item in events}
                if len(events) >= limit or (wanted is not None and wanted <= names):
                    break
            continue
        if line.startswith(":"):
            continue
        if line.startswith("event: "):
            current["event"] = line.removeprefix("event: ")
        elif line.startswith("data: "):
            current["data"] = line.removeprefix("data: ")
    return events


def test_create_app_default_does_not_start_watch_runtime(tmp_path, monkeypatch):
    TestClient = _client_or_skip()
    config_path = write_default_config(tmp_path / "physical-agent.yaml", overwrite=True)
    _prepare_store(config_path)

    calls = {"loader": 0}

    def fail_loader():
        calls["loader"] += 1
        raise AssertionError("enable_watch=False must not load WatchRuntime")

    monkeypatch.setattr(watch_service, "_load_watch_runtime_class", fail_loader)

    with TestClient(create_app(config_path, enable_watch=False)) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["ready"] is True
    assert calls == {"loader": 0}


def test_events_stream_returns_hello_and_state_without_watch(tmp_path, monkeypatch):
    TestClient = _client_or_skip()
    config_path = write_default_config(tmp_path / "physical-agent.yaml", overwrite=True)
    _prepare_store(config_path)

    def fail_loader():
        raise AssertionError("/api/events without watch must not load WatchRuntime")

    monkeypatch.setattr(watch_service, "_load_watch_runtime_class", fail_loader)

    with TestClient(create_app(config_path, enable_watch=False)) as client:
        events = _read_sse_events(client, limit=2)

    assert [item["event"] for item in events] == ["hello", "state"]
    assert events[0]["data"]["payload"] == {
        "version": "0.1.0",
        "watch_enabled": False,
    }
    state_payload = events[1]["data"]["payload"]
    assert state_payload["reason"] == "connect"
    assert state_payload["state"]["ready"] is True
    assert state_payload["state"]["pending_actions"] == []


def test_enable_watch_background_loop_publishes_step_and_error(tmp_path, monkeypatch):
    TestClient = _client_or_skip()
    config_path = write_default_config(tmp_path / "physical-agent.yaml", overwrite=True)
    _prepare_store(config_path)

    class FakeWatchRuntime:
        instances = []

        def __init__(self, config_path):
            self.config_path = Path(config_path)
            self.config = SimpleNamespace(watch=SimpleNamespace(tick_ms=1))
            self.steps = 0
            self.setup_called = False
            self.shutdown_called = False
            FakeWatchRuntime.instances.append(self)

        async def setup(self):
            self.setup_called = True

        async def step(self, *, setup=True):
            assert setup is False
            self.steps += 1
            if self.steps == 1:
                return 1
            raise RuntimeError("fake watch step failed")

        async def shutdown(self):
            self.shutdown_called = True

    monkeypatch.setattr(
        watch_service,
        "_load_watch_runtime_class",
        lambda: FakeWatchRuntime,
    )

    with TestClient(
        create_app(config_path, enable_watch=True, watch_interval_s=0.005)
    ) as client:
        time.sleep(0.05)
        events = _read_sse_events(
            client,
            limit=20,
            wanted={"watch_step", "error"},
        )

    runtime = FakeWatchRuntime.instances[0]
    assert runtime.setup_called is True
    assert runtime.shutdown_called is True
    assert runtime.steps >= 2

    names = [item["event"] for item in events]
    assert "watch_step" in names
    assert "error" in names
    watch_step = next(item for item in events if item["event"] == "watch_step")
    error = next(item for item in events if item["event"] == "error")
    assert watch_step["data"]["payload"]["executed"] == 1
    assert watch_step["data"]["payload"]["state"]["ready"] is True
    assert error["data"]["payload"]["phase"] == "watch_step"
    assert error["data"]["payload"]["error_type"] == "RuntimeError"


def test_http_auto_step_like_fields_do_not_start_watch(tmp_path, monkeypatch):
    TestClient = _client_or_skip()
    config_path = write_default_config(tmp_path / "physical-agent.yaml", overwrite=True)
    _prepare_store(config_path)

    def fail_loader():
        raise AssertionError("request handlers must not load WatchRuntime")

    monkeypatch.setattr(watch_service, "_load_watch_runtime_class", fail_loader)

    with TestClient(create_app(config_path, enable_watch=False)) as client:
        proposed = client.post(
            "/api/actions/propose",
            json={
                "id": "act_auto_step_ignored",
                "robot": "arm_1",
                "capability": "observe",
                "params": {},
                "reason": "auto_step must be ignored by API proposal handlers",
                "depends_on": [],
                "auto_step": True,
            },
        )
        submitted = client.post(
            "/api/tasks/submit",
            json={"task": "look around", "auto_step": True},
        )
        chat = client.post(
            "/api/chat",
            json={"message": "look around", "auto_step": True},
        )

    assert proposed.status_code == 200
    assert submitted.status_code == 200
    assert chat.status_code == 200
    assert chat.json()["executed"] == 0

    store = open_state_store(config_path=config_path)
    board = store.read_actions()
    assert [item.id for item in board["completed"]] == []
    assert [item.id for item in board["cancelled"]] == []
    assert "act_auto_step_ignored" in {item.id for item in board["pending"]}


@pytest.mark.asyncio
async def test_concurrent_api_proposals_sqlite_do_not_drop_action_ids(tmp_path):
    pytest.importorskip("fastapi")
    httpx = pytest.importorskip("httpx")
    config_path = write_default_config(tmp_path / "physical-agent.yaml", overwrite=True)
    _prepare_store(config_path)
    expected_ids = {f"act_concurrent_{index:03d}" for index in range(16)}

    transport = httpx.ASGITransport(app=create_app(config_path, enable_watch=False))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        responses = await asyncio.gather(
            *[
                client.post(
                    "/api/actions/propose",
                    json={
                        "id": action_id,
                        "robot": "arm_1",
                        "capability": "observe",
                        "params": {},
                        "reason": "concurrent API proposal",
                        "depends_on": [],
                    },
                )
                for action_id in sorted(expected_ids)
            ]
        )

    assert {response.status_code for response in responses} == {200}
    store = open_state_store(config_path=config_path)
    pending_ids = {item.id for item in store.read_actions()["pending"]}
    assert expected_ids <= pending_ids
