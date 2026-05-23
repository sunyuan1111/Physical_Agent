from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from typing import Any

from physical_agent.drivers import (
    Action,
    ActionResult,
    Capability,
    DriverContext,
    HealthStatus,
    Observation,
    PhysicalDriver,
)


RAW_COUNTS_PER_REV = 4096
RAW_DEGREES_PER_REV = 360.0
MULTI_TURN_ABSOLUTE_RAW_LIMIT = 30719


class MomoagentDriver(PhysicalDriver):
    def __init__(self, context: DriverContext):
        super().__init__(context)
        self.config = context.config
        self.mode = str(self.config.get("mode", "mock"))
        self.hardware_profile = str(self.config.get("hardware_profile", "full"))
        self.state = dict(self.config.get("mock_state") or {})
        self.connected = False

        self.robot: Any | None = None
        self.bus: Any | None = None
        self.sdk: Any | None = None
        self.robot_script_common: Any | None = None

        self.runtime_config = self.config.get("runtime_config")
        self.sdk_repo = Path(
            str(self.config.get("sdk_repo") or "/home/houzhinan/MomoAgent")
        ).expanduser()
        self.timeout_s = float(self.config.get("timeout_s", 5.0))
        self.default_speed_percent = self.config.get("speed_percent")
        self.release_torque_on_disconnect = bool(
            self.config.get("release_torque_on_disconnect", False)
        )

        self.partial_joint_name = str(self.config.get("partial_joint_name") or "wrist_roll")
        self.partial_joint_id = int(self.config.get("partial_joint_id", 5))
        self.partial_joint_reduction_ratio = float(
            self.config.get("partial_joint_reduction_ratio", 1.0)
        )
        self.gripper_available = bool(self.config.get("gripper_available", True))
        self.gripper_id = int(self.config.get("gripper_id", 6))
        self.partial_gripper_open_raw = self._optional_int(
            self.config.get("partial_gripper_open_raw")
        )
        self.partial_gripper_close_raw = self._optional_int(
            self.config.get("partial_gripper_close_raw")
        )
        self.serial_port = str(self.config.get("serial_port") or "").strip()
        self.calibration_path = self.config.get("calibration_path")
        self.partial_startup_raw: int | None = None
        self.partial_gripper_spec: dict[str, Any] | None = None

    async def connect(self) -> None:
        if self.mode == "mock":
            self.connected = True
            return

        sdk, robot_script_common = self._load_momo_modules()
        self.sdk = sdk
        self.robot_script_common = robot_script_common

        if self.hardware_profile == "partial":
            self._connect_partial_hardware()
            self.connected = True
            return

        robot = sdk.CompatibleRuntimeRobot.from_config(self.runtime_config)
        robot.connect()
        self.robot = robot
        self.connected = True

    async def disconnect(self) -> None:
        self.connected = False

        robot = self.robot
        self.robot = None
        if robot is not None:
            robot.close(disable_torque=self.release_torque_on_disconnect)

        bus = self.bus
        self.bus = None
        if bus is not None and self.robot_script_common is not None:
            self.robot_script_common.disconnect_bus(
                bus,
                disable_torque=self.release_torque_on_disconnect,
            )

    async def health(self) -> HealthStatus:
        if self.mode == "mock":
            return HealthStatus(
                ok=self.connected,
                message="mock connected" if self.connected else "mock disconnected",
            )

        details = {
            "mode": self.mode,
            "hardware_profile": self.hardware_profile,
            "runtime_config": self.runtime_config,
            "sdk_repo": str(self.sdk_repo),
        }
        if self.hardware_profile == "partial":
            details["serial_port"] = self._resolve_serial_port()
            details["partial_joint_name"] = self.partial_joint_name
            details["partial_joint_id"] = self.partial_joint_id
            details["gripper_id"] = self.gripper_id if self.gripper_available else None
            return HealthStatus(
                ok=self.connected and self.bus is not None,
                message="connected" if self.connected and self.bus is not None else "not connected",
                details=details,
            )

        if self.robot is None:
            return HealthStatus(ok=False, message="hardware not connected", details=details)
        return HealthStatus(ok=bool(self.robot.connected), message="connected", details=details)

    async def observe(self) -> Observation:
        if self.mode == "mock":
            return self._observe_mock()

        if self.hardware_profile == "partial":
            return self._observe_partial()

        if self.robot is None or self.sdk is None:
            return self._observe_mock()

        payload = self.sdk.to_jsonable(self.robot.get_state())
        joint_state = payload.get("joint_state") or {}
        tcp_pose = payload.get("tcp_pose") or {}
        gripper = payload.get("gripper_state") or {}
        summary = (
            f"{self.context.robot_id} is connected over serial. "
            f"Gripper available: {bool(gripper.get('available', False))}."
        )
        return Observation(
            summary=summary,
            robots={
                self.context.robot_id: {
                    "status": "idle",
                    "mode": self.mode,
                    "hardware_profile": self.hardware_profile,
                    "transport": "serial",
                    "joints_deg": dict(joint_state),
                    "tcp_pose": tcp_pose,
                    "gripper": gripper,
                    "permissions": payload.get("permissions") or {},
                }
            },
            raw=payload,
        )

    def capabilities(self) -> list[Capability]:
        joint_enum = self._available_joint_names()
        capabilities = [
            Capability(
                name="observe",
                description="Observe the current arm state.",
                params_schema={
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            ),
            Capability(
                name="home",
                description="Return the arm to its runtime home pose.",
                params_schema={
                    "type": "object",
                    "properties": {
                        "speed_percent": {
                            "type": "number",
                            "minimum": 1,
                            "maximum": 100,
                        }
                    },
                    "additionalProperties": False,
                },
            ),
            Capability(
                name="stop",
                description="Stop the current arm motion and hold the current pose.",
                params_schema={
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            ),
        ]

        if joint_enum:
            capabilities.extend(
                [
                    Capability(
                        name="move_joint",
                        description="Move one available joint by absolute target or relative delta in degrees.",
                        params_schema={
                            "type": "object",
                            "required": ["joint_name"],
                            "properties": {
                                "joint_name": {"type": "string", "enum": joint_enum},
                                "target_deg": {"type": "number"},
                                "delta_deg": {"type": "number"},
                                "speed_percent": {
                                    "type": "number",
                                    "minimum": 1,
                                    "maximum": 100,
                                },
                            },
                            "additionalProperties": False,
                            "anyOf": [
                                {"required": ["target_deg"]},
                                {"required": ["delta_deg"]},
                            ],
                        },
                    ),
                    Capability(
                        name="move_joints",
                        description="Move multiple available joints to target degrees.",
                        params_schema={
                            "type": "object",
                            "required": ["targets_deg"],
                            "properties": {
                                "targets_deg": {
                                    "type": "object",
                                    "properties": {
                                        joint_name: {"type": "number"} for joint_name in joint_enum
                                    },
                                    "additionalProperties": False,
                                },
                                "speed_percent": {
                                    "type": "number",
                                    "minimum": 1,
                                    "maximum": 100,
                                },
                            },
                            "additionalProperties": False,
                        },
                    ),
                ]
            )

        if self._gripper_enabled():
            capabilities.extend(
                [
                    Capability(
                        name="set_gripper",
                        description="Set gripper opening ratio from 0.0 to 1.0.",
                        params_schema={
                            "type": "object",
                            "required": ["open_ratio"],
                            "properties": {
                                "open_ratio": {
                                    "type": "number",
                                    "minimum": 0.0,
                                    "maximum": 1.0,
                                },
                                "speed_percent": {
                                    "type": "number",
                                    "minimum": 1,
                                    "maximum": 100,
                                },
                            },
                            "additionalProperties": False,
                        },
                    ),
                    Capability(
                        name="open_gripper",
                        description="Fully open the gripper.",
                        params_schema={
                            "type": "object",
                            "properties": {
                                "speed_percent": {
                                    "type": "number",
                                    "minimum": 1,
                                    "maximum": 100,
                                }
                            },
                            "additionalProperties": False,
                        },
                    ),
                    Capability(
                        name="close_gripper",
                        description="Fully close the gripper.",
                        params_schema={
                            "type": "object",
                            "properties": {
                                "speed_percent": {
                                    "type": "number",
                                    "minimum": 1,
                                    "maximum": 100,
                                }
                            },
                            "additionalProperties": False,
                        },
                    ),
                ]
            )

        return capabilities

    async def execute(self, action: Action) -> ActionResult:
        if action.capability == "observe":
            observation = await self.observe()
            return ActionResult(
                status="completed",
                message="Observation completed.",
                result={"observation": observation.model_dump(mode="json")},
            )

        if self.mode == "mock":
            return self._execute_mock(action)

        try:
            if self.hardware_profile == "partial":
                return self._execute_partial(action)
            return self._execute_full(action)
        except Exception as exc:
            return ActionResult(
                status="failed",
                message=f"{action.capability} failed: {exc}",
            )

    def _execute_full(self, action: Action) -> ActionResult:
        if self.robot is None or self.sdk is None:
            return ActionResult(status="failed", message="Hardware driver is not connected.")

        if action.capability == "home":
            result = self.robot.home(
                speed_percent=self._speed(action.params),
                wait=True,
                timeout=self.timeout_s,
            )
            return self._completed("Arm returned home.", result)

        if action.capability == "stop":
            result = self.robot.stop()
            return self._completed("Arm stop command sent.", result)

        if action.capability == "move_joint":
            result = self.robot.move_joint(
                joint=str(action.params["joint_name"]),
                target_deg=action.params.get("target_deg"),
                delta_deg=action.params.get("delta_deg"),
                speed_percent=self._speed(action.params),
                wait=True,
                timeout=self.timeout_s,
            )
            return self._completed("Joint move completed.", result)

        if action.capability == "move_joints":
            targets = self._merge_joint_targets(action.params["targets_deg"])
            result = self.robot.move_joints(
                targets,
                speed_percent=self._speed(action.params),
                wait=True,
                timeout=self.timeout_s,
            )
            return self._completed("Joint group move completed.", result)

        if action.capability == "set_gripper":
            result = self.robot.set_gripper(
                open_ratio=float(action.params["open_ratio"]),
                speed_percent=self._speed(action.params),
                wait=True,
                timeout=self.timeout_s,
            )
            return self._completed("Gripper command completed.", result)

        if action.capability == "open_gripper":
            result = self.robot.open_gripper(
                speed_percent=self._speed(action.params),
                wait=True,
                timeout=self.timeout_s,
            )
            return self._completed("Gripper opened.", result)

        if action.capability == "close_gripper":
            result = self.robot.close_gripper(
                speed_percent=self._speed(action.params),
                wait=True,
                timeout=self.timeout_s,
            )
            return self._completed("Gripper closed.", result)

        return ActionResult(
            status="failed",
            message=f"Unsupported capability: {action.capability}",
        )

    def _execute_partial(self, action: Action) -> ActionResult:
        bus = self._require_partial_bus()

        if action.capability == "home":
            if self.partial_startup_raw is not None:
                bus.write("Goal_Position", self.partial_joint_name, int(self.partial_startup_raw), normalize=False)
            return self._completed(
                "Partial hardware home sent.",
                {"profile": "partial", "joint_name": self.partial_joint_name},
            )

        if action.capability == "stop":
            current_raw = int(bus.read("Present_Position", self.partial_joint_name, normalize=False))
            bus.write("Goal_Position", self.partial_joint_name, current_raw, normalize=False)
            if self._gripper_enabled():
                gripper_raw = int(bus.read("Present_Position", "gripper", normalize=False))
                bus.write("Goal_Position", "gripper", gripper_raw, normalize=False)
            return self._completed(
                "Partial hardware stop sent.",
                {"profile": "partial", "joint_name": self.partial_joint_name},
            )

        if action.capability == "move_joint":
            joint_name = str(action.params["joint_name"])
            if joint_name != self.partial_joint_name:
                return ActionResult(
                    status="failed",
                    message=f"Partial hardware only supports move_joint for {self.partial_joint_name}.",
                )
            target_deg = self._resolve_joint_target_deg(action.params)
            goal_raw = self._joint_deg_to_goal_raw(target_deg)
            bus.write("Goal_Position", self.partial_joint_name, int(goal_raw), normalize=False)
            return self._completed(
                f"Moved {joint_name} to {target_deg:.2f} deg.",
                {
                    "profile": "partial",
                    "joint_name": joint_name,
                    "target_deg": float(target_deg),
                    "goal_raw": int(goal_raw),
                },
            )

        if action.capability == "move_joints":
            targets_deg = dict(action.params["targets_deg"] or {})
            if set(targets_deg) - {self.partial_joint_name}:
                return ActionResult(
                    status="failed",
                    message=f"Partial hardware only supports move_joints for {self.partial_joint_name}.",
                )
            target_deg = float(targets_deg.get(self.partial_joint_name, self._current_joint_deg()))
            goal_raw = self._joint_deg_to_goal_raw(target_deg)
            bus.write("Goal_Position", self.partial_joint_name, int(goal_raw), normalize=False)
            return self._completed(
                "Partial joint group move sent.",
                {
                    "profile": "partial",
                    "targets_deg": {self.partial_joint_name: float(target_deg)},
                    "goal_raw": {self.partial_joint_name: int(goal_raw)},
                },
            )

        if action.capability == "set_gripper":
            self._write_gripper_ratio(float(action.params["open_ratio"]))
            return self._completed(
                "Gripper command completed.",
                {
                    "profile": "partial",
                    "open_ratio": float(action.params["open_ratio"]),
                },
            )

        if action.capability == "open_gripper":
            self._write_gripper_ratio(1.0)
            return self._completed("Gripper opened.", {"profile": "partial", "open_ratio": 1.0})

        if action.capability == "close_gripper":
            self._write_gripper_ratio(0.0)
            return self._completed("Gripper closed.", {"profile": "partial", "open_ratio": 0.0})

        return ActionResult(
            status="failed",
            message=f"Unsupported capability: {action.capability}",
        )

    def _execute_mock(self, action: Action) -> ActionResult:
        joints = dict(self.state.get("joints_deg") or {})
        gripper = dict(self.state.get("gripper") or {"available": True, "open_ratio": 1.0})

        if action.capability == "home":
            self.state["joints_deg"] = {joint_name: 0.0 for joint_name in joints}
            return ActionResult(status="completed", message="Mock home completed.")

        if action.capability == "stop":
            return ActionResult(status="completed", message="Mock stop completed.")

        if action.capability == "move_joint":
            joint_name = str(action.params["joint_name"])
            current = float(joints.get(joint_name, 0.0))
            if "target_deg" in action.params:
                joints[joint_name] = float(action.params["target_deg"])
            else:
                joints[joint_name] = current + float(action.params["delta_deg"])
            self.state["joints_deg"] = joints
            return ActionResult(
                status="completed",
                message=f"Mock joint move completed for {joint_name}.",
                result={"joints_deg": joints},
            )

        if action.capability == "move_joints":
            for joint_name, value in dict(action.params["targets_deg"]).items():
                joints[str(joint_name)] = float(value)
            self.state["joints_deg"] = joints
            return ActionResult(
                status="completed",
                message="Mock group joint move completed.",
                result={"joints_deg": joints},
            )

        if action.capability == "set_gripper":
            gripper["open_ratio"] = float(action.params["open_ratio"])
            self.state["gripper"] = gripper
            return ActionResult(
                status="completed",
                message="Mock gripper command completed.",
                result={"gripper": gripper},
            )

        if action.capability == "open_gripper":
            gripper["open_ratio"] = 1.0
            self.state["gripper"] = gripper
            return ActionResult(
                status="completed",
                message="Mock gripper opened.",
                result={"gripper": gripper},
            )

        if action.capability == "close_gripper":
            gripper["open_ratio"] = 0.0
            self.state["gripper"] = gripper
            return ActionResult(
                status="completed",
                message="Mock gripper closed.",
                result={"gripper": gripper},
            )

        return ActionResult(
            status="failed",
            message=f"Unsupported capability in mock mode: {action.capability}",
        )

    def _observe_mock(self) -> Observation:
        joints = dict(self.state.get("joints_deg") or {})
        tcp_pose = dict(self.state.get("tcp_pose") or {})
        gripper = dict(self.state.get("gripper") or {"available": True, "open_ratio": 1.0})
        return Observation(
            summary=(
                f"{self.context.robot_id} is "
                f"{'connected' if self.connected else 'offline'} in {self.mode} mode."
            ),
            robots={
                self.context.robot_id: {
                    "status": "idle" if self.connected else "offline",
                    "mode": self.mode,
                    "hardware_profile": self.hardware_profile,
                    "joints_deg": joints,
                    "tcp_pose": tcp_pose,
                    "gripper": gripper,
                }
            },
            raw={"state": dict(self.state)},
        )

    def _observe_partial(self) -> Observation:
        bus = self._require_partial_bus()
        joint_deg = self._current_joint_deg()
        joints_deg = {self.partial_joint_name: joint_deg}
        gripper_state = self._read_gripper_state() if self._gripper_enabled() else {"available": False}
        summary = (
            f"{self.context.robot_id} is connected over serial in partial hardware mode. "
            f"Active joint: {self.partial_joint_name}. "
            f"Gripper available: {bool(gripper_state.get('available', False))}."
        )
        raw = {
            "serial_port": self._resolve_serial_port(),
            "partial_joint_name": self.partial_joint_name,
            "partial_joint_id": self.partial_joint_id,
            "partial_joint_present_raw": int(bus.read("Present_Position", self.partial_joint_name, normalize=False)),
            "partial_joint_startup_raw": self.partial_startup_raw,
            "gripper": gripper_state,
        }
        return Observation(
            summary=summary,
            robots={
                self.context.robot_id: {
                    "status": "idle",
                    "mode": self.mode,
                    "hardware_profile": self.hardware_profile,
                    "transport": "serial",
                    "active_joints": [self.partial_joint_name],
                    "joints_deg": joints_deg,
                    "gripper": gripper_state,
                }
            },
            raw=raw,
        )

    def _load_momo_modules(self) -> tuple[Any, Any]:
        sdk_src = self.sdk_repo / "sdk" / "src"
        sdk_scripts = self.sdk_repo / "sdk" / "scripts"
        if not sdk_src.exists():
            raise RuntimeError(
                f"MomoAgent SDK source not found: {sdk_src}. "
                "Set config.sdk_repo to your local MomoAgent checkout."
            )
        for path in (sdk_scripts, sdk_src):
            path_text = str(path.resolve())
            if path_text not in sys.path:
                sys.path.insert(0, path_text)
        sdk = importlib.import_module("soarmmoce_sdk")
        robot_script_common = importlib.import_module("_robot_script_common")
        return sdk, robot_script_common

    def _connect_partial_hardware(self) -> None:
        if self.robot_script_common is None:
            raise RuntimeError("MomoAgent helper module is not loaded.")

        port = self._resolve_serial_port()
        motors = {
            self.partial_joint_name: self.robot_script_common.make_motor(
                self.partial_joint_id,
                "sts3215",
            )
        }
        if self._gripper_enabled():
            motors["gripper"] = self.robot_script_common.make_motor(self.gripper_id, "sts3215")
        self.bus = self.robot_script_common.make_bus(port=port, motors=motors)
        self.partial_startup_raw = int(
            self.bus.read("Present_Position", self.partial_joint_name, normalize=False)
        )
        self.partial_gripper_spec = self._load_gripper_spec()

    def _resolve_serial_port(self) -> str:
        if self.serial_port:
            return self.serial_port
        if self.runtime_config:
            path = Path(str(self.runtime_config)).expanduser().resolve()
            if path.exists():
                try:
                    import yaml

                    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                    transport = payload.get("transport", {}) if isinstance(payload, dict) else {}
                    port = str(transport.get("port", "")).strip() if isinstance(transport, dict) else ""
                    if port:
                        return port
                except Exception:
                    pass
        raise RuntimeError(
            "Could not resolve a serial port. Set config.serial_port or a valid runtime_config."
        )

    def _load_gripper_spec(self) -> dict[str, Any] | None:
        if not self._gripper_enabled():
            return None
        calibration_path = self._resolve_calibration_path()
        if calibration_path is None or not calibration_path.exists():
            return None
        payload = json.loads(calibration_path.read_text(encoding="utf-8"))
        gripper = payload.get("gripper")
        return dict(gripper) if isinstance(gripper, dict) else None

    def _resolve_calibration_path(self) -> Path | None:
        if self.calibration_path:
            return Path(str(self.calibration_path)).expanduser().resolve()
        default_path = (
            self.sdk_repo
            / "sdk"
            / "src"
            / "soarmmoce_sdk"
            / "clabration"
            / "soarmmoce.json"
        )
        return default_path.resolve() if default_path.exists() else None

    def _gripper_enabled(self) -> bool:
        return bool(self.gripper_available)

    def _require_partial_bus(self) -> Any:
        if self.bus is None:
            raise RuntimeError("Partial hardware bus is not connected.")
        return self.bus

    def _available_joint_names(self) -> list[str]:
        if self.mode != "hardware":
            joints = sorted(dict(self.state.get("joints_deg") or {}).keys())
            return joints or [self.partial_joint_name]
        if self.hardware_profile == "partial":
            return [self.partial_joint_name]
        if self.sdk is not None:
            return list(self.sdk.JOINTS)
        return [self.partial_joint_name]

    def _current_joint_deg(self) -> float:
        bus = self._require_partial_bus()
        if self.partial_startup_raw is None:
            raise RuntimeError("Partial startup reference is not initialized.")
        present_raw = int(bus.read("Present_Position", self.partial_joint_name, normalize=False))
        relative_raw = present_raw - int(self.partial_startup_raw)
        return (
            float(relative_raw)
            * RAW_DEGREES_PER_REV
            / float(RAW_COUNTS_PER_REV)
            / float(self.partial_joint_reduction_ratio)
        )

    def _resolve_joint_target_deg(self, params: dict[str, Any]) -> float:
        current_deg = self._current_joint_deg()
        if "target_deg" in params:
            return float(params["target_deg"])
        return current_deg + float(params["delta_deg"])

    def _joint_deg_to_goal_raw(self, joint_deg: float) -> int:
        if self.partial_startup_raw is None:
            raise RuntimeError("Partial startup reference is not initialized.")
        relative_raw = (
            float(joint_deg)
            * float(self.partial_joint_reduction_ratio)
            * float(RAW_COUNTS_PER_REV)
            / RAW_DEGREES_PER_REV
        )
        goal_raw = int(round(float(self.partial_startup_raw) + relative_raw))
        if goal_raw < -MULTI_TURN_ABSOLUTE_RAW_LIMIT or goal_raw > MULTI_TURN_ABSOLUTE_RAW_LIMIT:
            raise RuntimeError(
                f"Requested goal_raw={goal_raw} is outside supported multi-turn range."
            )
        return goal_raw

    def _read_gripper_state(self) -> dict[str, Any]:
        if not self._gripper_enabled():
            return {"available": False, "open_ratio": None}
        if (
            self.partial_gripper_open_raw is not None
            and self.partial_gripper_close_raw is not None
        ):
            bus = self._require_partial_bus()
            present_raw = int(bus.read("Present_Position", "gripper", normalize=False))
            open_ratio = self._raw_to_partial_gripper_ratio(present_raw)
            return {
                "available": True,
                "open_ratio": open_ratio,
                "present_raw": present_raw,
                "open_raw": int(self.partial_gripper_open_raw),
                "close_raw": int(self.partial_gripper_close_raw),
                "mapping": "partial_raw_window",
            }
        spec = self.partial_gripper_spec
        if spec is None:
            return {"available": False, "open_ratio": None}
        bus = self._require_partial_bus()
        register_raw = int(bus.read("Present_Position", "gripper", normalize=False))
        adjusted_raw = self._wrap_single_turn(register_raw + int(spec["homing_offset"]))
        span = float(int(spec["range_max"]) - int(spec["range_min"]))
        ratio = 0.0 if abs(span) <= 1e-9 else (float(adjusted_raw) - float(spec["range_min"])) / span
        return {
            "available": True,
            "open_ratio": float(min(1.0, max(0.0, ratio))),
            "present_raw": int(register_raw),
            "adjusted_raw": int(adjusted_raw),
            "range_min": int(spec["range_min"]),
            "range_max": int(spec["range_max"]),
        }

    def _write_gripper_ratio(self, open_ratio: float) -> None:
        if not self._gripper_enabled():
            raise RuntimeError("Gripper is disabled in this driver config.")
        if (
            self.partial_gripper_open_raw is not None
            and self.partial_gripper_close_raw is not None
        ):
            ratio = float(min(1.0, max(0.0, open_ratio)))
            goal_raw = int(
                round(
                    float(self.partial_gripper_close_raw)
                    + ratio
                    * float(self.partial_gripper_open_raw - self.partial_gripper_close_raw)
                )
            )
            bus = self._require_partial_bus()
            bus.write("Goal_Position", "gripper", int(goal_raw), normalize=False)
            return
        spec = self.partial_gripper_spec
        if spec is None:
            raise RuntimeError("Gripper calibration data is unavailable.")
        ratio = float(min(1.0, max(0.0, open_ratio)))
        adjusted_raw = int(
            round(float(spec["range_min"]) + ratio * float(int(spec["range_max"]) - int(spec["range_min"])))
        )
        register_raw = self._wrap_single_turn(adjusted_raw - int(spec["homing_offset"]))
        bus = self._require_partial_bus()
        bus.write("Goal_Position", "gripper", int(register_raw), normalize=False)

    def _wrap_single_turn(self, raw_value: int | float) -> int:
        return int(round(float(raw_value))) % RAW_COUNTS_PER_REV

    def _raw_to_partial_gripper_ratio(self, present_raw: int) -> float | None:
        if (
            self.partial_gripper_open_raw is None
            or self.partial_gripper_close_raw is None
        ):
            return None
        span = float(self.partial_gripper_open_raw - self.partial_gripper_close_raw)
        if abs(span) <= 1e-9:
            return None
        ratio = (float(present_raw) - float(self.partial_gripper_close_raw)) / span
        return float(min(1.0, max(0.0, ratio)))

    def _optional_int(self, value: Any) -> int | None:
        if value in (None, ""):
            return None
        return int(value)

    def _merge_joint_targets(self, targets_deg: dict[str, Any]) -> list[float]:
        if self.robot is None or self.sdk is None:
            raise RuntimeError("Robot is not connected.")
        payload = self.sdk.to_jsonable(self.robot.get_state())
        current = dict(payload.get("joint_state") or {})
        targets = dict(targets_deg or {})
        merged: list[float] = []
        for joint_name in list(self.sdk.JOINTS):
            value = targets.get(joint_name, current.get(joint_name, 0.0))
            merged.append(float(value))
        return merged

    def _speed(self, params: dict[str, Any]) -> int | float | None:
        if "speed_percent" in params:
            return params["speed_percent"]
        return self.default_speed_percent

    def _completed(self, message: str, payload: Any) -> ActionResult:
        result = self.sdk.to_jsonable(payload) if self.sdk is not None else {"value": payload}
        return ActionResult(status="completed", message=message, result=result)
