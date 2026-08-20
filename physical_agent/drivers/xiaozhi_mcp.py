from __future__ import annotations
import json
import os
import urllib.request
from copy import deepcopy
from typing import Any

from physical_agent.drivers.base import PhysicalDriver
from physical_agent.drivers.transport import (
    ReconnectPolicy,
    TransportDisconnected,
    TransportReconnecting,
    WebSocketTransport,
)
from physical_agent.env import load_dotenv
from physical_agent.protocol.schemas import Action, ActionResult, Capability, DriverContext, HealthStatus, Observation


MANIFEST = {
    "schema": "physical-agent/driver/v1",
    "name": "xiaozhi_mcp",
    "version": "0.1.0",
    "description": "Example driver that treats a Xiaozhi MCP tool endpoint as hardware.",
    "entrypoint": {"module": "xiaozhi_mcp", "class": "XiaozhiMcpDriver"},
    "robot": {"kind": "mcp_device", "supports_simulation": True},
    "config_schema": {
        "type": "object",
        "properties": {
            "mode": {"type": "string", "enum": ["mock", "http", "ws"], "default": "mock"},
            "endpoint_env": {"type": "string", "default": "XIAOZHI_MCP_ENDPOINT"},
            "token_env": {"type": "string", "default": "XIAOZHI_MCP_TOKEN"},
            "ws_url_env": {"type": "string", "default": "XIAOZHI_MCP_URL"},
            "host_env": {"type": "string", "default": "XIAOZHI_MCP_HOST"},
            "port_env": {"type": "string", "default": "XIAOZHI_MCP_PORT"},
            "path_env": {"type": "string", "default": "XIAOZHI_MCP_PATH"},
            "timeout_s": {"type": "number", "minimum": 1, "default": 10},
            "connect_timeout_s": {"type": "number", "minimum": 0.1, "default": 2},
            "wait_for_responses": {"type": "boolean", "default": True},
            "reconnect_policy": {
                "type": "object",
                "properties": {
                    "enabled": {"type": "boolean", "default": False},
                    "max_retries": {"type": "integer", "minimum": 0, "default": 3},
                    "backoff_base_ms": {"type": "integer", "minimum": 1, "default": 250},
                    "backoff_cap_ms": {"type": "integer", "minimum": 1, "default": 5000},
                    "jitter_ms": {"type": "integer", "minimum": 0, "default": 0},
                },
                "additionalProperties": False,
            },
            "device_name": {"type": "string", "default": "xiaozhi-device"},
            "tool_prefix": {"type": "string", "default": "self.device"},
            "url": {"type": "string"},
            "host": {"type": "string"},
            "port": {"type": "integer", "minimum": 1, "maximum": 65535},
            "path": {"type": "string"},
            "tools": {
                "type": "object",
                "properties": {
                    "observe": {"type": "string"},
                    "set_volume": {"type": "string"},
                    "otto_action": {"type": "string"},
                    "home": {"type": "string"},
                    "stop": {"type": "string"},
                },
                "additionalProperties": {"type": "string"},
            },
            "mock_state": {"type": "object"},
        },
        "additionalProperties": False,
    },
    "dependencies": {"python": []},
    "capability_contract": {"source": "runtime"},
}


DEFAULT_TOOLS = {
    "observe": "self.get_device_status",
    "set_volume": "self.audio_speaker.set_volume",
    "otto_action": "self.otto.action",
    "home": "self.otto.action",
    "stop": "self.otto.stop",
}

OTTO_ACTION_ALIASES = {
    "wave": "hand_wave",
    "waving": "hand_wave",
    "handwave": "hand_wave",
    "hello": "greeting",
    "reset": "home",
    "stand": "home",
}

OTTO_ARG_RANGES = {
    "steps": (1, 100),
    "speed": (100, 3000),
    "direction": (-1, 1),
    "amount": (0, 170),
    "arm_swing": (0, 170),
}

