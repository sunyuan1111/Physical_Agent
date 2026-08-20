from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from physical_agent.config import DEFAULT_CONFIG_NAME, load_config
from physical_agent.llm import OpenAICompatibleClient, OpenAICompatibleSettings
from physical_agent.mcp.server import PhysicalAgentMCP


ALLOWED_TOOL_NAMES = frozenset(
    {
        "physical_agent_submit_task",
        "physical_agent_propose_action",
        "physical_agent_get_state",
    }
)


class ToolLoopError(RuntimeError):
    pass


@dataclass(frozen=True)
class ToolLoopStep:
    name: str
    arguments: dict[str, Any]
    result: dict[str, Any]
    call_id: str | None = None


@dataclass(frozen=True)
class ToolLoopResult:
    content: str
    steps: list[ToolLoopStep] = field(default_factory=list)
    iterations: int = 0
    raw_response: dict[str, Any] = field(default_factory=dict)


class OpenAIToolLoop:
    """Run OpenAI tool calls against Physical Agent's proposal-only MCP facade."""

    def __init__(
        self,
        config_path: str | Path = DEFAULT_CONFIG_NAME,
        *,
        client: OpenAICompatibleClient | None = None,
        settings: OpenAICompatibleSettings | None = None,
        mcp: PhysicalAgentMCP | None = None,
        max_steps: int | None = None,
        allowed_tool_names: set[str] | frozenset[str] | None = None,
    ):
        self.config_path = Path(config_path).resolve()
        self.base_dir = self.config_path.parent
        self.client = client
        self.settings = settings
        self.mcp = mcp or PhysicalAgentMCP(self.config_path)
        self.max_steps = max_steps
        requested = allowed_tool_names or ALLOWED_TOOL_NAMES
        self.allowed_tool_names = frozenset(requested) & ALLOWED_TOOL_NAMES

    async def run(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        metadata: dict[str, str] | None = None,
    ) -> ToolLoopResult:
        client = self._client()
        if client.settings.api_mode == "responses":
            return await self._run_responses(
                client,
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
                metadata=metadata,
            )
        return await self._run_chat_completions(
            client,
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            metadata=metadata,
        )

    async def _run_chat_completions(
        self,
        client: OpenAICompatibleClient,
        messages: list[dict[str, Any]],
        *,
        temperature: float,
        max_tokens: int,
        metadata: dict[str, str] | None,
    ) -> ToolLoopResult:
        running_messages = [dict(message) for message in messages]
        steps: list[ToolLoopStep] = []
        tools = _chat_completion_tools(self._tool_specs())
        raw: dict[str, Any] = {}

        for iteration in range(1, self._max_steps() + 1):
            raw = client.chat_completion_create(
                running_messages,
                temperature=temperature,
                max_tokens=max_tokens,
                tools=tools,
                metadata=metadata,
            )
            message = _chat_message(raw)
            tool_calls = message.get("tool_calls") or []
            if not tool_calls:
                return ToolLoopResult(
                    content=str(message.get("content") or ""),
                    steps=steps,
                    iterations=iteration,
                    raw_response=raw,
                )

            running_messages.append(
                {
                    "role": "assistant",
                    "content": message.get("content"),
                    "tool_calls": tool_calls,
                }
            )
            for call in tool_calls:
                name, arguments, call_id = _parse_chat_tool_call(call)
                result = await self._dispatch(name, arguments)
                steps.append(
                    ToolLoopStep(
                        name=name,
                        arguments=arguments,
                        result=result,
                        call_id=call_id,
                    )
                )
                running_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )

        raise ToolLoopError(f"Tool loop exceeded max_steps={self._max_steps()}.")

    async def _run_responses(
        self,
        client: OpenAICompatibleClient,
        messages: list[dict[str, Any]],
        *,
        temperature: float,
        max_tokens: int,
        metadata: dict[str, str] | None,
    ) -> ToolLoopResult:
        instructions, input_items = _messages_to_responses_parts(messages)
        running_input = [dict(item) for item in input_items]
        steps: list[ToolLoopStep] = []
        raw: dict[str, Any] = {}

        for iteration in range(1, self._max_steps() + 1):
            raw = client.responses_create_input(
                running_input,
                instructions=instructions or None,
                temperature=temperature,
                max_tokens=max_tokens,
                tools=self._tool_specs(),
                metadata=metadata,
            )
            output_items = _response_output_items(raw)
            tool_calls = _response_tool_calls(output_items)
            if not tool_calls:
                return ToolLoopResult(
                    content=_responses_text(raw),
                    steps=steps,
                    iterations=iteration,
                    raw_response=raw,
                )

            running_input.extend(output_items)
            for call in tool_calls:
                name = call["name"]
                arguments = call["arguments"]
                call_id = call["call_id"]
                result = await self._dispatch(name, arguments)
                steps.append(
                    ToolLoopStep(
                        name=name,
                        arguments=arguments,
                        result=result,
                        call_id=call_id,
                    )
                )
                running_input.append(
                    {
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": json.dumps(result, ensure_ascii=False),
                    }
                )

        raise ToolLoopError(f"Tool loop exceeded max_steps={self._max_steps()}.")

    async def _dispatch(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name not in self.allowed_tool_names:
            raise ToolLoopError(f"Tool is not allowlisted: {name}")

        if name == "physical_agent_submit_task":
            task = arguments.get("task")
            if not isinstance(task, str) or not task.strip():
                raise ToolLoopError("physical_agent_submit_task requires a non-empty task.")
            result = await self.mcp.submit_task(task)
            return _jsonable_dict(result)

        if name == "physical_agent_propose_action":
            action = arguments.get("action") if isinstance(arguments.get("action"), dict) else arguments
            return _jsonable_dict(self.mcp.propose_action(action))

        if name == "physical_agent_get_state":
            return _jsonable_dict(self.mcp.get_state())

        raise ToolLoopError(f"Tool is not implemented: {name}")

    def _client(self) -> OpenAICompatibleClient:
        if self.client is not None:
            return self.client
        config = load_config(self.config_path)
        settings = self.settings or OpenAICompatibleSettings.from_env(
            env_file=self.base_dir / ".env",
            workspace_path=config.workspace_path(self.base_dir),
        )
        self.client = OpenAICompatibleClient(settings)
        return self.client

    def _max_steps(self) -> int:
        if self.max_steps is not None:
            return max(1, self.max_steps)
        try:
            return max(1, load_config(self.config_path).agent.max_steps)
        except Exception:
            return 8

    def _tool_specs(self) -> list[dict[str, Any]]:
        specs: list[dict[str, Any]] = []
        for spec in self.mcp.tool_specs():
            name = str(spec.get("name") or "")
            if name not in self.allowed_tool_names:
                continue
            item = dict(spec)
            item["strict"] = bool(item.get("strict", True))
            specs.append(item)
        return specs


def _chat_completion_tools(specs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = []
    for spec in specs:
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": spec["name"],
                    "description": spec.get("description", ""),
                    "parameters": spec.get(
                        "parameters",
                        {"type": "object", "additionalProperties": False, "properties": {}},
                    ),
                    "strict": bool(spec.get("strict", True)),
                },
            }
        )
    return tools


