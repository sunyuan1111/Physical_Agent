from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import re
import tempfile
import threading
from typing import Any, Iterator
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from physical_agent.api.watch_service import (
    ApiEventBroker,
    ApiWatchService,
    error_payload,
    format_sse_event,
    summarize_state,
)
from physical_agent.config import DEFAULT_CONFIG_NAME, PhysicalAgentConfig, load_config
from physical_agent.ingest.files import (
    ALLOWED_TEXT_SUFFIXES,
    FileIngestionError,
    ingest_file,
    sanitize_filename,
)
from physical_agent.llm import (
    LLMSettingsError,
    OpenAICompatibleClient,
    OpenAICompatibleSettings,
    llm_settings_path,
    public_llm_settings_summary,
    resolve_llm_settings_values,
    write_llm_settings_file,
)
from physical_agent.protocol.schemas import Action, ChatPlan
from physical_agent.state import StateStore, open_state_store
from physical_agent.state.check import run_state_check, state_check_ok


BROWSER_UPLOAD_MAX_BYTES = 5 * 1024 * 1024
UPLOAD_READ_CHUNK_BYTES = 1024 * 1024

SERVER_EXTRA_HINT = (
    "FastAPI backend dependencies are not installed. "
    "Install them with `pip install -e .[server]` or `pip install physical-agent[server]`."
)


class MissingServerDependencyError(RuntimeError):
    """Raised when the optional FastAPI server dependencies are unavailable."""


