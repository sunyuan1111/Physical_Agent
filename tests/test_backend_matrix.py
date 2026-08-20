from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sqlite3

import pytest
import yaml
from typer.testing import CliRunner

import physical_agent.cli as cli_module
from physical_agent.agent.chat_runtime import ChatRuntime
from physical_agent.config import RETIRED_MARKDOWN_BACKEND_GUIDANCE, load_config, write_default_config
from physical_agent.mcp.server import PhysicalAgentMCP
from physical_agent.protocol.schemas import Action, Observation
from physical_agent.protocol.workspace import Workspace
from physical_agent.state import SqliteStateStore, open_state_store
from physical_agent.watch.runtime import WatchRuntime


BACKENDS = ("sqlite",)


class _NoSkills:
    def match(self, message):
        return None

    def list_skills(self):
        return []


def _config_for_backend(tmp_path: Path, backend: str) -> Path:
    config_path = write_default_config(tmp_path / "physical-agent.yaml", overwrite=True)
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    data["workspace"]["backend"] = backend
    config_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return config_path


def _ids(actions: list[Action]) -> list[str]:
    return [action.id for action in actions]


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_default_init_setup_and_state_check_use_sqlite_with_safety_file(tmp_path):
    runner = CliRunner()
    for command in ("init", "setup"):
        project_dir = tmp_path / command
        project_dir.mkdir()
        config_path = project_dir / "physical-agent.yaml"

        result = runner.invoke(cli_module.app, [command, "--config", str(config_path)])

        assert result.exit_code == 0, result.output
        data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        assert data["workspace"]["backend"] == "sqlite"
        store = open_state_store(config_path=config_path)
        assert isinstance(store, SqliteStateStore)
        assert store.exists()
        assert store.db_path.exists()
        assert store.file("safety").exists()

        check = runner.invoke(
            cli_module.app,
            ["state-check", "--config", str(config_path)],
        )

        assert check.exit_code == 0, check.output
        assert "Backend: sqlite" in check.output
        assert "Backend role: recommended" in check.output
        assert "Source of truth:" in check.output
        assert "Workspace initialized: yes" in check.output
        assert "SQLite schema complete: yes" in check.output
        assert "Audit export writable: yes" in check.output


def test_load_config_rejects_legacy_markdown_workspace_when_backend_omitted(tmp_path):
    config_path = write_default_config(tmp_path / "physical-agent.yaml", overwrite=True)
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    del data["workspace"]["backend"]
    config_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    Workspace(tmp_path / "workspace").initialize()

    with pytest.raises(ValueError) as exc_info:
        load_config(config_path)
    message = str(exc_info.value)
    assert "migrate-md-to-sqlite" in message
    assert "workspace.backend: sqlite" in message
    assert message == RETIRED_MARKDOWN_BACKEND_GUIDANCE

    with pytest.raises(ValueError, match="migrate-md-to-sqlite"):
        open_state_store(config_path=config_path)


def test_load_config_keeps_sqlite_default_without_legacy_markdown_workspace(tmp_path):
    config_path = write_default_config(tmp_path / "physical-agent.yaml", overwrite=True)
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    del data["workspace"]["backend"]
    config_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    config = load_config(config_path)
    store = open_state_store(config_path=config_path)

    assert config.workspace.backend == "sqlite"
    assert isinstance(store, SqliteStateStore)


@pytest.mark.parametrize("backend", BACKENDS)
def test_backend_matrix_init_append_and_audit_export(tmp_path, backend):
    config_path = _config_for_backend(tmp_path, backend)
    store = open_state_store(config_path=config_path)

    store.initialize()
    assert store.exists()

    appended = store.append_pending_action(
        Action(id=f"act_append_{backend}", robot="arm_1", capability="observe")
    )
    assert appended.id == f"act_append_{backend}"
    assert _ids(store.read_actions()["pending"]) == [f"act_append_{backend}"]

    result = store.export_human_view()
    audit_dir = Path(result["out_dir"])

    assert result["backend"] == backend
    assert _read_json(audit_dir / "manifest.json")["backend"] == backend
    assert _read_json(audit_dir / "actions.json")["pending"][0]["id"] == appended.id
    assert (audit_dir / "SAFETY.md").exists()


