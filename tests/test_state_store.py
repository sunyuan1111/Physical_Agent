import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3

import pytest
import yaml
from typer.testing import CliRunner

import physical_agent.agent.chat_runtime as chat_runtime_module
import physical_agent.agent.runtime as agent_runtime_module
import physical_agent.watch.runtime as watch_runtime_module
from physical_agent.agent.chat_runtime import ChatRuntime
from physical_agent.agent.runtime import AgentRuntime
from physical_agent.cli import app
from physical_agent.config import PhysicalAgentConfig, load_config, write_default_config
from physical_agent.protocol.schemas import Action, ChatPlan, Observation
from physical_agent.protocol.workspace import Workspace
from physical_agent.state.base import StateStore
from physical_agent.state.legacy_markdown import LegacyMarkdownWorkspaceReader
from physical_agent.state import SqliteStateStore, open_state_store
from physical_agent.state import factory as state_factory
from physical_agent.watch.runtime import WatchRuntime


def _read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


class _NoSkills:
    def match(self, message):
        return None

    def list_skills(self):
        return []


def _set_config_backend(config_path, backend: str) -> None:
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    data["workspace"]["backend"] = backend
    config_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def test_open_state_store_defaults_to_sqlite(tmp_path):
    config_path = write_default_config(tmp_path / "physical-agent.yaml", overwrite=True)

    store = open_state_store(config_path=config_path)

    assert yaml.safe_load(config_path.read_text(encoding="utf-8"))["workspace"]["backend"] == "sqlite"
    assert isinstance(store, SqliteStateStore)
    assert store.path == (tmp_path / "workspace").resolve()


def test_open_state_store_rejects_explicit_markdown_backend(tmp_path):
    config_path = write_default_config(tmp_path / "physical-agent.yaml", overwrite=True)
    _set_config_backend(config_path, "markdown")

    with pytest.raises(ValueError) as exc_info:
        load_config(config_path)
    message = str(exc_info.value)
    assert "migrate-md-to-sqlite" in message
    assert "workspace.backend: sqlite" in message

    config = PhysicalAgentConfig.model_validate(
        {"workspace": {"path": "./workspace", "backend": "markdown"}}
    )
    with pytest.raises(ValueError, match="migrate-md-to-sqlite"):
        open_state_store(config, base_dir=tmp_path)


def test_open_state_store_rejects_unsupported_backend(tmp_path):
    config = PhysicalAgentConfig.model_validate(
        {"workspace": {"path": "./workspace", "backend": "unknown"}}
    )

    with pytest.raises(ValueError, match="Supported backend: sqlite"):
        open_state_store(config, base_dir=tmp_path)


def test_open_state_store_sqlite_backend(tmp_path):
    config = PhysicalAgentConfig.model_validate(
        {"workspace": {"path": "./workspace", "backend": "sqlite"}}
    )

    store = open_state_store(config, base_dir=tmp_path)

    assert isinstance(store, SqliteStateStore)
    assert store.path == (tmp_path / "workspace").resolve()


def test_legacy_markdown_reader_is_migration_only_not_state_store(tmp_path):
    reader = LegacyMarkdownWorkspaceReader(tmp_path / "workspace")

    assert not isinstance(reader, StateStore)
    for runtime_method in (
        "initialize",
        "append_pending_action",
        "claim_next_ready_action",
        "mark_action_completed",
        "mark_action_cancelled",
        "append_log",
        "export_human_view",
    ):
        assert not hasattr(reader, runtime_method)


