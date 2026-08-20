import asyncio
import json
import sqlite3

import pytest
import yaml
from pydantic import ValidationError

from physical_agent.config import load_config, write_default_config
from physical_agent.drivers.transport import (
    TransportClosedError,
    TransportReconnectFailed,
    TransportReconnecting,
)
from physical_agent.protocol.schemas import Action, Observation
from physical_agent.state import open_state_store
from physical_agent.watch.runtime import WatchRuntime


def _write_config_backend(config_path, backend: str):
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    data["workspace"]["backend"] = backend
    config_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _write_watch_config(config_path, **updates):
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    data.setdefault("watch", {}).update(updates)
    config_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _write_two_robot_config(config_path, *, reverse_ids: bool = False):
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    arm_config = data["robots"]["arm_1"]
    rover_config = {
        "driver": "mock_rover",
        "config": {"start_pose": {"x": 2.0, "y": 3.0}, "battery": 88.0},
    }
    if reverse_ids:
        data["robots"] = {"z_arm": arm_config, "a_rover": rover_config}
    else:
        data["robots"] = {"arm_1": arm_config, "rover_1": rover_config}
    config_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _feedback_events(store, event: str):
    return [
        item
        for item in store.read_feedback()["history"]
        if item.get("event") == event
    ]


def _expectation_events(store):
    return _feedback_events(store, "expectation_check")


def test_watch_runtime_step_executes_action(tmp_path):
    config_path = write_default_config(tmp_path / "physical-agent.yaml", overwrite=True)
    _write_config_backend(config_path, "sqlite")
    runtime = WatchRuntime(config_path)
    asyncio.run(runtime.setup())
    store = open_state_store(config_path=config_path)
    assert store.read_capabilities()["robots"]["arm_1"]["driver"] == "mock_arm"
    store.write_actions(
        [
            Action(
                id="act_001",
                robot="arm_1",
                capability="pick",
                params={"object_id": "red_block"},
            )
        ],
        [],
        [],
    )
    count = asyncio.run(runtime.step(setup=False))
    assert count == 1
    actions = store.read_actions()
    assert actions["pending"] == []
    assert actions["completed"][0].id == "act_001"
    assert store.read_feedback()["latest"]["status"] == "completed"


def test_watch_runtime_records_verified_expectation_after_world_update(tmp_path):
    config_path = write_default_config(tmp_path / "physical-agent.yaml", overwrite=True)
    _write_config_backend(config_path, "sqlite")
    runtime = WatchRuntime(config_path)
    asyncio.run(runtime.setup())
    store = open_state_store(config_path=config_path)
    store.write_actions(
        [
            Action(
                id="act_pick",
                robot="arm_1",
                capability="pick",
                params={"object_id": "red_block"},
            ),
            Action(
                id="act_place",
                robot="arm_1",
                capability="place",
                params={"target": "tray"},
                depends_on=["act_pick"],
                metadata={
                    "expected": [
                        {
                            "path": "world.objects.red_block.location",
                            "op": "eq",
                            "value": "tray",
                        },
                        {
                            "path": "objects.red_block.pose.x",
                            "op": "range",
                            "value": [-0.3, -0.1],
                        },
                    ]
                },
            ),
        ],
        [],
        [],
    )

    try:
        count = asyncio.run(runtime.step(setup=False))
    finally:
        asyncio.run(runtime.shutdown())

    assert count == 2
    events = _expectation_events(store)
    assert len(events) == 1
    event = events[0]
    assert event["action_id"] == "act_place"
    assert event["status"] == "verified"
    assert [check["status"] for check in event["checks"]] == ["verified", "verified"]
    assert store.read_world()["state"]["objects"]["red_block"]["location"] == "tray"


def test_watch_runtime_records_violated_expectation(tmp_path):
    config_path = write_default_config(tmp_path / "physical-agent.yaml", overwrite=True)
    _write_config_backend(config_path, "sqlite")
    runtime = WatchRuntime(config_path)
    asyncio.run(runtime.setup())
    store = open_state_store(config_path=config_path)
    store.write_actions(
        [
            Action(
                id="act_pick",
                robot="arm_1",
                capability="pick",
                params={"object_id": "red_block"},
            ),
            Action(
                id="act_place",
                robot="arm_1",
                capability="place",
                params={"target": "tray"},
                depends_on=["act_pick"],
                metadata={
                    "expected": [
                        {
                            "path": "objects.red_block.location",
                            "op": "eq",
                            "value": "table",
                        }
                    ]
                },
            ),
        ],
        [],
        [],
    )

    try:
        count = asyncio.run(runtime.step(setup=False))
    finally:
        asyncio.run(runtime.shutdown())

    assert count == 2
    event = _expectation_events(store)[0]
    assert event["status"] == "violated"
    assert event["checks"][0]["actual"] == "tray"
    assert "actual was" in event["message"]