@pytest.mark.parametrize("backend", BACKENDS)
def test_backend_matrix_mcp_propose_action_only_writes_pending(tmp_path, backend):
    config_path = _config_for_backend(tmp_path, backend)
    store = open_state_store(config_path=config_path)
    store.initialize()

    result = PhysicalAgentMCP(config_path).propose_action(
        {
            "id": f"act_mcp_{backend}",
            "robot": "arm_1",
            "capability": "observe",
            "params": {},
            "reason": "Matrix proposal.",
            "depends_on": [],
        }
    )

    assert result["ok"] is True
    assert result["action_id"] == f"act_mcp_{backend}"
    actions = store.read_actions()
    assert _ids(actions["pending"]) == [f"act_mcp_{backend}"]
    assert actions["completed"] == []
    assert actions["cancelled"] == []


@pytest.mark.parametrize("backend", BACKENDS)
def test_backend_matrix_chat_runtime_drafts_actions_only(tmp_path, monkeypatch, backend):
    config_path = _config_for_backend(tmp_path, backend)
    watch = WatchRuntime(config_path)
    asyncio.run(watch.setup())
    asyncio.run(watch.shutdown())

    monkeypatch.setattr(ChatRuntime, "_skill_router", lambda self: _NoSkills())

    result = ChatRuntime(config_path, planner_name="rule_based").respond("look around")
    store = open_state_store(config_path=config_path)
    actions = store.read_actions()

    assert result["ok"] is True
    assert result["executed"] == 0
    assert result["actions"] == []
    assert [action["capability"] for action in result["draft_actions"]] == ["observe"]
    assert _ids(actions["pending"]) == []
    assert actions["completed"] == []
    assert actions["cancelled"] == []
    assert store.read_plan()["plan"].needs_watch is False


@pytest.mark.parametrize("backend", BACKENDS)
def test_backend_matrix_watch_success_rejection_and_driver_exception(
    tmp_path,
    monkeypatch,
    backend,
):
    config_path = _config_for_backend(tmp_path, backend)
    runtime = WatchRuntime(config_path)
    asyncio.run(runtime.setup())
    store = open_state_store(config_path=config_path)
    store.write_actions(
        [
            Action(id="act_success", robot="arm_1", capability="observe"),
            Action(id="act_reject", robot="arm_1", capability="unsafe_capability"),
            Action(id="act_exception", robot="arm_1", capability="observe"),
        ],
        [],
        [],
    )

    executed_ids: list[str] = []
    original_execute = runtime.loaded_drivers["arm_1"].driver.execute

    async def execute_or_fail(action):
        executed_ids.append(action.id)
        if action.id == "act_exception":
            raise RuntimeError("matrix boom")
        return await original_execute(action)

    monkeypatch.setattr(runtime.loaded_drivers["arm_1"].driver, "execute", execute_or_fail)

    try:
        count = asyncio.run(runtime.step(setup=False))
    finally:
        asyncio.run(runtime.shutdown())

    actions = store.read_actions()
    feedback = store.read_feedback()

    assert count == 2
    assert executed_ids == ["act_success", "act_exception"]
    assert actions["pending"] == []
    assert _ids(actions["completed"]) == ["act_success"]
    assert _ids(actions["cancelled"]) == ["act_reject", "act_exception"]
    assert feedback["latest"]["action_id"] == "act_exception"
    assert feedback["latest"]["status"] == "failed"
    assert "matrix boom" in feedback["latest"]["message"]
    by_id = {item["action_id"]: item for item in feedback["history"]}
    assert "does not expose capability" in by_id["act_reject"]["message"]
    assert by_id["act_success"]["status"] == "completed"


