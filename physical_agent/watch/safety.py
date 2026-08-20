from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from physical_agent.protocol.schemas import Action, Capability, RobotRuntimeProfile


@dataclass(frozen=True)
class SafetyDecision:
    ok: bool
    message: str = ""


class SafetyGate:
    """Watch-side safety gate for every physical action."""

    def __init__(
        self,
        *,
        robots: dict[str, RobotRuntimeProfile],
        safety_rules: dict[str, Any] | None = None,
        completed_action_ids: set[str] | None = None,
        executed_action_ids: set[str] | None = None,
    ):
        self.robots = robots
        self.safety_rules = safety_rules or {}
        self.completed_action_ids = completed_action_ids or set()
        self.executed_action_ids = executed_action_ids or set()

    def validate(self, action: Action) -> SafetyDecision:
        if self.safety_rules.get("forbid_duplicate_action_ids", True):
            if action.id in self.executed_action_ids:
                return SafetyDecision(False, f"Duplicate action id rejected: {action.id}")

        for dependency in action.depends_on:
            if dependency not in self.completed_action_ids:
                return SafetyDecision(
                    False,
                    f"Action {action.id} waits for unmet dependency: {dependency}",
                )

        robot = self.robots.get(action.robot)
        if robot is None:
            return SafetyDecision(False, f"Unknown robot: {action.robot}")

        capability = _find_capability(robot.capabilities, action.capability)
        if capability is None:
            return SafetyDecision(
                False,
                f"Robot {action.robot} does not expose capability: {action.capability}",
            )

        autonomous = self.safety_rules.get("allow_autonomous_execution", True)
        if not autonomous:
            return SafetyDecision(False, "Autonomous execution is disabled by SAFETY.md")

        if capability.requires_approval:
            if not _has_human_approval(action):
                return SafetyDecision(
                    False,
                    f"Capability requires approved human approval: {capability.name}",
                )

        if robot.requires_approval and self.safety_rules.get(
            "require_human_approval_for_real_hardware", True
        ):
            if not _has_human_approval(action):
                return SafetyDecision(
                    False,
                    f"Robot requires approved human approval: {action.robot}",
                )

        schema_decision = _validate_params_schema(action, capability)
        if not schema_decision.ok:
            return schema_decision

        constraint_decision = _validate_constraints(action, capability)
        if not constraint_decision.ok:
            return constraint_decision

        timeout_s = capability.timeout_s
        max_timeout = self.safety_rules.get("max_action_timeout_s")
        if timeout_s is not None and max_timeout is not None and timeout_s > max_timeout:
            return SafetyDecision(
                False,
                f"Capability timeout {timeout_s}s exceeds safety max {max_timeout}s",
            )

        return SafetyDecision(True, "Action accepted by watch safety gate.")


def _find_capability(capabilities: list[Capability], name: str) -> Capability | None:
    for capability in capabilities:
        if capability.name == name:
            return capability
    return None


def _has_human_approval(action: Action) -> bool:
    metadata = action.metadata if isinstance(action.metadata, dict) else {}
    approval = metadata.get("approval")
    return bool(isinstance(approval, dict) and approval.get("status") == "approved")


def _validate_params_schema(action: Action, capability: Capability) -> SafetyDecision:
    try:
        Draft202012Validator(capability.params_schema).validate(action.params)
    except ValidationError as exc:
        path = ".".join(str(part) for part in exc.path)
        detail = f" at {path}" if path else ""
        return SafetyDecision(
            False,
            f"Invalid params for {action.capability}{detail}: {exc.message}",
        )
    return SafetyDecision(True)


def _validate_constraints(action: Action, capability: Capability) -> SafetyDecision:
    bounds = capability.constraints.get("bounds")
    if isinstance(bounds, dict):
        for axis, limit in bounds.items():
            if axis not in action.params:
                continue
            if not isinstance(limit, (list, tuple)) or len(limit) != 2:
                continue
            value = action.params[axis]
            lower, upper = limit
            if value < lower or value > upper:
                return SafetyDecision(
                    False,
                    f"Param {axis}={value} is outside allowed bounds [{lower}, {upper}]",
                )
    return SafetyDecision(True)
