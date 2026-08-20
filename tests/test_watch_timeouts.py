from __future__ import annotations

import asyncio
from pathlib import Path

import yaml

from physical_agent.config import write_default_config
from physical_agent.protocol.schemas import Action
from physical_agent.state import open_state_store
from physical_agent.watch.runtime import WatchRuntime


def _write_config(tmp_path: Path, **watch_overrides: object) -> Path:
    config_path = write_default_config(tmp_path / "physical-agent.yaml", overwrite=True)
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    data["watch"].update(watch_overrides)
    config_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return config_path


async def _hang(*args, **kwargs):
    await asyncio.sleep(3600)


def _propose_observe(config_path: Path, action_id: str) -> None:
    store = open_state_store(config_path=config_path)
    store.append_pending_action(
        Action(
            id=action_id,
            robot="arm_1",
            capability="observe",
            params={},
            reason="timeout regression test",
        )
    )


def test_execute_timeout_fails_action_and_keeps_loop_alive(tmp_path):
    config_path = _write_config(tmp_path, action_timeout_s=0.1)
    watch = WatchRuntime(config_path)
    asyncio.run(watch.setup())
    driver = watch.loaded_drivers["arm_1"].driver

    halted: list[bool] = []
    original_execute = driver.execute

    async def record_halt(*args, **kwargs):
        halted.append(True)

    driver.execute = _hang
    driver.halt = record_halt
    _propose_observe(config_path, "act_hang_1")

    executed = asyncio.run(watch.step(setup=False))

    store = open_state_store(config_path=config_path)
    last = store.read_feedback()["history"][-1]
    assert executed == 1
    assert last["action_id"] == "act_hang_1"
    assert last["status"] == "failed"
    assert "timed out" in last["message"]
    # Unknown hardware state after timeout must trigger best-effort halt.
    assert halted
    cancelled_ids = {item.id for item in store.read_actions()["cancelled"]}
    assert "act_hang_1" in cancelled_ids

    # The loop must stay alive: a healthy action still executes afterwards.
    driver.execute = original_execute
    _propose_observe(config_path, "act_after_hang")
    executed = asyncio.run(watch.step(setup=False))
    assert executed == 1
    last = open_state_store(config_path=config_path).read_feedback()["history"][-1]
    assert last["action_id"] == "act_after_hang"
    assert last["status"] == "completed"


def test_observe_timeout_skips_driver_without_feedback_spam(tmp_path):
    config_path = _write_config(tmp_path, observe_timeout_s=0.1)
    watch = WatchRuntime(config_path)
    asyncio.run(watch.setup())
    driver = watch.loaded_drivers["arm_1"].driver
    store = open_state_store(config_path=config_path)
    feedback_before = len(store.read_feedback()["history"])

    driver.observe = _hang
    merged = asyncio.run(watch.update_world())

    assert merged is not None  # returned promptly instead of hanging
    store = open_state_store(config_path=config_path)
    # Log-only policy: no feedback entries for observe timeouts.
    assert len(store.read_feedback()["history"]) == feedback_before


def test_heartbeat_timeout_counts_toward_watchdog_halt(tmp_path):
    config_path = _write_config(
        tmp_path,
        heartbeat_timeout_s=0.1,
        heartbeat_failure_threshold=1,
        halt_on_heartbeat_failure=True,
    )
    watch = WatchRuntime(config_path)
    asyncio.run(watch.setup())
    driver = watch.loaded_drivers["arm_1"].driver
    driver.heartbeat = _hang

    asyncio.run(watch.step(setup=False))

    store = open_state_store(config_path=config_path)
    events = [
        item.get("event")
        for item in store.read_feedback()["history"]
        if item.get("event")
    ]
    assert "driver_heartbeat" in events
    assert "driver_watchdog_halt" in events


def test_shutdown_survives_hung_halt_and_disconnect(tmp_path):
    config_path = _write_config(tmp_path, halt_timeout_s=0.1)
    watch = WatchRuntime(config_path)
    asyncio.run(watch.setup())
    driver = watch.loaded_drivers["arm_1"].driver
    driver.halt = _hang
    driver.disconnect = _hang

    asyncio.run(watch.shutdown())  # must return promptly instead of hanging

    store = open_state_store(config_path=config_path)
    halt_failures = [
        item
        for item in store.read_feedback()["history"]
        if item.get("event") == "driver_halt"
    ]
    assert halt_failures
    assert "timed out" in halt_failures[-1]["message"]
