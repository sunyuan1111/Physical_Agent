from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any

from physical_agent.agent.chat_runtime import ChatRuntime
from physical_agent.agent.driver_coder import DriverCodingAgent
from physical_agent.agent.onboarding import HardwareIntegrationAssistant
from physical_agent.agent.runtime import AgentRuntime
from physical_agent.config import DEFAULT_CONFIG_NAME, load_config, write_default_config
from physical_agent.doctor import doctor_ok, run_doctor
from physical_agent.protocol.schemas import Action
from physical_agent.quickstart import setup_project
from physical_agent.state import open_state_store
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
                "runtime": _unknown_runtime_info(),
                "doctor": [check.as_dict() for check in run_doctor(self.config_path)],
            }

        config = load_config(self.config_path)
        runtime_info = _runtime_info(config)
        workspace = open_state_store(config, base_dir=self.config_path.parent)
        if not workspace.exists():
            return {
                "ready": False,
                "watch_started": self._watch_started,
                "message": "Workspace is missing. Click Setup Project.",
                "runtime": runtime_info,
                "doctor": [check.as_dict() for check in run_doctor(self.config_path)],
            }

        actions = workspace.read_actions()
        feedback = workspace.read_feedback()
        code_result = _latest_code_result(workspace.read_chat())
        return {
            "ready": True,
            "watch_started": self._watch_started,
            "message": "Ready.",
            "config_path": str(self.config_path),
            "workspace_path": str(workspace.path),
            "task": workspace.read_task(),
            "capabilities": workspace.read_capabilities(),
            "world": workspace.read_world(),
            "code_result": code_result,
            "runtime": runtime_info,
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
            state = self.state()
            if result.get("code_result") is not None:
                state = {**state, "code_result": result["code_result"]}
            return {
                "ok": True,
                "message": result["reply"],
                "result": _json_safe(result),
                "code_result": _json_safe(result.get("code_result")),
                "executed": executed,
                "state": state,
            }

    def integrate_hardware(
        self,
        source: str,
        *,
        output: str | None = None,
        name: str | None = None,
        llm: bool = False,
        model: str | None = None,
    ) -> dict[str, Any]:
        with self.lock:
            if not self.config_path.exists():
                write_default_config(self.config_path)
            config = load_config(self.config_path)
            open_state_store(config, base_dir=self.config_path.parent).initialize()
            if llm:
                result = DriverCodingAgent(
                    source,
                    output_dir=output or None,
                    name=name or None,
                    base_dir=self.config_path.parent,
                    model=model or None,
                ).generate()
                message = (
                    f"Generated LLM driver draft at {result.output_path}."
                    if result.llm_used
                    else f"Generated safe scaffold at {result.output_path}; LLM coding did not validate."
                )
                return {
                    "ok": True,
                    "message": message,
                    "result": _json_safe(result.model_dump(mode="json")),
                    "state": self.state(),
                }
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
        open_state_store(config, base_dir=self.config_path.parent).initialize()
        if self.watch_runtime is None or not self.watch_runtime.started:
            self.watch_runtime = WatchRuntime(self.config_path)
            asyncio.run(self.watch_runtime.setup())


def _dump_actions(actions: list[Action]) -> list[dict[str, Any]]:
    return [action.model_dump(mode="json") for action in actions]


def _unknown_runtime_info() -> dict[str, Any]:
    return {"mode": "unknown", "requires_confirmation": False, "drivers": []}


def _runtime_info(config: Any) -> dict[str, Any]:
    drivers = [
        {
            "robot_id": robot_id,
            "driver": robot.driver,
            "mode": "mock" if _is_mock_driver(robot.driver) else "hardware",
        }
        for robot_id, robot in config.robots.items()
    ]
    has_hardware = any(driver["mode"] == "hardware" for driver in drivers)
    mode = "hardware" if has_hardware else ("mock" if drivers else "unknown")
    return {
        "mode": mode,
        "requires_confirmation": bool(config.watch.require_human_approval or has_hardware),
        "drivers": drivers,
    }


def _is_mock_driver(driver_ref: str) -> bool:
    name = str(driver_ref).strip().replace("\\", "/").rstrip("/").split("/")[-1].lower()
    return name.startswith("mock_")


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


def _latest_code_result(chat: dict[str, Any]) -> dict[str, Any] | None:
    messages = chat.get("messages", [])
    for message in reversed(messages):
        metadata = None
        if hasattr(message, "metadata"):
            metadata = getattr(message, "metadata")
        elif isinstance(message, dict):
            metadata = message.get("metadata")
        if isinstance(metadata, dict) and metadata.get("code_result") is not None:
            return _json_safe(metadata["code_result"])
    return None
