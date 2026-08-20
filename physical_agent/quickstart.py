from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from physical_agent.agent.runtime import AgentRuntime
from physical_agent.config import DEFAULT_CONFIG_NAME, load_config, write_default_config
from physical_agent.doctor import doctor_ok, run_doctor
from physical_agent.state import open_state_store
from physical_agent.watch.runtime import WatchRuntime


def setup_project(
    config_path: str | Path = DEFAULT_CONFIG_NAME,
    *,
    force: bool = False,
    publish: bool = True,
    smoke_test: bool = False,
) -> dict[str, Any]:
    path = write_default_config(config_path, overwrite=force)
    config = load_config(path)
    workspace = open_state_store(config, base_dir=path.parent)
    workspace.initialize(overwrite=force)

    result: dict[str, Any] = {
        "config_path": str(path),
        "workspace_path": str(workspace.path),
        "published": False,
        "smoke_test": None,
    }

    runtime = WatchRuntime(path)
    if publish or smoke_test:
        asyncio.run(runtime.setup())
        result["published"] = True

    if smoke_test:
        agent = AgentRuntime(path)
        task_result = asyncio.run(
            agent.run_task(
                "pick the red block and place it on the tray",
                wait_for_feedback=False,
            )
        )
        executed = asyncio.run(runtime.step(setup=False))
        world = workspace.read_world()
        placed = world["state"]["objects"]["red_block"]["location"] == "tray"
        result["smoke_test"] = {
            "ok": bool(task_result["ok"] and executed == 2 and placed),
            "executed_actions": executed,
            "red_block_location": world["state"]["objects"]["red_block"]["location"],
        }

    if runtime.started:
        asyncio.run(runtime.shutdown())

    checks = run_doctor(path)
    result["doctor_ok"] = doctor_ok(checks)
    result["doctor"] = [check.as_dict() for check in checks]
    return result