OTTO_ACTION_ARGS = {
    "walk": {"steps", "speed", "direction", "arm_swing"},
    "turn": {"steps", "speed", "direction", "arm_swing"},
    "jump": {"steps", "speed"},
    "swing": {"steps", "speed", "amount"},
    "moonwalk": {"steps", "speed", "direction", "amount"},
    "bend": {"steps", "speed", "direction"},
    "shake_leg": {"steps", "speed", "direction"},
    "updown": {"steps", "speed", "amount"},
    "whirlwind_leg": {"steps", "speed", "amount"},
    "hands_up": {"speed", "direction"},
    "hands_down": {"speed", "direction"},
    "hand_wave": {"direction"},
    "windmill": {"steps", "speed", "amount"},
    "takeoff": {"steps", "speed", "amount"},
    "fitness": {"steps", "speed", "amount"},
    "greeting": {"steps", "direction"},
    "shy": {"steps", "direction"},
    "home": set(),
}


class XiaozhiMcpWebSocketClient:
    """Small blocking JSON-RPC client for XiaoZhi's local WebSocket MCP server."""

    def __init__(
        self,
        url: str,
        *,
        connect_timeout_s: float = 2.0,
        timeout_s: float = 10.0,
        reconnect_policy: ReconnectPolicy | dict[str, Any] | None = None,
        on_reconnected: Any | None = None,
    ) -> None:
        self.url = url
        self.connect_timeout_s = connect_timeout_s
        self.timeout_s = timeout_s
        self.transport = WebSocketTransport(
            url,
            connect_timeout_s=connect_timeout_s,
            timeout_s=timeout_s,
            reconnect_policy=reconnect_policy,
            on_reconnected=on_reconnected,
        )
        self._next_id = 1

    @property
    def is_connected(self) -> bool:
        return self.transport.is_open

    def connect(self) -> None:
        self.close()
        self.transport.open()

    def close(self) -> None:
        self.transport.close()

    def initialize(self) -> dict[str, Any]:
        return self.request(
            "initialize",
            {
                "capabilities": {},
                "clientInfo": {"name": "physical-agent-watch", "version": "0.1.0"},
            },
        )

    def list_tools(self) -> list[dict[str, Any]]:
        response = self.request("tools/list", {})
        tools = response.get("tools", [])
        if not isinstance(tools, list):
            return []
        return [item for item in tools if isinstance(item, dict)]

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.request(
            "tools/call",
            {"name": name, "arguments": arguments or {}},
        )

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._require_connected()

        request_id = self._next_id
        self._next_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params or {},
        }
        self._send_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))

        while True:
            response = self._decode_message(self._recv_text())
            if response.get("id") != request_id:
                continue
            if "error" in response:
                error = response["error"]
                if isinstance(error, dict):
                    raise RuntimeError(str(error.get("message") or error))
                raise RuntimeError(str(error))
            result = response.get("result")
            return result if isinstance(result, dict) else {"value": result}

    def send_request(self, method: str, params: dict[str, Any] | None = None) -> int:
        self._require_connected()

        request_id = self._next_id
        self._next_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params or {},
        }
        self._send_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        return request_id

    def send_tool_call(self, name: str, arguments: dict[str, Any] | None = None) -> int:
        return self.send_request(
            "tools/call",
            {"name": name, "arguments": arguments or {}},
        )

    def _send_text(self, message: str) -> None:
        self.transport.write_text(message)

    def _recv_text(self) -> str:
        return self.transport.read(self.timeout_s).decode("utf-8", errors="replace")

    def _decode_message(self, message: str | bytes) -> dict[str, Any]:
        if isinstance(message, bytes):
            message = message.decode("utf-8", errors="replace")
        data = json.loads(message)
        if isinstance(data, dict) and data.get("type") == "mcp":
            payload = data.get("payload")
            if isinstance(payload, dict):
                return payload
        if isinstance(data, dict):
            return data
        raise RuntimeError(f"Unexpected MCP response: {data!r}")

    def _require_connected(self) -> None:
        if self.is_connected:
            return
        health = self.transport.health()
        if health.status == "reconnecting":
            raise TransportReconnecting(
                "XiaoZhi MCP WebSocket is reconnecting; command was not queued."
            )
        raise TransportDisconnected(
            "XiaoZhi MCP WebSocket is disconnected; command was not queued."
        )


