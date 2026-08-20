from __future__ import annotations

import threading

import pytest

from physical_agent.drivers.transport import (
    LoopbackTransport,
    ReconnectPolicy,
    TransportClosedError,
    TransportReconnectFailed,
    TransportReconnecting,
    TransportTimeoutError,
)


class _DelayedOpenLoopbackTransport(LoopbackTransport):
    def __init__(
        self,
        *,
        entered: threading.Event,
        release: threading.Event,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._entered = entered
        self._release = release

    def _open_once(self) -> None:
        self._entered.set()
        if not self._release.wait(timeout=1):
            raise AssertionError("test did not release delayed open")
        super()._open_once()


def test_loopback_transport_open_write_read_and_health():
    transport = LoopbackTransport()
    assert transport.health().status == "closed"

    transport.open()
    health = transport.health()
    assert health.ok is True
    assert health.status == "open"

    transport.write(b"hello")
    assert transport.drain_written() == b"hello"
    assert transport.drain_written() == b""

    transport.inject_read_data(b"world")
    assert transport.read(timeout_s=0.05) == b"world"

    transport.close()
    assert transport.health().status == "closed"


def test_loopback_transport_read_timeout_is_clear():
    transport = LoopbackTransport()
    transport.open()

    with pytest.raises(TransportTimeoutError, match="Loopback read timed out"):
        transport.read(timeout_s=0.01)

    health = transport.health()
    assert health.ok is True
    assert health.status == "open"
    assert "timed out" in health.details["last_error"]


def test_loopback_transport_closed_state_rejects_io():
    transport = LoopbackTransport()

    with pytest.raises(TransportClosedError, match="not open"):
        transport.write(b"closed")
    with pytest.raises(TransportClosedError, match="not open"):
        transport.read(timeout_s=0)
    with pytest.raises(TransportClosedError, match="not open"):
        transport.inject_read_data(b"closed")

    transport.open()
    transport.write(b"before-close")
    transport.close()

    with pytest.raises(TransportClosedError, match="not open"):
        transport.write(b"after-close")
    assert transport.drain_written() == b"before-close"


def test_loopback_reconnect_policy_retries_connect_with_backoff():
    sleeps: list[float] = []
    transport = LoopbackTransport(
        reconnect_policy=ReconnectPolicy(
            enabled=True,
            max_retries=2,
            backoff_base_ms=10,
            backoff_cap_ms=100,
        ),
        reconnect_sleeper=sleeps.append,
        fail_connect_attempts=2,
    )

    transport.open()

    assert transport.is_open is True
    assert transport.connection_state == "connected"
    assert transport.open_attempts == 3
    assert sleeps == [0.01, 0.02]


def test_loopback_reconnect_policy_exhausts_max_retries():
    transport = LoopbackTransport(
        reconnect_policy={
            "enabled": True,
            "max_retries": 1,
            "backoff_base_ms": 10,
            "backoff_cap_ms": 10,
        },
        reconnect_sleeper=lambda _delay: None,
        fail_connect_attempts=99,
    )

    with pytest.raises(TransportReconnectFailed, match="failed after 2 attempt"):
        transport.open()

    assert transport.is_open is False
    assert transport.open_attempts == 2
    assert transport.connection_state == "disconnected"


def test_loopback_reconnecting_write_fails_fast_without_queueing():
    transport = LoopbackTransport(
        reconnect_policy=ReconnectPolicy(
            enabled=True,
            max_retries=1,
            backoff_base_ms=100,
            backoff_cap_ms=100,
        )
    )
    transport.open()
    transport.set_fail_connect_attempts(99)
    transport.simulate_disconnect(start_reconnect=True)

    with pytest.raises(TransportReconnecting, match="not queued"):
        transport.write(b"must-not-queue")

    assert transport.drain_written() == b""
    transport.close()


def test_loopback_cancelled_background_reconnect_cleans_late_open():
    entered = threading.Event()
    release = threading.Event()
    hooks: list[str] = []
    transport = _DelayedOpenLoopbackTransport(
        entered=entered,
        release=release,
        reconnect_policy=ReconnectPolicy(
            enabled=True,
            max_retries=0,
            backoff_base_ms=1,
            backoff_cap_ms=1,
        ),
        on_reconnected=lambda: hooks.append("called"),
    )

    transport._start_background_reconnect(  # noqa: SLF001 - lifecycle race coverage
        open_once=transport._open_once,
        label="Loopback transport",
    )
    thread = transport._reconnect_thread  # noqa: SLF001
    assert thread is not None
    assert entered.wait(timeout=1)

    transport._reconnect_cancel.set()  # noqa: SLF001
    release.set()
    thread.join(timeout=1)

    assert thread.is_alive() is False
    assert transport.is_open is False
    assert transport.connection_state == "disconnected"
    assert hooks == []


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_retries": -1},
        {"backoff_base_ms": 0},
        {"backoff_base_ms": 50, "backoff_cap_ms": 10},
        {"jitter_ms": -1},
    ],
)
def test_reconnect_policy_validation(kwargs):
    with pytest.raises(ValueError):
        ReconnectPolicy(**kwargs)
