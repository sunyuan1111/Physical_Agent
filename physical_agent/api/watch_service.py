from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import UTC, datetime
import json
from pathlib import Path
import queue
import threading
from typing import Any, Callable

from physical_agent.config import DEFAULT_CONFIG_NAME, load_config


DEFAULT_EVENT_QUEUE_SIZE = 100
DEFAULT_EVENT_BACKLOG_SIZE = 100
MIN_WATCH_INTERVAL_S = 0.001


class ApiEventBroker:
    """Thread-safe broker for API SSE events."""

    def __init__(
        self,
        *,
        queue_size: int = DEFAULT_EVENT_QUEUE_SIZE,
        backlog_size: int = DEFAULT_EVENT_BACKLOG_SIZE,
    ) -> None:
        self._queue_size = queue_size
        self._backlog_size = backlog_size
        self._next_id = 1
        self._subscribers: set[queue.Queue[dict[str, Any]]] = set()
        self._backlog: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def make_event(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            return self._make_event_locked(event_type, payload)

    def publish(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            event = self._make_event_locked(event_type, payload)
            self._backlog.append(event)
            if len(self._backlog) > self._backlog_size:
                self._backlog = self._backlog[-self._backlog_size :]
            subscribers = list(self._subscribers)

        for subscriber in subscribers:
            _offer_event(subscriber, event)
        return event

    def subscribe(self, *, replay: bool = True) -> "ApiEventSubscription":
        events: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=self._queue_size)
        with self._lock:
            if replay:
                for event in self._backlog:
                    _offer_event(events, event)
            self._subscribers.add(events)
        return ApiEventSubscription(self, events)

    def _unsubscribe(self, events: queue.Queue[dict[str, Any]]) -> None:
        with self._lock:
            self._subscribers.discard(events)

    def _make_event_locked(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        event = {
            "id": self._next_id,
            "type": event_type,
            "ts": _now(),
            "payload": payload,
        }
        self._next_id += 1
        return event


class ApiEventSubscription:
    def __init__(
        self,
        broker: ApiEventBroker,
        events: queue.Queue[dict[str, Any]],
    ) -> None:
        self._broker = broker
        self._events = events
        self._closed = False

    def get(self, *, timeout_s: float = 15.0) -> dict[str, Any] | None:
        try:
            return self._events.get(timeout=timeout_s)
        except queue.Empty:
            return None

    def close(self) -> None:
        if self._closed:
            return
        self._broker._unsubscribe(self._events)
        self._closed = True


class ApiWatchService:
    """Small background service that owns the API process watch loop."""

    def __init__(
        self,
        config_path: str | Path = DEFAULT_CONFIG_NAME,
        *,
        events: ApiEventBroker,
        interval_s: float | None = None,
        state_provider: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        self.config_path = Path(config_path).resolve()
        self.events = events
        self.interval_s = interval_s
        self.state_provider = state_provider
        self._task: asyncio.Task[None] | None = None
        self._runtime: Any | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if self.running:
            return
        self._task = asyncio.create_task(self._run(), name="physical-agent-api-watch")

    async def stop(self) -> None:
        task = self._task
        if task is None:
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        self._task = None

    async def _run(self) -> None:
        runtime = None
        try:
            WatchRuntime = _load_watch_runtime_class()
            runtime = WatchRuntime(self.config_path)
            self._runtime = runtime
            await runtime.setup()
            while True:
                try:
                    executed = await _run_watch_tick(runtime)
                    self.events.publish(
                        "watch_step",
                        {
                            "executed": int(executed),
                            "state": self._state_summary(),
                        },
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self.events.publish("error", error_payload(exc, phase="watch_step"))
                await asyncio.sleep(self._interval_for(runtime))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.events.publish("error", error_payload(exc, phase="setup"))
        finally:
            if runtime is not None:
                try:
                    await runtime.shutdown()
                except Exception as exc:
                    self.events.publish("error", error_payload(exc, phase="shutdown"))
            self._runtime = None

    def _interval_for(self, runtime: Any) -> float:
        if self.interval_s is not None:
            return max(MIN_WATCH_INTERVAL_S, float(self.interval_s))
        config = getattr(runtime, "config", None)
        tick_ms = getattr(getattr(config, "watch", None), "tick_ms", None)
        if tick_ms is None:
            tick_ms = load_config(self.config_path).watch.tick_ms
        return max(MIN_WATCH_INTERVAL_S, float(tick_ms) / 1000.0)

    def _state_summary(self) -> dict[str, Any] | None:
        if self.state_provider is None:
            return None
        try:
            return summarize_state(self.state_provider())
        except Exception as exc:
            return {
                "ok": False,
                "ready": False,
                "message": f"State snapshot failed: {type(exc).__name__}: {exc}",
            }


def format_sse_event(event: dict[str, Any]) -> str:
    data = json.dumps(event, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return f"event: {event['type']}\ndata: {data}\n\n"


def summarize_state(state: dict[str, Any]) -> dict[str, Any]:
    actions = state.get("actions") or {}
    pending = _action_ids(actions.get("pending") or [])
    completed = _action_ids(actions.get("completed") or [])
    cancelled = _action_ids(actions.get("cancelled") or [])
    return {
        "ok": bool(state.get("ok")),
        "ready": bool(state.get("ready")),
        "message": state.get("message"),
        "backend": state.get("backend"),
        "workspace_path": state.get("workspace_path"),
        "pending_actions": pending,
        "completed_count": len(completed),
        "cancelled_count": len(cancelled),
        "chat_messages": len((state.get("chat") or {}).get("messages") or []),
        "memory_notes": len((state.get("memory") or {}).get("notes") or []),
        "uploads": len((state.get("uploads") or {}).get("uploads") or []),
    }


def error_payload(exc: BaseException, *, phase: str) -> dict[str, Any]:
    return {
        "phase": phase,
        "error_type": type(exc).__name__,
        "message": str(exc),
    }


def _load_watch_runtime_class() -> Any:
    from physical_agent.watch.runtime import WatchRuntime

    return WatchRuntime


async def _run_watch_tick(runtime: Any) -> Any:
    tick = getattr(runtime, "tick", None)
    if callable(tick):
        return await tick()
    return await runtime.step(setup=False)


def _offer_event(events: queue.Queue[dict[str, Any]], event: dict[str, Any]) -> None:
    try:
        events.put_nowait(event)
        return
    except queue.Full:
        pass
    with suppress(queue.Empty):
        events.get_nowait()
    with suppress(queue.Full):
        events.put_nowait(event)


def _action_ids(items: list[Any]) -> list[str]:
    result: list[str] = []
    for item in items:
        if hasattr(item, "id"):
            result.append(str(item.id))
        elif isinstance(item, dict) and "id" in item:
            result.append(str(item["id"]))
    return result


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
