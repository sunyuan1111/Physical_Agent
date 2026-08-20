from __future__ import annotations

import pytest

from physical_agent.drivers.transport import (
    ReconnectPolicy,
    SerialTransport,
    TransportClosedError,
    TransportError,
    TransportReconnectFailed,
    TransportTimeoutError,
)
from physical_agent.drivers.transport import serial as serial_transport_module


def test_serial_transport_missing_pyserial_has_clear_error(monkeypatch):
    def missing_serial(name: str):
        assert name == "serial"
        raise ModuleNotFoundError("No module named 'serial'")

    monkeypatch.setattr(serial_transport_module.importlib, "import_module", missing_serial)

    with pytest.raises(TransportError) as exc_info:
        SerialTransport(port="COM3")

    assert 'Install with pip install -e ".[serial]"' in str(exc_info.value)


def test_serial_transport_fake_serial_open_write_read_close_health():
    fake_module = _FakeSerialModule(read_data=b"ok")
    transport = SerialTransport(
        port="COM3",
        baudrate=9600,
        timeout_s=0.2,
        write_timeout_s=0.3,
        serial_module=fake_module,
    )

    assert transport.health().status == "closed"
    transport.open()

    fake = fake_module.instances[0]
    assert fake.port == "COM3"
    assert fake.baudrate == 9600
    assert fake.timeout == 0.2
    assert fake.write_timeout == 0.3

    health = transport.health()
    assert health.ok is True
    assert health.status == "open"
    assert health.details["port"] == "COM3"

    transport.write(b"ping")
    assert fake.written == b"ping"
    assert fake.flush_count == 1

    assert transport.read(timeout_s=0.05) == b"ok"
    assert fake.timeout == 0.2

    transport.close()
    assert fake.is_open is False
    assert transport.health().status == "closed"


def test_serial_transport_write_timeout_is_transport_timeout():
    fake_module = _FakeSerialModule(write_timeout=True)
    transport = SerialTransport(port="/dev/ttyUSB0", serial_module=fake_module)
    transport.open()

    with pytest.raises(TransportTimeoutError, match="Serial write timed out"):
        transport.write(b"cmd")

    health = transport.health()
    assert health.ok is True
    assert health.status == "open"
    assert "write timed out" in health.details["last_error"]


def test_serial_transport_read_timeout_is_transport_timeout():
    fake_module = _FakeSerialModule(read_data=b"")
    transport = SerialTransport(port="/dev/ttyUSB0", serial_module=fake_module)
    transport.open()

    with pytest.raises(TransportTimeoutError, match="Serial read timed out"):
        transport.read(timeout_s=0.01)

    health = transport.health()
    assert health.ok is True
    assert health.status == "open"
    assert "read timed out" in health.details["last_error"]


def test_serial_transport_retries_open_with_reconnect_policy():
    sleeps: list[float] = []
    fake_module = _FakeSerialModule(read_data=b"ok", open_failures=1)
    transport = SerialTransport(
        port="/dev/ttyUSB0",
        serial_module=fake_module,
        reconnect_policy=ReconnectPolicy(
            enabled=True,
            max_retries=1,
            backoff_base_ms=10,
            backoff_cap_ms=10,
        ),
        reconnect_sleeper=sleeps.append,
    )

    transport.open()

    assert transport.is_open is True
    assert fake_module.open_calls == 2
    assert len(fake_module.instances) == 1
    assert sleeps == [0.01]


def test_serial_transport_reconnect_exhausted_has_clear_error():
    fake_module = _FakeSerialModule(open_failures=99)
    transport = SerialTransport(
        port="/dev/ttyUSB0",
        serial_module=fake_module,
        reconnect_policy={
            "enabled": True,
            "max_retries": 1,
            "backoff_base_ms": 10,
            "backoff_cap_ms": 10,
        },
        reconnect_sleeper=lambda _delay: None,
    )

    with pytest.raises(TransportReconnectFailed, match="failed after 2 attempt"):
        transport.open()

    assert fake_module.open_calls == 2
    assert transport.health().status == "error"


