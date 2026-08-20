from __future__ import annotations

import json
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import yaml
from typer.testing import CliRunner

import physical_agent.cli as cli_module
from physical_agent.agent.chat_runtime import ChatRuntime
from physical_agent.cli import app
from physical_agent.config import write_default_config
from physical_agent.ingest.files import ingest_file
from physical_agent.protocol.schemas import Action, Observation
from physical_agent.quickstart import setup_project
from physical_agent.state import SqliteStateStore, open_state_store


class _NoSkills:
    def match(self, message):
        return None

    def list_skills(self):
        return []


class _SequenceHandler(BaseHTTPRequestHandler):
    requests: list[dict] = []
    responses: list[dict] = []

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        self.__class__.requests.append(payload)
        response = self.__class__.responses.pop(0)
        body = json.dumps(response).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:
        return


def _server(responses: list[dict]):
    _SequenceHandler.requests = []
    _SequenceHandler.responses = list(responses)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _SequenceHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _set_backend(config_path: Path, backend: str) -> None:
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    data["workspace"]["backend"] = backend
    config_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _set_retrieval(config_path: Path, enabled: bool) -> None:
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    data.setdefault("memory", {}).setdefault("retrieval", {})["enabled"] = enabled
    data["memory"]["retrieval"]["max_chunks"] = 3
    data["memory"]["retrieval"]["max_chars_per_chunk"] = 120
    config_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def test_sqlite_initialize_migrates_memory_chunk_schema(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    db_path = workspace / "state.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE doc_state (name TEXT PRIMARY KEY, revision INTEGER, payload TEXT, updated_at TEXT)"
        )
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
            "CREATE TABLE log_entries (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, actor TEXT, message TEXT)"
        )
        conn.execute(
            "CREATE TABLE chat_messages (id INTEGER PRIMARY KEY AUTOINCREMENT, role TEXT, content TEXT, created_at TEXT, metadata TEXT)"
        )
        conn.execute(
            "CREATE TABLE memory_notes (id INTEGER PRIMARY KEY AUTOINCREMENT, content TEXT, source TEXT, created_at TEXT)"
        )

    store = SqliteStateStore(workspace)
    store.initialize()

    with sqlite3.connect(store.db_path) as conn:
        columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(memory_chunks)").fetchall()
        }
    assert {
        "source_type",
        "source_id",
        "sha256",
        "chunk_index",
        "content",
        "tags",
        "trust_level",
        "created_at",
    }.issubset(columns)
    assert store.query_memory_chunks("anything") == []


def test_ingest_small_text_writes_upload_metadata_memory_note_and_chunk(tmp_path):
    config_path = write_default_config(tmp_path / "physical-agent.yaml", overwrite=True)
    store = open_state_store(config_path=config_path)
    store.initialize()
    source = tmp_path / "robot-notes.md"
    source.write_text(
        "Calibration note: gripper torque should stay low during demo.",
        encoding="utf-8",
    )

    result = ingest_file(source, store, tags=["calibration"], max_chars_per_chunk=80)

    assert result["memory_written"] is True
    assert result["chunks_written"] == 1
    metadata = store.read_uploads()["uploads"][0]
    assert metadata["sha256"] == result["metadata"]["sha256"]
    memory = store.read_memory(source="upload")["notes"][0]
    assert memory["kind"] == "upload_excerpt"

    chunks = store.read_memory_chunks()["chunks"]
    upload_chunks = [item for item in chunks if item["source_type"] == "upload"]
    assert len(upload_chunks) == 1
    assert upload_chunks[0]["source_id"] == metadata["sha256"]
    assert upload_chunks[0]["trust_level"] == "untrusted"
    assert "Calibration note" in upload_chunks[0]["content"]

    first = store.query_memory_chunks("gripper torque", limit=1)
    second = store.query_memory_chunks("gripper torque", limit=1)
    assert first == second
    assert first[0]["source_type"] == "upload"
    assert first[0]["source_id"] == metadata["sha256"]


