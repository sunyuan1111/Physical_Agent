from physical_agent.config import write_default_config
from physical_agent.mcp.server import PhysicalAgentMCP
from physical_agent.state import open_state_store


def test_mcp_propose_action_sqlite_only_writes_pending_board(tmp_path):
    config_path = write_default_config(tmp_path / "physical-agent.yaml", overwrite=True)
    store = open_state_store(config_path=config_path)
    store.initialize()
    mcp = PhysicalAgentMCP(config_path)

    result = mcp.propose_action(
        {
            "id": "act_mcp_sqlite",
            "robot": "arm_1",
            "capability": "observe",
            "params": {},
            "reason": "Tool caller wants observation.",
            "metadata": {
                "expected": {
                    "path": "robots.arm_1.status",
                    "op": "eq",
                    "value": "idle",
                }
            },
        }
    )

    assert result["ok"] is True
    assert result["action_id"] == "act_mcp_sqlite"
    actions = store.read_actions()
    assert [action.id for action in actions["pending"]] == ["act_mcp_sqlite"]
    assert actions["pending"][0].metadata["expected"][0]["path"] == "robots.arm_1.status"
    assert actions["completed"] == []
    assert actions["cancelled"] == []


def test_mcp_tool_specs_describe_proposal_only_tools(tmp_path):
    config_path = write_default_config(tmp_path / "physical-agent.yaml", overwrite=True)
    specs = PhysicalAgentMCP(config_path).tool_specs()

    names = {spec["name"] for spec in specs}
    assert "physical_agent_submit_task" in names
    assert "physical_agent_propose_action" in names
    assert "physical_agent_get_state" in names
    assert all("Does not execute hardware" in spec["description"] for spec in specs)
    assert all(spec["strict"] is True for spec in specs)
    propose_spec = next(spec for spec in specs if spec["name"] == "physical_agent_propose_action")
    metadata_schema = propose_spec["parameters"]["properties"]["metadata"]
    assert "expected" in metadata_schema["properties"]