def test_serial_transport_read_os_error_marks_disconnected_and_can_reopen():
    fake_module = _FakeSerialModule(read_os_error=True)
    transport = SerialTransport(port="/dev/ttyUSB0", serial_module=fake_module)
    transport.open()

    with pytest.raises(TransportClosedError, match="Serial read failed"):
        transport.read(timeout_s=0.01)

    assert transport.is_open is False
    health = transport.health()
    assert health.ok is False
    assert health.status == "error"
    assert "Serial read failed" in health.message

    fake_module.read_os_error = False
    fake_module.read_data = b"ok"
    transport.open()
    assert transport.read(timeout_s=0.01) == b"ok"


class _FakeSerialException(Exception):
    pass


class _FakeSerialTimeoutException(_FakeSerialException, TimeoutError):
    pass


class _FakeSerialModule:
    SerialException = _FakeSerialException
    SerialTimeoutException = _FakeSerialTimeoutException

    def __init__(
        self,
        *,
        read_data: bytes = b"",
        write_timeout: bool = False,
        read_timeout: bool = False,
        write_os_error: bool = False,
        read_os_error: bool = False,
        open_failures: int = 0,
    ) -> None:
        self.read_data = read_data
        self.write_timeout = write_timeout
        self.read_timeout = read_timeout
        self.write_os_error = write_os_error
        self.read_os_error = read_os_error
        self.open_failures = open_failures
        self.open_calls = 0
        self.instances: list[_FakeSerial] = []

    def Serial(
        self,
        *,
        port: str,
        baudrate: int,
        timeout: float,
        write_timeout: float | None,
    ) -> "_FakeSerial":
        self.open_calls += 1
        if self.open_failures > 0:
            self.open_failures -= 1
            raise _FakeSerialException("open failed")
        instance = _FakeSerial(
            port=port,
            baudrate=baudrate,
            timeout=timeout,
            write_timeout=write_timeout,
            read_data=self.read_data,
            write_timeout_enabled=self.write_timeout,
            read_timeout_enabled=self.read_timeout,
            write_os_error_enabled=self.write_os_error,
            read_os_error_enabled=self.read_os_error,
        )
        self.instances.append(instance)
        return instance


class _FakeSerial:
    def __init__(
        self,
        *,
        port: str,
        baudrate: int,
        timeout: float,
        write_timeout: float | None,
        read_data: bytes,
        write_timeout_enabled: bool,
        read_timeout_enabled: bool,
        write_os_error_enabled: bool,
        read_os_error_enabled: bool,
    ) -> None:
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.write_timeout = write_timeout
        self._read_buffer = bytearray(read_data)
        self.write_timeout_enabled = write_timeout_enabled
        self.read_timeout_enabled = read_timeout_enabled
        self.write_os_error_enabled = write_os_error_enabled
        self.read_os_error_enabled = read_os_error_enabled
        self.written = b""
        self.flush_count = 0
        self.is_open = True

    @property
    def in_waiting(self) -> int:
        return len(self._read_buffer)

    def write(self, data: bytes) -> int:
        if self.write_timeout_enabled:
            raise _FakeSerialTimeoutException("write timeout")
        if self.write_os_error_enabled:
            raise OSError("port disappeared")
        payload = bytes(data)
        self.written += payload
        return len(payload)

    def read(self, size: int = 1) -> bytes:
        if self.read_timeout_enabled:
            raise _FakeSerialTimeoutException("read timeout")
        if self.read_os_error_enabled:
            raise OSError("port disappeared")
        payload = bytes(self._read_buffer[:size])
        del self._read_buffer[:size]
        return payload

    def flush(self) -> None:
        self.flush_count += 1

    def close(self) -> None:
        self.is_open = False
