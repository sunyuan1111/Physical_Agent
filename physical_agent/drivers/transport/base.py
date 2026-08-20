from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import logging
import random
import threading
import time
from typing import Any, Literal, Protocol, runtime_checkable


TransportConnectionState = Literal["connected", "disconnected", "reconnecting"]
ReconnectCallback = Callable[[], None]
ReconnectSleeper = Callable[[float], None]


@dataclass(frozen=True)
class TransportHealth:
    ok: bool
    status: str
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ReconnectPolicy:
    enabled: bool = False
    max_retries: int = 3
    backoff_base_ms: int = 250
    backoff_cap_ms: int = 5000
    jitter_ms: int = 0

    def __post_init__(self) -> None:
        if self.max_retries < 0:
            raise ValueError("reconnect_policy.max_retries must be >= 0")
        if self.backoff_base_ms <= 0:
            raise ValueError("reconnect_policy.backoff_base_ms must be > 0")
        if self.backoff_cap_ms < self.backoff_base_ms:
            raise ValueError(
                "reconnect_policy.backoff_cap_ms must be >= backoff_base_ms"
            )
        if self.jitter_ms < 0:
            raise ValueError("reconnect_policy.jitter_ms must be >= 0")

    @classmethod
    def from_config(cls, value: Any | None) -> ReconnectPolicy:
        if value is None:
            return cls()
        if isinstance(value, ReconnectPolicy):
            return value
        if not isinstance(value, dict):
            raise ValueError("reconnect_policy must be an object")
        return cls(**value)

    def delay_s(self, attempt: int) -> float:
        delay_ms = min(self.backoff_cap_ms, self.backoff_base_ms * (2 ** attempt))
        if self.jitter_ms:
            delay_ms += random.uniform(0, self.jitter_ms)
        return delay_ms / 1000.0


class TransportError(RuntimeError):
    """Base error raised by watch-side byte transports."""


class TransportTimeoutError(TimeoutError, TransportError):
    """Raised when a transport operation exceeds its timeout."""


class TransportClosedError(TransportError):
    """Raised when the peer closes before an operation can complete."""


class TransportDisconnected(TransportClosedError):
    """Raised when an operation needs a connected transport but none is open."""


class TransportReconnecting(TransportDisconnected):
    """Raised when an operation is attempted while reconnect is in progress."""


class TransportReconnectFailed(TransportError):
    """Raised when reconnect policy is exhausted."""


class TransportProtocolError(TransportError):
    """Raised when the peer violates the expected transport protocol."""