def test_watch_runtime_records_skipped_expectation_for_bad_path(tmp_path):
    config_path = write_default_config(tmp_path / "physical-agent.yaml", overwrite=True)
    _write_config_backend(config_path, "sqlite")
    runtime = WatchRuntime(config_path)
    asyncio.run(runtime.setup())
    store = open_state_store(config_path=config_path)
    store.write_actions(
        [
            Action(
                id="act_observe_bad_path",
                robot="arm_1",
                capability="observe",
                params={},
                metadata={
                    "expected": [
                        {
                            "path": "objects.blue_block.location",
                            "op": "eq",
                            "value": "tray",
                        }
                    ]
                },
            )
        ],
        [],
        [],
    )

    try:
        count = asyncio.run(runtime.step(setup=False))
    finally:
        asyncio.run(runtime.shutdown())

    assert count == 1
    event = _expectation_events(store)[0]
    assert event["status"] == "skipped"
    assert "could not be resolved" in event["message"]


def test_watch_runtime_records_skipped_expectation_for_driver_failure(tmp_path):
    config_path = write_default_config(tmp_path / "physical-agent.yaml", overwrite=True)
    _write_config_backend(config_path, "sqlite")
    runtime = WatchRuntime(config_path)
    asyncio.run(runtime.setup())
    store = open_state_store(config_path=config_path)
    store.write_actions(
        [
            Action(
                id="act_place_without_pick",
                robot="arm_1",
                capability="place",
                params={"target": "tray"},
                metadata={
                    "expected": [
                        {
                            "path": "objects.red_block.location",
                            "op": "eq",
                            "value": "tray",
                        }
                    ]
                },
            )
        ],
        [],
        [],
    )

    try:
        count = asyncio.run(runtime.step(setup=False))
    finally:
        asyncio.run(runtime.shutdown())

    assert count == 1
    event = _expectation_events(store)[0]
    assert event["status"] == "skipped"
    assert "Action failed before expectation check" in event["message"]


def test_watch_runtime_does_not_check_expectation_when_safety_gate_rejects(tmp_path, monkeypatch):
    config_path = write_default_config(tmp_path / "physical-agent.yaml", overwrite=True)
    _write_config_backend(config_path, "sqlite")

    runtime = WatchRuntime(config_path)
    asyncio.run(runtime.setup())
    store = open_state_store(config_path=config_path)
    store.append_pending_action(
        Action(
            id="act_gate_expected",
            robot="arm_1",
            capability="move_to",
            params={"x": 99.0, "y": 0.0, "z": 0.4},
            metadata={
                "expected": [
                    {
                        "path": "robots.arm_1.pose.x",
                        "op": "eq",
                        "value": 99.0,
                    }
                ]
            },
        )
    )

    async def fail_execute(action):
        raise AssertionError("SafetyGate must reject before driver.execute")

    monkeypatch.setattr(runtime.loaded_drivers["arm_1"].driver, "execute", fail_execute)

    try:
        count = asyncio.run(runtime.step(setup=False))
    finally:
        asyncio.run(runtime.shutdown())

    assert count == 0
    assert _expectation_events(store) == []
    feedback = store.read_feedback()["latest"]
    assert feedback["action_id"] == "act_gate_expected"
    assert feedback["status"] == "failed"


def test_update_world_observes_robots_concurrently(tmp_path, monkeypatch):
    config_path = write_default_config(tmp_path / "physical-agent.yaml", overwrite=True)
    _write_config_backend(config_path, "sqlite")
    _write_two_robot_config(config_path)
    runtime = WatchRuntime(config_path)
    asyncio.run(runtime.setup())
    started: list[str] = []

    async def run_update():
        release = asyncio.Event()

        async def observe(robot_id):
            started.append(robot_id)
            if len(started) == 2:
                release.set()
            await release.wait()
            return Observation(
                summary=f"{robot_id} observed",
                robots={robot_id: {"status": "fresh"}},
            )

        monkeypatch.setattr(
            runtime.loaded_drivers["arm_1"].driver,
            "observe",
            lambda: observe("arm_1"),
        )
        monkeypatch.setattr(
            runtime.loaded_drivers["rover_1"].driver,
            "observe",
            lambda: observe("rover_1"),
        )
        return await asyncio.wait_for(runtime.update_world(), timeout=0.5)

    try:
        world = asyncio.run(run_update())
    finally:
        asyncio.run(runtime.shutdown())

    assert started == ["arm_1", "rover_1"]
    assert list(world.robots) == ["arm_1", "rover_1"]