class ApiRequestError(ValueError):
    def __init__(self, message: str, *, status_code: int = 400, details: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.details = details


class ActionProposalRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    action: dict[str, Any] | None = None
    id: str | None = None
    robot: str | None = None
    capability: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    reason: str | None = None
    depends_on: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def action_payload(self) -> dict[str, Any]:
        if self.action is not None:
            return dict(self.action)
        data = self.model_dump(exclude_none=True, exclude={"action"})
        return data


class ActionApprovalRequest(BaseModel):
    actor: str | None = None
    reason: str | None = None

    def normalized_actor(self, default: str = "gui") -> str:
        return (self.actor or default).strip() or default

    def normalized_reason(self) -> str | None:
        value = (self.reason or "").strip()
        return value or None


class SubmitTaskRequest(BaseModel):
    task: str


class ChatRequest(BaseModel):
    message: str
    planner: str | None = None
    auto_step: bool = False
    request_id: str | None = None
    stream_id: str | None = None


class LLMSettingsRequest(BaseModel):
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None
    api_mode: str | None = None
    reasoning_enabled: bool | None = None
    reasoning_effort: str | None = None
    reasoning_summary: str | None = None
    reasoning_extra_body: dict[str, Any] | None = None
    clear_api_key: bool = False


class SearchMemoryRequest(BaseModel):
    query: str
    limit: int = 5
    tags: list[str] | str | None = None
    source_type: str | None = None


class IngestFileRequest(BaseModel):
    path: str
    tags: list[str] | str | None = None
    importance: int = 0


class ExportAuditRequest(BaseModel):
    out: str | None = None


class WorkspaceResetRequest(BaseModel):
    confirm: bool = False


class IntegrateRequest(BaseModel):
    source: str
    name: str | None = None
    output: str | None = None
    llm: bool = False
    model: str | None = None


class RegisterRobotRequest(BaseModel):
    robot_id: str
    driver: str
    config: dict[str, Any] = Field(default_factory=dict)


@dataclass
class ChatStreamState:
    stream_id: str
    request_id: str
    abort_event: threading.Event


def create_app(
    config_path: str | Path = DEFAULT_CONFIG_NAME,
    *,
    enable_watch: bool = False,
    watch_interval_s: float | None = None,
) -> Any:
    """Create the optional FastAPI app; watch is disabled unless explicitly enabled."""

    fastapi = _load_fastapi()
    FastAPI = fastapi["FastAPI"]
    File = fastapi["File"]
    Form = fastapi["Form"]
    JSONResponse = fastapi["JSONResponse"]
    PlainTextResponse = fastapi["PlainTextResponse"]
    Request = fastapi["Request"]
    StreamingResponse = fastapi["StreamingResponse"]
    UploadFile = fastapi["UploadFile"]

    # FastAPI resolves postponed annotations from module globals.
    globals()["Request"] = Request
    globals()["UploadFile"] = UploadFile

    events = ApiEventBroker()
    controller = ApiController(config_path, events=events)

    @asynccontextmanager
    async def lifespan(app: Any) -> Any:
        app.state.events = events
        app.state.controller = controller
        app.state.watch_enabled = bool(enable_watch)
        app.state.watch_service = None
        if enable_watch:
            service = ApiWatchService(
                config_path,
                events=events,
                interval_s=watch_interval_s,
                state_provider=controller.state,
            )
            app.state.watch_service = service
            await service.start()
        try:
            yield
        finally:
            service = getattr(app.state, "watch_service", None)
            if service is not None:
                await service.stop()

    app = FastAPI(
        title="Physical Agent API",
        version="0.1.0",
        description="Proposal-only HTTP API for Physical Agent state.",
        lifespan=lifespan,
    )

    def handle_error(exc: ApiRequestError) -> Any:
        payload = {"ok": False, "message": str(exc)}
        if exc.details is not None:
            payload["details"] = _json_safe(exc.details)
        return JSONResponse(status_code=exc.status_code, content=payload)

    @app.exception_handler(Exception)
    async def handle_unexpected_error(_request: Request, exc: Exception) -> Any:
        # Endpoints only translate ApiRequestError themselves; anything else
        # would otherwise surface to the client as a bare "Internal Server
        # Error" with no way to see the cause from the dashboard.
        return JSONResponse(
            status_code=500,
            content={"ok": False, "message": f"{type(exc).__name__}: {exc}"},
        )

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return controller.health()

    @app.get("/api/state")
    def state() -> dict[str, Any]:
        return controller.state()

    @app.get("/api/state-check")
    def state_check() -> dict[str, Any]:
        try:
            return controller.state_check()
        except ApiRequestError as exc:
            return handle_error(exc)

    @app.get("/api/events")
    def event_stream(limit: int | None = None) -> Any:
        subscription = events.subscribe(replay=True)
        max_events = limit if limit is not None and limit > 0 else None

        def stream() -> Any:
            sent = 0

            def emit(event: dict[str, Any]) -> str:
                nonlocal sent
                sent += 1
                return format_sse_event(event)

            def should_stop() -> bool:
                return max_events is not None and sent >= max_events

            try:
                yield emit(
                    events.make_event(
                        "hello",
                        {
                            "version": "0.1.0",
                            "watch_enabled": bool(enable_watch),
                        },
                    )
                )
                if should_stop():
                    return
                yield emit(events.make_event("state", _state_event_payload(controller, "connect")))
                if should_stop():
                    return
                while True:
                    event = subscription.get(timeout_s=15.0)
                    if event is None:
                        if max_events is not None:
                            return
                        yield ": keepalive\n\n"
                        continue
                    yield emit(event)
                    if should_stop():
                        return
            finally:
                subscription.close()

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    @app.post("/api/actions/propose")
    def propose_action(payload: ActionProposalRequest) -> dict[str, Any]:
        try:
            return controller.propose_action(payload)
        except ApiRequestError as exc:
            return handle_error(exc)

    @app.post("/api/actions/{action_id}/approve")
    def approve_action(action_id: str, payload: ActionApprovalRequest | None = None) -> dict[str, Any]:
        try:
            return controller.approve_action(action_id, payload or ActionApprovalRequest())
        except ApiRequestError as exc:
            return handle_error(exc)

    @app.post("/api/actions/{action_id}/reject")
    def reject_action(action_id: str, payload: ActionApprovalRequest | None = None) -> dict[str, Any]:
        try:
            return controller.reject_action(action_id, payload or ActionApprovalRequest())
        except ApiRequestError as exc:
            return handle_error(exc)

    @app.post("/api/tasks/submit")
    def submit_task(payload: SubmitTaskRequest) -> dict[str, Any]:
        try:
            return controller.submit_task(payload)
        except ApiRequestError as exc:
            return handle_error(exc)

    @app.post("/api/chat")
    def chat(payload: ChatRequest) -> dict[str, Any]:
        try:
            return controller.chat(payload)
        except ApiRequestError as exc:
            return handle_error(exc)

    @app.post("/api/chat/reset")
    def reset_chat() -> dict[str, Any]:
        try:
            return controller.reset_chat()
        except ApiRequestError as exc:
            return handle_error(exc)

    @app.post("/api/chat/stream")
    async def chat_stream(payload: ChatRequest, request: Request) -> Any:
        try:
            stream_state = controller.register_chat_stream(payload)
        except ApiRequestError as exc:
            return handle_error(exc)

        async def stream() -> Any:
            yield format_sse_event(
                events.make_event(
                    "start",
                    {
                        "stream_id": stream_state.stream_id,
                        "request_id": stream_state.request_id,
                    },
                )
            )
            iterator = controller.chat_stream(payload, stream_state=stream_state)
            try:
                while True:
                    if await request.is_disconnected():
                        controller.abort_chat_stream(
                            stream_state.stream_id,
                            reason="client disconnected",
                        )
                        controller.log_chat_stream_disconnect(stream_state.stream_id)
                        _close_iterator(iterator)
                        return
                    item = await asyncio.to_thread(_next_stream_item, iterator)
                    if item is None:
                        return
                    yield format_sse_event(events.make_event(item["type"], item["payload"]))
                    await asyncio.sleep(0)
            except Exception as exc:  # noqa: BLE001 - stream errors must become SSE events.
                error_payload_data = {
                    "stream_id": stream_state.stream_id,
                    "request_id": stream_state.request_id,
                    "message": _sanitize_api_message(
                        str(exc),
                        controller.safe_resolved_llm_settings_values(),
                    ),
                }
                yield format_sse_event(events.make_event("error", error_payload_data))
            finally:
                controller.unregister_chat_stream(stream_state.stream_id)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    @app.post("/api/chat/abort/{stream_id}")
    def abort_chat(stream_id: str) -> dict[str, Any]:
        aborted = controller.abort_chat_stream(stream_id, reason="abort endpoint")
        return {
            "ok": True,
            "stream_id": stream_id,
            "aborted": aborted,
        }

    @app.get("/api/settings/llm")
    def get_llm_settings() -> dict[str, Any]:
        try:
            return controller.get_llm_settings()
        except ApiRequestError as exc:
            return handle_error(exc)

    @app.post("/api/settings/llm")
    def update_llm_settings(payload: LLMSettingsRequest) -> dict[str, Any]:
        try:
            return controller.update_llm_settings(payload)
        except ApiRequestError as exc:
            return handle_error(exc)

    @app.post("/api/settings/llm/test")
    def test_llm_settings() -> dict[str, Any]:
        try:
            return controller.test_llm_settings()
        except ApiRequestError as exc:
            return handle_error(exc)

    @app.post("/api/search-memory")
    def search_memory(payload: SearchMemoryRequest) -> dict[str, Any]:
        try:
            return controller.search_memory(payload)
        except ApiRequestError as exc:
            return handle_error(exc)

    @app.post("/api/ingest-file")
    def ingest_file_endpoint(payload: IngestFileRequest) -> dict[str, Any]:
        try:
            return controller.ingest_file(payload)
        except ApiRequestError as exc:
            return handle_error(exc)

    @app.post("/api/upload")
    async def upload_endpoint(
        file: UploadFile = File(...),
        tags: str | None = Form(None),
        importance: int = Form(0),
    ) -> dict[str, Any] | Any:
        try:
            return await controller.upload_file(
                file,
                tags=tags,
                importance=importance,
            )
        except ApiRequestError as exc:
            return handle_error(exc)
        finally:
            try:
                await file.close()
            except Exception:
                pass

    @app.post("/api/export-audit")
    def export_audit(payload: ExportAuditRequest) -> dict[str, Any]:
        try:
            return controller.export_audit(payload)
        except ApiRequestError as exc:
            return handle_error(exc)

    @app.post("/api/workspace/reset")
    def workspace_reset(payload: WorkspaceResetRequest) -> dict[str, Any]:
        try:
            return controller.reset_workspace(payload)
        except ApiRequestError as exc:
            return handle_error(exc)

    @app.post("/api/integrate")
    def integrate(payload: IntegrateRequest) -> dict[str, Any]:
        try:
            return controller.integrate_hardware(payload)
        except ApiRequestError as exc:
            return handle_error(exc)

    @app.get("/api/config")
    def get_config() -> dict[str, Any]:
        try:
            return controller.get_config()
        except ApiRequestError as exc:
            return handle_error(exc)

    @app.post("/api/config/robots")
    def register_robot(payload: RegisterRobotRequest) -> dict[str, Any]:
        try:
            return controller.register_robot(payload)
        except ApiRequestError as exc:
            return handle_error(exc)

    _install_frontend_routes(app, fastapi, PlainTextResponse)

    return app


class ApiController:
    def __init__(
        self,
        config_path: str | Path = DEFAULT_CONFIG_NAME,
        *,
        events: ApiEventBroker | None = None,
    ):
        self.config_path = Path(config_path).resolve()
        self.base_dir = self.config_path.parent
        self.events = events
        self.planner = SafeProposalPlanner()
        self._chat_streams: dict[str, ChatStreamState] = {}
        self._chat_stream_lock = threading.Lock()

    def health(self) -> dict[str, Any]:
        if not self.config_path.exists():
            return {
                "ok": False,
                "ready": False,
                "message": "Config file is missing.",
                "config_path": str(self.config_path),
                "config_exists": False,
                "workspace_exists": False,
            }
        try:
            config, store = self._store()
        except Exception as exc:
            return {
                "ok": False,
                "ready": False,
                "message": str(exc),
                "config_path": str(self.config_path),
                "config_exists": True,
                "workspace_exists": False,
            }
        exists = store.exists()
        return {
            "ok": True,
            "ready": exists,
            "message": "Ready." if exists else "Workspace is not initialized.",
            "config_path": str(self.config_path),
            "workspace_path": str(store.path),
            "backend": config.workspace.backend,
            "config_exists": True,
            "workspace_exists": exists,
        }

    def state(self) -> dict[str, Any]:
        if not self.config_path.exists():
            return {
                "ok": False,
                "ready": False,
                "message": "Config file is missing.",
                "config_path": str(self.config_path),
            }
        config, store = self._store()
        if not store.exists():
            return {
                "ok": False,
                "ready": False,
                "message": "Workspace is not initialized.",
                "config_path": str(self.config_path),
                "workspace_path": str(store.path),
                "backend": config.workspace.backend,
            }
        return self._state(config, store)

    def state_check(self) -> dict[str, Any]:
        if not self.config_path.exists():
            raise ApiRequestError(
                f"Could not find {self.config_path}. Run `physical-agent init` first.",
                status_code=404,
            )
        config = load_config(self.config_path)
        result = run_state_check(config, base_dir=self.base_dir)
        ok = state_check_ok(result)
        return {
            "ok": ok,
            "ready": bool(result["workspace_initialized"]),
            "message": "State backend is ready." if ok else "State backend needs attention.",
            **_json_safe(result),
        }

    def propose_action(self, payload: ActionProposalRequest) -> dict[str, Any]:
        _, store = self._store(initialize=True)
        action = _validate_action(
            _with_proposal_metadata(
                payload.action_payload(),
                source="manual",
                proposed_by="api",
            )
        )
        appended = store.append_pending_action(action)
        store.append_log(f"API proposed action `{appended.id}`.", actor="api")
        state = self.state()
        self._publish_state("action_proposed", state)
        return {
            "ok": True,
            "message": "Action proposed in the action board; watch must validate before execution.",
            "action": _json_safe(appended),
            "state": state,
        }

    def approve_action(
        self,
        action_id: str,
        payload: ActionApprovalRequest,
    ) -> dict[str, Any]:
        _, store = self._store(require_exists=True)
        try:
            action, changed = store.approve_action(
                action_id,
                actor=payload.normalized_actor(),
                reason=payload.normalized_reason(),
            )
        except KeyError as exc:
            raise ApiRequestError(
                f"Action not found: {action_id}",
                status_code=404,
            ) from exc
        except ValueError as exc:
            raise ApiRequestError(str(exc), status_code=409) from exc
        if changed:
            store.append_log(
                f"API approved action `{action.id}` for execution.",
                actor="api",
            )
        state = self.state()
        self._publish_state("action_approved", state)
        return {
            "ok": True,
            "message": (
                "Action approved for watch execution."
                if changed
                else "Action approval is already current."
            ),
            "action": _json_safe(action),
            "changed": changed,
            "state": state,
        }

    def reject_action(
        self,
        action_id: str,
        payload: ActionApprovalRequest,
    ) -> dict[str, Any]:
        _, store = self._store(require_exists=True)
        reason = payload.normalized_reason()
        try:
            action = store.reject_action(
                action_id,
                actor=payload.normalized_actor(),
                reason=reason,
            )
        except KeyError as exc:
            raise ApiRequestError(
                f"Action not found: {action_id}",
                status_code=404,
            ) from exc
        except ValueError as exc:
            raise ApiRequestError(str(exc), status_code=409) from exc
        store.append_log(
            f"API rejected action `{action.id}`: "
            f"{reason or 'Rejected by human reviewer.'}",
            actor="api",
        )
        state = self.state()
        self._publish_state("action_rejected", state)
        return {
            "ok": True,
            "message": "Action rejected and moved to cancelled.",
            "action": _json_safe(action),
            "state": state,
        }

    def submit_task(self, payload: SubmitTaskRequest) -> dict[str, Any]:
        task = payload.task.strip()
        if not task:
            raise ApiRequestError("Task cannot be empty.")
        config, store = self._store(initialize=True)
        store.write_task(task, owner="human")
        actions = self._plan_actions(task, store)
        _write_plan(store, task, actions, intent="act" if actions else "task")
        if actions:
            store.append_log(
                f"API submitted task `{task}` as {len(actions)} pending action(s).",
                actor="api",
            )
        else:
            store.append_log(f"API submitted task `{task}` with no action proposal.", actor="api")
        refusal_reason = getattr(self.planner, "last_refusal_reason", None)
        state = self._state(config, store)
        self._publish_state("task_submitted", state)
        return {
            "ok": True,
            "message": (
                "Task recorded and actions proposed; watch must validate before execution."
                if actions
                else "Task recorded. No action proposal was created from current capabilities."
            ),
            "actions": _json_safe(actions),
            "refusal_reason": refusal_reason,
            "state": state,
        }

    def chat(self, payload: ChatRequest) -> dict[str, Any]:
        message = payload.message.strip()
        if not message:
            raise ApiRequestError("Chat message cannot be empty.")
        self._store(initialize=True)
        runtime = _new_chat_runtime(
            self.config_path,
            planner_name=_api_chat_planner(payload.planner),
            enable_code_skills=False,
            enable_hardware_integration=False,
        )
        response = runtime.respond(message, auto_step=False)
        config, store = self._store(require_exists=True)
        store.append_log("API chat replied without executing watch.", actor="api")
        state = self._state(config, store)
        self._publish_state("chat", state)
        return {
            "ok": True,
            "mode": response.get("mode", "rule_based"),
            "reply": response.get("reply", ""),
            "actions": _json_safe(response.get("actions", [])),
            "memory": _json_safe(response.get("memory", [])),
            "plan": _json_safe(response.get("plan")),
            "executed": 0,
            "refusal_reason": response.get("refusal_reason"),
            "state": state,
        }

    def reset_chat(self) -> dict[str, Any]:
        config, store = self._store(initialize=True)
        store.write_chat([], running_summary="", compact=False)
        store.append_log("API reset chat history.", actor="api")
        state = self._state(config, store)
        self._publish_state("chat_reset", state)
        return {
            "ok": True,
            "message": "Chat history cleared.",
            "state": state,
        }

    def register_chat_stream(self, payload: ChatRequest) -> ChatStreamState:
        stream_id = (payload.stream_id or "").strip() or f"chat_{uuid4().hex}"
        request_id = (payload.request_id or "").strip() or stream_id
        stream_state = ChatStreamState(
            stream_id=stream_id,
            request_id=request_id,
            abort_event=threading.Event(),
        )
        with self._chat_stream_lock:
            if stream_id in self._chat_streams:
                raise ApiRequestError(
                    f"Chat stream already exists: {stream_id}",
                    status_code=409,
                )
            self._chat_streams[stream_id] = stream_state
        return stream_state

    def unregister_chat_stream(self, stream_id: str) -> None:
        with self._chat_stream_lock:
            self._chat_streams.pop(stream_id, None)

    def abort_chat_stream(self, stream_id: str, *, reason: str = "abort requested") -> bool:
        with self._chat_stream_lock:
            stream_state = self._chat_streams.get(stream_id)
        if stream_state is None:
            return False
        stream_state.abort_event.set()
        try:
            _, store = self._store(require_exists=True)
            store.append_log(f"API chat stream `{stream_id}` abort requested: {reason}.", actor="api")
        except Exception:
            pass
        return True

    def log_chat_stream_disconnect(self, stream_id: str) -> None:
        try:
            _, store = self._store(require_exists=True)
            store.append_log(f"API chat stream `{stream_id}` stopped after client disconnect.", actor="api")
        except Exception:
            pass

    def chat_stream(
        self,
        payload: ChatRequest,
        *,
        stream_state: ChatStreamState,
    ) -> Iterator[dict[str, Any]]:
        message = payload.message.strip()
        if not message:
            raise ApiRequestError("Chat message cannot be empty.")
        self._store(initialize=True)
        runtime = _new_chat_runtime(
            self.config_path,
            planner_name=_api_chat_planner(payload.planner),
            enable_code_skills=False,
            enable_hardware_integration=False,
        )
        runtime_stream = runtime.respond_stream(
            message,
            auto_step=False,
            cancel_check=stream_state.abort_event.is_set,
        )
        try:
            while True:
                if stream_state.abort_event.is_set():
                    close = getattr(runtime_stream, "close", None)
                    if callable(close):
                        close()
                    config, store = self._store(require_exists=True)
                    state = self._state(config, store)
                    self._publish_state("chat_stream_aborted", state)
                    yield {
                        "type": "aborted",
                        "payload": {
                            "stream_id": stream_state.stream_id,
                            "request_id": stream_state.request_id,
                            "state": _json_safe(state),
                        },
                    }
                    return
                try:
                    item = next(runtime_stream)
                except StopIteration:
                    return
                event_type = str(item.get("type") or "delta")
                payload_data = {
                    "stream_id": stream_state.stream_id,
                    "request_id": stream_state.request_id,
                }
                if event_type == "delta":
                    payload_data["delta"] = str(item.get("delta") or "")
                elif event_type == "done":
                    config, store = self._store(require_exists=True)
                    store.append_log("API chat stream completed without executing watch.", actor="api")
                    state = self._state(config, store)
                    self._publish_state("chat_stream", state)
                    payload_data.update(
                        {
                            "reply": item.get("reply", ""),
                            "mode": item.get("mode", "rule_based"),
                            "state": _json_safe(state),
                        }
                    )
                elif event_type in {"aborted", "error"}:
                    config, store = self._store(require_exists=True)
                    store.append_log(f"API chat stream {event_type} without executing watch.", actor="api")
                    state = self._state(config, store)
                    self._publish_state(f"chat_stream_{event_type}", state)
                    payload_data.update(
                        {
                            "reply": item.get("reply", ""),
                            "mode": item.get("mode", "rule_based"),
                            "message": item.get("message", ""),
                            "state": _json_safe(state),
                        }
                    )
                else:
                    payload_data.update(_json_safe(item))
                yield {"type": event_type, "payload": payload_data}
        except Exception:
            raise

    def safe_resolved_llm_settings_values(self) -> dict[str, str]:
        try:
            return self._resolved_llm_settings_values()
        except Exception:
            return {}

    def get_llm_settings(self) -> dict[str, Any]:
        values = self._resolved_llm_settings_values()
        summary = public_llm_settings_summary(
            values,
            settings_path=self._llm_settings_path(),
        )
        return {
            "ok": True,
            **summary,
            "settings": summary,
        }

    def update_llm_settings(self, payload: LLMSettingsRequest) -> dict[str, Any]:
        settings_path = self._llm_settings_path()
        data = payload.model_dump(exclude_unset=True)
        if payload.clear_api_key and "api_key" not in data:
            data["api_key"] = ""
        try:
            written = write_llm_settings_file(
                settings_path,
                data,
                preserve_existing_api_key=not payload.clear_api_key,
            )
        except LLMSettingsError as exc:
            raise ApiRequestError(str(exc), status_code=400) from exc
        summary = public_llm_settings_summary(
            written,
            settings_path=settings_path,
        )
        return {
            "ok": True,
            "message": "LLM settings saved.",
            **summary,
            "settings": summary,
        }

    def test_llm_settings(self) -> dict[str, Any]:
        settings_path = self._llm_settings_path()
        try:
            settings = OpenAICompatibleSettings.from_env(
                env_file=self.base_dir / ".env",
                workspace_path=settings_path.parent,
            )
            result = OpenAICompatibleClient(settings).test_connection()
        except Exception as exc:
            message = _sanitize_api_message(str(exc), self._resolved_llm_settings_values())
            summary = public_llm_settings_summary(
                self._resolved_llm_settings_values(),
                settings_path=settings_path,
            )
            return {
                "ok": False,
                "message": message,
                **summary,
                "settings": summary,
            }
        summary = public_llm_settings_summary(
            {
                "base_url": settings.base_url,
                "model": settings.model,
                "api_mode": settings.api_mode,
                "reasoning_enabled": settings.reasoning_enabled,
                "reasoning_effort": settings.reasoning_effort,
                "reasoning_summary": settings.reasoning_summary,
                "reasoning_extra_body": settings.reasoning_extra_body,
                "api_key": settings.api_key,
            },
            settings_path=settings_path,
        )
        return {
            "ok": True,
            "message": "LLM connection test passed.",
            "result": {
                key: value
                for key, value in result.items()
                if key != "content"
            },
            **summary,
            "settings": summary,
        }

    def search_memory(self, payload: SearchMemoryRequest) -> dict[str, Any]:
        query = payload.query.strip()
        if not query:
            raise ApiRequestError("Search query cannot be empty.")
        _, store = self._store(require_exists=True)
        results = store.query_memory_chunks(
            query,
            limit=max(1, payload.limit),
            tags=payload.tags,
            source_type=payload.source_type,
        )
        return {"ok": True, "query": query, "results": _json_safe(results)}

    def ingest_file(self, payload: IngestFileRequest) -> dict[str, Any]:
        path = payload.path.strip()
        if not path:
            raise ApiRequestError("File path cannot be empty.")
        config, store = self._store(initialize=True)
        try:
            result = ingest_file(
                path,
                store,
                tags=payload.tags,
                importance=payload.importance,
                max_chars_per_chunk=config.memory.retrieval.max_chars_per_chunk,
            )
        except FileIngestionError as exc:
            raise ApiRequestError(
                str(exc),
                status_code=400,
                details={"metadata": exc.metadata},
            ) from exc
        state = self._state(config, store)
        self._publish_state("file_ingested", state)
        return {
            "ok": True,
            "message": "File ingested.",
            "result": _json_safe(result),
            "state": state,
        }

    async def upload_file(
        self,
        upload: Any,
        *,
        tags: str | None = None,
        importance: int = 0,
    ) -> dict[str, Any]:
        filename = _browser_upload_filename(getattr(upload, "filename", None))
        suffix = Path(filename).suffix.lower()
        if suffix not in ALLOWED_TEXT_SUFFIXES:
            allowed = ", ".join(sorted(ALLOWED_TEXT_SUFFIXES))
            raise ApiRequestError(
                (
                    f"Unsupported upload type: {suffix or '<none>'}. "
                    f"Supported text suffixes: {allowed}. PDF, OCR, and image ingestion "
                    "are not implemented in this phase."
                ),
                status_code=400,
            )

        config, store = self._store(initialize=True)
        incoming_root = store.uploads_path / ".incoming"
        incoming_root.mkdir(parents=True, exist_ok=True)

        try:
            with tempfile.TemporaryDirectory(
                prefix="browser-upload-",
                dir=incoming_root,
            ) as temp_dir:
                temp_path = Path(temp_dir) / filename
                size_bytes = await _write_browser_upload(upload, temp_path)
                try:
                    result = ingest_file(
                        temp_path,
                        store,
                        tags=_parse_upload_tags(tags),
                        importance=importance,
                        max_chars_per_chunk=config.memory.retrieval.max_chars_per_chunk,
                    )
                except FileIngestionError as exc:
                    raise ApiRequestError(
                        str(exc),
                        status_code=400,
                        details={"metadata": exc.metadata},
                    ) from exc
        except ApiRequestError:
            raise
        except OSError as exc:
            raise ApiRequestError(
                f"Could not store browser upload: {exc}",
                status_code=500,
            ) from exc

        state = self._state(config, store)
        self._publish_state("browser_file_uploaded", state)
        return {
            "ok": True,
            "message": (
                "File uploaded and ingested as untrusted proposal context; "
                "watch must validate any derived action before execution."
            ),
            "filename": filename,
            "size_bytes": size_bytes,
            "result": _json_safe(result),
            "state": state,
        }

    def export_audit(self, payload: ExportAuditRequest) -> dict[str, Any]:
        _, store = self._store(require_exists=True)
        out_dir = None
        if payload.out:
            out_path = Path(payload.out)
            out_dir = out_path if out_path.is_absolute() else self.base_dir / out_path
        result = store.export_human_view(out_dir)
        self._publish_state("audit_exported")
        return {
            "ok": True,
            "message": "Exported audit view.",
            "backend": result.get("backend"),
            "workspace_path": result.get("workspace_path"),
            "out_dir": result.get("out_dir"),
            "manifest": result.get("manifest"),
            "result": _json_safe(result),
        }

    def reset_workspace(self, payload: WorkspaceResetRequest) -> dict[str, Any]:
        if not payload.confirm:
            raise ApiRequestError(
                "Workspace reset requires explicit confirmation. "
                "Send {\"confirm\": true} to clear world, actions, memory, and chat.",
                status_code=400,
            )
        config, store = self._store()
        store.initialize(overwrite=True)
        store.append_log(
            "API reset the workspace (full state re-init; config file untouched).",
            actor="api",
        )
        state = self.state()
        self._publish_state("workspace_reset", state)
        return {
            "ok": True,
            "message": (
                "Workspace has been reset: world, actions, memory, chat, and uploads "
                "are cleared; SAFETY is restored to defaults. "
                "physical-agent.yaml is untouched. "
                "Capabilities will be republished the next time watch runs."
            ),
            "workspace_path": str(store.path),
            "backend": config.workspace.backend,
            "state": state,
        }

    def integrate_hardware(self, payload: IntegrateRequest) -> dict[str, Any]:
        source = payload.source.strip()
        if not source:
            raise ApiRequestError("Integration source cannot be empty.")
        _, store = self._store(initialize=True)
        from physical_agent.agent.driver_coder import DriverCodingAgent
        from physical_agent.agent.onboarding import HardwareIntegrationAssistant

        try:
            if payload.llm:
                coding_result = DriverCodingAgent(
                    source,
                    output_dir=payload.output or None,
                    name=payload.name or None,
                    base_dir=self.base_dir,
                    model=payload.model or None,
                ).generate()
                message = (
                    f"Generated LLM driver draft at {coding_result.output_path}."
                    if coding_result.llm_used
                    else (
                        f"Generated safe scaffold at {coding_result.output_path}; "
                        "LLM coding did not validate."
                    )
                )
                result_payload = coding_result.model_dump(mode="json")
            else:
                integration_result = HardwareIntegrationAssistant(
                    source,
                    output_dir=payload.output or None,
                    name=payload.name or None,
                    base_dir=self.base_dir,
                ).generate()
                message = f"Generated driver scaffold at {integration_result.output_path}."
                result_payload = integration_result.model_dump(mode="json")
        except ApiRequestError:
            raise
        except Exception as exc:
            raise ApiRequestError(str(exc), status_code=400) from exc
        store.append_log(
            f"API generated a driver {'draft' if payload.llm else 'scaffold'} "
            f"from `{source}`. Watch must load and validate it before execution.",
            actor="api",
        )
        state = self.state()
        self._publish_state("hardware_integrated", state)
        return {
            "ok": True,
            "message": message,
            "result": _json_safe(result_payload),
            "state": state,
        }

    def get_config(self) -> dict[str, Any]:
        if not self.config_path.exists():
            raise ApiRequestError(
                f"Could not find {self.config_path}. Run `physical-agent init` first.",
                status_code=404,
            )
        try:
            config = load_config(self.config_path)
        except Exception as exc:
            raise ApiRequestError(f"Config file is invalid: {exc}", status_code=400) from exc
        return {
            "ok": True,
            "message": "Effective configuration as watch would load it. Read-only.",
            "config_path": str(self.config_path),
            "config": _json_safe(config.model_dump(mode="json")),
        }

    def register_robot(self, payload: RegisterRobotRequest) -> dict[str, Any]:
        robot_id = payload.robot_id.strip()
        driver = payload.driver.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", robot_id or ""):
            raise ApiRequestError(
                "robot_id must start with a letter or underscore and contain only "
                "letters, digits, '_' or '-'."
            )
        if not driver:
            raise ApiRequestError("driver cannot be empty.")
        if not self.config_path.exists():
            raise ApiRequestError(
                f"Could not find {self.config_path}. Run `physical-agent init` first.",
                status_code=404,
            )
        import yaml as _yaml

        try:
            data = _yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}
        except Exception as exc:
            raise ApiRequestError(f"Config file is invalid YAML: {exc}", status_code=400) from exc
        if not isinstance(data, dict):
            raise ApiRequestError(
                "Config file is invalid: top level must be a mapping.", status_code=400
            )
        robots = data.setdefault("robots", {})
        if not isinstance(robots, dict):
            raise ApiRequestError(
                "Config file is invalid: `robots` must be a mapping.", status_code=400
            )
        if robot_id in robots:
            raise ApiRequestError(
                f"Robot `{robot_id}` already exists in {self.config_path.name}. "
                "Editing existing robots from the GUI is not supported; edit the file manually.",
                status_code=409,
            )
        robots[robot_id] = {"driver": driver, "config": dict(payload.config)}
        try:
            PhysicalAgentConfig.model_validate(data)
        except Exception as exc:
            raise ApiRequestError(
                f"New robot entry failed config validation; nothing was written: {exc}",
                status_code=400,
            ) from exc
        self.config_path.write_text(
            _yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        try:
            _, store = self._store()
            store.append_log(
                f"API registered robot `{robot_id}` (driver `{driver}`) in "
                f"{self.config_path.name}. Restart watch to apply.",
                actor="api",
            )
        except Exception:
            pass
        self._publish_state("config_updated")
        return {
            "ok": True,
            "message": (
                f"Robot `{robot_id}` registered in {self.config_path.name}. "
                "Restart watch (`physical-agent watch`) to connect it."
            ),
            "requires_watch_restart": True,
            "robot_id": robot_id,
            "config_path": str(self.config_path),
            "config": self.get_config()["config"],
        }

    def _store(
        self,
        *,
        initialize: bool = False,
        require_exists: bool = False,
    ) -> tuple[PhysicalAgentConfig, StateStore]:
        if not self.config_path.exists():
            raise ApiRequestError(
                f"Could not find {self.config_path}. Run `physical-agent init` first.",
                status_code=404,
            )
        config = load_config(self.config_path)
        store = open_state_store(config, base_dir=self.base_dir)
        if initialize:
            store.initialize()
        if require_exists and not store.exists():
            raise ApiRequestError(
                "Workspace is not initialized. Run `physical-agent init` first.",
                status_code=404,
            )
        return config, store

    def _llm_settings_path(self) -> Path:
        if not self.config_path.exists():
            raise ApiRequestError(
                f"Could not find {self.config_path}. Run `physical-agent init` first.",
                status_code=404,
            )
        config = load_config(self.config_path)
        return llm_settings_path(config.workspace_path(self.base_dir))

    def _resolved_llm_settings_values(self) -> dict[str, str]:
        settings_path = self._llm_settings_path()
        try:
            return resolve_llm_settings_values(
                env_file=self.base_dir / ".env",
                workspace_path=settings_path.parent,
            )
        except LLMSettingsError as exc:
            raise ApiRequestError(str(exc), status_code=400) from exc

    def _state(self, config: PhysicalAgentConfig, store: StateStore) -> dict[str, Any]:
        actions = store.read_actions()
        return {
            "ok": True,
            "ready": True,
            "message": "Ready.",
            "config_path": str(self.config_path),
            "workspace_path": str(store.path),
            "backend": config.workspace.backend,
            "task": store.read_task(),
            "capabilities": store.read_capabilities(),
            "world": store.read_world(),
            "actions": {
                "pending": _json_safe(actions["pending"]),
                "completed": _json_safe(actions["completed"]),
                "cancelled": _json_safe(actions["cancelled"]),
            },
            "feedback": store.read_feedback(),
            "safety": store.read_safety(),
            "chat": _json_safe(store.read_chat()),
            "plan": _json_safe(store.read_plan()),
            "memory": _json_safe(store.read_memory()),
            "uploads": _json_safe(store.read_uploads()),
            "chunks": _json_safe(store.read_memory_chunks()),
        }

    def _publish_state(self, reason: str, state: dict[str, Any] | None = None) -> None:
        if self.events is None:
            return
        try:
            snapshot = state if state is not None else self.state()
            self.events.publish(
                "state",
                {
                    "reason": reason,
                    "state": summarize_state(snapshot),
                },
            )
        except Exception as exc:
            try:
                self.events.publish("error", error_payload(exc, phase="state_publish"))
            except Exception:
                pass

    def _plan_actions(self, task: str, store: StateStore) -> list[Action]:
        actions = self.planner.plan(
            task=task,
            capabilities=store.read_capabilities(),
            world=store.read_world(),
        )
        return self._append_planned_actions(actions, store, original_task=task)

    def _append_planned_actions(
        self,
        actions: list[Action],
        store: StateStore,
        *,
        original_task: str,
    ) -> list[Action]:
        if not actions:
            return []
        renumbered = _renumber_actions(actions, store)
        renumbered = [
            _validate_action(
                _with_proposal_metadata(
                    action.model_dump(mode="json"),
                    source="planner",
                    proposed_by="api",
                    original_task=original_task,
                    planner_reason=action.reason,
                )
            )
            for action in renumbered
        ]
        return [store.append_pending_action(action) for action in renumbered]

    def _rule_chat(self, message: str, store: StateStore) -> dict[str, Any]:
        remember_match = re.search(r"\bremember(?: that)?\s+(.+)", message, re.IGNORECASE)
        if remember_match:
            note = remember_match.group(1).strip()
            return {
                "reply": f"I will remember: {note}",
                "intent": "remember",
                "steps": [],
                "actions": [],
                "memory": [note],
            }

        actions = self.planner.plan(
            task=message,
            capabilities=store.read_capabilities(),
            world=store.read_world(),
        )
        if actions:
            names = ", ".join(f"{action.robot}.{action.capability}" for action in actions)
            return {
                "reply": (
                    f"I proposed {len(actions)} action(s): {names}. "
                    "Watch will validate them before anything touches the physical world."
                ),
                "intent": "act",
                "steps": ["Interpret the message.", "Write proposed actions to the action board."],
                "actions": actions,
                "memory": [],
            }

        text = message.lower().strip()
        if "status" in text or "world" in text or "see" in text:
            latest = store.read_feedback().get("latest", {})
            world = store.read_world()
            reply = world.get("summary") or "No world state has been published yet."
            if latest:
                reply += f" Latest feedback: {latest.get('status')} - {latest.get('message')}"
            return {
                "reply": reply,
                "intent": "inspect",
                "steps": [],
                "actions": [],
                "memory": [],
            }

        if "memory" in text or "remember" in text:
            notes = store.read_memory().get("notes", [])
            notes_text = "; ".join(note.get("content", "") for note in notes[-5:])
            return {
                "reply": notes_text or "I do not have saved memory notes yet.",
                "intent": "inspect",
                "steps": [],
                "actions": [],
                "memory": [],
            }

        return {
            "reply": (
                "I can chat about the workspace, remember short notes, or propose actions like "
                "`look around` and `pick the red block and place it on the tray`."
            ),
            "intent": "chat",
            "steps": [],
            "actions": [],
            "memory": [],
        }


class SafeProposalPlanner:
    """Small request-side planner that only returns pending Action intents."""

    def __init__(self) -> None:
        self.last_refusal_reason: str | None = None

    def plan(
        self,
        *,
        task: str,
        capabilities: dict[str, Any],
        world: dict[str, Any],
    ) -> list[Action]:
        self.last_refusal_reason = None
        text = task.lower()
        robots = capabilities.get("robots", {})
        actions: list[Action] = []

        if any(word in text for word in ("observe", "look", "scan")):
            robot_id = self._choose_robot(robots, ["observe"])
            if robot_id:
                actions.append(
                    Action(
                        id=self._action_id(len(actions) + 1),
                        robot=robot_id,
                        capability="observe",
                        params={},
                        reason="The request asks for an observation.",
                    )
                )

        if re.search(r"\b(move|go)\b", text):
            robot_id = self._choose_robot(robots, ["move_to"])
            if robot_id:
                actions.append(
                    Action(
                        id=self._action_id(len(actions) + 1),
                        robot=robot_id,
                        capability="move_to",
                        params=self._move_params(text, robots[robot_id]),
                        reason="The request asks for movement.",
                    )
                )

        if any(word in text for word in ("pick", "grasp")):
            robot_id = self._choose_robot(robots, ["pick"])
            if robot_id:
                actions.append(
                    Action(
                        id=self._action_id(len(actions) + 1),
                        robot=robot_id,
                        capability="pick",
                        params={"object_id": self._object_id(text, world)},
                        reason="The request asks to pick an object.",
                    )
                )

        if any(word in text for word in ("place", "drop")):
            robot_id = self._choose_robot(robots, ["place"])
            if robot_id:
                depends_on = [actions[-1].id] if actions and actions[-1].capability == "pick" else []
                actions.append(
                    Action(
                        id=self._action_id(len(actions) + 1),
                        robot=robot_id,
                        capability="place",
                        params={"target": self._target_id(text, world)},
                        reason="The request asks to place or drop an object.",
                        depends_on=depends_on,
                    )
                )

        if "open gripper" in text:
            robot_id = self._choose_robot(robots, ["open_gripper"])
            if robot_id:
                actions.append(
                    Action(
                        id=self._action_id(len(actions) + 1),
                        robot=robot_id,
                        capability="open_gripper",
                        params={},
                        reason="The request asks to open the gripper.",
                    )
                )

        if "close gripper" in text:
            robot_id = self._choose_robot(robots, ["close_gripper"])
            if robot_id:
                actions.append(
                    Action(
                        id=self._action_id(len(actions) + 1),
                        robot=robot_id,
                        capability="close_gripper",
                        params={},
                        reason="The request asks to close the gripper.",
                    )
                )

        if any(word in text for word in ("home", "reset")):
            robot_id = self._choose_robot(robots, ["home"])
            if robot_id:
                actions.append(
                    Action(
                        id=self._action_id(len(actions) + 1),
                        robot=robot_id,
                        capability="home",
                        params={},
                        reason="The request asks the robot to return home.",
                    )
                )

        if any(word in text for word in ("stop", "halt")):
            robot_id = self._choose_robot(robots, ["stop"])
            if robot_id:
                actions.append(
                    Action(
                        id=self._action_id(len(actions) + 1),
                        robot=robot_id,
                        capability="stop",
                        params={},
                        reason="The request asks the robot to stop.",
                    )
                )

        if not actions:
            self.last_refusal_reason = (
                "No supported robot capability matched the submitted task."
            )
        return actions

    def _choose_robot(self, robots: dict[str, Any], required: list[str]) -> str | None:
        for robot_id, robot in robots.items():
            names = {capability.get("name") for capability in robot.get("capabilities", [])}
            if all(name in names for name in required):
                return robot_id
        return None

    def _action_id(self, number: int) -> str:
        return f"act_{number:03d}"

    def _object_id(self, text: str, world: dict[str, Any]) -> str:
        objects = world.get("state", {}).get("objects", {})
        if "red block" in text:
            for object_id, item in objects.items():
                if item.get("color") == "red" and item.get("type") == "block":
                    return object_id
            return "red_block"
        match = re.search(r"(?:pick|grasp)\s+(?:the\s+)?([a-z0-9_ -]+?)(?:\s+and|\s+then|$)", text)
        if match:
            candidate = match.group(1).strip().replace(" ", "_").replace("-", "_")
            if candidate:
                return candidate
        return "red_block"

    def _target_id(self, text: str, world: dict[str, Any]) -> str:
        objects = world.get("state", {}).get("objects", {})
        for object_id in objects:
            if object_id.lower() in text:
                return object_id
        if "tray" in text:
            return "tray"
        match = re.search(r"(?:on|in|at|to)\s+(?:the\s+)?([a-z0-9_ -]+?)(?:\.|$)", text)
        if match:
            candidate = match.group(1).strip().replace(" ", "_").replace("-", "_")
            if candidate:
                return candidate
        return "tray"

    def _move_params(self, text: str, robot: dict[str, Any]) -> dict[str, Any]:
        numbers = [float(value) for value in re.findall(r"-?\d+(?:\.\d+)?", text)]
        move_schema = {}
        for capability in robot.get("capabilities", []):
            if capability.get("name") == "move_to":
                move_schema = capability.get("params_schema", {})
                break
        required = move_schema.get("required", ["x", "y", "z"])
        return {
            name: numbers[index] if index < len(numbers) else 0.0
            for index, name in enumerate(required)
        }


def _load_fastapi() -> dict[str, Any]:
    try:
        from fastapi import FastAPI, File, Form, Request, UploadFile
        from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, StreamingResponse
        from fastapi.staticfiles import StaticFiles
    except ImportError as exc:
        raise MissingServerDependencyError(SERVER_EXTRA_HINT) from exc
    return {
        "FastAPI": FastAPI,
        "File": File,
        "Form": Form,
        "HTMLResponse": HTMLResponse,
        "JSONResponse": JSONResponse,
        "PlainTextResponse": PlainTextResponse,
        "Request": Request,
        "StreamingResponse": StreamingResponse,
        "StaticFiles": StaticFiles,
        "UploadFile": UploadFile,
    }


def _install_frontend_routes(
    app: Any,
    fastapi: dict[str, Any],
    PlainTextResponse: Any,
) -> None:
    dist = _frontend_dist_path()
    index = dist / "index.html"
    assets = dist / "assets"
    HTMLResponse = fastapi["HTMLResponse"]
    StaticFiles = fastapi["StaticFiles"]

    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="frontend-assets")

    @app.get("/", include_in_schema=False)
    def frontend_home() -> Any:
        if index.exists():
            return HTMLResponse(index.read_text(encoding="utf-8"))
        return PlainTextResponse(
            "Physical Agent API is running. GUI build not found; run "
            "`cd frontend && npm install && npm run build` to serve the React dashboard.",
            status_code=200,
        )


