from __future__ import annotations

import re
from pprint import pformat
from pathlib import Path
from typing import Any
from textwrap import dedent, indent


def class_name_from_driver_name(name: str) -> str:
    parts = re.split(r"[^0-9A-Za-z]+", name)
    filtered = [part for part in parts if part and part.lower() != "driver"]
    if not filtered:
        filtered = [name]
    return "".join(part[:1].upper() + part[1:] for part in filtered) + "Driver"


def manifest_template(
    name: str,
    class_name: str | None = None,
    *,
    description: str = "Local Physical Agent driver.",
    kind: str = "generic",
    supports_simulation: bool = True,
    config_schema: dict[str, Any] | None = None,
) -> str:
    class_name = class_name or class_name_from_driver_name(name)
    schema = config_schema or {"type": "object", "properties": {}, "additionalProperties": True}
    return f"""schema: physical-agent/driver/v1

name: {name}
version: 0.1.0
description: {description}

entrypoint:
  module: driver
  class: {class_name}

robot:
  kind: {kind}
  supports_simulation: {str(supports_simulation).lower()}

config_schema:
{_dump_yaml_block(schema, indent=2)}

dependencies:
  python: []

capability_contract:
  source: runtime
"""


def driver_template(
    name: str,
    class_name: str | None = None,
    *,
    capabilities: list[dict[str, Any]] | None = None,
) -> str:
    class_name = class_name or class_name_from_driver_name(name)
    capabilities = capabilities or [
        {
            "name": "observe",
            "description": "Observe the current device state.",
            "params_schema": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            "notes": "Replace the body of observe() with the real SDK read path.",
        }
    ]
    capability_entries = ",\n                ".join(
        _render_capability_entry(capability) for capability in capabilities
    )
    execute_branches = "\n\n".join(_render_execute_branch(capability) for capability in capabilities)
    template = f'''
from physical_agent.drivers import (
    Action,
    ActionResult,
    Capability,
    DriverContext,
    HealthStatus,
    Observation,
    PhysicalDriver,
)


class {class_name}(PhysicalDriver):
    def __init__(self, context: DriverContext):
        super().__init__(context)
        self.config = context.config
        self.mode = str(self.config.get("mode", "mock"))
        self.state = dict(self.config.get("mock_state") or {{}})
        self.pose = dict(self.state.get("pose") or {{"x": 0.0, "y": 0.0, "z": 0.0}})
        self.holding = self.state.get("holding")
        self.objects = dict(self.state.get("objects") or {{}})
        self.messages: list[str] = []
        self.light = dict(self.state.get("light") or {{"r": 0, "g": 0, "b": 0}})
        self.connected = False

    async def connect(self) -> None:
        # Keep mock mode runnable; place real SDK connection setup here.
        self.connected = True

    async def disconnect(self) -> None:
        self.connected = False

    async def health(self) -> HealthStatus:
        return HealthStatus(
            ok=self.connected,
            message="connected" if self.connected else "not connected",
        )

    async def observe(self) -> Observation:
        return Observation(
            summary=f"{{self.context.robot_id}} is {{'connected' if self.connected else 'offline'}} in {{self.mode}} mode.",
            robots={{
                self.context.robot_id: {{
                    "status": "idle" if self.connected else "offline",
                    "mode": self.mode,
                    "pose": self.pose,
                    "holding": self.holding,
                    "light": self.light,
                }}
            }},
            objects=self.objects,
            raw={{"messages": list(self.messages)}},
        )

    def capabilities(self) -> list[Capability]:
        return [
{capability_entries}
        ]

    async def execute(self, action: Action) -> ActionResult:
{execute_branches}
        return ActionResult(
            status="failed",
            message=f"Unsupported capability: {{action.capability}}",
        )
'''
    return dedent(template).strip() + "\n"


def _render_capability_entry(capability: dict[str, Any]) -> str:
    params_schema = capability.get("params_schema") or {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }
    returns_schema = capability.get("returns_schema")
    return indent(
        f'''Capability(
    name={_python_literal(capability.get("name", "unknown"))},
    description={_python_literal(capability.get("description", ""))},
    params_schema={_python_literal(params_schema)},
    returns_schema={_python_literal(returns_schema) if returns_schema is not None else "None"},
    constraints={_python_literal(capability.get("constraints") or {})},
    requires_approval={repr(bool(capability.get("requires_approval", False)))},
    timeout_s={repr(capability.get("timeout_s"))},
)'''.rstrip(),
        " " * 12,
    )