def test_update_world_merges_observations_in_stable_robot_order(tmp_path, monkeypatch):
    config_path = write_default_config(tmp_path / "physical-agent.yaml", overwrite=True)
    _write_config_backend(config_path, "sqlite")
    _write_two_robot_config(config_path, reverse_ids=True)
    runtime = WatchRuntime(config_path)
    asyncio.run(runtime.setup())

    async def observe_z_arm():
        await asyncio.sleep(0.02)
        return Observation(
            summary="z arm",
            robots={"z_arm": {"status": "fresh"}},
            objects={"z_block": {"type": "block"}},
        )

    async def observe_a_rover():
        return Observation(
            summary="a rover",
            robots={"a_rover": {"status": "fresh"}},
            objects={"a_crate": {"type": "crate"}},
        )

    monkeypatch.setattr(runtime.loaded_drivers["z_arm"].driver, "observe", observe_z_arm)
    monkeypatch.setattr(runtime.loaded_drivers["a_rover"].driver, "observe", observe_a_rover)

    try:
        snapshots = []
        for _ in range(3):
            world = asyncio.run(runtime.update_world())
            snapshots.append(json.dumps(world.model_dump(mode="json"), ensure_ascii=False))
    finally:
        asyncio.run(runtime.shutdown())

    assert len(set(snapshots)) == 1
    assert list(world.robots) == ["a_rover", "z_arm"]
    assert list(world.objects) == ["a_crate", "z_block"]


def test_update_world_isolates_single_robot_observe_exception(tmp_path, monkeypatch):
    config_path = write_default_config(tmp_path / "physical-agent.yaml", overwrite=True)
    _write_config_backend(config_path, "sqlite")
    _write_two_robot_config(config_path)
    runtime = WatchRuntime(config_path)
    asyncio.run(runtime.setup())
    store = open_state_store(config_path=config_path)
    previous_arm_state = store.read_world()["state"]["robots"]["arm_1"]

    async def fail_arm():
        raise RuntimeError("camera offline")

    async def observe_rover():
        return Observation(
            summary="rover fresh",
            robots={"rover_1": {"status": "fresh"}},
            objects={"beacon": {"type": "marker"}},
        )

    monkeypatch.setattr(runtime.loaded_drivers["arm_1"].driver, "observe", fail_arm)
    monkeypatch.setattr(runtime.loaded_drivers["rover_1"].driver, "observe", observe_rover)

    try:
        world = asyncio.run(runtime.update_world())
    finally:
        asyncio.run(runtime.shutdown())

    assert world.robots["arm_1"] == previous_arm_state
    assert world.robots["rover_1"] == {"status": "fresh"}
    assert world.objects["beacon"] == {"type": "marker"}
    with sqlite3.connect(store.db_path) as conn:
        log_message = conn.execute(
            """
            SELECT message
            FROM log_entries
            WHERE actor = 'watch' AND message LIKE ?
            ORDER BY id DESC
            LIMIT 1
            """,
            ("%Skipped observation for `arm_1`%",),
        ).fetchone()[0]
    assert "RuntimeError" in log_message
    assert "camera offline" in log_message


def test_watch_runtime_driver_exception_cancels_sqlite_action(tmp_path, monkeypatch):
    config_path = write_default_config(tmp_path / "physical-agent.yaml", overwrite=True)
    _write_config_backend(config_path, "sqlite")

    runtime = WatchRuntime(config_path)
    asyncio.run(runtime.setup())
    store = open_state_store(config_path=config_path)
    store.write_actions(
        [
            Action(
                id="act_boom",
                robot="arm_1",
                capability="pick",
                params={"object_id": "red_block"},
            )
        ],
        [],
        [],
    )

    async def fail_execute(action):
        raise RuntimeError("boom")

    monkeypatch.setattr(runtime.loaded_drivers["arm_1"].driver, "execute", fail_execute)

    try:
        count = asyncio.run(runtime.step(setup=False))
    finally:
        asyncio.run(runtime.shutdown())

    assert count == 1
    actions = store.read_actions()
    assert actions["pending"] == []
    assert actions["completed"] == []
    assert [action.id for action in actions["cancelled"]] == ["act_boom"]
    feedback = store.read_feedback()
    assert feedback["latest"]["status"] == "failed"
    assert feedback["latest"]["action_id"] == "act_boom"
    assert "boom" in feedback["latest"]["message"]
    with sqlite3.connect(store.db_path) as conn:
        row = conn.execute(
            "SELECT status, claimed_at, claim_owner FROM actions WHERE id = ?",
            ("act_boom",),
        ).fetchone()
        log_message = conn.execute(
            """
            SELECT message
            FROM log_entries
            WHERE actor = 'watch' AND message LIKE ?
            ORDER BY id DESC
            LIMIT 1
            """,
            ("Action `act_boom` failed%",),
        ).fetchone()[0]
    assert row == ("cancelled", None, None)
    assert "Action `act_boom` failed" in log_message
    assert "boom" in log_message