def _frontend_dist_path() -> Path:
    candidates = [
        Path.cwd() / "frontend" / "dist",
        Path(__file__).resolve().parents[2] / "frontend" / "dist",
    ]
    for candidate in candidates:
        if (candidate / "index.html").exists():
            return candidate
    return candidates[0]


def _state_event_payload(controller: ApiController, reason: str) -> dict[str, Any]:
    try:
        return {
            "reason": reason,
            "state": summarize_state(controller.state()),
        }
    except Exception as exc:
        return {
            "reason": reason,
            "state": {
                "ok": False,
                "ready": False,
                "message": f"State snapshot failed: {type(exc).__name__}: {exc}",
            },
        }


def _next_stream_item(iterator: Iterator[dict[str, Any]]) -> dict[str, Any] | None:
    try:
        return next(iterator)
    except StopIteration:
        return None


def _close_iterator(iterator: Any) -> None:
    close = getattr(iterator, "close", None)
    if callable(close):
        close()


def _validate_action(payload: dict[str, Any]) -> Action:
    try:
        return Action.model_validate(payload)
    except Exception as exc:
        raise ApiRequestError(f"Invalid action proposal: {exc}") from exc


def _with_proposal_metadata(
    payload: dict[str, Any],
    *,
    source: str,
    proposed_by: str,
    original_task: str | None = None,
    user_message: str | None = None,
    draft_reason: str | None = None,
    planner_reason: str | None = None,
) -> dict[str, Any]:
    data = dict(payload)
    metadata = dict(data.get("metadata") or {})
    metadata.setdefault("source", source)
    metadata.setdefault("proposed_by", proposed_by)
    if original_task:
        metadata.setdefault("original_task", original_task)
    if user_message:
        metadata.setdefault("user_message", user_message)
    if draft_reason:
        metadata.setdefault("draft_reason", draft_reason)
    if planner_reason:
        metadata.setdefault("planner_reason", planner_reason)
    data["metadata"] = metadata
    return data