def test_markdown_to_sqlite_migration_preserves_readiness_state_and_audit(tmp_path):
    config_path = write_default_config(tmp_path / "physical-agent.yaml", overwrite=True)
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    data["workspace"]["backend"] = "markdown"
    config_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    workspace = Workspace(tmp_path / "workspace")
    workspace.initialize()
    workspace.write_task("Inspect readiness", ["preserve state"])
    workspace.write_capabilities(
        {
            "arm_1": {
                "kind": "arm",
                "driver": "mock_arm",
                "status": "connected",
                "capabilities": [{"name": "observe", "params_schema": {"type": "object"}}],
            }
        }
    )
    workspace.write_world(
        Observation(
            summary="readiness world",
            robots={"arm_1": {"status": "idle"}},
            objects={"red_block": {"location": "table"}},
        )
    )
    workspace.write_actions(
        [Action(id="act_pending", robot="arm_1", capability="observe")],
        [Action(id="act_completed", robot="arm_1", capability="pick")],
        [Action(id="act_cancelled", robot="arm_1", capability="place")],
    )
    workspace.write_feedback(
        {"action_id": "act_completed", "status": "completed"},
        [{"action_id": "act_completed", "status": "completed"}],
    )
    workspace.write_chat(
        [{"role": "user", "content": "hello readiness"}],
        running_summary="readiness summary",
        compact=False,
    )
    workspace.write_memory(
        [
            {
                "content": "readiness memory",
                "source": "test",
                "kind": "lesson",
                "tags": ["readiness"],
                "importance": 7,
            }
        ]
    )
    workspace.append_log("readiness log", actor="test")

    migrate_result = CliRunner().invoke(
        cli_module.app,
        ["migrate-md-to-sqlite", "--config", str(config_path)],
    )

    assert migrate_result.exit_code == 0, migrate_result.output
    assert "workspace.backend: sqlite" in migrate_result.output
    assert yaml.safe_load(config_path.read_text(encoding="utf-8"))["workspace"]["backend"] == "markdown"

    sqlite_store = SqliteStateStore(tmp_path / "workspace")
    assert sqlite_store.exists()
    assert sqlite_store.read_task()["task"] == "Inspect readiness"
    assert sqlite_store.read_capabilities()["robots"]["arm_1"]["driver"] == "mock_arm"
    assert sqlite_store.read_world()["state"]["objects"]["red_block"]["location"] == "table"
    assert _ids(sqlite_store.read_actions()["pending"]) == ["act_pending"]
    assert _ids(sqlite_store.read_actions()["completed"]) == ["act_completed"]
    assert _ids(sqlite_store.read_actions()["cancelled"]) == ["act_cancelled"]
    assert sqlite_store.read_feedback()["latest"]["action_id"] == "act_completed"
    assert sqlite_store.read_chat()["running_summary"] == "readiness summary"
    assert sqlite_store.read_chat()["messages"][0].content == "hello readiness"
    memory = sqlite_store.read_memory()["notes"][0]
    assert memory["content"] == "readiness memory"
    assert memory["kind"] == "lesson"
    assert memory["tags"] == ["readiness"]
    assert memory["importance"] == 7

    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    data["workspace"]["backend"] = "sqlite"
    config_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    audit_dir = tmp_path / "sqlite-audit"
    export_result = CliRunner().invoke(
        cli_module.app,
        ["export-audit", "--config", str(config_path), "--out", str(audit_dir)],
    )

    assert export_result.exit_code == 0, export_result.output
    assert _read_json(audit_dir / "task.json")["task"] == "Inspect readiness"
    assert _read_json(audit_dir / "world.json")["state"]["objects"]["red_block"]["location"] == "table"
    assert _read_json(audit_dir / "actions.json")["pending"][0]["id"] == "act_pending"
    assert _read_json(audit_dir / "feedback.json")["latest"]["action_id"] == "act_completed"
    assert _read_json(audit_dir / "chat.json")["running_summary"] == "readiness summary"
    audit_memory = _read_json(audit_dir / "memory.json")["notes"][0]
    assert audit_memory["content"] == "readiness memory"
    assert audit_memory["kind"] == "lesson"
    assert audit_memory["tags"] == ["readiness"]
    assert audit_memory["importance"] == 7
    assert _read_json(audit_dir / "log.json")["entries"][0]["message"] == "readiness log"


def test_markdown_to_sqlite_migration_reads_legacy_workspace_when_backend_omitted(
    tmp_path,
):
    config_path = write_default_config(tmp_path / "physical-agent.yaml", overwrite=True)
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    del data["workspace"]["backend"]
    config_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    workspace = Workspace(tmp_path / "workspace")
    workspace.initialize()
    workspace.write_task("Migrate omitted backend", ["legacy reader only"])
    workspace.write_actions([Action(id="act_omitted", robot="arm_1", capability="observe")])

    migrate_result = CliRunner().invoke(
        cli_module.app,
        ["migrate-md-to-sqlite", "--config", str(config_path)],
    )

    assert migrate_result.exit_code == 0, migrate_result.output
    assert "workspace.backend: sqlite" in migrate_result.output
    assert "backend" not in yaml.safe_load(config_path.read_text(encoding="utf-8"))[
        "workspace"
    ]
    sqlite_store = SqliteStateStore(tmp_path / "workspace")
    assert sqlite_store.read_task()["task"] == "Migrate omitted backend"
    assert _ids(sqlite_store.read_actions()["pending"]) == ["act_omitted"]