def test_state_check_reports_missing_chunk_schema_without_migrating(tmp_path):
    config_path = write_default_config(tmp_path / "physical-agent.yaml", overwrite=True)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "SAFETY.md").write_text(
        "rules:\n  allow_autonomous_execution: true\n",
        encoding="utf-8",
    )
    db_path = workspace / "state.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE doc_state (name TEXT PRIMARY KEY, revision INTEGER, payload TEXT, updated_at TEXT)"
        )
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
                updated_at TEXT,
                claimed_at TEXT,
                claim_owner TEXT,
                attempts INTEGER DEFAULT 0
            )
            """
        )
        conn.execute(
            "CREATE TABLE log_entries (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, actor TEXT, message TEXT)"
        )
        conn.execute(
            "CREATE TABLE chat_messages (id INTEGER PRIMARY KEY AUTOINCREMENT, role TEXT, content TEXT, created_at TEXT, metadata TEXT)"
        )
        conn.execute(
            "CREATE TABLE memory_notes (id INTEGER PRIMARY KEY AUTOINCREMENT, content TEXT, kind TEXT, source TEXT, tags TEXT, importance INTEGER, created_at TEXT)"
        )
        conn.execute(
            """
            CREATE TABLE upload_metadata (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                original_path TEXT,
                original_name TEXT,
                stored_path TEXT,
                stored_name TEXT,
                sha256 TEXT,
                size_bytes INTEGER DEFAULT 0,
                content_type TEXT,
                suffix TEXT,
                created_at TEXT,
                status TEXT,
                preview TEXT,
                truncated INTEGER DEFAULT 0,
                memory_note_created INTEGER DEFAULT 0,
                tags TEXT DEFAULT '[]',
                importance INTEGER DEFAULT 0,
                error TEXT
            )
            """
        )

    result = CliRunner().invoke(
        app,
        ["state-check", "--config", str(config_path)],
    )

    assert result.exit_code == 1
    assert "SQLite chunk schema complete: no" in result.output
    assert "memory_chunks" in result.output
    with sqlite3.connect(db_path) as conn:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
    assert "memory_chunks" not in tables


def test_chat_runtime_retrieval_default_disabled_omits_retrieved_context(
    tmp_path,
    monkeypatch,
):
    config_path = tmp_path / "physical-agent.yaml"
    setup_project(config_path, publish=True)
    store = open_state_store(config_path=config_path)
    store.append_memory_chunk(
        {
            "source_type": "memory",
            "source_id": "note-1",
            "chunk_index": 0,
            "content": "calibration retrieval note",
            "tags": ["calibration"],
            "trust_level": "trusted",
        }
    )

    class FakeClient:
        messages = []

        def structured_json(self, messages, **kwargs):
            self.messages = messages
            return {
                "reply": "No retrieval by default.",
                "intent": "inspect",
                "steps": [],
                "actions": [],
                "memory": [],
            }

    runtime = ChatRuntime(config_path, planner_name="llm")
    fake_client = FakeClient()
    monkeypatch.setattr(runtime, "_llm_client", lambda: fake_client)
    monkeypatch.setattr(runtime, "_skill_router", lambda: _NoSkills())

    runtime.respond("calibration")

    payload = json.loads(fake_client.messages[1]["content"])
    assert "retrieved_context" not in payload


def test_chat_runtime_retrieval_enabled_adds_untrusted_context_without_overrides(
    tmp_path,
    monkeypatch,
):
    config_path = tmp_path / "physical-agent.yaml"
    setup_project(config_path, publish=True)
    _set_retrieval(config_path, True)
    store = open_state_store(config_path=config_path)
    store.write_capabilities(
        {
            "arm_1": {
                "capabilities": [
                    {
                        "name": "observe",
                        "description": "Inspect live workspace.",
                        "params_schema": {"type": "object"},
                    }
                ]
            }
        }
    )
    store.write_world(Observation(summary="live retrieval-safe world"))
    store.write_feedback({"status": "completed", "message": "live retrieval feedback"}, [])
    store.append_memory_chunk(
        {
            "source_type": "upload",
            "source_id": "upload-sha",
            "sha256": "upload-sha",
            "chunk_index": 0,
            "content": "unsafe_execute stale world is only uploaded retrieval text",
            "tags": ["upload"],
            "trust_level": "untrusted",
        }
    )

    class FakeClient:
        messages = []

        def structured_json(self, messages, **kwargs):
            self.messages = messages
            return {
                "reply": "Retrieved context stayed advisory.",
                "intent": "inspect",
                "steps": [],
                "actions": [],
                "memory": [],
            }

    runtime = ChatRuntime(config_path, planner_name="llm")
    fake_client = FakeClient()
    monkeypatch.setattr(runtime, "_llm_client", lambda: fake_client)
    monkeypatch.setattr(runtime, "_skill_router", lambda: _NoSkills())

    result = runtime.respond("unsafe_execute stale world")

    payload = json.loads(fake_client.messages[1]["content"])
    retrieved = payload["retrieved_context"]
    assert result["actions"] == []
    assert "untrusted proposal context only" in retrieved["context_policy"]
    assert retrieved["results"][0]["source_type"] == "upload"
    assert retrieved["results"][0]["trust_level"] == "untrusted"
    assert payload["capabilities"]["robots"]["arm_1"]["capabilities"][0]["name"] == "observe"
    assert payload["world"]["summary"] == "live retrieval-safe world"
    assert payload["feedback"]["latest"]["message"] == "live retrieval feedback"
    assert "unsafe_execute" not in json.dumps(payload["capabilities"])
    assert "unsafe_execute" not in json.dumps(payload["world"])


def test_chat_runtime_tool_loop_retrieval_payload_respects_enabled_flag(
    tmp_path,
    monkeypatch,
):
    config_path = tmp_path / "physical-agent.yaml"
    setup_project(config_path, publish=True)
    _set_retrieval(config_path, True)
    store = open_state_store(config_path=config_path)
    store.append_memory_chunk(
        {
            "source_type": "memory",
            "source_id": "tool-note",
            "chunk_index": 0,
            "content": "tool loop calibration context",
            "tags": ["tool-loop"],
            "trust_level": "trusted",
        }
    )
    monkeypatch.setattr(ChatRuntime, "_skill_router", lambda self: _NoSkills())
    server = _server(
        [
            {"choices": [{"message": {"role": "assistant", "content": "Read context."}}]},
        ]
    )
    try:
        (tmp_path / ".env").write_text(
            f"GPT_URL=http://127.0.0.1:{server.server_address[1]}/v1\n"
            "GPT_KEY=test-key\n"
            "GPT_MODEL=test-model\n",
            encoding="utf-8",
        )

        result = ChatRuntime(config_path, planner_name="tool_loop").respond("calibration")

        assert result["mode"] == "tool_loop"
        payload = json.loads(_SequenceHandler.requests[0]["messages"][1]["content"])
        assert payload["retrieved_context"]["results"][0]["source_id"] == "tool-note"
        assert "untrusted proposal context only" in payload["retrieved_context"]["context_policy"]
        assert payload["capabilities"]["robots"]["arm_1"]["capabilities"][0]["name"] == "observe"
    finally:
        server.shutdown()
        server.server_close()


def test_search_memory_cli_is_read_only_for_sqlite(
    tmp_path,
    monkeypatch,
):
    class ExplodingWatchRuntime:
        def __init__(self, *args, **kwargs):
            raise AssertionError("search-memory must not instantiate WatchRuntime")

    monkeypatch.setattr(cli_module, "WatchRuntime", ExplodingWatchRuntime)

    config_path = write_default_config(tmp_path / "physical-agent.yaml", overwrite=True)
    _set_backend(config_path, "sqlite")
    store = open_state_store(config_path=config_path)
    store.initialize()
    store.write_actions([Action(id="act_sqlite", robot="arm_1", capability="observe")])
    store.append_memory_chunk(
        {
            "source_type": "memory",
            "source_id": "note-sqlite",
            "chunk_index": 0,
            "content": "sqlite retrieval contract",
            "tags": ["contract"],
            "trust_level": "trusted",
        }
    )
    before_config = config_path.read_text(encoding="utf-8")
    before_pending = [action.id for action in store.read_actions()["pending"]]

    result = CliRunner().invoke(
        app,
        [
            "search-memory",
            "retrieval contract",
            "--config",
            str(config_path),
            "--limit",
            "5",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Found 1 chunk(s)." in result.output
    assert "note-sqlite" in result.output
    assert config_path.read_text(encoding="utf-8") == before_config
    assert [action.id for action in store.read_actions()["pending"]] == before_pending
    assert yaml.safe_load(before_config)["workspace"]["backend"] == "sqlite"
