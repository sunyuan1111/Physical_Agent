from __future__ import annotations

import importlib
from types import ModuleType
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


_INSTALL_HINT = 'Install with pip install -e ".[serial]"'


class SerialTransport(ReconnectableTransport):
    """PySerial-backed byte transport for watch-side drivers."""

    def __init__(
        self,
        *,
        port: str,
        baudrate: int = 115200,
        timeout_s: float = 1.0,
        write_timeout_s: float | None = None,
        serial_module: Any | None = None,
        reconnect_policy: ReconnectPolicy | dict[str, Any] | None = None,
        reconnect_sleeper: ReconnectSleeper | None = None,
        on_reconnected: ReconnectCallback | None = None,
    ) -> None:
        super().__init__(
            reconnect_policy=reconnect_policy,
            reconnect_sleeper=reconnect_sleeper,
            on_reconnected=on_reconnected,
        )
        self.port = str(port)
        self.baudrate = int(baudrate)
        self.timeout_s = float(timeout_s)
        self.write_timeout_s = (
            None if write_timeout_s is None else float(write_timeout_s)
        )
        self._serial_module = serial_module if serial_module is not None else _import_pyserial()
        self._serial: Any | None = None

    @property
    def is_open(self) -> bool:
        conn = self._serial
        return conn is not None and bool(getattr(conn, "is_open", True))

    def open(self) -> None:
        self._open_with_reconnect_policy(
            open_once=self._open_once,
            label=f"Serial transport {self.port}",
        )

    def _open_once(self) -> None:
        self._close_serial_handle()
        self._last_error = None
        try:
            self._serial = self._serial_module.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=self.timeout_s,
                write_timeout=self.write_timeout_s,
            )
        except _serial_exception_types(self._serial_module) as exc:
            self._last_error = f"Serial connection failed: {exc}"
            raise TransportError(self._last_error) from exc
        except (OSError, ValueError) as exc:
            self._last_error = f"Serial connection failed: {exc}"
            raise TransportError(self._last_error) from exc

    def close(self) -> None:
        self._cancel_background_reconnect()
        self._close_serial_handle()
        self._set_transport_error(None)
        self._mark_transport_disconnected()

    def _close_serial_handle(self) -> None:
        conn = self._serial
        self._serial = None
        if conn is None:
            return
        try:
            conn.close()
        except _serial_exception_types(self._serial_module) as exc:
            self._last_error = f"Serial close failed: {exc}"
        except OSError as exc:
            self._last_error = f"Serial close failed: {exc}"

    def write(self, data: bytes) -> None:
        payload = bytes(data)
        conn = self._require_serial()
        written: int | None = None
        try:
            written = conn.write(payload)
            flush = getattr(conn, "flush", None)
            if callable(flush):
                flush()
        except _serial_timeout_types(self._serial_module) as exc:
            self._last_error = "Serial write timed out"
            raise TransportTimeoutError(self._last_error) from exc
        except _serial_exception_types(self._serial_module) as exc:
            self._last_error = f"Serial write failed: {exc}"
            self._drop_serial_after_disconnect()
            raise TransportClosedError(self._last_error) from exc
        except OSError as exc:
            self._last_error = f"Serial write failed: {exc}"
            self._drop_serial_after_disconnect()
            raise TransportClosedError(self._last_error) from exc
        if written is not None and int(written) < len(payload):
            self._last_error = "Serial write timed out before all bytes were written"
            raise TransportTimeoutError(self._last_error)

    def read(self, timeout_s: float) -> bytes:
        conn = self._require_serial()
        previous_timeout = getattr(conn, "timeout", None)
        can_restore_timeout = hasattr(conn, "timeout")
        try:
            if can_restore_timeout:
                conn.timeout = float(timeout_s)
            available = int(getattr(conn, "in_waiting", 0) or 0)
            size = max(1, available)
            data = bytes(conn.read(size))
        except _serial_timeout_types(self._serial_module) as exc:
            self._last_error = "Serial read timed out"
            raise TransportTimeoutError(self._last_error) from exc
        except _serial_exception_types(self._serial_module) as exc:
            self._last_error = f"Serial read failed: {exc}"
            self._drop_serial_after_disconnect()
            raise TransportClosedError(self._last_error) from exc
        except OSError as exc:
            self._last_error = f"Serial read failed: {exc}"
            self._drop_serial_after_disconnect()
            raise TransportClosedError(self._last_error) from exc
        finally:
            if can_restore_timeout and self._serial is conn:
                conn.timeout = previous_timeout

        if not data:
            self._last_error = f"Serial read timed out after {float(timeout_s):g}s"
            raise TransportTimeoutError(self._last_error)
        return data

    def health(self) -> TransportHealth:
        if self.is_open:
            return TransportHealth(
                ok=True,
                status="open",
                message="Serial transport open",
                details={
                    "port": self.port,
                    "baudrate": self.baudrate,
                    "timeout_s": self.timeout_s,
                    "write_timeout_s": self.write_timeout_s,
                    "last_error": self._last_error,
                    "connection_state": self.connection_state,
                    "reconnect_attempts": self.reconnect_attempts,
                },
            )
        if self.connection_state == "reconnecting":
            return TransportHealth(
                ok=False,
                status="reconnecting",
                message="Serial transport reconnecting",
                details={
                    "port": self.port,
                    "baudrate": self.baudrate,
                    "last_error": self._last_error,
                    "reconnect_attempts": self.reconnect_attempts,
                },
            )
        if self._last_error:
            if not self.reconnect_exhausted:
                self._start_reconnect_after_disconnect()
            if self.connection_state == "reconnecting":
                return TransportHealth(
                    ok=False,
                    status="reconnecting",
                    message="Serial transport reconnecting",
                    details={
                        "port": self.port,
                        "baudrate": self.baudrate,
                        "last_error": self._last_error,
                        "reconnect_attempts": self.reconnect_attempts,
                    },
                )
            return TransportHealth(
                ok=False,
                status="error",
                message=self._last_error,
                details={
                    "port": self.port,
                    "baudrate": self.baudrate,
                    "connection_state": self.connection_state,
                    "reconnect_attempts": self.reconnect_attempts,
                },
            )
        return TransportHealth(
            ok=False,
            status="closed",
            message="Serial transport closed",
            details={
                "port": self.port,
                "baudrate": self.baudrate,
                "connection_state": self.connection_state,
                "reconnect_attempts": self.reconnect_attempts,
            },
        )

    def _require_serial(self) -> Any:
        conn = self._serial
        is_open = conn is not None and bool(getattr(conn, "is_open", True))
        if conn is not None and not is_open:
            self._last_error = "Serial transport port is closed"
            self._drop_serial_after_disconnect()
            is_open = False
        self._ensure_transport_ready_for_io(
            is_open=is_open,
            label="Serial transport",
        )
        assert conn is not None
        return conn

    def _drop_serial_after_disconnect(self) -> None:
        self._close_serial_handle()
        self._mark_transport_disconnected(self._last_error)
        self._start_reconnect_after_disconnect()

    def _start_reconnect_after_disconnect(self) -> None:
        self._start_background_reconnect(
            open_once=self._open_once,
            label=f"Serial transport {self.port}",
        )

    def _cleanup_after_cancelled_open(self) -> None:
        self._close_serial_handle()


def _import_pyserial() -> ModuleType:
    try:
        return importlib.import_module("serial")
    except ModuleNotFoundError as exc:
        raise TransportError(f"pyserial is required for SerialTransport. {_INSTALL_HINT}") from exc


def _serial_exception_types(serial_module: Any) -> tuple[type[BaseException], ...]:
    serial_exception = getattr(serial_module, "SerialException", None)
    if isinstance(serial_exception, type) and issubclass(serial_exception, BaseException):
        return (serial_exception,)
    return ()


def _serial_timeout_types(serial_module: Any) -> tuple[type[BaseException], ...]:
    timeout_exception = getattr(serial_module, "SerialTimeoutException", None)
    if isinstance(timeout_exception, type) and issubclass(timeout_exception, BaseException):
        return (timeout_exception,)
    return ()
