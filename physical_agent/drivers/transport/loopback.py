from __future__ import annotations

import threading
import time
from typing import Any

from physical_agent.drivers.transport.base import (
    ReconnectCallback,
    ReconnectPolicy,
    ReconnectSleeper,
    ReconnectableTransport,
    TransportClosedError,
    TransportError,
    TransportHealth,
    TransportTimeoutError,
)


class LoopbackTransport(ReconnectableTransport):
    """In-memory byte transport for watch-side tests and local simulations."""

    def __init__(
        self,
        *,
        reconnect_policy: ReconnectPolicy | dict[str, Any] | None = None,
        reconnect_sleeper: ReconnectSleeper | None = None,
        on_reconnected: ReconnectCallback | None = None,
        fail_connect_attempts: int = 0,
    ) -> None:
        super().__init__(
            reconnect_policy=reconnect_policy,
            reconnect_sleeper=reconnect_sleeper,
            on_reconnected=on_reconnected,
        )
        self._condition = threading.Condition()
        self._is_open = False
        self._read_buffer = bytearray()
        self._written_buffer = bytearray()
        self._fail_connect_attempts = max(0, int(fail_connect_attempts))
        self.open_attempts = 0

    @property
    def is_open(self) -> bool:
        return self._is_open

    def open(self) -> None:
        self._open_with_reconnect_policy(
            open_once=self._open_once,
            label="Loopback transport",
        )

    def _open_once(self) -> None:
        with self._condition:
            self.open_attempts += 1
            if self._fail_connect_attempts > 0:
                self._fail_connect_attempts -= 1
                self._last_error = "Loopback simulated connect failure"
                raise TransportError(self._last_error)
            self._is_open = True
            self._last_error = None
            self._condition.notify_all()

    def close(self) -> None:
        self._cancel_background_reconnect()
        with self._condition:
            self._is_open = False
            self._read_buffer.clear()
            self._condition.notify_all()
        self._set_transport_error(None)
        self._mark_transport_disconnected()

    def write(self, data: bytes) -> None:
        payload = bytes(data)
        with self._condition:
            self._require_open_locked()
            self._written_buffer.extend(payload)

    def read(self, timeout_s: float) -> bytes:
        timeout = max(0.0, float(timeout_s))
        deadline = time.monotonic() + timeout
        with self._condition:
            self._require_open_locked()
            while not self._read_buffer:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._last_error = f"Loopback read timed out after {timeout:g}s"
                    raise TransportTimeoutError(self._last_error)
                self._condition.wait(timeout=remaining)
                self._require_open_locked()

            payload = bytes(self._read_buffer)
            self._read_buffer.clear()
            return payload

    def inject_read_data(self, data: bytes) -> None:
        payload = bytes(data)
        with self._condition:
            self._require_open_locked()
            self._read_buffer.extend(payload)
            self._condition.notify_all()

    def drain_written(self) -> bytes:
        with self._condition:
            payload = bytes(self._written_buffer)
            self._written_buffer.clear()
            return payload

    def health(self) -> TransportHealth:
        with self._condition:
            if self._is_open:
                return TransportHealth(
                    ok=True,
                    status="open",
                    message="Loopback transport open",
                    details={
                        "read_buffer_bytes": len(self._read_buffer),
                        "written_buffer_bytes": len(self._written_buffer),
                        "last_error": self._last_error,
                        "connection_state": self.connection_state,
                        "reconnect_attempts": self.reconnect_attempts,
                    },
                )
            if self.connection_state == "reconnecting":
                return TransportHealth(
                    ok=False,
                    status="reconnecting",
                    message="Loopback transport reconnecting",
                    details={
                        "last_error": self._last_error,
                        "reconnect_attempts": self.reconnect_attempts,
                    },
                )
            return TransportHealth(
                ok=False,
                status="closed",
                message="Loopback transport closed",
                details={
                    "last_error": self._last_error,
                    "connection_state": self.connection_state,
                    "reconnect_attempts": self.reconnect_attempts,
                },
            )

    def set_fail_connect_attempts(self, count: int) -> None:
        self._fail_connect_attempts = max(0, int(count))

    def simulate_disconnect(self, *, start_reconnect: bool = True) -> None:
        with self._condition:
            self._is_open = False
            self._read_buffer.clear()
            self._condition.notify_all()
        self._mark_transport_disconnected("Loopback simulated disconnect")
        if start_reconnect:
            self._start_background_reconnect(
                open_once=self._open_once,
                label="Loopback transport",
            )

    def _require_open_locked(self) -> None:
        try:
            self._ensure_transport_ready_for_io(
                is_open=self._is_open,
                label="Loopback transport",
            )
        except TransportClosedError:
            raise

    def _cleanup_after_cancelled_open(self) -> None:
        with self._condition:
            self._is_open = False
            self._read_buffer.clear()
            self._condition.notify_all()
