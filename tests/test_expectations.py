from __future__ import annotations

from physical_agent.protocol.expectations import (
    EXPECTED_MAX_CHECKS,
    evaluate_expected,
    normalize_expected_value,
)
from physical_agent.config import write_default_config
from physical_agent.protocol.schemas import Action, Observation
from physical_agent.state import open_state_store


def test_evaluate_expected_verifies_multiple_checks_with_path_aliases():
    world = Observation(
        summary="block placed",
        objects={
            "red_block": {"location": "tray", "pose": {"x": 0.1}},
            "tray": {"location": "table"},
        },
    )

    result = evaluate_expected(
        [
            {"path": "world.objects.red_block.location", "op": "eq", "value": "tray"},
            {"path": "objects.red_block.pose.x", "op": "range", "value": [0.0, 0.2]},
        ],
        world,
    )

    assert result["status"] == "verified"
    assert result["message"] == "All 2 expected check(s) verified."
    assert [check["status"] for check in result["checks"]] == ["verified", "verified"]


def test_evaluate_expected_aggregate_prefers_violated_over_skipped():
    world = {
        "state": {
            "objects": {
                "red_block": {"location": "table"},
            }
        }
    }

    result = evaluate_expected(
        [
            {"path": "objects.red_block.location", "op": "eq", "value": "tray"},
            {"path": "objects.missing.location", "op": "eq", "value": "tray"},
        ],
        world,
    )

    assert result["status"] == "violated"
    assert result["message"] == result["checks"][0]["message"]
    assert [check["status"] for check in result["checks"]] == ["violated", "skipped"]


def test_evaluate_expected_skips_bad_path_bad_op_and_bad_range():
    world = {"state": {"objects": {"red_block": {"location": "table"}}}}

    missing = evaluate_expected(
        [{"path": "objects.blue_block.location", "op": "eq", "value": "tray"}],
        world,
    )
    bad_op = evaluate_expected(
        [{"path": "objects.red_block.location", "op": "contains", "value": "tray"}],
        world,
    )
    bad_range = evaluate_expected(
        [{"path": "objects.red_block.location", "op": "range", "value": [0, 1]}],
        world,
    )

    assert missing["status"] == "skipped"
    assert "could not be resolved" in missing["message"]
    assert bad_op["status"] == "skipped"
    assert "unsupported op" in bad_op["message"]
    assert bad_range["status"] == "skipped"
    assert "numeric actual" in bad_range["message"]


def test_evaluate_expected_supports_selector_for_list_world_without_schema_change():
    world = {
        "state": {
            "objects": [
                {"id": "red_block", "location": "tray"},
                {"id": "tray", "location": "table"},
            ]
        }
    }

    result = evaluate_expected(
        [{"path": "objects[id=red_block].location", "op": "eq", "value": "tray"}],
        world,
    )

    assert result["status"] == "verified"
    assert result["checks"][0]["actual"] == "tray"


def test_normalize_expected_preserves_bad_shapes_as_skipped_checks_without_throwing():
    assert normalize_expected_value({"path": "objects.red_block.location", "op": "eq", "value": "tray"}) == [
        {"path": "objects.red_block.location", "op": "eq", "value": "tray"}
    ]

    invalid = normalize_expected_value("not a list")
    assert len(invalid) == 1
    assert "_invalid" in invalid[0]

    too_many = normalize_expected_value(
        [{"path": f"objects.obj_{index}.location", "op": "eq", "value": "tray"} for index in range(30)]
    )
    assert len(too_many) == EXPECTED_MAX_CHECKS
    assert "_invalid" in too_many[-1]


def test_sqlite_action_write_normalizes_expected_without_rejecting_bad_expected(tmp_path):
    config_path = write_default_config(tmp_path / "physical-agent.yaml", overwrite=True)
    store = open_state_store(config_path=config_path)
    store.initialize()

    store.append_pending_action(
        Action(
            id="act_expected_single_object",
            robot="arm_1",
            capability="observe",
            metadata={
                "expected": {
                    "path": "objects.red_block.location",
                    "op": "eq",
                    "value": "table",
                }
            },
        )
    )
    store.append_pending_action(
        Action(
            id="act_expected_bad_shape",
            robot="arm_1",
            capability="observe",
            metadata={"expected": "not a list"},
        )
    )

    pending = store.read_actions()["pending"]
    assert pending[0].metadata["expected"] == [
        {"path": "objects.red_block.location", "op": "eq", "value": "table"}
    ]
    assert "_invalid" in pending[1].metadata["expected"][0]
