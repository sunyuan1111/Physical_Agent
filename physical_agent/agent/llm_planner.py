from __future__ import annotations

import json
import re
from typing import Any

from physical_agent.agent.planner import Planner
from physical_agent.agent.rule_based import RuleBasedPlanner
from physical_agent.llm import OpenAICompatibleClient, OpenAICompatibleSettings
from physical_agent.protocol.schemas import Action


class LLMPlanner(Planner):
    def __init__(
        self,
        *,
        settings: OpenAICompatibleSettings | None = None,
        env_file: str = ".env",
        model: str | None = None,
    ):
        self.settings = settings or OpenAICompatibleSettings.from_env(
            env_file=env_file,
            model=model,
        )
        self.client = OpenAICompatibleClient(self.settings)
        self.fallback = RuleBasedPlanner()

    def plan(
        self,
        *,
        task: str,
        capabilities: dict[str, Any],
        world: dict[str, Any],
    ) -> list[Action]:
        content = self.client.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "You convert physical-world tasks into JSON action intents. "
                        "Return only JSON with this shape: "
                        '{"actions":[{"robot":"...","capability":"...","params":{},'
                        '"reason":"...","depends_on":[]}]} '
                        "Use only robots and capabilities present in the provided capability document. "
                        "Do not invent hardware calls. Do not include Markdown."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "task": task,
                            "capabilities": _json_safe(capabilities),
                            "world": _json_safe(world),
                        },
                        ensure_ascii=True,
                    ),
                },
            ],
            temperature=0.0,
            max_tokens=1200,
        )
        payload = _extract_json(content)
        actions_data = payload.get("actions", [])
        if not isinstance(actions_data, list):
            raise ValueError("LLM planner response must contain an actions list.")
        normalized_items: list[dict[str, Any]] = []
        for index, item in enumerate(actions_data, start=1):
            if not isinstance(item, dict):
                raise ValueError("Each LLM planner action must be an object.")
            item = dict(item)
            item["id"] = str(item.get("id") or f"act_{index:03d}")
            item.setdefault("params", {})
            normalized_items.append(item)

        action_ids = [item["id"] for item in normalized_items]
        actions = []
        for item in normalized_items:
            item["depends_on"] = _normalize_depends_on(item.get("depends_on", []), action_ids)
            actions.append(Action.model_validate(item))
        return actions


def _extract_json(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", stripped, re.DOTALL)
        if not match:
            raise
        value = json.loads(match.group(0))
    if not isinstance(value, dict):
        raise ValueError("LLM planner response must be a JSON object.")
    return value


def _json_safe(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def _normalize_depends_on(value: Any, action_ids: list[str]) -> list[str]:
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        value = [value]
    dependencies: list[str] = []
    for dependency in value:
        if isinstance(dependency, int):
            if dependency == 0 and action_ids:
                dependencies.append(action_ids[0])
                continue
            if 1 <= dependency <= len(action_ids):
                dependencies.append(action_ids[dependency - 1])
                continue
        text = str(dependency)
        if text.isdigit():
            number = int(text)
            if number == 0 and action_ids:
                dependencies.append(action_ids[0])
                continue
            if 1 <= number <= len(action_ids):
                dependencies.append(action_ids[number - 1])
                continue
        dependencies.append(text)
    return dependencies