def _new_chat_runtime(
    config_path: str | Path,
    *,
    planner_name: str,
    enable_code_skills: bool,
    enable_hardware_integration: bool,
) -> Any:
    from physical_agent.agent.chat_runtime import ChatRuntime

    return ChatRuntime(
        config_path,
        planner_name=planner_name,
        enable_code_skills=enable_code_skills,
        enable_hardware_integration=enable_hardware_integration,
    )


def _api_chat_planner(value: str | None) -> str:
    planner = (value or "auto").strip().lower()
    if planner in {"llm", "openai", "openai_compatible", "openai-compatible"}:
        return "llm"
    if planner in {"rule_based", "rules", "offline"}:
        return "rule_based"
    return "auto"


def _sanitize_api_message(message: str, settings: dict[str, str]) -> str:
    sanitized = message
    api_key = settings.get("api_key") or ""
    if api_key:
        sanitized = sanitized.replace(api_key, "<redacted>")
    sanitized = re.sub(
        r"Bearer\s+[A-Za-z0-9._~+/=-]+",
        "Bearer <redacted>",
        sanitized,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(
        r"(api[_-]?key=)[^&\s]+",
        r"\1<redacted>",
        sanitized,
        flags=re.IGNORECASE,
    )
    return sanitized


def _write_plan(store: StateStore, summary: str, actions: list[Action], *, intent: str) -> None:
    store.write_plan(
        ChatPlan(
            status="proposed_actions" if actions else "answered",
            intent=intent,
            summary=summary,
            steps=["Record task.", "Write proposed actions to the action board."] if actions else ["Record task."],
            actions=actions,
            needs_watch=bool(actions),
        )
    )


def _renumber_actions(actions: list[Action], store: StateStore) -> list[Action]:
    start = _max_action_number(_known_action_ids(store)) + 1
    old_to_new: dict[str, str] = {}
    items: list[dict[str, Any]] = []
    for offset, action in enumerate(actions):
        data = action.model_dump(mode="json")
        old_id = data["id"]
        new_id = f"act_{start + offset:03d}"
        old_to_new[old_id] = new_id
        data["id"] = new_id
        items.append(data)

    result = []
    for data in items:
        data["depends_on"] = [
            old_to_new.get(str(dependency), str(dependency))
            for dependency in data.get("depends_on", [])
        ]
        result.append(Action.model_validate(data))
    return result


async def _write_browser_upload(upload: Any, destination: Path) -> int:
    total = 0
    with destination.open("wb") as handle:
        while True:
            chunk = await upload.read(UPLOAD_READ_CHUNK_BYTES)
            if not chunk:
                break
            total += len(chunk)
            if total > BROWSER_UPLOAD_MAX_BYTES:
                limit_mb = BROWSER_UPLOAD_MAX_BYTES // (1024 * 1024)
                raise ApiRequestError(
                    f"Uploaded file exceeds the {limit_mb}MB limit.",
                    status_code=413,
                    details={
                        "max_bytes": BROWSER_UPLOAD_MAX_BYTES,
                        "received_bytes": total,
                    },
                )
            handle.write(chunk)
    return total


def _browser_upload_filename(filename: str | None) -> str:
    safe_name = sanitize_filename(filename or "upload.txt")
    if not safe_name:
        raise ApiRequestError("Upload filename cannot be empty.")
    return safe_name


def _parse_upload_tags(tags: str | None) -> list[str]:
    if not tags:
        return []
    return [
        item.strip()
        for item in re.split(r"[,;\n]+", tags)
        if item.strip()
    ]


def _known_action_ids(store: StateStore) -> set[str]:
    board = store.read_actions()
    ids = {
        action.id
        for action in board["pending"] + board["completed"] + board["cancelled"]
    }
    for item in store.read_feedback().get("history", []):
        action_id = item.get("action_id")
        if action_id:
            ids.add(str(action_id))
    return ids


def _max_action_number(action_ids: set[str]) -> int:
    maximum = 0
    for action_id in action_ids:
        if action_id.startswith("act_"):
            try:
                maximum = max(maximum, int(action_id.removeprefix("act_")))
            except ValueError:
                continue
    return maximum


def _json_safe(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return value