def _chat_message(raw: dict[str, Any]) -> dict[str, Any]:
    try:
        message = raw["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ToolLoopError("Chat Completions response did not include a message.") from exc
    if not isinstance(message, dict):
        raise ToolLoopError("Chat Completions message must be an object.")
    return message


def _parse_chat_tool_call(call: dict[str, Any]) -> tuple[str, dict[str, Any], str]:
    if not isinstance(call, dict):
        raise ToolLoopError("Tool call must be an object.")
    function = call.get("function")
    if not isinstance(function, dict):
        raise ToolLoopError("Chat tool call missing function payload.")
    name = str(function.get("name") or "")
    arguments = _parse_arguments(function.get("arguments"))
    call_id = str(call.get("id") or "")
    if not call_id:
        raise ToolLoopError("Chat tool call missing id.")
    return name, arguments, call_id


def _response_output_items(raw: dict[str, Any]) -> list[dict[str, Any]]:
    output = raw.get("output", [])
    if not isinstance(output, list):
        raise ToolLoopError("Responses API response did not include an output list.")
    return [dict(item) for item in output if isinstance(item, dict)]


def _response_tool_calls(output_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for item in output_items:
        if item.get("type") != "function_call":
            continue
        name = str(item.get("name") or "")
        call_id = str(item.get("call_id") or item.get("id") or "")
        if not name or not call_id:
            raise ToolLoopError("Responses function_call item missing name or call_id.")
        calls.append(
            {
                "name": name,
                "call_id": call_id,
                "arguments": _parse_arguments(item.get("arguments")),
            }
        )
    return calls


def _responses_text(raw: dict[str, Any]) -> str:
    direct = raw.get("output_text")
    if isinstance(direct, str):
        return direct

    fragments: list[str] = []
    for item in _response_output_items(raw):
        content = item.get("content", [])
        if not isinstance(content, list):
            continue
        for part in content:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                fragments.append(part["text"])
    return "".join(fragments)


def _messages_to_responses_parts(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    instructions: list[str] = []
    items: list[dict[str, Any]] = []
    for message in messages:
        role = str(message.get("role", "user"))
        content = str(message.get("content", ""))
        if role == "system":
            if content:
                instructions.append(content)
            continue
        items.append({"role": role, "content": content})
    return "\n\n".join(instructions), items


def _parse_arguments(raw: Any) -> dict[str, Any]:
    if raw is None or raw == "":
        return {}
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        raise ToolLoopError("Tool arguments must be a JSON object.")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ToolLoopError(f"Tool arguments were not valid JSON: {raw[:200]}") from exc
    if not isinstance(parsed, dict):
        raise ToolLoopError("Tool arguments must decode to a JSON object.")
    return parsed


def _jsonable_dict(value: Any) -> dict[str, Any]:
    encoded = json.loads(json.dumps(value, default=_json_default))
    if not isinstance(encoded, dict):
        return {"value": encoded}
    return encoded


def _json_default(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return str(value)