@pytest.mark.parametrize("backend", BACKENDS)
def test_backend_matrix_export_audit_cli_is_read_only(tmp_path, monkeypatch, backend):
    config_path = _config_for_backend(tmp_path, backend)
    store = open_state_store(config_path=config_path)
    store.initialize()
    store.write_actions([Action(id=f"act_audit_{backend}", robot="arm_1", capability="observe")])
    before_config = config_path.read_text(encoding="utf-8")
    before_actions = store.read_actions()

    class ExplodingWatchRuntime:
        def __init__(self, *args, **kwargs):
            raise AssertionError("export-audit must not instantiate WatchRuntime")

    monkeypatch.setattr(cli_module, "WatchRuntime", ExplodingWatchRuntime)

    result = CliRunner().invoke(
        cli_module.app,
        [
            "export-audit",
            "--config",
            str(config_path),
            "--out",
            str(tmp_path / f"audit-{backend}"),
        ],
    )

    after_actions = store.read_actions()
    assert result.exit_code == 0, result.output
    assert config_path.read_text(encoding="utf-8") == before_config
    assert _ids(after_actions["pending"]) == _ids(before_actions["pending"])
    assert _ids(after_actions["completed"]) == _ids(before_actions["completed"])
    assert _ids(after_actions["cancelled"]) == _ids(before_actions["cancelled"])
    assert yaml.safe_load(before_config)["workspace"]["backend"] == backend


@pytest.mark.parametrize("backend", BACKENDS)
def test_state_check_reports_backend_readiness_without_mutating_state(
    tmp_path,
    monkeypatch,
    backend,
):
    config_path = _config_for_backend(tmp_path, backend)
    store = open_state_store(config_path=config_path)
    store.initialize()
    store.write_actions([Action(id=f"act_check_{backend}", robot="arm_1", capability="observe")])
    before_config = config_path.read_text(encoding="utf-8")
    before_actions = store.read_actions()

    class ExplodingWatchRuntime:
        def __init__(self, *args, **kwargs):
            raise AssertionError("state-check must not instantiate WatchRuntime")

    monkeypatch.setattr(cli_module, "WatchRuntime", ExplodingWatchRuntime)

    result = CliRunner().invoke(
        cli_module.app,
        ["state-check", "--config", str(config_path)],
    )

    assert result.exit_code == 0, result.output
    assert f"Backend: {backend}" in result.output
    assert "Backend role: recommended" in result.output
    assert "Workspace initialized: yes" in result.output
    assert "Audit export writable: yes" in result.output
    assert "SQLite schema complete: yes" in result.output
    assert "workspace/state.db" in result.output.replace("\\", "/")
    assert "SAFETY.md remains the file source" in result.output
    assert config_path.read_text(encoding="utf-8") == before_config
    assert _ids(store.read_actions()["pending"]) == _ids(before_actions["pending"])


def test_state_check_reports_incomplete_legacy_sqlite_schema_without_migrating(tmp_path):
    config_path = _config_for_backend(tmp_path, "sqlite")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "SAFETY.md").write_text("rules:\n  allow_autonomous_execution: true\n", encoding="utf-8")
    db_path = workspace / "state.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE doc_state (name TEXT PRIMARY KEY, revision INTEGER, payload TEXT, updated_at TEXT)")
        conn.execute(
            """
            CREATE TABLE actions (
                id TEXT PRIMARY KEY,
                robot TEXT,
                capability TEXT,
                params TEXT,
                reason TEXT,
                depends_on TEXT,
                status TEXT,
                result TEXT,
                seq INTEGER,
                created_at TEXT,
                updated_at TEXT
            )
            """
        )
        conn.execute("CREATE TABLE log_entries (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, actor TEXT, message TEXT)")
        conn.execute("CREATE TABLE chat_messages (id INTEGER PRIMARY KEY AUTOINCREMENT, role TEXT, content TEXT, created_at TEXT, metadata TEXT)")
        conn.execute("CREATE TABLE memory_notes (id INTEGER PRIMARY KEY AUTOINCREMENT, content TEXT, source TEXT, created_at TEXT)")

    result = CliRunner().invoke(
        cli_module.app,
        ["state-check", "--config", str(config_path)],
    )

    assert result.exit_code == 1
    assert "Workspace initialized: yes" in result.output
    assert "SQLite schema complete: no" in result.output
    assert "claimed_at" in result.output
    assert "kind" in result.output
    assert "importance" in result.output
    with sqlite3.connect(db_path) as conn:
        action_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(actions)").fetchall()
        }
        memory_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(memory_notes)").fetchall()
        }
    assert "claimed_at" not in action_columns
    assert "kind" not in memory_columns
    assert "importance" not in memory_columns
