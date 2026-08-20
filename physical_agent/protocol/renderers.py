from __future__ import annotations

from typing import Any

from physical_agent.protocol.markdown import fenced_yaml, render_front_matter
from physical_agent.protocol.memory import normalize_memory_notes
from physical_agent.protocol.schemas import Action, ChatMessage, ChatPlan, Observation


def _as_plain(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", exclude_none=True)
    if isinstance(value, list):
        return [_as_plain(item) for item in value]
    if isinstance(value, dict):
        return {key: _as_plain(item) for key, item in value.items()}
    return value


def render_task(
    task: str,
    constraints: list[str] | None = None,
    *,
    owner: str = "human",
    revision: int = 1,
    status: str = "active",
) -> str:
    metadata = {
        "schema": "physical-agent/task/v1",
        "owner": owner,
        "status": status,
        "revision": revision,
    }
    body = f"# Task\n\n{task.strip() or 'No active task.'}\n\n# Constraints\n\n{fenced_yaml(constraints or [])}\n"
    return render_front_matter(metadata, body)


def render_capabilities(robots: dict[str, Any], *, revision: int = 1) -> str:
    metadata = {
        "schema": "physical-agent/capabilities/v1",
        "owner": "watch",
        "revision": revision,
    }
    body = f"# Capabilities\n\n## Robots\n\n{fenced_yaml(_as_plain(robots))}\n"
    return render_front_matter(metadata, body)


def render_world(observation: Observation | dict[str, Any], *, revision: int = 1) -> str:
    data = _as_plain(observation)
    summary = data.get("summary", "") if isinstance(data, dict) else ""
    state = {
        "robots": data.get("robots", {}),
        "objects": data.get("objects", {}),
        "environment": data.get("environment", {}),
        "artifacts": data.get("artifacts", []),
        "raw": data.get("raw", {}),
    }
    metadata = {
        "schema": "physical-agent/world/v1",
        "owner": "watch",
        "revision": revision,
    }
    body = (
        "# World State\n\n"
        "## Summary\n\n"
        f"{summary or 'No observation has been recorded yet.'}\n\n"
        "## State\n\n"
        f"{fenced_yaml(state)}\n"
    )
    return render_front_matter(metadata, body)


def render_actions(
    pending: list[Action | dict[str, Any]] | None = None,
    completed: list[Action | dict[str, Any]] | None = None,
    cancelled: list[Action | dict[str, Any]] | None = None,
    *,
    revision: int = 1,
) -> str:
    metadata = {
        "schema": "physical-agent/actions/v1",
        "owner": "agent",
        "revision": revision,
    }
    body = (
        "# Action Board\n\n"
        "## Pending\n\n"
        f"{fenced_yaml(_as_plain(pending or []))}\n\n"
        "## Completed\n\n"
        f"{fenced_yaml(_as_plain(completed or []))}\n\n"
        "## Cancelled\n\n"
        f"{fenced_yaml(_as_plain(cancelled or []))}\n"
    )
    return render_front_matter(metadata, body)


def render_feedback(
    latest: dict[str, Any] | None = None,
    history: list[dict[str, Any]] | None = None,
    *,
    revision: int = 1,
) -> str:
    metadata = {
        "schema": "physical-agent/feedback/v1",
        "owner": "watch",
        "revision": revision,
    }
    body = (
        "# Execution Feedback\n\n"
        "## Latest\n\n"
        f"{fenced_yaml(latest or {})}\n\n"
        "## History\n\n"
        f"{fenced_yaml(history or [])}\n"
    )
    return render_front_matter(metadata, body)


def render_safety(rules: dict[str, Any] | None = None, *, revision: int = 1) -> str:
    metadata = {
        "schema": "physical-agent/safety/v1",
        "owner": "human",
        "revision": revision,
    }
    defaults = {
        "require_human_approval_for_real_hardware": True,
        "allow_autonomous_execution": True,
        "max_action_timeout_s": 30,
        "forbid_duplicate_action_ids": True,
    }
    if rules:
        defaults.update(rules)
    body = "# Safety Policy\n\n## Rules\n\n" f"{fenced_yaml(defaults)}\n"
    return render_front_matter(metadata, body)


def render_log(body: str = "# Physical Agent Log\n", *, revision: int = 1) -> str:
    metadata = {
        "schema": "physical-agent/log/v1",
        "owner": "system",
        "revision": revision,
    }
    return render_front_matter(metadata, body)


def render_chat(
    messages: list[ChatMessage | dict[str, Any]] | None = None,
    *,
    running_summary: str = "",
    revision: int = 1,
) -> str:
    metadata = {
        "schema": "physical-agent/chat/v1",
        "owner": "agent",
        "revision": revision,
    }
    summary = {"summary": running_summary.strip()}
    body = (
        "# Chat\n\n"
        "## Running Summary\n\n"
        f"{fenced_yaml(summary)}\n\n"
        "## Messages\n\n"
        f"{fenced_yaml(_as_plain(messages or []))}\n"
    )
    return render_front_matter(metadata, body)


def render_plan(plan: ChatPlan | dict[str, Any] | None = None, *, revision: int = 1) -> str:
    metadata = {
        "schema": "physical-agent/plan/v1",
        "owner": "agent",
        "revision": revision,
    }
    value = plan or ChatPlan()
    body = "# Plan\n\n## Current\n\n" f"{fenced_yaml(_as_plain(value))}\n"
    return render_front_matter(metadata, body)


def render_memory(notes: list[dict[str, Any]] | None = None, *, revision: int = 1) -> str:
    metadata = {
        "schema": "physical-agent/memory/v1",
        "owner": "agent",
        "revision": revision,
    }
    body = "# Memory\n\n## Notes\n\n" f"{fenced_yaml(normalize_memory_notes(notes or []))}\n"
    return render_front_matter(metadata, body)