def test_watch_runtime_reconnecting_execute_fails_fast_with_feedback(tmp_path, monkeypatch):
    config_path = write_default_config(tmp_path / "physical-agent.yaml", overwrite=True)
    _write_config_backend(config_path, "sqlite")
    runtime = WatchRuntime(config_path)
    asyncio.run(runtime.setup())
    store = open_state_store(config_path=config_path)
    store.write_actions(
        [
            Action(
                id="act_reconnecting",
                robot="arm_1",
                capability="pick",
                params={"object_id": "red_block"},
            )
        ],
        [],
        [],
    )

    async def fail_fast_execute(action):
        raise TransportReconnecting("transport reconnecting")

    monkeypatch.setattr(runtime.loaded_drivers["arm_1"].driver, "execute", fail_fast_execute)

    try:
        count = asyncio.run(runtime.step(setup=False))
    finally:
        asyncio.run(runtime.shutdown())

    assert count == 1
    actions = store.read_actions()
    assert actions["pending"] == []
    assert [action.id for action in actions["cancelled"]] == ["act_reconnecting"]
    feedback = store.read_feedback()["latest"]
    assert feedback["status"] == "failed"
    assert "failed fast" in feedback["message"]
    assert "not queued" in feedback["message"]
    assert feedback["result"]["error_type"] == "TransportReconnecting"


def test_watch_runtime_disconnected_during_execution_marks_unknown_failed(
    tmp_path,
    monkeypatch,
):
    config_path = write_default_config(tmp_path / "physical-agent.yaml", overwrite=True)
    _write_config_backend(config_path, "sqlite")
    runtime = WatchRuntime(config_path)
    asyncio.run(runtime.setup())
    store = open_state_store(config_path=config_path)
    store.write_actions(
        [
            Action(
                id="act_disconnect_mid_execute",
                robot="arm_1",
                capability="pick",
                params={"object_id": "red_block"},
            )
        ],
        [],
        [],
    )

    async def disconnect_mid_execute(action):
        raise TransportClosedError("WebSocket connection closed by peer")

    monkeypatch.setattr(
        runtime.loaded_drivers["arm_1"].driver,
        "execute",
        disconnect_mid_execute,
    )

    try:
        count = asyncio.run(runtime.step(setup=False))
    finally:
        asyncio.run(runtime.shutdown())

    assert count == 1
    actions = store.read_actions()
    assert actions["pending"] == []
    assert actions["completed"] == []
    assert [action.id for action in actions["cancelled"]] == ["act_disconnect_mid_execute"]
    feedback = store.read_feedback()["latest"]
    assert feedback["status"] == "failed"
    assert "execution state unknown" in feedback["message"]
    assert "not be retried automatically" in feedback["message"]


def test_watch_runtime_reconnect_exhausted_when_action_attempted(tmp_path, monkeypatch):
    config_path = write_default_config(tmp_path / "physical-agent.yaml", overwrite=True)
    _write_config_backend(config_path, "sqlite")
    runtime = WatchRuntime(config_path)
    asyncio.run(runtime.setup())
    store = open_state_store(config_path=config_path)
    store.write_actions(
        [
            Action(
                id="act_reconnect_exhausted",
                robot="arm_1",
                capability="pick",
                params={"object_id": "red_block"},
            )
        ],
        [],
        [],
    )

    async def reconnect_exhausted(action):
        raise TransportReconnectFailed("WebSocket reconnect failed after 4 attempts")

    monkeypatch.setattr(runtime.loaded_drivers["arm_1"].driver, "execute", reconnect_exhausted)

    try:
        count = asyncio.run(runtime.step(setup=False))
    finally:
        asyncio.run(runtime.shutdown())

    assert count == 1
    assert store.read_actions()["pending"] == []
    feedback = store.read_feedback()["latest"]
    assert feedback["status"] == "failed"
    assert "reconnect exhausted" in feedback["message"]
    assert "not queued" in feedback["message"]


def test_watch_runtime_gate_rejects_direct_bad_proposal_before_driver(tmp_path, monkeypatch):
    config_path = write_default_config(tmp_path / "physical-agent.yaml", overwrite=True)
    _write_config_backend(config_path, "sqlite")

    runtime = WatchRuntime(config_path)
    asyncio.run(runtime.setup())
    store = open_state_store(config_path=config_path)
    store.append_pending_action(
        Action(
            id="act_gate_direct",
            robot="arm_1",
            capability="move_to",
            params={"x": 99.0, "y": 0.0, "z": 0.4},
            metadata={"source": "f0_gate_direct"},
        )
    )

    async def fail_execute(action):
        raise AssertionError("SafetyGate must reject before driver.execute")

    monkeypatch.setattr(runtime.loaded_drivers["arm_1"].driver, "execute", fail_execute)

    try:
        count = asyncio.run(runtime.step(setup=False))
    finally:
        asyncio.run(runtime.shutdown())

    assert count == 0
    actions = store.read_actions()
    assert actions["pending"] == []
    assert actions["cancelled"][0].id == "act_gate_direct"
    assert actions["cancelled"][0].metadata["source"] == "f0_gate_direct"
    feedback = store.read_feedback()["latest"]
    assert feedback["action_id"] == "act_gate_direct"
    assert feedback["status"] == "failed"
    assert "Invalid params for move_to" in feedback["message"]


