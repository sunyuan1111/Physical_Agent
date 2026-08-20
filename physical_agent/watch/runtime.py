from __future__ import annotations

import asyncio
from pathlib import Path
import time
from typing import Any

from physical_agent.config import DEFAULT_CONFIG_NAME, PhysicalAgentConfig, load_config
from physical_agent.drivers.loader import LoadedDriver, load_driver
from physical_agent.drivers.transport import (
    TransportClosedError,
    TransportDisconnected,
    TransportReconnectFailed,
    TransportReconnecting,
)
from physical_agent.protocol.expectations import evaluate_expected, normalize_expected_value
from physical_agent.protocol.schemas import Action, ActionResult, Observation, RobotRuntimeProfile
from physical_agent.state import StateStore, open_state_store
from physical_agent.watch.safety import SafetyGate


ACTION_LEASE_SECONDS = 300
CLAIM_OWNER = "watch"


class DriverCallTimeout(Exception):
    """A driver call exceeded its watch-side timeout budget."""


async def _call_with_timeout(coro: Any, timeout_s: float, description: str) -> Any:
    try:
        return await asyncio.wait_for(coro, timeout=timeout_s)
    except asyncio.TimeoutError as exc:
        raise DriverCallTimeout(
            f"{description} timed out after {timeout_s}s"
        ) from exc