def test_sqlite_state_store_protocol_roundtrip(tmp_path):
    store = SqliteStateStore(tmp_path / "workspace")
    store.initialize()

    assert store.exists()
    assert store.db_path.exists()
    assert store.file("safety").exists()

    store.write_task("Move the block", ["simulation first"], owner="human", status="active")
    assert store.read_task()["task"] == "Move the block"
    assert store.read_task()["constraints"] == ["simulation first"]

    store.write_capabilities(
        {
            "arm_1": {
                "kind": "mock",
                "driver": "mock_arm",
                "capabilities": [{"name": "observe", "params_schema": {"type": "object"}}],
            }
        }
    )
    assert store.read_capabilities()["robots"]["arm_1"]["driver"] == "mock_arm"

    store.write_world(
        Observation(
            summary="red block is on the table",
            objects={"red_block": {"location": "table"}},
        )
    )
    assert store.read_world()["state"]["objects"]["red_block"]["location"] == "table"

    pending = Action(id="act_001", robot="arm_1", capability="observe")
    completed = Action(id="act_002", robot="arm_1", capability="pick")
    cancelled = Action(id="act_003", robot="arm_1", capability="place")
    store.write_actions([pending], [completed], [cancelled])
    actions = store.read_actions()
    assert [action.id for action in actions["pending"]] == ["act_001"]
    assert [action.id for action in actions["completed"]] == ["act_002"]
    assert [action.id for action in actions["cancelled"]] == ["act_003"]

    store.write_feedback({"status": "completed"}, [{"action_id": "act_002"}])
    assert store.read_feedback()["latest"]["status"] == "completed"

    store.write_safety({"allow_autonomous_execution": False})
    assert store.read_safety()["rules"]["allow_autonomous_execution"] is False

    store.write_chat(
        [{"role": "user", "content": "older"}],
        running_summary="summary",
        compact=False,
    )
    message = store.append_chat_message("assistant", "new reply")
    assert message.content == "new reply"
    chat = store.read_chat()
    assert chat["running_summary"] == "summary"
    assert [item.content for item in chat["messages"]] == ["older", "new reply"]

    store.write_plan(ChatPlan(status="answered", intent="chat", summary="done"))
    assert store.read_plan()["plan"].summary == "done"

    store.write_memory(
        [
            {
                "content": "prefers simulation",
                "source": "test",
                "kind": "preference",
                "tags": ["safety", "planning"],
                "importance": 3,
            }
        ]
    )
    note = store.append_memory_note(
        "likes short plans",
        source="chat",
        kind="preference",
        tags=["planning"],
        importance=2,
    )
    assert note["created_at"]
    assert [item["content"] for item in store.read_memory()["notes"]] == [
        "prefers simulation",
        "likes short plans",
    ]
    assert store.read_memory()["notes"][0]["kind"] == "preference"
    assert store.read_memory()["notes"][0]["tags"] == ["safety", "planning"]
    assert store.read_memory()["notes"][0]["importance"] == 3
    assert [item["content"] for item in store.read_memory(tags=["planning"])["notes"]] == [
        "prefers simulation",
        "likes short plans",
    ]
    assert [item["content"] for item in store.read_memory(source="chat", limit=1)["notes"]] == [
        "likes short plans"
    ]

    store.append_log("hello", actor="test")
    with sqlite3.connect(store.db_path) as conn:
        count = conn.execute("SELECT count(*) FROM log_entries").fetchone()[0]
    assert count == 1


def test_sqlite_append_pending_action_writes_pending(tmp_path):
    store = SqliteStateStore(tmp_path / "workspace")
    store.initialize()

    action = store.append_pending_action(
        Action(id="act_append", robot="arm_1", capability="observe")
    )

    assert action.id == "act_append"
    assert [item.id for item in store.read_actions()["pending"]] == ["act_append"]
    with sqlite3.connect(store.db_path) as conn:
        row = conn.execute(
            "SELECT status FROM actions WHERE id = ?",
            ("act_append",),
        ).fetchone()
    assert row == ("pending",)


