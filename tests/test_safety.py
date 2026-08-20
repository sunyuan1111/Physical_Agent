from physical_agent.protocol.schemas import Action, Capability, RobotRuntimeProfile
from physical_agent.watch.safety import SafetyGate


def _gate(**kwargs):
    capabilities = [
        Capability(
            name="move_to",
            description="move",
            params_schema={
                "type": "object",
                "required": ["x"],
                "properties": {"x": {"type": "number"}},
                "additionalProperties": False,
            },
            constraints={"bounds": {"x": [-1.0, 1.0]}},
        )
    ]
    robots = {
        "arm_1": RobotRuntimeProfile(
            robot_id="arm_1",
            kind="arm",
            driver="mock_arm",
            status="connected",
            capabilities=capabilities,
        )
    }
    return SafetyGate(robots=robots, safety_rules={}, **kwargs)


def _approval_gate():
    capabilities = [
        Capability(
            name="move_to",
            description="move",
            params_schema={
                "type": "object",
                "required": ["x"],
                "properties": {"x": {"type": "number"}},
                "additionalProperties": False,
            },
            constraints={"bounds": {"x": [-1.0, 1.0]}},
            requires_approval=True,
        )
    ]
    robots = {
        "arm_1": RobotRuntimeProfile(
            robot_id="arm_1",
            kind="arm",
            driver="mock_arm",
            status="connected",
            capabilities=capabilities,
        )
    }
    return SafetyGate(robots=robots, safety_rules={})


def test_unknown_robot_rejected():
    decision = _gate().validate(Action(id="a", robot="missing", capability="move_to", params={"x": 0}))
    assert not decision.ok
    assert "Unknown robot" in decision.message


def test_unknown_capability_rejected():
    decision = _gate().validate(Action(id="a", robot="arm_1", capability="fly", params={}))
    assert not decision.ok
    assert "does not expose" in decision.message


def test_invalid_params_rejected():
    decision = _gate().validate(Action(id="a", robot="arm_1", capability="move_to", params={}))
    assert not decision.ok
    assert "Invalid params" in decision.message


def test_out_of_bounds_rejected():
    decision = _gate().validate(Action(id="a", robot="arm_1", capability="move_to", params={"x": 2.0}))
    assert not decision.ok
    assert "outside allowed bounds" in decision.message


def test_duplicate_action_id_rejected():
    decision = _gate(executed_action_ids={"a"}).validate(
        Action(id="a", robot="arm_1", capability="move_to", params={"x": 0})
    )
    assert not decision.ok
    assert "Duplicate" in decision.message


def test_unmet_depends_on_rejected():
    decision = _gate(completed_action_ids=set()).validate(
        Action(id="a", robot="arm_1", capability="move_to", params={"x": 0}, depends_on=["b"])
    )
    assert not decision.ok
    assert "unmet dependency" in decision.message


def test_requires_approval_rejected_until_action_metadata_is_approved():
    gate = _approval_gate()

    missing = gate.validate(
        Action(id="a", robot="arm_1", capability="move_to", params={"x": 0})
    )
    approved = gate.validate(
        Action(
            id="b",
            robot="arm_1",
            capability="move_to",
            params={"x": 0},
            metadata={"approval": {"required": False, "status": "approved"}},
        )
    )

    assert not missing.ok
    assert "requires approved human approval" in missing.message
    assert approved.ok


def test_approval_does_not_bypass_schema_or_bounds():
    gate = _approval_gate()

    decision = gate.validate(
        Action(
            id="a",
            robot="arm_1",
            capability="move_to",
            params={"x": 2.0},
            metadata={"approval": {"required": True, "status": "approved"}},
        )
    )

    assert not decision.ok
    assert "outside allowed bounds" in decision.message