class WatchRuntime:
    def __init__(self, config_path: str | Path = DEFAULT_CONFIG_NAME):
        self.config_path = Path(config_path).resolve()
        self.base_dir = self.config_path.parent
        self.config: PhysicalAgentConfig | None = None
        self.workspace: StateStore | None = None
        self.loaded_drivers: dict[str, LoadedDriver] = {}
        self.profiles: dict[str, RobotRuntimeProfile] = {}
        self._heartbeat_failure_counts: dict[str, int] = {}
        self._watchdog_halted_robots: set[str] = set()
        self._last_idle_observe_at: float | None = None
        self.started = False

    async def setup(self) -> None:
        if self.started:
            return
        self.config = load_config(self.config_path)
        self.workspace = open_state_store(self.config, base_dir=self.base_dir)
        self.workspace.initialize()
        self.workspace.append_log("`physical-agent watch` started.", actor="watch")

        for robot_id, robot_config in self.config.robots.items():
            loaded = load_driver(
                robot_id=robot_id,
                driver_ref=robot_config.driver,
                config=robot_config.config,
                workspace_path=self.workspace.path,
                artifacts_path=self.workspace.artifacts_path,
                base_dir=self.base_dir,
            )
            await loaded.driver.connect()
            capabilities = loaded.driver.capabilities()
            self.loaded_drivers[robot_id] = loaded
            self._heartbeat_failure_counts[robot_id] = 0
            self._watchdog_halted_robots.discard(robot_id)
            self.profiles[robot_id] = RobotRuntimeProfile(
                robot_id=robot_id,
                kind=loaded.manifest.robot.kind,
                driver=loaded.manifest.name,
                status="connected",
                capabilities=capabilities,
                requires_approval=(
                    self.config.watch.require_human_approval
                    or not loaded.manifest.robot.supports_simulation
                ),
            )
            self.workspace.append_log(f"`{robot_id}` connected via `{loaded.manifest.name}`.", actor="watch")

        self.workspace.write_capabilities(self._capabilities_document())
        await self.update_world()
        self.started = True

    async def shutdown(self) -> None:
        await self._halt_loaded_drivers()
        for robot_id, loaded in self.loaded_drivers.items():
            try:
                await _call_with_timeout(
                    loaded.driver.disconnect(),
                    self._halt_timeout_s(),
                    f"Driver disconnect for robot `{robot_id}`",
                )
            except Exception as exc:
                if self.workspace is not None:
                    self.workspace.append_log(
                        f"Driver disconnect failed for `{robot_id}`: "
                        f"{type(exc).__name__}: {exc}",
                        actor="watch",
                    )
        if self.workspace is not None:
            self.workspace.append_log("`physical-agent watch` stopped.", actor="watch")
        self.started = False

    async def run_forever(self) -> None:
        await self.setup()
        assert self.config is not None
        try:
            while True:
                await self.tick()
                await asyncio.sleep(self.config.watch.tick_ms / 1000)
        finally:
            await self.shutdown()

    async def tick(self) -> int:
        should_observe = self._should_observe_now()
        executed_count = await self.step(setup=False, observe_when_idle=should_observe)
        if executed_count == 0 and should_observe:
            self._last_idle_observe_at = self._monotonic()
        return executed_count

    async def step(self, *, setup: bool = True, observe_when_idle: bool = True) -> int:
        if setup:
            await self.setup()
        await self._heartbeat_loaded_drivers()
        workspace = self._workspace()
        workspace.recover_stale_actions(ACTION_LEASE_SECONDS)
        actions_doc = workspace.read_actions()
        safety_rules = workspace.read_safety()["rules"]
        executed_count = 0
        initial_pending_count = len(actions_doc["pending"])

        for _ in range(initial_pending_count):
            action = workspace.claim_next_ready_action(claim_owner=CLAIM_OWNER)
            if action is None:
                break
            latest_actions = workspace.read_actions()
            completed_ids = {item.id for item in latest_actions["completed"]}
            executed_ids = {
                item.id
                for item in latest_actions["completed"] + latest_actions["cancelled"]
            }
            for item in workspace.read_feedback().get("history", []):
                action_id = item.get("action_id")
                if action_id:
                    executed_ids.add(str(action_id))
            gate = SafetyGate(
                robots=self.profiles,
                safety_rules=safety_rules,
                completed_action_ids=completed_ids,
                executed_action_ids=executed_ids,
            )
            decision = gate.validate(action)
            if not decision.ok:
                result = ActionResult(status="failed", message=decision.message)
                workspace.mark_action_cancelled(action)
                await self._record_action_result(action, result)
                continue

            loaded = self.loaded_drivers[action.robot]
            timeout_s = self._action_timeout_s(action)
            try:
                result = await _call_with_timeout(
                    loaded.driver.execute(action),
                    timeout_s,
                    f"Driver execute for action `{action.id}`",
                )
            except DriverCallTimeout as exc:
                result = ActionResult(
                    status="failed",
                    message=(
                        f"Driver execute timed out: {exc}. Hardware state is "
                        "unknown; attempting best-effort halt."
                    ),
                    result={"error_type": "DriverCallTimeout", "timeout_s": timeout_s},
                )
                workspace.mark_action_cancelled(action)
                executed_count += 1
                await self._record_action_result(action, result)
                await self._record_expectation_skipped(
                    action,
                    f"Action failed before expectation check: {result.message}",
                )
                await self._halt_robot_after_timeout(action.robot, loaded)
                continue
            except (
                TransportReconnecting,
                TransportReconnectFailed,
                TransportDisconnected,
                TransportClosedError,
            ) as exc:
                result = _transport_action_failure_result(exc)
                workspace.mark_action_cancelled(action)
                executed_count += 1
                await self._record_action_result(action, result)
                await self._record_expectation_skipped(
                    action,
                    f"Action failed before expectation check: {result.message}",
                )
                continue
            except Exception as exc:
                result = ActionResult(
                    status="failed",
                    message=f"Driver execute failed: {type(exc).__name__}: {exc}",
                    result={"error_type": type(exc).__name__},
                )
                workspace.mark_action_cancelled(action)
                executed_count += 1
                await self._record_action_result(action, result)
                await self._record_expectation_skipped(
                    action,
                    f"Action failed before expectation check: {result.message}",
                )
                continue
            if result.status == "completed":
                workspace.mark_action_completed(action)
            else:
                workspace.mark_action_cancelled(action)
            executed_count += 1
            await self._record_action_result(action, result)
            if result.status != "completed":
                await self._record_expectation_skipped(
                    action,
                    f"Action failed before expectation check: {result.message}",
                )
                await self.update_world()
                continue
            try:
                world = await self.update_world()
            except Exception as exc:
                await self._record_expectation_skipped(
                    action,
                    (
                        "World update failed before expectation check: "
                        f"{type(exc).__name__}: {exc}"
                    ),
                )
                raise
            await self._record_expectation_check(action, world)

        if executed_count == 0 and observe_when_idle:
            await self.update_world()
        return executed_count

    async def update_world(self) -> Observation:
        observations, failed_robot_ids = await self._observe_all_robots_concurrently()
        previous = self._current_world_observation() if failed_robot_ids else None
        merged = merge_observations(observations, base=previous)
        self._workspace().write_world(merged)
        return merged

    async def _observe_all_robots_concurrently(self) -> tuple[list[Observation], list[str]]:
        timeout_s = (
            self.config.watch.observe_timeout_s if self.config is not None else 10.0
        )
        robot_items = sorted(self.loaded_drivers.items(), key=lambda item: item[0])
        results = await asyncio.gather(
            *[
                self._observe_robot(robot_id, loaded, timeout_s)
                for robot_id, loaded in robot_items
            ],
            return_exceptions=True,
        )

        observations: list[Observation] = []
        failed_robot_ids: list[str] = []
        for (robot_id, _loaded), result in zip(robot_items, results):
            if isinstance(result, asyncio.CancelledError):
                raise result
            if isinstance(result, Exception):
                failed_robot_ids.append(robot_id)
                self._record_observe_failure(robot_id, result)
                continue
            observations.append(result)
        return observations, failed_robot_ids

    async def _observe_robot(
        self,
        robot_id: str,
        loaded: LoadedDriver,
        timeout_s: float,
    ) -> Observation:
        return await _call_with_timeout(
            loaded.driver.observe(),
            timeout_s,
            f"Driver observe for robot `{robot_id}`",
        )

    def _record_observe_failure(self, robot_id: str, exc: Exception) -> None:
        # Log-only: a hung sensor at tick rate would flood feedback.
        # Persistent failure is escalated by the heartbeat watchdog.
        if isinstance(exc, DriverCallTimeout):
            message = f"Skipped observation for `{robot_id}`: {exc}"
        else:
            message = (
                f"Skipped observation for `{robot_id}`: Driver observe failed: "
                f"{type(exc).__name__}: {exc}"
            )
        self._workspace().append_log(message, actor="watch")

    def _capabilities_document(self) -> dict[str, Any]:
        document: dict[str, Any] = {}
        for robot_id, profile in self.profiles.items():
            document[robot_id] = {
                "kind": profile.kind,
                "driver": profile.driver,
                "status": profile.status,
                "requires_approval": profile.requires_approval,
                "capabilities": [
                    capability.model_dump(mode="json", exclude_none=True)
                    for capability in profile.capabilities
                ],
            }
        return document

    async def _record_action_result(self, action: Action, result: ActionResult) -> None:
        workspace = self._workspace()
        feedback = workspace.read_feedback()
        latest = {
            "action_id": action.id,
            "status": result.status,
            "robot": action.robot,
            "capability": action.capability,
            "message": result.message,
            "result": result.result,
            "artifacts": result.artifacts,
        }
        history = list(feedback["history"])
        history.append(latest)
        workspace.write_feedback(latest, history)
        workspace.append_log(
            f"Action `{action.id}` {result.status}: {result.message}",
            actor="watch",
        )

    async def _record_expectation_check(self, action: Action, world: Observation) -> None:
        expected = _expected_checks(action)
        if not expected:
            return
        evaluation = evaluate_expected(expected, world)
        latest = {
            "event": "expectation_check",
            "action_id": action.id,
            "status": evaluation["status"],
            "robot": action.robot,
            "capability": action.capability,
            "message": evaluation["message"],
            "expected": evaluation["expected"],
            "actual": evaluation["actual"],
            "checks": evaluation["checks"],
            "result": {
                "status": evaluation["status"],
                "check_count": len(evaluation["checks"]),
            },
            "artifacts": [],
        }
        self._record_feedback_event(
            latest,
            f"Expectation check for `{action.id}` {evaluation['status']}: {evaluation['message']}",
        )

    async def _record_expectation_skipped(self, action: Action, message: str) -> None:
        expected = _expected_checks(action)
        if not expected:
            return
        checks = [
            {
                "status": "skipped",
                "message": message,
                "expected": item,
                "actual": None,
                "path": item.get("path") if isinstance(item, dict) else None,
                "op": item.get("op") if isinstance(item, dict) else None,
            }
            for item in expected
        ]
        latest = {
            "event": "expectation_check",
            "action_id": action.id,
            "status": "skipped",
            "robot": action.robot,
            "capability": action.capability,
            "message": message,
            "expected": expected,
            "actual": [
                {
                    "path": check.get("path"),
                    "value": None,
                    "status": "skipped",
                }
                for check in checks
            ],
            "checks": checks,
            "result": {
                "status": "skipped",
                "check_count": len(checks),
            },
            "artifacts": [],
        }
        self._record_feedback_event(latest, f"Expectation check for `{action.id}` skipped: {message}")

    async def _heartbeat_loaded_drivers(self) -> None:
        if self.config is None or not self.config.watch.heartbeat_enabled:
            return
        heartbeat_timeout_s = self.config.watch.heartbeat_timeout_s
        for robot_id, loaded in self.loaded_drivers.items():
            try:
                await _call_with_timeout(
                    loaded.driver.heartbeat(),
                    heartbeat_timeout_s,
                    f"Driver heartbeat for robot `{robot_id}`",
                )
            except Exception as exc:
                failure_count = self._heartbeat_failure_counts.get(robot_id, 0) + 1
                self._heartbeat_failure_counts[robot_id] = failure_count
                self._record_driver_hook_failure(
                    robot_id,
                    "heartbeat",
                    exc,
                    extra_result={"failure_count": failure_count},
                )
                await self._maybe_halt_for_heartbeat_failure(
                    robot_id,
                    loaded,
                    failure_count,
                    exc,
                )
            else:
                previous_failure_count = self._heartbeat_failure_counts.get(robot_id, 0)
                self._heartbeat_failure_counts[robot_id] = 0
                self._watchdog_halted_robots.discard(robot_id)
                if previous_failure_count > 0:
                    self._record_heartbeat_recovered(robot_id, previous_failure_count)

    async def _halt_loaded_drivers(self) -> None:
        if self.config is None or not self.config.watch.halt_on_shutdown:
            return
        for robot_id, loaded in self.loaded_drivers.items():
            try:
                await _call_with_timeout(
                    loaded.driver.halt(),
                    self._halt_timeout_s(),
                    f"Driver halt for robot `{robot_id}`",
                )
            except Exception as exc:
                self._record_driver_hook_failure(robot_id, "halt", exc)

    async def _halt_robot_after_timeout(self, robot_id: str, loaded: LoadedDriver) -> None:
        try:
            await _call_with_timeout(
                loaded.driver.halt(),
                self._halt_timeout_s(),
                f"Driver halt after execute timeout for robot `{robot_id}`",
            )
        except Exception as exc:
            self._record_driver_hook_failure(robot_id, "halt", exc)
        else:
            self._workspace().append_log(
                f"Best-effort halt completed for `{robot_id}` after execute timeout.",
                actor="watch",
            )

    def _action_timeout_s(self, action: Action) -> float:
        default_timeout = (
            self.config.watch.action_timeout_s if self.config is not None else 30.0
        )
        profile = self.profiles.get(action.robot)
        if profile is None:
            return default_timeout
        for capability in profile.capabilities:
            if capability.name == action.capability and capability.timeout_s:
                return float(capability.timeout_s)
        return default_timeout

    def _halt_timeout_s(self) -> float:
        return self.config.watch.halt_timeout_s if self.config is not None else 5.0

    def _observe_interval_ms(self) -> int:
        if self.config is None:
            return 500
        configured = self.config.watch.observe_interval_ms
        return self.config.watch.tick_ms if configured is None else configured

    def _should_observe_now(self) -> bool:
        if self._last_idle_observe_at is None:
            return True
        elapsed_s = self._monotonic() - self._last_idle_observe_at
        return elapsed_s >= (self._observe_interval_ms() / 1000.0)

    def _monotonic(self) -> float:
        return time.monotonic()

    def _current_world_observation(self) -> Observation | None:
        world = self._workspace().read_world()
        observation = world.get("observation")
        if isinstance(observation, Observation):
            return observation
        if isinstance(observation, dict):
            return Observation.model_validate(observation)
        state = world.get("state") or {}
        if not isinstance(state, dict):
            return None
        return Observation(
            summary=str(world.get("summary") or ""),
            robots=dict(state.get("robots") or {}),
            objects=dict(state.get("objects") or {}),
            environment=dict(state.get("environment") or {}),
            artifacts=list(state.get("artifacts") or []),
            raw=dict(state.get("raw") or {}),
        )

    async def _maybe_halt_for_heartbeat_failure(
        self,
        robot_id: str,
        loaded: LoadedDriver,
        failure_count: int,
        heartbeat_exc: Exception,
    ) -> None:
        if self.config is None:
            return
        threshold = self.config.watch.heartbeat_failure_threshold
        if failure_count < threshold or robot_id in self._watchdog_halted_robots:
            return

        self._watchdog_halted_robots.add(robot_id)
        if not self.config.watch.halt_on_heartbeat_failure:
            self._record_watchdog_halt(
                robot_id=robot_id,
                failure_count=failure_count,
                threshold=threshold,
                halt_status="disabled",
                heartbeat_exc=heartbeat_exc,
            )
            return

        try:
            await loaded.driver.halt()
        except Exception as halt_exc:
            self._record_watchdog_halt(
                robot_id=robot_id,
                failure_count=failure_count,
                threshold=threshold,
                halt_status="failed",
                heartbeat_exc=heartbeat_exc,
                halt_exc=halt_exc,
            )
        else:
            self._record_watchdog_halt(
                robot_id=robot_id,
                failure_count=failure_count,
                threshold=threshold,
                halt_status="completed",
                heartbeat_exc=heartbeat_exc,
            )

    def _record_driver_hook_failure(
        self,
        robot_id: str,
        hook: str,
        exc: Exception,
        *,
        extra_result: dict[str, Any] | None = None,
    ) -> None:
        error_type = type(exc).__name__
        error_message = str(exc)
        message = (
            f"Driver {hook} failed for robot `{robot_id}`: "
            f"{error_type}: {error_message}"
        )
        result = {
            "hook": hook,
            "error_type": error_type,
            "error_message": error_message,
        }
        if extra_result is not None:
            result.update(extra_result)
        latest = {
            "status": "failed",
            "event": f"driver_{hook}",
            "robot": robot_id,
            "robot_id": robot_id,
            "message": message,
            "result": result,
            "artifacts": [],
        }
        self._record_driver_feedback(latest, message)

    def _record_heartbeat_recovered(
        self,
        robot_id: str,
        previous_failure_count: int,
    ) -> None:
        message = (
            f"Driver heartbeat recovered for robot `{robot_id}` "
            f"after {previous_failure_count} consecutive failure(s)."
        )
        latest = {
            "status": "completed",
            "event": "driver_heartbeat_recovered",
            "robot": robot_id,
            "robot_id": robot_id,
            "failure_count": previous_failure_count,
            "message": message,
            "result": {
                "hook": "heartbeat",
                "failure_count": previous_failure_count,
            },
            "artifacts": [],
        }
        self._record_driver_feedback(latest, message)

    def _record_watchdog_halt(
        self,
        *,
        robot_id: str,
        failure_count: int,
        threshold: int,
        halt_status: str,
        heartbeat_exc: Exception,
        halt_exc: Exception | None = None,
    ) -> None:
        heartbeat_error_type = type(heartbeat_exc).__name__
        heartbeat_error_message = str(heartbeat_exc)
        error_type = type(halt_exc).__name__ if halt_exc is not None else heartbeat_error_type
        error_message = str(halt_exc) if halt_exc is not None else heartbeat_error_message
        message = (
            f"Heartbeat watchdog threshold reached for robot `{robot_id}` "
            f"after {failure_count} consecutive failure(s); "
            f"threshold={threshold}; halt_status={halt_status}."
        )
        if halt_exc is not None:
            message = (
                f"{message} Halt failed: "
                f"{type(halt_exc).__name__}: {halt_exc}"
            )
        latest = {
            "status": "failed",
            "event": "driver_watchdog_halt",
            "robot": robot_id,
            "robot_id": robot_id,
            "failure_count": failure_count,
            "threshold": threshold,
            "halt_status": halt_status,
            "message": message,
            "result": {
                "hook": "halt",
                "failure_count": failure_count,
                "threshold": threshold,
                "halt_status": halt_status,
                "heartbeat_error_type": heartbeat_error_type,
                "heartbeat_error_message": heartbeat_error_message,
                "error_type": error_type,
                "error_message": error_message,
            },
            "artifacts": [],
        }
        self._record_driver_feedback(latest, message)

    def _record_driver_feedback(self, latest: dict[str, Any], message: str) -> None:
        self._record_feedback_event(latest, message)

    def _record_feedback_event(self, latest: dict[str, Any], message: str) -> None:
        workspace = self._workspace()
        feedback = workspace.read_feedback()
        history = list(feedback["history"])
        history.append(latest)
        workspace.write_feedback(latest, history)
        workspace.append_log(message, actor="watch")

    def _workspace(self) -> StateStore:
        if self.workspace is None:
            raise RuntimeError("WatchRuntime has not been set up.")
        return self.workspace