def test_sqlite_initialize_migrates_old_action_claim_schema(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    db_path = workspace / "state.db"
    with sqlite3.connect(db_path) as conn:
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
        conn.execute(
            """
            INSERT INTO actions(
                id, robot, capability, params, reason, depends_on,
                status, result, seq, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "act_legacy",
                "arm_1",
                "observe",
                "{}",
                None,
                "[]",
                "pending",
                "{}",
                1,
                "2026-01-01T00:00:00Z",
                "2026-01-01T00:00:00Z",
            ),
        )

    store = SqliteStateStore(workspace)
    store.initialize()

    assert store.exists()
    with sqlite3.connect(store.db_path) as conn:
        columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(actions)").fetchall()
        }
    assert {"claimed_at", "claim_owner", "attempts"}.issubset(columns)

    claimed = store.claim_next_ready_action(claim_owner="test-watch")
    assert claimed is not None
    assert claimed.id == "act_legacy"
    with sqlite3.connect(store.db_path) as conn:
        row = conn.execute(
            """
            SELECT status, claimed_at, claim_owner, attempts
            FROM actions
            WHERE id = ?
            """,
            ("act_legacy",),
        ).fetchone()
    assert row[0] == "in_progress"
    assert row[1]
    assert row[2] == "test-watch"
    assert row[3] == 1


def test_sqlite_initialize_migrates_old_memory_schema(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    db_path = workspace / "state.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE memory_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT,
                source TEXT,
                created_at TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO memory_notes(content, source, created_at)
            VALUES (?, ?, ?)
            """,
            ("legacy memory", "chat", "2026-01-01T00:00:00Z"),
        )

    store = SqliteStateStore(workspace)
    store.initialize()

    with sqlite3.connect(store.db_path) as conn:
        columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(memory_notes)").fetchall()
        }
        row = conn.execute(
            """
            SELECT content, kind, source, tags, importance, created_at
            FROM memory_notes
            """
        ).fetchone()
    assert {"kind", "tags", "importance"}.issubset(columns)
    assert row == (
        "legacy memory",
        "note",
        "chat",
        "[]",
        0,
        "2026-01-01T00:00:00Z",
    )
    assert store.read_memory()["notes"][0] == {
        "content": "legacy memory",
        "kind": "note",
        "source": "chat",
        "tags": [],
        "importance": 0,
        "created_at": "2026-01-01T00:00:00Z",
    }


def test_sqlite_claim_next_ready_action_is_not_duplicated(tmp_path):
    store = SqliteStateStore(tmp_path / "workspace")
    store.initialize()
    store.append_pending_action(Action(id="act_once", robot="arm_1", capability="observe"))

    def claim_once():
        return SqliteStateStore(store.path).claim_next_ready_action()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: claim_once(), range(2)))

    claimed = [action for action in results if action is not None]
    assert [action.id for action in claimed] == ["act_once"]
    assert sum(action is None for action in results) == 1
    actions = store.read_actions()
    assert actions["pending"] == []
    assert actions["completed"] == []
    assert actions["cancelled"] == []
    with sqlite3.connect(store.db_path) as conn:
        row = conn.execute(
            """
            SELECT status, claimed_at, claim_owner, attempts
            FROM actions
            WHERE id = ?
            """,
            ("act_once",),
        ).fetchone()
    assert row[0] == "in_progress"
    assert row[1]
    assert row[2] == "watch"
    assert row[3] == 1

    store.mark_action_completed(claimed[0])
    assert [action.id for action in store.read_actions()["completed"]] == ["act_once"]


def test_sqlite_claim_skips_unapproved_required_action_without_blocking_later_ready(
    tmp_path,
):
    store = SqliteStateStore(tmp_path / "workspace")
    store.initialize()
    store.write_capabilities(
        {
            "arm_1": {
                "kind": "arm",
                "driver": "mock_arm",
                "capabilities": [
                    {
                        "name": "precise_move",
                        "description": "Move with human approval.",
                        "params_schema": {"type": "object"},
                        "requires_approval": True,
                    },
                    {
                        "name": "observe",
                        "description": "Observe.",
                        "params_schema": {"type": "object"},
                    },
                ],
            }
        }
    )
    store.append_pending_action(
        Action(
            id="act_needs_approval",
            robot="arm_1",
            capability="precise_move",
            metadata={"approval": {"required": False}},
        )
    )
    store.append_pending_action(Action(id="act_ready", robot="arm_1", capability="observe"))

    pending = store.read_actions()["pending"]
    assert pending[0].metadata["approval"]["required"] is True
    assert pending[0].metadata["approval"]["status"] == "pending"
    assert pending[1].metadata["approval"]["required"] is False

    claimed = store.claim_next_ready_action(claim_owner="test-watch")

    assert claimed is not None
    assert claimed.id == "act_ready"
    assert [action.id for action in store.read_actions()["pending"]] == [
        "act_needs_approval"
    ]
    with sqlite3.connect(store.db_path) as conn:
        rows = {
            row[0]: row[1]
            for row in conn.execute(
                "SELECT id, status FROM actions ORDER BY seq"
            ).fetchall()
        }
    assert rows == {"act_needs_approval": "pending", "act_ready": "in_progress"}