def test_watch_runtime_step_calls_driver_heartbeat(tmp_path, monkeypatch):
    config_path = write_default_config(tmp_path / "physical-agent.yaml", overwrite=True)
    _write_config_backend(config_path, "sqlite")
    runtime = WatchRuntime(config_path)
    asyncio.run(runtime.setup())

    calls = []

    async def heartbeat():
        calls.append("heartbeat")

    monkeypatch.setattr(runtime.loaded_drivers["arm_1"].driver, "heartbeat", heartbeat)

    try:
        count = asyncio.run(runtime.step(setup=False))
    finally:
        asyncio.run(runtime.shutdown())

    assert count == 0
    assert calls == ["heartbeat"]


def test_watch_runtime_heartbeat_failure_is_audited(tmp_path, monkeypatch):
    config_path = write_default_config(tmp_path / "physical-agent.yaml", overwrite=True)
    _write_config_backend(config_path, "sqlite")
    runtime = WatchRuntime(config_path)
    asyncio.run(runtime.setup())
    store = open_state_store(config_path=config_path)

    async def heartbeat():
        raise RuntimeError("pulse lost")

    monkeypatch.setattr(runtime.loaded_drivers["arm_1"].driver, "heartbeat", heartbeat)

    try:
        count = asyncio.run(runtime.step(setup=False))
    finally:
        asyncio.run(runtime.shutdown())

    assert count == 0
    feedback = store.read_feedback()
    latest = feedback["latest"]
    assert latest["event"] == "driver_heartbeat"
    assert latest["robot_id"] == "arm_1"
    assert latest["result"]["error_type"] == "RuntimeError"
    assert latest["result"]["error_message"] == "pulse lost"
    assert "Driver heartbeat failed" in latest["message"]
    assert "arm_1" in latest["message"]

    with sqlite3.connect(store.db_path) as conn:
        log_message = conn.execute(
            """
            SELECT message
            FROM log_entries
            WHERE actor = 'watch' AND message LIKE ?
            ORDER BY id DESC
            LIMIT 1
            """,
            ("%Driver heartbeat failed%",),
        ).fetchone()[0]
    assert "RuntimeError" in log_message
    assert "pulse lost" in log_message


def test_watch_runtime_heartbeat_failure_count_increments_without_early_halt(
    tmp_path,
    monkeypatch,
):
    config_path = write_default_config(tmp_path / "physical-agent.yaml", overwrite=True)
    _write_config_backend(config_path, "sqlite")
    _write_watch_config(
        config_path,
        halt_on_shutdown=False,
        heartbeat_failure_threshold=3,
    )
    runtime = WatchRuntime(config_path)
    asyncio.run(runtime.setup())
    store = open_state_store(config_path=config_path)
    halt_calls = []

    async def heartbeat():
        raise RuntimeError("pulse lost")

    async def halt():
        halt_calls.append("halt")

    monkeypatch.setattr(runtime.loaded_drivers["arm_1"].driver, "heartbeat", heartbeat)
    monkeypatch.setattr(runtime.loaded_drivers["arm_1"].driver, "halt", halt)

    try:
        assert asyncio.run(runtime.step(setup=False)) == 0
        assert asyncio.run(runtime.step(setup=False)) == 0
    finally:
        asyncio.run(runtime.shutdown())

    assert runtime._heartbeat_failure_counts["arm_1"] == 2
    assert halt_calls == []
    heartbeat_events = _feedback_events(store, "driver_heartbeat")
    assert [item["result"]["failure_count"] for item in heartbeat_events] == [1, 2]
    assert _feedback_events(store, "driver_watchdog_halt") == []