def _render_execute_branch(capability: dict[str, Any]) -> str:
    name = capability.get("name", "unknown")
    note = capability.get("notes") or f"Implement {name} using the vendor SDK or service API."
    if name == "observe":
        return """        if action.capability == "observe":
            observation = await self.observe()
            return ActionResult(
                status="completed",
                message="Observation completed.",
                result={"observation": observation.model_dump(mode="json")},
            )"""
    if name == "move_to":
        return """        if action.capability == "move_to":
            self.pose["x"] = action.params["x"]
            self.pose["y"] = action.params["y"]
            if "z" in action.params:
                self.pose["z"] = action.params["z"]
            # TODO: replace the mock state update with the vendor SDK movement call.
            return ActionResult(
                status="completed",
                message=f"Moved to {self.pose}.",
                result={"pose": dict(self.pose), "mode": self.mode},
            )"""
    if name == "pick":
        return """        if action.capability == "pick":
            object_id = str(action.params["object_id"])
            if self.holding is not None:
                return ActionResult(
                    status="failed",
                    message=f"Already holding {self.holding}.",
                    result={"holding": self.holding},
                )
            self.holding = object_id
            self.objects.setdefault(object_id, {"type": "object"})
            self.objects[object_id]["location"] = "held"
            # TODO: replace the mock state update with the vendor SDK pick call.
            return ActionResult(
                status="completed",
                message=f"Picked {object_id}.",
                result={"holding": object_id, "mode": self.mode},
            )"""
    if name == "place":
        return """        if action.capability == "place":
            target = str(action.params["target"])
            if self.holding is None:
                return ActionResult(
                    status="failed",
                    message="Cannot place because nothing is being held.",
                    result={},
                )
            object_id = self.holding
            self.holding = None
            self.objects.setdefault(object_id, {"type": "object"})
            self.objects[object_id]["location"] = target
            # TODO: replace the mock state update with the vendor SDK place call.
            return ActionResult(
                status="completed",
                message=f"Placed {object_id} at {target}.",
                result={"object_id": object_id, "target": target, "mode": self.mode},
            )"""
    if name == "say":
        return """        if action.capability == "say":
            text = str(action.params["text"])
            self.messages.append(text)
            # TODO: replace the mock append with the vendor SDK speech or command call.
            return ActionResult(
                status="completed",
                message="Speech command accepted.",
                result={"text": text, "mode": self.mode},
            )"""
    if name == "set_light":
        return """        if action.capability == "set_light":
            self.light = {
                "r": int(action.params["r"]),
                "g": int(action.params["g"]),
                "b": int(action.params["b"]),
            }
            # TODO: replace the mock state update with the vendor SDK light call.
            return ActionResult(
                status="completed",
                message=f"Set light to RGB({self.light['r']}, {self.light['g']}, {self.light['b']}).",
                result={"light": dict(self.light), "mode": self.mode},
            )"""
    return f'''        if action.capability == "{name}":
            # TODO: {note}
            return ActionResult(
                status="failed",
                message="TODO: implement {name} in the watch-side driver.",
            )'''


def _dump_yaml_block(data: Any, *, indent: int) -> str:
    import yaml

    dumped = yaml.safe_dump(data, sort_keys=False).rstrip()
    prefix = " " * indent
    return "\n".join(f"{prefix}{line}" if line else prefix for line in dumped.splitlines())


def _python_literal(data: Any) -> str:
    return pformat(_normalize_for_python(data), width=88, sort_dicts=False)


def _normalize_for_python(data: Any) -> Any:
    if isinstance(data, dict):
        return {str(key): _normalize_for_python(value) for key, value in data.items()}
    if isinstance(data, list):
        return [_normalize_for_python(item) for item in data]
    if isinstance(data, tuple):
        return tuple(_normalize_for_python(item) for item in data)
    if isinstance(data, Path):
        return str(data)
    return data


def readme_template(name: str) -> str:
    return f"""# {name}

This is a local Physical Agent driver.

The watch process loads this directory, validates `physical_driver.yaml`,
imports `driver.py`, and passes structured `Action` objects into the driver.
The driver does not parse Markdown and does not call the agent runtime.
"""


def readme_template_zh(name: str) -> str:
    return f"""# {name}

这是一个本地 Physical Agent driver 模板。

watch 进程会加载这个目录，校验 `physical_driver.yaml`，
导入 `driver.py`，并把结构化的 `Action` 对象传给 driver。
driver 不解析 Markdown，也不会直接调用 agent runtime。
"""


def create_driver_template(target_dir: str | Path, *, name: str | None = None) -> Path:
    return create_driver_scaffold(target_dir, name=name)


def create_driver_scaffold(
    target_dir: str | Path,
    *,
    name: str | None = None,
    description: str = "Local Physical Agent driver.",
    kind: str = "generic",
    supports_simulation: bool = True,
    config_schema: dict[str, Any] | None = None,
    capabilities: list[dict[str, Any]] | None = None,
    readme: str | None = None,
    readme_zh: str | None = None,
) -> Path:
    path = Path(target_dir).resolve()
    driver_name = name or path.name
    class_name = class_name_from_driver_name(driver_name)
    path.mkdir(parents=True, exist_ok=True)
    (path / "physical_driver.yaml").write_text(
        manifest_template(
            driver_name,
            class_name,
            description=description,
            kind=kind,
            supports_simulation=supports_simulation,
            config_schema=config_schema,
        ),
        encoding="utf-8",
    )
    (path / "driver.py").write_text(
        driver_template(driver_name, class_name, capabilities=capabilities),
        encoding="utf-8",
    )
    (path / "README.md").write_text(readme or readme_template(driver_name), encoding="utf-8")
    (path / "README.zh-CN.md").write_text(
        readme_zh or readme_template_zh(driver_name),
        encoding="utf-8",
    )
    return path