class XiaozhiMcpDriver(PhysicalDriver):
    """Physical Agent driver for a Xiaozhi-style MCP device adapter.

    The driver deliberately lives on the watch side. The agent only sees the
    capabilities published through StateStore and never calls the MCP endpoint
    directly.
    """

    def __init__(self, context: DriverContext):
        super().__init__(context)
        load_dotenv(context.workspace_path.parent / ".env")
        self.config = dict(context.config)
        self.mode = self.config.get("mode", "mock")
        self.timeout_s = float(self.config.get("timeout_s", 10))
        self.connect_timeout_s = float(self.config.get("connect_timeout_s", 2))
        self.reconnect_policy = ReconnectPolicy.from_config(
            self.config.get("reconnect_policy")
        )
        wait_default = False if self.mode == "ws" else True
        self.wait_for_responses = bool(self.config.get("wait_for_responses", wait_default))
        self.device_name = self.config.get("device_name", "xiaozhi-device")
        self.tool_prefix = self.config.get("tool_prefix", "self.device")
        self.tools = dict(DEFAULT_TOOLS)
        self.tools.update(self.config.get("tools", {}))
        self.session_id: str | None = None
        self.remote_tools: dict[str, dict[str, Any]] = {}
        self.ws_client: XiaozhiMcpWebSocketClient | None = None
        self.connected = False
        self._transport_reconnected = False
        self.last_action: str | None = None
        self.state = _default_mock_state(self.config.get("mock_state", {}))

    async def connect(self) -> None:
        if self.mode == "http":
            self._endpoint()
        elif self.mode == "ws":
            await self._connect_websocket()
        elif self.mode != "mock":
            raise ValueError(f"Unsupported xiaozhi_mcp mode: {self.mode}")

        if self.mode in {"http", "ws"}:
            if self.wait_for_responses:
                await self._initialize_remote_session()
                await self._refresh_remote_tools()
            else:
                self.remote_tools = {
                    tool_name: {"name": tool_name, "mapped_from": key}
                    for key, tool_name in self.tools.items()
                }
        self.connected = True

    async def disconnect(self) -> None:
        if self.ws_client is not None:
            client = self.ws_client
            self.ws_client = None
            client.close()
        self.connected = False

    async def health(self) -> HealthStatus:
        if self.mode == "http":
            ok = self.connected and bool(self._endpoint(required=False))
            message = "connected to MCP endpoint" if ok else "missing MCP endpoint"
            return HealthStatus(
                ok=ok,
                message=message,
                details={
                    "mode": self.mode,
                    "session_id": self.session_id,
                    "remote_tools": sorted(self.remote_tools),
                },
            )
        if self.mode == "ws":
            await self._maybe_reinitialize_after_reconnect()
            url = self._ws_url(required=False)
            transport_health = (
                self.ws_client.transport.health()
                if self.ws_client is not None
                else None
            )
            ok = self.connected and self.ws_client is not None and self.ws_client.is_connected
            detail = "fire-and-forget" if not self.wait_for_responses else "request-response"
            message = (
                f"connected to local MCP websocket ({detail})"
                if ok
                else "missing or disconnected MCP websocket"
            )
            return HealthStatus(
                ok=ok,
                message=message,
                details={
                    "mode": self.mode,
                    "ws_url": url,
                    "wait_for_responses": self.wait_for_responses,
                    "session_id": self.session_id,
                    "remote_tools": sorted(self.remote_tools),
                    "transport": (
                        transport_health.details | {"status": transport_health.status}
                        if transport_health is not None
                        else {}
                    ),
                },
            )
        return HealthStatus(ok=self.connected, message="mock device connected", details={"mode": self.mode})

    async def observe(self) -> Observation:
        if self.mode in {"http", "ws"} and self.connected:
            if self.mode == "ws" and not self.wait_for_responses:
                await self._maybe_reinitialize_after_reconnect()
                return Observation(
                    summary=(
                        f"{self.device_name} is connected over local MCP WebSocket in fire-and-forget mode. "
                        "Remote observe responses are disabled, so state is limited."
                    ),
                    robots={
                        self.context.robot_id: {
                            "status": "idle",
                            "device": self.device_name,
                            "mode": self.mode,
                            "last_action": self.last_action,
                            "endpoint": self._remote_endpoint_label(),
                        }
                    },
                    environment={
                        "xiaozhi_mcp": {
                            "transport": "websocket",
                            "wait_for_responses": False,
                            "known_tools": sorted(self.remote_tools),
                            "state_cache": deepcopy(self.state),
                        }
                    },
                )
            response = await self._call_tool(self.tools["observe"], {})
            summary = str(response.get("summary") or "Xiaozhi MCP device responded to observe.")
            raw_state = response.get("state") if isinstance(response.get("state"), dict) else response
            return Observation(
                summary=summary,
                robots={
                    self.context.robot_id: {
                        "status": "idle",
                        "device": self.device_name,
                        "mode": self.mode,
                        "session_id": self.session_id,
                        "last_action": self.last_action,
                        "endpoint": self._remote_endpoint_label(),
                    }
                },
                environment={"xiaozhi_mcp": raw_state},
                raw={"mcp_observe": response},
            )

        summary = (
            f"{self.device_name} is online in mock mode. "
            f"Volume is {self.state['speaker']['volume']}. "
            f"Last motion is {self.state['motion']['last_action']}."
        )
        return Observation(
            summary=summary,
            robots={
                self.context.robot_id: {
                    "status": "idle" if self.connected else "offline",
                    "device": self.device_name,
                    "mode": self.mode,
                    "last_action": self.last_action,
                }
            },
            environment={"xiaozhi_mcp": deepcopy(self.state)},
        )

    def capabilities(self) -> list[Capability]:
        return [
            Capability(
                name="observe",
                description="Observe the Xiaozhi MCP device state.",
                params_schema={"type": "object", "properties": {}, "additionalProperties": False},
            ),
            Capability(
                name="set_volume",
                description="Set the XiaoZhi device speaker volume to 0-100.",
                params_schema={
                    "type": "object",
                    "required": ["volume"],
                    "properties": {
                        "volume": {"type": "integer", "minimum": 0, "maximum": 100},
                    },
                    "additionalProperties": False,
                },
            ),
            Capability(
                name="otto_action",
                description="Run an Otto motion such as hand_wave, walk, turn, greeting, or jump.",
                params_schema={
                    "type": "object",
                    "required": ["action"],
                    "properties": {
                        "action": {"type": "string", "minLength": 1},
                        "steps": {"type": "integer", "minimum": 1, "maximum": 100},
                        "speed": {"type": "integer", "minimum": 100, "maximum": 3000},
                        "direction": {"type": "integer", "minimum": -1, "maximum": 1},
                        "amount": {"type": "integer", "minimum": 0, "maximum": 170},
                        "arm_swing": {"type": "integer", "minimum": 0, "maximum": 170},
                    },
                    "additionalProperties": False,
                },
            ),
            Capability(
                name="home",
                description="Return the robot to its home pose.",
                params_schema={"type": "object", "properties": {}, "additionalProperties": False},
            ),
            Capability(
                name="stop",
                description="Stop the robot's current motion.",
                params_schema={"type": "object", "properties": {}, "additionalProperties": False},
            ),
        ]

    async def execute(self, action: Action) -> ActionResult:
        if action.capability == "observe":
            observation = await self.observe()
            return ActionResult(
                status="completed",
                message="Xiaozhi MCP observation completed.",
                result={"observation": observation.model_dump(mode="json")},
            )
        if action.capability == "set_volume":
            volume = int(action.params["volume"])
            if self.mode in {"http", "ws"}:
                response = await self._call_tool(self.tools["set_volume"], {"volume": volume})
            else:
                response = {"volume": volume, "mode": "mock"}
            self.last_action = f"set_volume:{volume}"
            self.state["speaker"]["volume"] = volume
            return ActionResult(
                status="completed",
                message=f"Xiaozhi MCP volume set to {volume}.",
                result={"volume": volume, "mcp_result": response},
            )
        if action.capability == "otto_action":
            params = self._normalize_otto_params(action.params)
            if self.mode in {"http", "ws"}:
                response = await self._call_tool(self.tools["otto_action"], params)
            else:
                response = {"action": params, "mode": "mock"}
            self.last_action = f"otto_action:{params['action']}"
            self.state["motion"]["last_action"] = deepcopy(params)
            return ActionResult(
                status="completed",
                message=f"Xiaozhi Otto action sent: {params['action']}.",
                result={"action": params, "mcp_result": response},
            )
        if action.capability == "home":
            params = {"action": "home"}
            if self.mode in {"http", "ws"}:
                response = await self._call_tool(self.tools["home"], params)
            else:
                response = {"action": "home", "mode": "mock"}
            self.last_action = "home"
            self.state["motion"]["last_action"] = deepcopy(params)
            return ActionResult(
                status="completed",
                message="Xiaozhi home action sent.",
                result={"action": params, "mcp_result": response},
            )
        if action.capability == "stop":
            if self.mode in {"http", "ws"}:
                response = await self._call_tool(self.tools["stop"], {})
            else:
                response = {"action": "stop", "mode": "mock"}
            self.last_action = "stop"
            self.state["motion"]["last_action"] = {"action": "stop"}
            return ActionResult(
                status="completed",
                message="Xiaozhi stop action sent.",
                result={"action": {"action": "stop"}, "mcp_result": response},
            )
        return ActionResult(status="failed", message=f"Unsupported capability: {action.capability}")

    async def _call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if self.mode == "ws":
            await self._maybe_reinitialize_after_reconnect()
            client = self._require_ws_client()
            if not self.wait_for_responses:
                request_id = client.send_tool_call(tool_name, arguments)
                return {
                    "sent": True,
                    "request_id": request_id,
                    "tool": tool_name,
                    "mode": "ws-fire-and-forget",
                }
            return client.call_tool(tool_name, arguments)
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_request_id(tool_name),
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }
        return self._post_jsonrpc(payload)

    async def _initialize_remote_session(self) -> None:
        if self.mode == "ws":
            client = self._require_ws_client()
            response = client.initialize()
            session_id = response.get("session_id") or response.get("sessionId")
            if session_id is not None:
                self.session_id = str(session_id)
            return
        response = self._post_jsonrpc(
            {
                "jsonrpc": "2.0",
                "id": self._next_request_id("initialize"),
                "method": "initialize",
                "params": {
                    "clientInfo": {
                        "name": "physical-agent-watch",
                        "version": "0.1.0",
                    },
                    "capabilities": {},
                },
            }
        )
        session_id = response.get("session_id") or response.get("sessionId")
        if session_id is not None:
            self.session_id = str(session_id)

    async def _refresh_remote_tools(self) -> None:
        if self.mode == "ws":
            client = self._require_ws_client()
            tools = client.list_tools()
            self.remote_tools = {
                str(tool.get("name")): tool
                for tool in tools
                if isinstance(tool, dict) and tool.get("name")
            }
            for key, tool_name in list(self.tools.items()):
                if tool_name not in self.remote_tools:
                    self.remote_tools[tool_name] = {"name": tool_name, "mapped_from": key}
            return
        response = self._post_jsonrpc(
            {
                "jsonrpc": "2.0",
                "id": self._next_request_id("tools/list"),
                "method": "tools/list",
                "params": {},
            }
        )
        tools = response.get("tools", [])
        if isinstance(tools, list):
            self.remote_tools = {
                str(tool.get("name")): tool
                for tool in tools
                if isinstance(tool, dict) and tool.get("name")
            }
            for key, tool_name in list(self.tools.items()):
                if tool_name not in self.remote_tools and self.mode == "http":
                    # Keep the configured tool mapping even when the endpoint does not echo it.
                    self.remote_tools[tool_name] = {"name": tool_name, "mapped_from": key}

    def _post_jsonrpc(self, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self._endpoint(),
            data=body,
            headers=self._headers(),
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
            data = json.loads(response.read().decode("utf-8"))
        if "error" in data:
            raise RuntimeError(f"MCP tool call failed: {data['error']}")
        result = data.get("result", {})
        return result if isinstance(result, dict) else {"value": result}

    def _next_request_id(self, method: str) -> str:
        suffix = f"{self.context.robot_id}:{method}"
        if self.session_id:
            return f"{self.session_id}:{suffix}"
        return f"pa:{suffix}"

    async def _connect_websocket(self) -> None:
        url = self._ws_url()
        client = self._build_ws_client(url)
        client.connect()
        self.ws_client = client

    def _build_ws_client(self, url: str) -> XiaozhiMcpWebSocketClient:
        return XiaozhiMcpWebSocketClient(
            url,
            connect_timeout_s=self.connect_timeout_s,
            timeout_s=self.timeout_s,
            reconnect_policy=self.reconnect_policy,
            on_reconnected=self._mark_transport_reconnected,
        )

    def _mark_transport_reconnected(self) -> None:
        self._transport_reconnected = True

    async def _maybe_reinitialize_after_reconnect(self) -> None:
        if not self._transport_reconnected:
            return
        await self.on_transport_reconnected()
        self._transport_reconnected = False

    async def on_transport_reconnected(self) -> None:
        if self.mode != "ws":
            return
        if self.wait_for_responses:
            self.session_id = None
            await self._initialize_remote_session()
            await self._refresh_remote_tools()
        else:
            self.remote_tools = {
                tool_name: {"name": tool_name, "mapped_from": key}
                for key, tool_name in self.tools.items()
            }
        self.connected = True

    def _endpoint(self, *, required: bool = True) -> str:
        endpoint_env = self.config.get("endpoint_env", "XIAOZHI_MCP_ENDPOINT")
        endpoint = os.getenv(endpoint_env) or self.config.get("endpoint")
        if required and not endpoint:
            raise ValueError(
                f"Missing Xiaozhi MCP endpoint. Set {endpoint_env} in .env or use mode: mock."
            )
        return str(endpoint or "")

    def _ws_url(self, *, required: bool = True) -> str:
        url_env = self.config.get("ws_url_env", "XIAOZHI_MCP_URL")
        direct_url = (
            os.getenv(url_env)
            or self.config.get("url")
            or (
                self.config.get("endpoint")
                if str(self.config.get("endpoint", "")).startswith(("ws://", "wss://"))
                else ""
            )
        )
        if direct_url:
            return str(direct_url)

        host_env = self.config.get("host_env", "XIAOZHI_MCP_HOST")
        port_env = self.config.get("port_env", "XIAOZHI_MCP_PORT")
        path_env = self.config.get("path_env", "XIAOZHI_MCP_PATH")

        host = os.getenv(host_env) or self.config.get("host")
        port_raw = os.getenv(port_env) or self.config.get("port") or 8080
        path = str(os.getenv(path_env) or self.config.get("path") or "/ws").strip() or "/ws"

        if required and not host:
            raise ValueError(
                f"Missing XiaoZhi MCP WebSocket host. Set {url_env} or {host_env} in .env."
            )
        if not host:
            return ""
        if not path.startswith("/"):
            path = "/" + path
        try:
            port = int(port_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid XiaoZhi MCP port: {port_raw}") from exc
        return f"ws://{host}:{port}{path}"

    def _require_ws_client(self) -> XiaozhiMcpWebSocketClient:
        if self.ws_client is None or not self.ws_client.is_connected:
            if self.ws_client is not None:
                health = self.ws_client.transport.health()
                if health.status == "reconnecting":
                    raise TransportReconnecting(
                        "XiaoZhi MCP WebSocket is reconnecting; command was not queued."
                    )
            raise TransportDisconnected(
                "XiaoZhi MCP WebSocket is disconnected; command was not queued."
            )
        return self.ws_client

    def _remote_endpoint_label(self) -> str:
        if self.mode == "ws":
            return self._ws_url(required=False)
        if self.mode == "http":
            return self._endpoint(required=False)
        return "mock"

    def _normalize_otto_params(self, params: dict[str, Any]) -> dict[str, Any]:
        action = str(params.get("action") or "home").strip().lower().replace("-", "_")
        action = OTTO_ACTION_ALIASES.get(action, action)
        normalized: dict[str, Any] = {"action": action}
        allowed_args = OTTO_ACTION_ARGS.get(action, set(OTTO_ARG_RANGES))
        for key in allowed_args:
            if key not in params:
                continue
            value = int(params[key])
            minimum, maximum = OTTO_ARG_RANGES[key]
            if key == "speed" and value < minimum:
                continue
            normalized[key] = max(minimum, min(maximum, value))
        return normalized

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        token_env = self.config.get("token_env", "XIAOZHI_MCP_TOKEN")
        token = os.getenv(token_env) or self.config.get("token")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers


def _default_mock_state(overrides: dict[str, Any]) -> dict[str, Any]:
    state: dict[str, Any] = {
        "speaker": {"volume": 50},
        "motion": {"last_action": None},
        "sensors": {"online": True},
    }
    _deep_update(state, deepcopy(overrides))
    return state


def _deep_update(target: dict[str, Any], updates: dict[str, Any]) -> None:
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_update(target[key], value)
        else:
            target[key] = value