def test_watch_runtime_watchdog_halt_triggers_once_at_threshold(
    tmp_path,
    monkeypatch,
):
    config_path = write_default_config(tmp_path / "physical-agent.yaml", overwrite=True)
    _write_config_backend(config_path, "sqlite")
    _write_watch_config(
        config_path,
        halt_on_shutdown=False,
        heartbeat_failure_threshold=2,
    )
    runtime = WatchRuntime(config_path)
    asyncio.run(runtime.setup())
    store = open_state_store(config_path=config_path)
    halt_calls = []

    async def heartbeat():
        raise RuntimeError("pulse lost")

    async def halt():
        halt_calls.append("halt")

    monkeypatch.setattr(runtime.loaded_drivers["arm_1"].driver, "heartbeat", heartbeat)
    monkeypatch.setattr(runtime.loaded_drivers["arm_1"].driver, "halt", halt)

    try:
        assert asyncio.run(runtime.step(setup=False)) == 0
        assert halt_calls == []
        assert asyncio.run(runtime.step(setup=False)) == 0
        assert halt_calls == ["halt"]
        latest = store.read_feedback()["latest"]
        assert latest["event"] == "driver_watchdog_halt"
        assert latest["robot_id"] == "arm_1"
        assert latest["failure_count"] == 2
        assert latest["threshold"] == 2
        assert latest["halt_status"] == "completed"
        assert latest["result"]["heartbeat_error_message"] == "pulse lost"

        assert asyncio.run(runtime.step(setup=False)) == 0
    finally:
        asyncio.run(runtime.shutdown())

    assert halt_calls == ["halt"]
    assert runtime._heartbeat_failure_counts["arm_1"] == 3
    assert len(_feedback_events(store, "driver_watchdog_halt")) == 1
    with sqlite3.connect(store.db_path) as conn:
        log_message = conn.execute(
            """
            SELECT message
            FROM log_entries
            WHERE actor = 'watch' AND message LIKE ?
            ORDER BY id DESC
            LIMIT 1
            """,
            ("%Heartbeat watchdog threshold reached%",),
        ).fetchone()[0]
    assert "halt_status=completed" in log_message


def test_watch_runtime_heartbeat_recovery_resets_count_and_audits(
    tmp_path,
    monkeypatch,
):
    config_path = write_default_config(tmp_path / "physical-agent.yaml", overwrite=True)
    _write_config_backend(config_path, "sqlite")
    _write_watch_config(
        config_path,
        halt_on_shutdown=False,
        heartbeat_failure_threshold=2,
    )
    runtime = WatchRuntime(config_path)
    asyncio.run(runtime.setup())
    store = open_state_store(config_path=config_path)
    heartbeat_calls = 0
    halt_calls = []

    async def heartbeat():
        nonlocal heartbeat_calls
        heartbeat_calls += 1
        if heartbeat_calls in {1, 2, 4, 5}:
            raise RuntimeError("pulse lost")

    async def halt():
        halt_calls.append("halt")

    monkeypatch.setattr(runtime.loaded_drivers["arm_1"].driver, "heartbeat", heartbeat)
    monkeypatch.setattr(runtime.loaded_drivers["arm_1"].driver, "halt", halt)

    try:
        asyncio.run(runtime.step(setup=False))
        asyncio.run(runtime.step(setup=False))
        assert halt_calls == ["halt"]

        asyncio.run(runtime.step(setup=False))
        latest = store.read_feedback()["latest"]
        assert latest["event"] == "driver_heartbeat_recovered"
        assert latest["robot_id"] == "arm_1"
        assert latest["failure_count"] == 2
        assert runtime._heartbeat_failure_counts["arm_1"] == 0
        assert "arm_1" not in runtime._watchdog_halted_robots

        asyncio.run(runtime.step(setup=False))
        asyncio.run(runtime.step(setup=False))
    finally:
        asyncio.run(runtime.shutdown())

    assert halt_calls == ["halt", "halt"]
    assert len(_feedback_events(store, "driver_heartbeat_recovered")) == 1
    assert len(_feedback_events(store, "driver_watchdog_halt")) == 2


def test_watch_runtime_watchdog_halt_disabled_still_audits_threshold(
    tmp_path,
    monkeypatch,
):
    config_path = write_default_config(tmp_path / "physical-agent.yaml", overwrite=True)
    _write_config_backend(config_path, "sqlite")
    _write_watch_config(
        config_path,
        halt_on_shutdown=False,
        heartbeat_failure_threshold=1,
        halt_on_heartbeat_failure=False,
    )
    runtime = WatchRuntime(config_path)
    asyncio.run(runtime.setup())
    store = open_state_store(config_path=config_path)
    halt_calls = []

    async def heartbeat():
        raise RuntimeError("pulse lost")

    async def halt():
        halt_calls.append("halt")

    monkeypatch.setattr(runtime.loaded_drivers["arm_1"].driver, "heartbeat", heartbeat)
    monkeypatch.setattr(runtime.loaded_drivers["arm_1"].driver, "halt", halt)

    try:
        asyncio.run(runtime.step(setup=False))
        latest = store.read_feedback()["latest"]
        assert latest["event"] == "driver_watchdog_halt"
        assert latest["halt_status"] == "disabled"

        asyncio.run(runtime.step(setup=False))
    finally:
        asyncio.run(runtime.shutdown())

    assert halt_calls == []
    assert len(_feedback_events(store, "driver_watchdog_halt")) == 1