def merge_observations(
    observations: list[Observation],
    *,
    base: Observation | None = None,
) -> Observation:
    if not observations and base is not None:
        return _ordered_observation(base)
    if not observations:
        return Observation(summary="No robots are configured.")
    summary = " ".join(observation.summary for observation in observations if observation.summary)
    robots: dict[str, Any] = dict(base.robots) if base is not None else {}
    objects: dict[str, Any] = dict(base.objects) if base is not None else {}
    environment: dict[str, Any] = dict(base.environment) if base is not None else {}
    artifacts: list[str] = list(base.artifacts) if base is not None else []
    raw: dict[str, Any] = dict(base.raw) if base is not None else {}
    for observation in observations:
        robots.update(observation.robots)
        objects.update(observation.objects)
        environment.update(observation.environment)
        artifacts.extend(observation.artifacts)
        raw.update(observation.raw)
    return Observation(
        summary=summary,
        robots=_ordered_mapping(robots),
        objects=_ordered_mapping(objects),
        environment=_ordered_mapping(environment),
        artifacts=artifacts,
        raw=_ordered_mapping(raw),
    )


def _ordered_observation(observation: Observation) -> Observation:
    return Observation(
        summary=observation.summary,
        robots=_ordered_mapping(observation.robots),
        objects=_ordered_mapping(observation.objects),
        environment=_ordered_mapping(observation.environment),
        artifacts=list(observation.artifacts),
        raw=_ordered_mapping(observation.raw),
    )


def _ordered_mapping(value: dict[str, Any]) -> dict[str, Any]:
    return {key: value[key] for key in sorted(value, key=str)}


def _expected_checks(action: Action) -> list[dict[str, Any]]:
    metadata = action.metadata if isinstance(action.metadata, dict) else {}
    if "expected" not in metadata:
        return []
    return normalize_expected_value(metadata.get("expected"))


def _transport_action_failure_result(exc: Exception) -> ActionResult:
    error_type = type(exc).__name__
    if isinstance(exc, TransportReconnecting):
        message = (
            "Transport is reconnecting; execute failed fast and command was not "
            f"queued: {exc}"
        )
    elif isinstance(exc, TransportReconnectFailed):
        message = (
            "Transport reconnect exhausted when action was attempted; command "
            f"was not queued: {exc}"
        )
    elif isinstance(exc, TransportDisconnected):
        message = (
            "Transport is disconnected; execute failed fast and command was not "
            f"queued: {exc}"
        )
    else:
        message = (
            "Transport disconnected during execution; execution state unknown; "
            f"action will not be retried automatically: {exc}"
        )
    return ActionResult(
        status="failed",
        message=message,
        result={"error_type": error_type},
    )
