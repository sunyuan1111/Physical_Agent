from __future__ import annotations

import asyncio
import time

from physical_agent.drivers.base import PhysicalDriver
from physical_agent.drivers.transport import LoopbackTransport, ReconnectPolicy
from physical_agent.protocol.schemas import (
    Action,
    ActionResult,
    Capability,
    DriverContext,
    HealthStatus,
    Observation,
)


class _MinimalDriver(PhysicalDriver):
    async def connect(self) -> None:
        return None

    async def disconnect(self) -> None:
        return None

    async def health(self) -> HealthStatus:
        return HealthStatus(ok=True)

    async def observe(self) -> Observation:
        return Observation(summary="minimal")

    def capabilities(self) -> list[Capability]:
        return []

    async def execute(self, action: Action) -> ActionResult:
        return ActionResult(status="failed", message="not implemented")


def test_driver_contract_heartbeat_and_halt_default_to_noop(tmp_path):
    driver = _MinimalDriver(
        DriverContext(
            robot_id="minimal_1",
            config={},
            workspace_path=tmp_path / "workspace",
            artifacts_path=tmp_path / "workspace" / "artifacts",
        )
    )

    assert asyncio.run(driver.heartbeat()) is None
    assert asyncio.run(driver.halt()) is None
    assert asyncio.run(driver.on_transport_reconnected()) is None


def test_driver_reconnect_hook_can_be_called_after_transport_reconnect(tmp_path):
    calls: list[str] = []

    class HookDriver(_MinimalDriver):
        async def on_transport_reconnected(self) -> None:
            calls.append("reconnected")

    driver = HookDriver(
        DriverContext(
            robot_id="minimal_1",
            config={},
            workspace_path=tmp_path / "workspace",
            artifacts_path=tmp_path / "workspace" / "artifacts",
        )
    )

    def on_reconnected() -> None:
        asyncio.run(driver.on_transport_reconnected())

    transport = LoopbackTransport(
        reconnect_policy=ReconnectPolicy(
            enabled=True,
            max_retries=1,
            backoff_base_ms=1,
            backoff_cap_ms=1,
        ),
        on_reconnected=on_reconnected,
    )
    transport.open()
    transport.simulate_disconnect(start_reconnect=True)

    for _ in range(100):
        if calls:
            break
        time.sleep(0.01)

    transport.close()

    assert calls == ["reconnected"]