def test_sqlite_approve_required_action_allows_claim_and_is_idempotent(tmp_path):
    store = SqliteStateStore(tmp_path / "workspace")
    store.initialize()
    store.write_capabilities(
        {
            "arm_1": {
                "kind": "arm",
                "driver": "mock_arm",
                "capabilities": [
                    {
                        "name": "precise_move",
                        "description": "Move with human approval.",
                        "params_schema": {"type": "object"},
                        "requires_approval": True,
                    }
                ],
            }
        }
    )
    store.append_pending_action(
        Action(id="act_approval", robot="arm_1", capability="precise_move")
    )

    assert store.claim_next_ready_action(claim_owner="test-watch") is None
    approved, changed = store.approve_action(
        "act_approval",
        actor="test_user",
        reason="Looks intentional.",
    )
    again, changed_again = store.approve_action("act_approval", actor="test_user")

    assert changed is True
    assert changed_again is False
    assert approved.metadata["approval"]["status"] == "approved"
    assert approved.metadata["approval"]["by"] == "test_user"
    assert again.metadata["approval"]["status"] == "approved"
    claimed = store.claim_next_ready_action(claim_owner="test-watch")
    assert claimed is not None
    assert claimed.id == "act_approval"
    assert claimed.metadata["approval"]["status"] == "approved"


def test_sqlite_recover_stale_actions_releases_only_expired_claims(tmp_path):
    store = SqliteStateStore(tmp_path / "workspace")
    store.initialize()
    store.append_pending_action(Action(id="act_stale", robot="arm_1", capability="observe"))
    store.append_pending_action(Action(id="act_fresh", robot="arm_1", capability="observe"))

    stale = store.claim_next_ready_action(claim_owner="watch-a")
    fresh = store.claim_next_ready_action(claim_owner="watch-a")
    assert stale is not None
    assert fresh is not None
    with sqlite3.connect(store.db_path) as conn:
        conn.execute(
            "UPDATE actions SET claimed_at = ? WHERE id = ?",
            ("2000-01-01T00:00:00Z", stale.id),
        )

    recovered = store.recover_stale_actions(max_age_s=60)

    assert recovered == 1
    assert [action.id for action in store.read_actions()["pending"]] == [stale.id]
    reclaimed = store.claim_next_ready_action(claim_owner="watch-b")
    assert reclaimed is not None
    assert reclaimed.id == stale.id
    assert store.claim_next_ready_action(claim_owner="watch-b") is None
    with sqlite3.connect(store.db_path) as conn:
        rows = {
            row[0]: (row[1], row[2], row[3])
            for row in conn.execute(
                "SELECT id, status, claim_owner, attempts FROM actions ORDER BY id"
            ).fetchall()
        }
    assert rows["act_stale"] == ("in_progress", "watch-b", 2)
    assert rows["act_fresh"] == ("in_progress", "watch-a", 1)


def test_sqlite_recover_stale_actions_leaves_fresh_claims_in_progress(tmp_path):
    store = SqliteStateStore(tmp_path / "workspace")
    store.initialize()
    store.append_pending_action(Action(id="act_fresh", robot="arm_1", capability="observe"))
    claimed = store.claim_next_ready_action()

    assert claimed is not None
    assert store.recover_stale_actions(max_age_s=60) == 0
    assert store.read_actions()["pending"] == []
    assert store.claim_next_ready_action() is None


def test_sqlite_state_store_chat_rolling_summary(tmp_path):
    store = SqliteStateStore(tmp_path / "workspace")
    store.initialize()

    for index in range(25):
        store.append_chat_message("user", f"message {index}")

    chat = store.read_chat()
    assert len(chat["messages"]) == 12
    assert [message.content for message in chat["messages"]] == [
        f"message {index}" for index in range(13, 25)
    ]
    assert "message 0" in chat["running_summary"]
    assert "message 12" in chat["running_summary"]


