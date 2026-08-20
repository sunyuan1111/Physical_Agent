from __future__ import annotations

from abc import ABC, abstractmethod

from physical_agent.protocol.schemas import (
    Action,
    ActionResult,
    Capability,
    DriverContext,
    HealthStatus,
    Observation,
)


class PhysicalDriver(ABC):
    """Base class for physical adapters owned by the watch process."""

    def __init__(self, context: DriverContext):
        self.context = context

    @abstractmethod
    async def connect(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def disconnect(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def health(self) -> HealthStatus:
        raise NotImplementedError

    @abstractmethod
    async def observe(self) -> Observation:
        raise NotImplementedError

    @abstractmethod
    def capabilities(self) -> list[Capability]:
        raise NotImplementedError

    @abstractmethod
    async def execute(self, action: Action) -> ActionResult:
        raise NotImplementedError

    async def heartbeat(self) -> None:
        """Optional hardware keepalive hook; no-op unless a driver overrides it."""

        return None

    async def halt(self) -> None:
        """Optional emergency stop hook; no-op unless a driver overrides it."""

        return None

    async def on_transport_reconnected(self) -> None:
        """Optional hook after a driver-owned transport reconnects."""

        return None