def test_watch_runtime_watchdog_halt_failure_is_audited_and_watch_continues(
    tmp_path,
    monkeypatch,
):
    config_path = write_default_config(tmp_path / "physical-agent.yaml", overwrite=True)
    _write_config_backend(config_path, "sqlite")
    _write_watch_config(
        config_path,
        halt_on_shutdown=False,
        heartbeat_failure_threshold=1,
    )
    runtime = WatchRuntime(config_path)
    asyncio.run(runtime.setup())
    store = open_state_store(config_path=config_path)
    halt_calls = []

    async def heartbeat():
        raise RuntimeError("pulse lost")

    async def halt():
        halt_calls.append("halt")
        raise RuntimeError("halt jammed")

    monkeypatch.setattr(runtime.loaded_drivers["arm_1"].driver, "heartbeat", heartbeat)
    monkeypatch.setattr(runtime.loaded_drivers["arm_1"].driver, "halt", halt)

    try:
        assert asyncio.run(runtime.step(setup=False)) == 0
        latest = store.read_feedback()["latest"]
        assert latest["event"] == "driver_watchdog_halt"
        assert latest["halt_status"] == "failed"
        assert latest["result"]["error_type"] == "RuntimeError"
        assert latest["result"]["error_message"] == "halt jammed"
        assert latest["result"]["heartbeat_error_message"] == "pulse lost"

        assert asyncio.run(runtime.step(setup=False)) == 0
    finally:
        asyncio.run(runtime.shutdown())

    assert halt_calls == ["halt"]
    assert runtime._heartbeat_failure_counts["arm_1"] == 2
    assert len(_feedback_events(store, "driver_watchdog_halt")) == 1


def test_watch_runtime_heartbeat_disabled_skips_heartbeat_and_watchdog(
    tmp_path,
    monkeypatch,
):
    config_path = write_default_config(tmp_path / "physical-agent.yaml", overwrite=True)
    _write_config_backend(config_path, "sqlite")
    _write_watch_config(
        config_path,
        heartbeat_enabled=False,
        halt_on_shutdown=False,
        heartbeat_failure_threshold=1,
    )
    runtime = WatchRuntime(config_path)
    asyncio.run(runtime.setup())
    store = open_state_store(config_path=config_path)
    calls = []

    async def heartbeat():
        calls.append("heartbeat")
        raise RuntimeError("pulse lost")

    async def halt():
        calls.append("halt")

    monkeypatch.setattr(runtime.loaded_drivers["arm_1"].driver, "heartbeat", heartbeat)
    monkeypatch.setattr(runtime.loaded_drivers["arm_1"].driver, "halt", halt)

    try:
        assert asyncio.run(runtime.step(setup=False)) == 0
    finally:
        asyncio.run(runtime.shutdown())

    assert calls == []
    assert runtime._heartbeat_failure_counts["arm_1"] == 0
    assert _feedback_events(store, "driver_heartbeat") == []
    assert _feedback_events(store, "driver_watchdog_halt") == []


def test_watch_config_rejects_non_positive_heartbeat_failure_threshold(tmp_path):
    config_path = write_default_config(tmp_path / "physical-agent.yaml", overwrite=True)
    _write_watch_config(config_path, heartbeat_failure_threshold=0)

    with pytest.raises(ValidationError):
        load_config(config_path)


def test_watch_config_observe_interval_defaults_to_tick_ms(tmp_path):
    config_path = write_default_config(tmp_path / "physical-agent.yaml", overwrite=True)
    _write_watch_config(config_path, tick_ms=123, observe_interval_ms=None)

    runtime = WatchRuntime(config_path)
    runtime.config = load_config(config_path)

    assert runtime.config.watch.observe_interval_ms is None
    assert runtime._observe_interval_ms() == 123


@pytest.mark.parametrize("observe_interval_ms", [0, -1])
def test_watch_config_rejects_non_positive_observe_interval(tmp_path, observe_interval_ms):
    config_path = write_default_config(tmp_path / "physical-agent.yaml", overwrite=True)
    _write_watch_config(config_path, observe_interval_ms=observe_interval_ms)

    with pytest.raises(ValidationError):
        load_config(config_path)