def test_sqlite_state_store_export_human_view_reads_sqlite_state(tmp_path):
    store = SqliteStateStore(tmp_path / "workspace")
    store.initialize()
    store.write_task("Export the sqlite state", ["read from state.db"])
    store.write_actions([Action(id="act_db", robot="arm_1", capability="observe")])
    store.write_chat(
        [{"role": "user", "content": "db chat"}],
        running_summary="sqlite summary",
        compact=False,
    )
    store.write_memory(
        [
            {
                "content": "db memory",
                "source": "test",
                "kind": "lesson",
                "tags": ["audit", "sqlite"],
                "importance": 5,
            }
        ]
    )
    store.append_log("db log", actor="test")
    store.file("actions").write_text("tampered markdown action board", encoding="utf-8")
    store.file("log").write_text("tampered markdown log", encoding="utf-8")

    result = store.export_human_view()
    audit_dir = store.path / "audit"

    assert result["backend"] == "sqlite"
    assert _read_json(audit_dir / "task.json")["task"] == "Export the sqlite state"
    assert _read_json(audit_dir / "actions.json")["pending"][0]["id"] == "act_db"
    assert _read_json(audit_dir / "chat.json")["running_summary"] == "sqlite summary"
    memory = _read_json(audit_dir / "memory.json")["notes"][0]
    assert memory["content"] == "db memory"
    assert memory["kind"] == "lesson"
    assert memory["tags"] == ["audit", "sqlite"]
    assert memory["importance"] == 5
    log_entries = _read_json(audit_dir / "log.json")["entries"]
    assert log_entries[0]["message"] == "db log"
    assert "tampered markdown log" not in (audit_dir / "log.json").read_text(encoding="utf-8")


def test_migrate_markdown_to_sqlite_cli_does_not_switch_backend(tmp_path):
    config_path = write_default_config(tmp_path / "physical-agent.yaml", overwrite=True)
    _set_config_backend(config_path, "markdown")
    workspace = Workspace(tmp_path / "workspace")
    workspace.initialize()
    workspace.write_task("Inspect the table", ["do not execute directly"])
    workspace.write_actions(
        [Action(id="act_001", robot="arm_1", capability="observe")],
        [Action(id="act_002", robot="arm_1", capability="pick")],
        [Action(id="act_003", robot="arm_1", capability="place")],
    )
    workspace.write_chat(
        [{"role": "user", "content": "hello"}],
        running_summary="older context",
        compact=False,
    )
    workspace.append_memory_note("remember this", source="test")
    workspace.append_log("migrated log", actor="test")

    result = CliRunner().invoke(
        app,
        ["migrate-md-to-sqlite", "--config", str(config_path)],
    )

    assert result.exit_code == 0, result.output
    assert "Config was not changed" in result.output
    assert "workspace.backend: sqlite" in result.output
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert data["workspace"]["backend"] == "markdown"

    store = SqliteStateStore(tmp_path / "workspace")
    assert store.exists()
    assert store.read_task()["task"] == "Inspect the table"
    assert [action.id for action in store.read_actions()["pending"]] == ["act_001"]
    assert [action.id for action in store.read_actions()["completed"]] == ["act_002"]
    assert [action.id for action in store.read_actions()["cancelled"]] == ["act_003"]
    assert store.read_chat()["running_summary"] == "older context"
    migrated_memory = store.read_memory()["notes"][0]
    assert migrated_memory["content"] == "remember this"
    assert migrated_memory["kind"] == "note"
    assert migrated_memory["tags"] == []
    assert migrated_memory["importance"] == 0

    with sqlite3.connect(store.db_path) as conn:
        log_count = conn.execute("SELECT count(*) FROM log_entries").fetchone()[0]
    assert log_count == 1