class ReconnectableTransport:
    """Reusable sync reconnect helper for watch-side byte transports."""

    def __init__(
        self,
        *,
        reconnect_policy: ReconnectPolicy | dict[str, Any] | None = None,
        reconnect_sleeper: ReconnectSleeper | None = None,
        on_reconnected: ReconnectCallback | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.reconnect_policy = ReconnectPolicy.from_config(reconnect_policy)
        self._reconnect_sleeper = reconnect_sleeper or time.sleep
        self._on_reconnected = on_reconnected
        self._logger = logger or logging.getLogger(__name__)
        self._connection_state: TransportConnectionState = "disconnected"
        self._last_error: str | None = None
        self._reconnect_attempts = 0
        self._reconnect_lock = threading.RLock()
        self._reconnect_cancel = threading.Event()
        self._reconnect_thread: threading.Thread | None = None
        self._closing = False
        self._reconnect_exhausted = False

    @property
    def connection_state(self) -> TransportConnectionState:
        with self._reconnect_lock:
            return self._connection_state

    @property
    def last_error(self) -> str | None:
        with self._reconnect_lock:
            return self._last_error

    @property
    def reconnect_attempts(self) -> int:
        with self._reconnect_lock:
            return self._reconnect_attempts

    @property
    def reconnect_exhausted(self) -> bool:
        with self._reconnect_lock:
            return self._reconnect_exhausted

    def _set_transport_error(self, message: str | None) -> None:
        with self._reconnect_lock:
            self._last_error = message

    def _mark_transport_connected(self) -> None:
        with self._reconnect_lock:
            self._connection_state = "connected"
            self._last_error = None

    def _mark_transport_disconnected(self, message: str | None = None) -> None:
        with self._reconnect_lock:
            if self._connection_state != "reconnecting":
                self._connection_state = "disconnected"
            if message:
                self._last_error = message

    def _open_with_reconnect_policy(
        self,
        *,
        open_once: Callable[[], None],
        label: str,
        notify_reconnected: bool = False,
    ) -> None:
        self._cancel_background_reconnect()
        with self._reconnect_lock:
            self._closing = False
            self._reconnect_cancel.clear()
            self._reconnect_exhausted = False
            self._connection_state = (
                "reconnecting" if self.reconnect_policy.enabled else "disconnected"
            )
            self._reconnect_attempts = 0
            self._last_error = None

        if not self.reconnect_policy.enabled:
            try:
                open_once()
            except Exception as exc:
                self._set_transport_error(str(exc))
                raise
            self._mark_transport_connected()
            return

        self._run_reconnect_loop(
            open_once=open_once,
            label=label,
            background=False,
            notify_reconnected=notify_reconnected,
        )

    def _ensure_transport_ready_for_io(self, *, is_open: bool, label: str) -> None:
        state = self.connection_state
        if state == "reconnecting":
            raise TransportReconnecting(
                f"{label} is reconnecting; command was not queued."
            )
        if not is_open:
            self._mark_transport_disconnected(f"{label} is not open")
            raise TransportDisconnected(
                f"{label} is not open (disconnected; command was not queued)."
            )

    def _start_background_reconnect(
        self,
        *,
        open_once: Callable[[], None],
        label: str,
    ) -> None:
        if not self.reconnect_policy.enabled:
            return
        with self._reconnect_lock:
            if self._closing or self._connection_state == "reconnecting":
                return
            self._connection_state = "reconnecting"
            self._reconnect_exhausted = False
            self._reconnect_attempts = 0
            self._reconnect_cancel.clear()
            thread = threading.Thread(
                target=self._run_reconnect_loop,
                kwargs={
                    "open_once": open_once,
                    "label": label,
                    "background": True,
                    "notify_reconnected": True,
                },
                name=f"{self.__class__.__name__}-reconnect",
                daemon=True,
            )
            self._reconnect_thread = thread
            thread.start()

    def _cancel_background_reconnect(self) -> None:
        with self._reconnect_lock:
            self._closing = True
            thread = self._reconnect_thread
            self._reconnect_cancel.set()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2)
        with self._reconnect_lock:
            if self._reconnect_thread is thread:
                self._reconnect_thread = None
            if self._connection_state == "reconnecting":
                self._connection_state = "disconnected"

    def _run_reconnect_loop(
        self,
        *,
        open_once: Callable[[], None],
        label: str,
        background: bool,
        notify_reconnected: bool,
    ) -> None:
        attempts_allowed = self.reconnect_policy.max_retries + 1
        last_exc: BaseException | None = None
        for attempt_index in range(attempts_allowed):
            if self._reconnect_cancel.is_set():
                return
            with self._reconnect_lock:
                self._connection_state = "reconnecting"
                self._reconnect_attempts = attempt_index + 1
            self._logger.info(
                "%s reconnect attempt %s/%s",
                label,
                attempt_index + 1,
                attempts_allowed,
            )
            try:
                open_once()
                if self._reconnect_cancel.is_set() or self._is_transport_closing():
                    self._cleanup_after_cancelled_open()
                    message = f"{label} reconnect cancelled"
                    with self._reconnect_lock:
                        self._connection_state = "disconnected"
                        self._last_error = message
                        if background:
                            self._reconnect_thread = None
                    if background:
                        return
                    raise TransportClosedError(message)
                self._mark_transport_connected()
                if notify_reconnected:
                    self._notify_reconnected(label)
            except Exception as exc:
                last_exc = exc
                self._set_transport_error(str(exc))
                if attempt_index >= self.reconnect_policy.max_retries:
                    message = (
                        f"{label} reconnect failed after {attempt_index + 1} "
                        f"attempt(s): {exc}"
                    )
                    self._logger.warning(message)
                    with self._reconnect_lock:
                        self._connection_state = "disconnected"
                        self._reconnect_exhausted = True
                        self._last_error = message
                        if background:
                            self._reconnect_thread = None
                    if background:
                        return
                    raise TransportReconnectFailed(message) from exc
                delay_s = self.reconnect_policy.delay_s(attempt_index)
                self._logger.info(
                    "%s reconnect attempt %s failed: %s; retrying in %.3fs",
                    label,
                    attempt_index + 1,
                    exc,
                    delay_s,
                )
                if background:
                    if self._reconnect_cancel.wait(delay_s):
                        return
                else:
                    self._reconnect_sleeper(delay_s)
                continue

            self._logger.info(
                "%s reconnected after %s attempt(s)",
                label,
                attempt_index + 1,
            )
            with self._reconnect_lock:
                self._reconnect_exhausted = False
                if background:
                    self._reconnect_thread = None
            return

        if last_exc is not None and not background:
            raise TransportReconnectFailed(
                f"{label} reconnect failed: {last_exc}"
            ) from last_exc

    def _notify_reconnected(self, label: str) -> None:
        if self._on_reconnected is None:
            return
        try:
            self._on_reconnected()
        except Exception as exc:
            self._set_transport_error(f"{label} reconnect hook failed: {exc}")
            self._logger.warning(
                "%s reconnect hook failed: %s",
                label,
                exc,
                exc_info=True,
            )

    def _is_transport_closing(self) -> bool:
        with self._reconnect_lock:
            return self._closing

    def _cleanup_after_cancelled_open(self) -> None:
        """Release resources opened after a reconnect cancellation."""
        return None


@runtime_checkable
class Transport(Protocol):
    """Byte transport owned by watch-side drivers."""

    def open(self) -> None:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError

    def write(self, data: bytes) -> None:
        raise NotImplementedError

    def read(self, timeout_s: float) -> bytes:
        raise NotImplementedError

    def health(self) -> TransportHealth:
        raise NotImplementedError