def test_watch_tick_decouples_idle_observe_from_action_claim(tmp_path, monkeypatch):
    config_path = write_default_config(tmp_path / "physical-agent.yaml", overwrite=True)
    _write_config_backend(config_path, "sqlite")
    _write_watch_config(
        config_path,
        tick_ms=10,
        observe_interval_ms=100,
        heartbeat_enabled=False,
        halt_on_shutdown=False,
    )
    runtime = WatchRuntime(config_path)
    asyncio.run(runtime.setup())
    store = open_state_store(config_path=config_path)
    now = {"value": 0.0}
    observe_calls: list[float] = []

    def monotonic():
        return now["value"]

    async def observe():
        observe_calls.append(now["value"])
        return Observation(
            summary="fresh arm",
            robots={"arm_1": {"status": "fresh"}},
        )

    monkeypatch.setattr(runtime, "_monotonic", monotonic)
    monkeypatch.setattr(runtime.loaded_drivers["arm_1"].driver, "observe", observe)

    try:
        assert asyncio.run(runtime.tick()) == 0
        assert observe_calls == [0.0]

        now["value"] = 0.01
        assert asyncio.run(runtime.tick()) == 0
        assert observe_calls == [0.0]

        store.append_pending_action(
            Action(
                id="act_move_despite_idle_interval",
                robot="arm_1",
                capability="move_to",
                params={"x": 0.1, "y": 0.0, "z": 0.4},
            )
        )
        now["value"] = 0.02
        assert asyncio.run(runtime.tick()) == 1
        assert observe_calls == [0.0, 0.02]
        assert store.read_actions()["completed"][0].id == "act_move_despite_idle_interval"

        now["value"] = 0.05
        assert asyncio.run(runtime.tick()) == 0
        assert observe_calls == [0.0, 0.02]

        now["value"] = 0.11
        assert asyncio.run(runtime.tick()) == 0
        assert observe_calls == [0.0, 0.02, 0.11]
    finally:
        asyncio.run(runtime.shutdown())


def test_watch_tick_post_action_world_refresh_still_feeds_expectation_check(tmp_path, monkeypatch):
    config_path = write_default_config(tmp_path / "physical-agent.yaml", overwrite=True)
    _write_config_backend(config_path, "sqlite")
    _write_watch_config(
        config_path,
        tick_ms=10,
        observe_interval_ms=10_000,
        heartbeat_enabled=False,
        halt_on_shutdown=False,
    )
    runtime = WatchRuntime(config_path)
    asyncio.run(runtime.setup())
    monkeypatch.setattr(runtime, "_monotonic", lambda: 0.01)
    runtime._last_idle_observe_at = 0.0
    store = open_state_store(config_path=config_path)
    store.write_actions(
        [
            Action(
                id="act_pick_for_tick_expected",
                robot="arm_1",
                capability="pick",
                params={"object_id": "red_block"},
            ),
            Action(
                id="act_place_for_tick_expected",
                robot="arm_1",
                capability="place",
                params={"target": "tray"},
                depends_on=["act_pick_for_tick_expected"],
                metadata={
                    "expected": [
                        {
                            "path": "objects.red_block.location",
                            "op": "eq",
                            "value": "tray",
                        }
                    ]
                },
            ),
        ],
        [],
        [],
    )

    try:
        assert asyncio.run(runtime.tick()) == 2
    finally:
        asyncio.run(runtime.shutdown())

    events = _expectation_events(store)
    assert len(events) == 1
    assert events[0]["action_id"] == "act_place_for_tick_expected"
    assert events[0]["status"] == "verified"
    assert store.read_world()["state"]["objects"]["red_block"]["location"] == "tray"


def test_watch_runtime_shutdown_calls_driver_halt(tmp_path, monkeypatch):
    config_path = write_default_config(tmp_path / "physical-agent.yaml", overwrite=True)
    _write_config_backend(config_path, "sqlite")
    runtime = WatchRuntime(config_path)
    asyncio.run(runtime.setup())

    calls = []

    async def halt():
        calls.append("halt")

    monkeypatch.setattr(runtime.loaded_drivers["arm_1"].driver, "halt", halt)

    asyncio.run(runtime.shutdown())

    assert calls == ["halt"]


def test_watch_runtime_halt_failure_is_audited_and_shutdown_completes(tmp_path, monkeypatch):
    config_path = write_default_config(tmp_path / "physical-agent.yaml", overwrite=True)
    _write_config_backend(config_path, "sqlite")
    runtime = WatchRuntime(config_path)
    asyncio.run(runtime.setup())
    store = open_state_store(config_path=config_path)

    async def halt():
        raise RuntimeError("halt jammed")

    monkeypatch.setattr(runtime.loaded_drivers["arm_1"].driver, "halt", halt)

    asyncio.run(runtime.shutdown())

    assert runtime.started is False
    feedback = store.read_feedback()
    latest = feedback["latest"]
    assert latest["event"] == "driver_halt"
    assert latest["robot_id"] == "arm_1"
    assert latest["result"]["error_type"] == "RuntimeError"
    assert latest["result"]["error_message"] == "halt jammed"
    assert "Driver halt failed" in latest["message"]

    with sqlite3.connect(store.db_path) as conn:
        log_message = conn.execute(
            """
            SELECT message
            FROM log_entries
            WHERE actor = 'watch' AND message LIKE ?
            ORDER BY id DESC
            LIMIT 1
            """,
            ("%Driver halt failed%",),
        ).fetchone()[0]
    assert "RuntimeError" in log_message
    assert "halt jammed" in log_message
