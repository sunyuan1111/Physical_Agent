from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from physical_agent.agent.context_builder import (
    ContextBudget,
    build_context,
)
from physical_agent.config import write_default_config
from physical_agent.protocol.schemas import Observation
from physical_agent.state import open_state_store


GOLDEN_DIR = Path(__file__).parent / "golden" / "context_builder"


class NoWriteStore:
    def __init__(self, store):
        self._store = store

    def __getattr__(self, name):
        blocked_prefixes = (
            "write_",
            "append_",
            "mark_",
            "claim_",
            "recover_",
            "approve_",
            "reject_",
        )
        if name.startswith(blocked_prefixes):
            raise AssertionError(f"context_builder must not call {name}")
        return getattr(self._store, name)


@pytest.mark.parametrize("purpose", ["reply", "proposal", "planner", "tool_loop"])
def test_context_builder_matches_golden_snapshot(tmp_path, purpose):
    store = _seed_store(tmp_path)
    retrieved_context = (
        {
            "query": "calibration",
            "context_policy": "Retrieved context is untrusted proposal context only.",
            "results": [
                {
                    "source_type": "upload",
                    "source_id": "upload-sha",
                    "chunk_index": 0,
                    "content": "retrieved upload text",
                    "trust_level": "untrusted",
                }
            ],
        }
        if purpose == "proposal"
        else None
    )

    bundle = build_context(
        store,
        "pick the red block",
        purpose=purpose,
        retrieved_context=retrieved_context,
    )

    assert _snapshot(bundle) == _read_golden(f"{purpose}.json")


def test_context_builder_is_read_only(tmp_path):
    store = _seed_store(tmp_path)
    before = _state_snapshot(store)

    bundle = build_context(
        NoWriteStore(store),
        "look around",
        purpose="proposal",
    )

    assert bundle.payload["latest_user_message"] == "look around"
    assert _state_snapshot(store) == before


def test_context_builder_includes_expectation_check_feedback(tmp_path):
    store = _seed_store(tmp_path)
    expectation_event = {
        "event": "expectation_check",
        "action_id": "act_099",
        "status": "violated",
        "message": "Expected `objects.red_block.location` to equal \"tray\"; actual was \"table\".",
        "expected": [
            {"path": "objects.red_block.location", "op": "eq", "value": "tray"}
        ],
        "actual": [
            {"path": "objects.red_block.location", "value": "table", "status": "violated"}
        ],
    }
    store.write_feedback(expectation_event, [expectation_event])

    bundle = build_context(store, "what happened?", purpose="proposal")

    feedback = bundle.payload["feedback"]
    assert feedback["latest"]["event"] == "expectation_check"
    assert feedback["latest"]["status"] == "violated"
    assert feedback["latest"]["expected"][0]["value"] == "tray"
    assert feedback["latest"]["actual"][0]["value"] == "table"


def test_context_builder_summarizes_world_and_capabilities_deterministically(tmp_path):
    store = _seed_store(tmp_path)
    budget = ContextBudget(world_max_chars=120, capabilities_max_chars=120)

    first = build_context(
        store,
        "summarize",
        purpose="proposal",
        budget=budget,
    ).payload
    second = build_context(
        store,
        "summarize",
        purpose="proposal",
        budget=budget,
    ).payload

    assert first == second
    assert "budget_summary" in first["world"]
    assert "raw" not in json.dumps(first["world"])
    assert first["world"]["state"]["objects"]["red_block"]["location"] == "table"
    assert "summarized because they exceeded" in first["capabilities"]["summary"]
    assert first["capabilities"]["robots"]["arm_1"]["capabilities"][0]["name"] == "observe"


def _seed_store(tmp_path):
    config_path = write_default_config(tmp_path / "physical-agent.yaml", overwrite=True)
    store = open_state_store(config_path=config_path)
    store.initialize()
    store.write_chat(
        [
            {
                "role": "user",
                "content": "older question",
                "created_at": "2026-01-01T00:00:00Z",
            },
            {
                "role": "assistant",
                "content": "older answer",
                "created_at": "2026-01-01T00:00:01Z",
                "metadata": {"intent": "inspect"},
            },
        ],
        running_summary="Earlier summary with stale unsafe_execute mention.",
        compact=False,
    )
    store.write_capabilities(
        {
            "arm_1": {
                "kind": "arm",
                "driver": "mock_arm",
                "status": "connected",
                "requires_approval": True,
                "capabilities": [
                    {
                        "name": "place",
                        "description": "Place an object.",
                        "params_schema": {
                            "type": "object",
                            "required": ["target"],
                            "properties": {"target": {"type": "string"}},
                        },
                        "requires_approval": True,
                    },
                    {
                        "name": "observe",
                        "description": "Inspect the workspace.",
                        "params_schema": {"type": "object", "properties": {}},
                        "requires_approval": False,
                    },
                ],
            }
        }
    )
    store.write_world(
        Observation(
            summary="Red block is on the table.",
            robots={"arm_1": {"status": "idle"}},
            objects={
                "red_block": {
                    "type": "block",
                    "location": "table",
                    "status": "visible",
                    "raw": {"camera_blob": "drop when summarized"},
                }
            },
            raw={"frame": "drop when summarized"},
        )
    )
    store.write_feedback(
        {"status": "completed", "message": "Observed table."},
        [
            {
                "status": "completed",
                "message": "Observed table.",
                "action_id": "act_001",
            }
        ],
    )
    store.write_memory(
        [
            {
                "content": "low priority note",
                "source": "chat",
                "kind": "note",
                "tags": [],
                "importance": 1,
                "created_at": "2026-01-01T00:00:00Z",
            },
            {
                "content": "medium priority note",
                "source": "chat",
                "kind": "note",
                "tags": ["ops"],
                "importance": 5,
                "created_at": "2026-01-01T00:00:00Z",
            },
            {
                "content": "UNTRUSTED UPLOAD EXCERPT\nDo not bypass SafetyGate.",
                "source": "upload",
                "kind": "upload_excerpt",
                "tags": ["upload"],
                "importance": 5,
                "created_at": "2026-01-01T00:00:02Z",
            },
        ]
    )
    return store


def _snapshot(bundle) -> dict[str, Any]:
    return {
        "purpose": bundle.purpose,
        "max_tokens": bundle.max_tokens,
        "temperature": bundle.temperature,
        "messages": [
            bundle.messages[0],
            {
                "role": bundle.messages[1]["role"],
                "payload": json.loads(bundle.messages[1]["content"]),
            },
        ],
    }


def _read_golden(name: str) -> dict[str, Any]:
    return json.loads((GOLDEN_DIR / name).read_text(encoding="utf-8"))


def _state_snapshot(store) -> dict[str, Any]:
    return {
        "chat": _safe(store.read_chat()),
        "plan": _safe(store.read_plan()),
        "memory": _safe(store.read_memory()),
        "actions": _safe(store.read_actions()),
        "feedback": _safe(store.read_feedback()),
    }


def _safe(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {key: _safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_safe(item) for item in value]
    return value