def test_migrated_sqlite_export_contains_action_board_chat_memory_and_log(tmp_path):
    config_path = write_default_config(tmp_path / "physical-agent.yaml", overwrite=True)
    _set_config_backend(config_path, "markdown")
    workspace = Workspace(tmp_path / "workspace")
    workspace.initialize()
    workspace.write_actions(
        [Action(id="act_pending", robot="arm_1", capability="observe")],
        [Action(id="act_completed", robot="arm_1", capability="pick")],
        [Action(id="act_cancelled", robot="arm_1", capability="place")],
    )
    workspace.write_chat(
        [{"role": "user", "content": "hello"}],
        running_summary="migrated summary",
        compact=False,
    )
    workspace.append_memory_note(
        "migrated memory",
        source="test",
        kind="lesson",
        tags=["migration"],
        importance=6,
    )
    workspace.append_log("migrated log", actor="test")

    migrate_result = CliRunner().invoke(
        app,
        ["migrate-md-to-sqlite", "--config", str(config_path)],
    )
    assert migrate_result.exit_code == 0, migrate_result.output

    config_data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config_data["workspace"]["backend"] = "sqlite"
    config_path.write_text(yaml.safe_dump(config_data, sort_keys=False), encoding="utf-8")

    audit_dir = tmp_path / "audit"
    export_result = CliRunner().invoke(
        app,
        ["export-audit", "--config", str(config_path), "--out", str(audit_dir)],
    )

    assert export_result.exit_code == 0, export_result.output
    actions = _read_json(audit_dir / "actions.json")
    assert [action["id"] for action in actions["pending"]] == ["act_pending"]
    assert [action["id"] for action in actions["completed"]] == ["act_completed"]
    assert [action["id"] for action in actions["cancelled"]] == ["act_cancelled"]
    assert _read_json(audit_dir / "chat.json")["running_summary"] == "migrated summary"
    memory = _read_json(audit_dir / "memory.json")["notes"][0]
    assert memory["content"] == "migrated memory"
    assert memory["kind"] == "lesson"
    assert memory["tags"] == ["migration"]
    assert memory["importance"] == 6
    assert _read_json(audit_dir / "log.json")["entries"][0]["message"] == "migrated log"


def test_export_audit_cli_does_not_change_backend_or_action_board(
    tmp_path,
    monkeypatch,
):
    config_path = write_default_config(tmp_path / "physical-agent.yaml", overwrite=True)
    store = open_state_store(config_path=config_path)
    store.initialize()
    store.write_actions([Action(id="act_cli", robot="arm_1", capability="observe")])
    before_config = config_path.read_text(encoding="utf-8")
    before_actions = store.read_actions()

    class ExplodingWatchRuntime:
        def __init__(self, *args, **kwargs):
            raise AssertionError("export-audit must not instantiate WatchRuntime")

    monkeypatch.setattr("physical_agent.cli.WatchRuntime", ExplodingWatchRuntime)

    result = CliRunner().invoke(
        app,
        [
            "export-audit",
            "--config",
            str(config_path),
            "--out",
            str(tmp_path / "audit"),
        ],
    )

    assert result.exit_code == 0, result.output
    assert config_path.read_text(encoding="utf-8") == before_config
    assert [action.id for action in store.read_actions()["pending"]] == [
        action.id for action in before_actions["pending"]
    ]
    assert [action.id for action in store.read_actions()["completed"]] == [
        action.id for action in before_actions["completed"]
    ]
    assert [action.id for action in store.read_actions()["cancelled"]] == [
        action.id for action in before_actions["cancelled"]
    ]
    assert yaml.safe_load(before_config)["workspace"]["backend"] == "sqlite"
    assert _read_json(tmp_path / "audit" / "actions.json")["pending"][0]["id"] == "act_cli"


def test_core_runtimes_use_state_store_factory(tmp_path, monkeypatch):
    config_path = write_default_config(tmp_path / "physical-agent.yaml", overwrite=True)
    calls = {"agent": 0, "chat": 0, "watch": 0}
    real_open = state_factory.open_state_store

    def spy(name):
        def _open_state_store(*args, **kwargs):
            calls[name] += 1
            return real_open(*args, **kwargs)

        return _open_state_store

    monkeypatch.setattr(agent_runtime_module, "open_state_store", spy("agent"))
    monkeypatch.setattr(chat_runtime_module, "open_state_store", spy("chat"))
    monkeypatch.setattr(watch_runtime_module, "open_state_store", spy("watch"))

    agent = AgentRuntime(config_path)
    asyncio.run(agent.setup())
    assert isinstance(agent.workspace, SqliteStateStore)

    chat = ChatRuntime(config_path, planner_name="rule_based")
    monkeypatch.setattr(chat, "_skill_router", lambda: _NoSkills())
    result = chat.respond("hello")
    assert result["ok"] is True
    assert isinstance(chat.workspace, SqliteStateStore)

    watch = WatchRuntime(config_path)
    asyncio.run(watch.setup())
    try:
        assert isinstance(watch.workspace, SqliteStateStore)
    finally:
        asyncio.run(watch.shutdown())

    assert calls == {"agent": 1, "chat": 1, "watch": 1}
