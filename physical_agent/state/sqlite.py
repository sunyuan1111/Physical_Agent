from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterator

from physical_agent.protocol.chat_summary import compact_chat_messages
from physical_agent.protocol.memory import (
    filter_memory_notes,
    normalize_memory_note,
    normalize_memory_tags,
)
from physical_agent.protocol.expectations import normalize_expected_metadata
from physical_agent.protocol.retrieval import (
    chunk_source_id_for_memory_note,
    make_chunks_for_text,
    normalize_memory_chunk,
    query_memory_chunks as score_memory_chunks,
)
from physical_agent.protocol.schemas import Action, ChatMessage, ChatPlan, Observation
from physical_agent.protocol.workspace import Workspace
from physical_agent.state.audit import export_audit_documents, read_markdown_log_entries


DOC_SCHEMAS = {
    "task": "physical-agent/task/v1",
    "capabilities": "physical-agent/capabilities/v1",
    "world": "physical-agent/world/v1",
    "actions": "physical-agent/actions/v1",
    "feedback": "physical-agent/feedback/v1",
    "chat": "physical-agent/chat/v1",
    "plan": "physical-agent/plan/v1",
    "memory": "physical-agent/memory/v1",
    "uploads": "physical-agent/uploads/v1",
    "log": "physical-agent/log/v1",
}

DOC_OWNERS = {
    "task": "human",
    "capabilities": "watch",
    "world": "watch",
    "actions": "agent",
    "feedback": "watch",
    "chat": "agent",
    "plan": "agent",
    "memory": "agent",
    "uploads": "human",
    "log": "system",
}

REQUIRED_TABLES = {
    "doc_state",
    "actions",
    "log_entries",
    "chat_messages",
    "memory_notes",
}

SQLITE_SCHEMA_TABLES = REQUIRED_TABLES | {"upload_metadata", "memory_chunks"}

DEFAULT_ACTION_LEASE_SECONDS = 300
DEFAULT_CLAIM_OWNER = "watch"

ACTION_CLAIM_COLUMNS = {
    "claimed_at": "TEXT",
    "claim_owner": "TEXT",
    "attempts": "INTEGER DEFAULT 0",
    "metadata": "TEXT DEFAULT '{}'",
}

MEMORY_NOTE_COLUMNS = {
    "content": "TEXT",
    "kind": "TEXT DEFAULT 'note'",
    "source": "TEXT DEFAULT 'chat'",
    "tags": "TEXT DEFAULT '[]'",
    "importance": "INTEGER DEFAULT 0",
    "created_at": "TEXT",
}

UPLOAD_METADATA_COLUMNS = {
    "original_path": "TEXT",
    "original_name": "TEXT",
    "stored_path": "TEXT",
    "stored_name": "TEXT",
    "sha256": "TEXT",
    "size_bytes": "INTEGER DEFAULT 0",
    "content_type": "TEXT",
    "suffix": "TEXT",
    "created_at": "TEXT",
    "status": "TEXT",
    "preview": "TEXT",
    "truncated": "INTEGER DEFAULT 0",
    "memory_note_created": "INTEGER DEFAULT 0",
    "tags": "TEXT DEFAULT '[]'",
    "importance": "INTEGER DEFAULT 0",
    "error": "TEXT",
}

MEMORY_CHUNK_COLUMNS = {
    "source_type": "TEXT",
    "source_id": "TEXT",
    "sha256": "TEXT",
    "chunk_index": "INTEGER DEFAULT 0",
    "content": "TEXT",
    "tags": "TEXT DEFAULT '[]'",
    "trust_level": "TEXT DEFAULT 'untrusted'",
    "created_at": "TEXT",
}


class SqliteStateStore:
    filenames = Workspace.filenames

    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()
        self.artifacts_path = self.path / "artifacts"
        self.uploads_path = self.path / "uploads"
        self.db_path = self.path / "state.db"
        self._file_workspace = Workspace(self.path)

    def file(self, name: str) -> Path:
        return self.path / self.filenames[name]

    def initialize(self, *, overwrite: bool = False) -> None:
        self.path.mkdir(parents=True, exist_ok=True)
        self.artifacts_path.mkdir(parents=True, exist_ok=True)
        self.uploads_path.mkdir(parents=True, exist_ok=True)
        if overwrite:
            self._clear_database()

        with self._connect() as conn:
            self._create_schema(conn)
            self._ensure_default_documents(conn)

        if overwrite or not self.file("safety").exists():
            self._file_workspace.write_safety()
        if overwrite or not self.file("log").exists():
            self.file("log").write_text(
                _render_log_file(),
                encoding="utf-8",
            )

    def exists(self) -> bool:
        if not self.path.exists() or not self.db_path.exists() or not self.file("safety").exists():
            return False
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
        except sqlite3.Error:
            return False
        return REQUIRED_TABLES.issubset({str(row["name"]) for row in rows})

    def write_task(
        self,
        task: str,
        constraints: list[str] | None = None,
        *,
        owner: str = "human",
        status: str = "active",
    ) -> None:
        revision = self._next_revision("task")
        payload = {
            "metadata": {
                "schema": DOC_SCHEMAS["task"],
                "owner": owner,
                "status": status,
                "revision": revision,
            },
            "task": task.strip() or "No active task.",
            "constraints": constraints or [],
        }
        self._replace_document("task", payload, revision=revision)

    def read_task(self) -> dict[str, Any]:
        payload = self._read_document("task")
        payload.setdefault("task", "No active task.")
        payload.setdefault("constraints", [])
        return payload

    def write_capabilities(self, robots: dict[str, Any]) -> None:
        revision = self._next_revision("capabilities")
        self._replace_document(
            "capabilities",
            {
                "metadata": self._metadata("capabilities", revision),
                "robots": _as_plain(robots),
            },
            revision=revision,
        )

    def read_capabilities(self) -> dict[str, Any]:
        payload = self._read_document("capabilities")
        payload.setdefault("robots", {})
        return payload

    def write_world(self, observation: Observation | dict[str, Any]) -> None:
        value = _coerce_observation(observation)
        revision = self._next_revision("world")
        state = {
            "robots": value.robots,
            "objects": value.objects,
            "environment": value.environment,
            "artifacts": value.artifacts,
            "raw": value.raw,
        }
        self._replace_document(
            "world",
            {
                "metadata": self._metadata("world", revision),
                "summary": value.summary,
                "state": _as_plain(state),
                "observation": value.model_dump(mode="json"),
            },
            revision=revision,
        )

    def read_world(self) -> dict[str, Any]:
        payload = self._read_document("world")
        state = payload.get("state") or {}
        summary = str(payload.get("summary") or "No observation has been recorded yet.")
        observation = Observation(
            summary=summary,
            robots=state.get("robots", {}),
            objects=state.get("objects", {}),
            environment=state.get("environment", {}),
            artifacts=state.get("artifacts", []),
            raw=state.get("raw", {}),
        )
        payload["summary"] = summary
        payload["state"] = state
        payload["observation"] = observation
        return payload

    def write_actions(
        self,
        pending: list[Action | dict[str, Any]] | None = None,
        completed: list[Action | dict[str, Any]] | None = None,
        cancelled: list[Action | dict[str, Any]] | None = None,
    ) -> None:
        with self._connect() as conn:
            revision = self._next_revision_conn(conn, "actions")
            self._replace_actions_conn(
                conn,
                pending or [],
                completed or [],
                cancelled or [],
            )
            self._upsert_document_conn(
                conn,
                "actions",
                {"metadata": self._metadata("actions", revision)},
                revision,
            )

    def read_actions(self) -> dict[str, Any]:
        with self._connect() as conn:
            metadata = self._read_metadata_conn(conn, "actions")
            capabilities = self._read_document_conn(conn, "capabilities")
            safety_rules = self.read_safety().get("rules", {})
            return {
                "metadata": metadata,
                "pending": self._read_actions_by_status(
                    conn,
                    "pending",
                    capabilities=capabilities,
                    safety_rules=safety_rules,
                ),
                "completed": self._read_actions_by_status(
                    conn,
                    "completed",
                    capabilities=capabilities,
                    safety_rules=safety_rules,
                ),
                "cancelled": self._read_actions_by_status(
                    conn,
                    "cancelled",
                    capabilities=capabilities,
                    safety_rules=safety_rules,
                ),
            }

    def append_pending_action(self, action: Action | dict[str, Any]) -> Action:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            capabilities = self._read_document_conn(conn, "capabilities")
            safety_rules = self.read_safety().get("rules", {})
            parsed = _with_backend_approval_metadata(
                _coerce_action(action),
                capabilities=capabilities,
                safety_rules=safety_rules,
            )
            revision = self._next_revision_conn(conn, "actions")
            seq = self._next_action_seq_conn(conn)
            timestamp = _now()
            conn.execute(
                """
                INSERT INTO actions(
                    id, robot, capability, params, reason, depends_on,
                    metadata, status, result, seq, created_at, updated_at,
                    claimed_at, claim_owner, attempts
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    parsed.id,
                    parsed.robot,
                    parsed.capability,
                    _json_dumps(parsed.params),
                    parsed.reason,
                    _json_dumps(parsed.depends_on),
                    _json_dumps(parsed.metadata),
                    "pending",
                    _json_dumps({}),
                    seq,
                    timestamp,
                    timestamp,
                    None,
                    None,
                    0,
                ),
            )
            self._upsert_document_conn(
                conn,
                "actions",
                {"metadata": self._metadata("actions", revision)},
                revision,
            )
        return parsed

    def approve_action(
        self,
        action_id: str,
        *,
        actor: str = "local_user",
        reason: str | None = None,
    ) -> tuple[Action, bool]:
        timestamp = _now()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT id, robot, capability, params, reason, depends_on, metadata, status
                FROM actions
                WHERE id = ?
                """,
                (action_id,),
            ).fetchone()
            if row is None:
                raise KeyError(action_id)
            status = str(row["status"] or "")
            if status in {"completed", "cancelled", "in_progress"}:
                raise ValueError(f"Cannot approve action `{action_id}` in status `{status}`.")

            capabilities = self._read_document_conn(conn, "capabilities")
            safety_rules = self.read_safety().get("rules", {})
            action = _with_backend_approval_metadata(
                _action_from_row(row),
                capabilities=capabilities,
                safety_rules=safety_rules,
            )
            metadata = dict(action.metadata)
            approval = dict(metadata.get("approval") or {})
            if not approval.get("required"):
                action = _replace_action_metadata(action, metadata)
                self._update_action_metadata_conn(conn, action.id, action.metadata, updated_at=timestamp)
                return action, False
            if approval.get("status") == "approved":
                self._update_action_metadata_conn(conn, action.id, action.metadata, updated_at=timestamp)
                return action, False

            approval.update(
                {
                    "required": True,
                    "status": "approved",
                    "by": actor,
                    "at": timestamp,
                    "approved_by": actor,
                    "approved_at": timestamp,
                }
            )
            if reason:
                approval["reason"] = reason
            metadata["approval"] = approval
            action = _replace_action_metadata(action, metadata)
            revision = self._next_revision_conn(conn, "actions")
            self._update_action_metadata_conn(conn, action.id, action.metadata, updated_at=timestamp)
            self._upsert_document_conn(
                conn,
                "actions",
                {"metadata": self._metadata("actions", revision)},
                revision,
            )
            return action, True

    def reject_action(
        self,
        action_id: str,
        *,
        actor: str = "local_user",
        reason: str | None = None,
    ) -> Action:
        timestamp = _now()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT id, robot, capability, params, reason, depends_on, metadata, status
                FROM actions
                WHERE id = ?
                """,
                (action_id,),
            ).fetchone()
            if row is None:
                raise KeyError(action_id)
            status = str(row["status"] or "")
            if status in {"completed", "cancelled", "in_progress"}:
                raise ValueError(f"Cannot reject action `{action_id}` in status `{status}`.")

            capabilities = self._read_document_conn(conn, "capabilities")
            safety_rules = self.read_safety().get("rules", {})
            action = _with_backend_approval_metadata(
                _action_from_row(row),
                capabilities=capabilities,
                safety_rules=safety_rules,
            )
            metadata = dict(action.metadata)
            approval = dict(metadata.get("approval") or {})
            approval.update(
                {
                    "required": bool(approval.get("required")),
                    "status": "rejected",
                    "by": actor,
                    "at": timestamp,
                    "rejected_by": actor,
                    "rejected_at": timestamp,
                    "reason": reason or "Rejected by human reviewer.",
                }
            )
            metadata["approval"] = approval
            action = _replace_action_metadata(action, metadata)
            revision = self._next_revision_conn(conn, "actions")
            conn.execute(
                """
                UPDATE actions
                SET metadata = ?,
                    status = 'cancelled',
                    claimed_at = NULL,
                    claim_owner = NULL,
                    updated_at = ?
                WHERE id = ? AND status = 'pending'
                """,
                (
                    _json_dumps(action.metadata),
                    timestamp,
                    action.id,
                ),
            )
            self._upsert_document_conn(
                conn,
                "actions",
                {"metadata": self._metadata("actions", revision)},
                revision,
            )
            return action

    def claim_next_ready_action(self, *, claim_owner: str = DEFAULT_CLAIM_OWNER) -> Action | None:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._recover_stale_actions_conn(
                conn,
                DEFAULT_ACTION_LEASE_SECONDS,
            )
            rows = conn.execute(
                """
                SELECT id, robot, capability, params, reason, depends_on, metadata
                FROM actions
                WHERE status = 'pending'
                ORDER BY seq, id
                """
            ).fetchall()
            if not rows:
                return None

            capabilities = self._read_document_conn(conn, "capabilities")
            safety_rules = self.read_safety().get("rules", {})
            timestamp = _now()
            row = None
            action = None
            metadata_changed = False
            for candidate in rows:
                candidate_action = _with_backend_approval_metadata(
                    _action_from_row(candidate),
                    capabilities=capabilities,
                    safety_rules=safety_rules,
                )
                candidate_metadata = _json_dumps(candidate_action.metadata)
                if candidate_metadata != (candidate["metadata"] or "{}"):
                    self._update_action_metadata_conn(
                        conn,
                        candidate_action.id,
                        candidate_action.metadata,
                        updated_at=timestamp,
                    )
                    metadata_changed = True
                if _approval_required(candidate_action) and not _approval_approved(candidate_action):
                    continue
                row = candidate
                action = candidate_action
                break
            if row is None or action is None:
                if metadata_changed:
                    revision = self._next_revision_conn(conn, "actions")
                    self._upsert_document_conn(
                        conn,
                        "actions",
                        {"metadata": self._metadata("actions", revision)},
                        revision,
                    )
                return None

            revision = self._next_revision_conn(conn, "actions")
            cursor = conn.execute(
                """
                UPDATE actions
                SET status = 'in_progress',
                    metadata = ?,
                    claimed_at = ?,
                    claim_owner = ?,
                    attempts = COALESCE(attempts, 0) + 1,
                    updated_at = ?
                WHERE id = ? AND status = 'pending'
                """,
                (_json_dumps(action.metadata), timestamp, claim_owner, timestamp, row["id"]),
            )
            if cursor.rowcount != 1:
                return None
            self._upsert_document_conn(
                conn,
                "actions",
                {"metadata": self._metadata("actions", revision)},
                revision,
            )
            return action

    def recover_stale_actions(
        self,
        max_age_s: float,
        *,
        claim_owner: str | None = None,
    ) -> int:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            return self._recover_stale_actions_conn(
                conn,
                max_age_s,
                claim_owner=claim_owner,
            )

    def mark_action_completed(self, action: Action | dict[str, Any]) -> None:
        self._mark_action_status(action, "completed")

    def mark_action_cancelled(self, action: Action | dict[str, Any]) -> None:
        self._mark_action_status(action, "cancelled")

    def write_feedback(
        self,
        latest: dict[str, Any] | None = None,
        history: list[dict[str, Any]] | None = None,
    ) -> None:
        revision = self._next_revision("feedback")
        self._replace_document(
            "feedback",
            {
                "metadata": self._metadata("feedback", revision),
                "latest": _as_plain(latest or {}),
                "history": _as_plain(history or []),
            },
            revision=revision,
        )

    def read_feedback(self) -> dict[str, Any]:
        payload = self._read_document("feedback")
        payload.setdefault("latest", {})
        payload.setdefault("history", [])
        return payload

    def write_safety(self, rules: dict[str, Any] | None = None) -> None:
        self.path.mkdir(parents=True, exist_ok=True)
        self._file_workspace.write_safety(rules)

    def read_safety(self) -> dict[str, Any]:
        if not self.file("safety").exists():
            self.write_safety()
        return self._file_workspace.read_safety()

    def write_chat(
        self,
        messages: list[ChatMessage | dict[str, Any]],
        *,
        running_summary: str | None = None,
        compact: bool = True,
    ) -> None:
        if running_summary is None:
            running_summary = self.read_chat().get("running_summary", "")
        summary = running_summary or ""
        output_messages = [
            item if isinstance(item, ChatMessage) else ChatMessage.model_validate(item)
            for item in messages
        ]
        if compact:
            summary, output_messages = compact_chat_messages(
                output_messages,
                running_summary=summary,
            )
        with self._connect() as conn:
            revision = self._next_revision_conn(conn, "chat")
            conn.execute("DELETE FROM chat_messages")
            for item in output_messages:
                conn.execute(
                    """
                    INSERT INTO chat_messages(role, content, created_at, metadata)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        item.role,
                        item.content,
                        item.created_at,
                        _json_dumps(item.metadata),
                    ),
                )
            self._upsert_document_conn(
                conn,
                "chat",
                {
                    "metadata": self._metadata("chat", revision),
                    "running_summary": summary,
                },
                revision,
            )

    def read_chat(self) -> dict[str, Any]:
        with self._connect() as conn:
            metadata = self._read_metadata_conn(conn, "chat")
            summary = self._read_document_conn(conn, "chat").get("running_summary", "")
            rows = conn.execute(
                """
                SELECT role, content, created_at, metadata
                FROM chat_messages
                ORDER BY id
                """
            ).fetchall()
        return {
            "metadata": metadata,
            "running_summary": str(summary or ""),
            "messages": [
                ChatMessage(
                    role=str(row["role"]),
                    content=str(row["content"]),
                    created_at=row["created_at"],
                    metadata=_json_loads(row["metadata"], default={}),
                )
                for row in rows
            ],
        }

    def append_chat_message(
        self,
        role: str,
        content: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> ChatMessage:
        messages = list(self.read_chat()["messages"])
        message = ChatMessage(
            role=role,
            content=content,
            created_at=_now(),
            metadata=metadata or {},
        )
        messages.append(message)
        self.write_chat(messages)
        return message

    def write_plan(self, plan: ChatPlan | dict[str, Any]) -> None:
        value = plan if isinstance(plan, ChatPlan) else ChatPlan.model_validate(plan)
        revision = self._next_revision("plan")
        self._replace_document(
            "plan",
            {
                "metadata": self._metadata("plan", revision),
                "plan": value.model_dump(mode="json"),
            },
            revision=revision,
        )

    def read_plan(self) -> dict[str, Any]:
        payload = self._read_document("plan")
        current = payload.get("plan") or {}
        payload["plan"] = current if isinstance(current, ChatPlan) else ChatPlan.model_validate(current)
        return payload

    def write_memory(self, notes: list[dict[str, Any]]) -> None:
        with self._connect() as conn:
            revision = self._next_revision_conn(conn, "memory")
            conn.execute("DELETE FROM memory_notes")
            conn.execute("DELETE FROM memory_chunks WHERE source_type = 'memory'")
            for note in notes:
                normalized = self._insert_memory_note_conn(conn, note)
                self._insert_memory_note_chunks_conn(conn, normalized)
            self._upsert_document_conn(
                conn,
                "memory",
                {"metadata": self._metadata("memory", revision)},
                revision,
            )

    def read_memory(
        self,
        *,
        kind: str | None = None,
        source: str | None = None,
        limit: int | None = None,
        tags: list[str] | str | None = None,
    ) -> dict[str, Any]:
        with self._connect() as conn:
            metadata = self._read_metadata_conn(conn, "memory")
            rows = conn.execute(
                """
                SELECT content, kind, source, tags, importance, created_at
                FROM memory_notes
                ORDER BY id
                """
            ).fetchall()
        notes = [_memory_note_from_row(row) for row in rows]
        return {
            "metadata": metadata,
            "notes": filter_memory_notes(
                notes,
                kind=kind,
                source=source,
                limit=limit,
                tags=tags,
            ),
        }

    def append_memory_note(
        self,
        content: str,
        *,
        source: str = "chat",
        kind: str = "note",
        tags: list[str] | str | None = None,
        importance: int = 0,
    ) -> dict[str, Any]:
        note = normalize_memory_note(
            {
                "content": content,
                "source": source,
                "kind": kind,
                "tags": tags,
                "importance": importance,
                "created_at": _now(),
            }
        )
        with self._connect() as conn:
            revision = self._next_revision_conn(conn, "memory")
            normalized = self._insert_memory_note_conn(conn, note)
            self._insert_memory_note_chunks_conn(conn, normalized)
            self._upsert_document_conn(
                conn,
                "memory",
                {"metadata": self._metadata("memory", revision)},
                revision,
            )
        return note

    def read_uploads(self) -> dict[str, Any]:
        with self._connect() as conn:
            metadata = self._read_metadata_conn(conn, "uploads")
            rows = conn.execute(
                """
                SELECT
                    original_path, original_name, stored_path, stored_name,
                    sha256, size_bytes, content_type, suffix, created_at,
                    status, preview, truncated, memory_note_created,
                    tags, importance, error
                FROM upload_metadata
                ORDER BY id
                """
            ).fetchall()
        return {
            "metadata": metadata,
            "uploads": [_upload_metadata_from_row(row) for row in rows],
        }

    def append_upload_metadata(self, metadata: dict[str, Any]) -> dict[str, Any]:
        upload = _normalize_upload_metadata(metadata)
        with self._connect() as conn:
            revision = self._next_revision_conn(conn, "uploads")
            self._insert_upload_metadata_conn(conn, upload)
            self._upsert_document_conn(
                conn,
                "uploads",
                {"metadata": self._metadata("uploads", revision)},
                revision,
            )
        return upload

    def read_memory_chunks(self) -> dict[str, Any]:
        with self._connect() as conn:
            metadata = {
                "schema": "physical-agent/retrieval-chunks/v1",
                "owner": "agent",
                "revision": 1,
            }
            tables = {
                str(row["name"])
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            if "memory_chunks" not in tables:
                return {"metadata": metadata, "chunks": []}
            rows = conn.execute(
                """
                SELECT
                    id, source_type, source_id, sha256, chunk_index,
                    content, tags, trust_level, created_at
                FROM memory_chunks
                ORDER BY id
                """
            ).fetchall()
        return {
            "metadata": metadata,
            "chunks": [_memory_chunk_from_row(row) for row in rows],
        }

    def append_memory_chunk(self, chunk: dict[str, Any]) -> dict[str, Any]:
        normalized = normalize_memory_chunk(chunk)
        with self._connect() as conn:
            self._insert_memory_chunk_conn(conn, normalized)
        return normalized

    def query_memory_chunks(
        self,
        query: str,
        *,
        limit: int = 5,
        tags: list[str] | str | None = None,
        source_type: str | None = None,
    ) -> list[dict[str, Any]]:
        return score_memory_chunks(
            self.read_memory_chunks().get("chunks", []),
            query,
            limit=limit,
            tags=tags,
            source_type=source_type,
        )

    def append_log(self, message: str, *, actor: str | None = None) -> None:
        timestamp = _now()
        with self._connect() as conn:
            revision = self._next_revision_conn(conn, "log")
            conn.execute(
                """
                INSERT INTO log_entries(ts, actor, message)
                VALUES (?, ?, ?)
                """,
                (timestamp, actor, message),
            )
            self._upsert_document_conn(
                conn,
                "log",
                {"metadata": self._metadata("log", revision)},
                revision,
            )
        self._file_workspace.append_log(message, actor=actor)

    def export_human_view(self, out_dir: Path | None = None) -> dict[str, Any]:
        documents = {
            "task": self.read_task(),
            "capabilities": self.read_capabilities(),
            "world": self.read_world(),
            "actions": self.read_actions(),
            "feedback": self.read_feedback(),
            "chat": self.read_chat(),
            "plan": self.read_plan(),
            "memory": self.read_memory(),
            "uploads": self.read_uploads(),
            "chunks": self.read_memory_chunks(),
            "log": self._read_log_document(),
        }
        return export_audit_documents(
            backend="sqlite",
            workspace_path=self.path,
            documents=documents,
            safety_source=self.file("safety"),
            out_dir=out_dir,
        )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _create_schema(self, conn: sqlite3.Connection) -> None:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS doc_state (
                name TEXT PRIMARY KEY,
                revision INTEGER DEFAULT 1,
                payload TEXT,
                updated_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS actions (
                id TEXT PRIMARY KEY,
                robot TEXT,
                capability TEXT,
                params TEXT,
                reason TEXT,
                depends_on TEXT,
                metadata TEXT,
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
        self._ensure_action_claim_columns(conn)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_actions_status ON actions(status, seq)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_actions_status_claimed_at ON actions(status, claimed_at)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS log_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT,
                actor TEXT,
                message TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT,
                content TEXT,
                created_at TEXT,
                metadata TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS memory_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT,
                kind TEXT DEFAULT 'note',
                source TEXT,
                tags TEXT DEFAULT '[]',
                importance INTEGER DEFAULT 0,
                created_at TEXT
            )
            """
        )
        self._ensure_memory_note_columns(conn)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_memory_notes_kind_source ON memory_notes(kind, source, id)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS upload_metadata (
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
        self._ensure_upload_metadata_columns(conn)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_upload_metadata_sha256 ON upload_metadata(sha256)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS memory_chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_type TEXT,
                source_id TEXT,
                sha256 TEXT,
                chunk_index INTEGER DEFAULT 0,
                content TEXT,
                tags TEXT DEFAULT '[]',
                trust_level TEXT DEFAULT 'untrusted',
                created_at TEXT
            )
            """
        )
        self._ensure_memory_chunk_columns(conn)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_memory_chunks_source_type ON memory_chunks(source_type, source_id)"
        )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_chunks_identity ON memory_chunks(source_type, source_id, chunk_index)"
        )

    def _clear_database(self) -> None:
        # Drop tables in place instead of deleting state.db: on Windows the
        # unlink raises PermissionError (WinError 32) whenever another thread
        # (a watch tick or a concurrent API request) holds a connection open.
        # File deletion remains only for databases sqlite cannot open at all.
        if not self._database_files_exist():
            return
        try:
            with self._connect() as conn:
                names = [
                    str(row["name"])
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master "
                        "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
                    ).fetchall()
                ]
                for name in names:
                    conn.execute(f'DROP TABLE IF EXISTS "{name}"')
        except sqlite3.Error:
            self._unlink_database_files()

    def _unlink_database_files(self) -> None:
        for path in (
            self.db_path,
            Path(f"{self.db_path}-wal"),
            Path(f"{self.db_path}-shm"),
        ):
            if path.exists():
                path.unlink()

    def _database_files_exist(self) -> bool:
        return any(
            path.exists()
            for path in (
                self.db_path,
                Path(f"{self.db_path}-wal"),
                Path(f"{self.db_path}-shm"),
            )
        )

    def _ensure_default_documents(self, conn: sqlite3.Connection) -> None:
        defaults = {
            "task": {
                "metadata": {
                    "schema": DOC_SCHEMAS["task"],
                    "owner": "human",
                    "status": "active",
                    "revision": 1,
                },
                "task": "No active task.",
                "constraints": [],
            },
            "capabilities": {
                "metadata": self._metadata("capabilities", 1),
                "robots": {},
            },
            "world": {
                "metadata": self._metadata("world", 1),
                "summary": "No observation has been recorded yet.",
                "state": {
                    "robots": {},
                    "objects": {},
                    "environment": {},
                    "artifacts": [],
                    "raw": {},
                },
                "observation": Observation(
                    summary="No observation has been recorded yet."
                ).model_dump(mode="json"),
            },
            "actions": {"metadata": self._metadata("actions", 1)},
            "feedback": {
                "metadata": self._metadata("feedback", 1),
                "latest": {},
                "history": [],
            },
            "chat": {
                "metadata": self._metadata("chat", 1),
                "running_summary": "",
            },
            "plan": {
                "metadata": self._metadata("plan", 1),
                "plan": ChatPlan().model_dump(mode="json"),
            },
            "memory": {"metadata": self._metadata("memory", 1)},
            "uploads": {"metadata": self._metadata("uploads", 1)},
            "log": {"metadata": self._metadata("log", 1)},
        }
        for name, payload in defaults.items():
            exists = conn.execute(
                "SELECT 1 FROM doc_state WHERE name = ?",
                (name,),
            ).fetchone()
            if exists is None:
                self._upsert_document_conn(conn, name, payload, 1)

    def _replace_actions_conn(
        self,
        conn: sqlite3.Connection,
        pending: list[Action | dict[str, Any]],
        completed: list[Action | dict[str, Any]],
        cancelled: list[Action | dict[str, Any]],
    ) -> None:
        existing = {
            str(row["id"]): row["created_at"]
            for row in conn.execute("SELECT id, created_at FROM actions").fetchall()
        }
        conn.execute("DELETE FROM actions")
        seq = 0
        timestamp = _now()
        capabilities = self._read_document_conn(conn, "capabilities")
        safety_rules = self.read_safety().get("rules", {})
        for status, items in (
            ("pending", pending),
            ("completed", completed),
            ("cancelled", cancelled),
        ):
            for item in items:
                seq += 1
                action = _with_backend_approval_metadata(
                    _coerce_action(item),
                    capabilities=capabilities,
                    safety_rules=safety_rules,
                )
                conn.execute(
                    """
                    INSERT INTO actions(
                        id, robot, capability, params, reason, depends_on,
                        metadata, status, result, seq, created_at, updated_at,
                        claimed_at, claim_owner, attempts
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        action.id,
                        action.robot,
                        action.capability,
                        _json_dumps(action.params),
                        action.reason,
                        _json_dumps(action.depends_on),
                        _json_dumps(action.metadata),
                        status,
                        _json_dumps({}),
                        seq,
                        existing.get(action.id, timestamp),
                        timestamp,
                        None,
                        None,
                        0,
                    ),
                )

    def _next_action_seq_conn(self, conn: sqlite3.Connection) -> int:
        row = conn.execute("SELECT COALESCE(MAX(seq), 0) + 1 AS next_seq FROM actions").fetchone()
        return int(row["next_seq"] or 1)

    def _mark_action_status(self, action: Action | dict[str, Any], status: str) -> None:
        if status not in {"completed", "cancelled"}:
            raise ValueError(f"Unsupported action status: {status}")
        parsed = _coerce_action(action)
        timestamp = _now()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            capabilities = self._read_document_conn(conn, "capabilities")
            safety_rules = self.read_safety().get("rules", {})
            parsed = _with_backend_approval_metadata(
                parsed,
                capabilities=capabilities,
                safety_rules=safety_rules,
            )
            revision = self._next_revision_conn(conn, "actions")
            existing = conn.execute(
                "SELECT seq, created_at FROM actions WHERE id = ?",
                (parsed.id,),
            ).fetchone()
            if existing is None:
                conn.execute(
                    """
                    INSERT INTO actions(
                        id, robot, capability, params, reason, depends_on,
                        metadata, status, result, seq, created_at, updated_at,
                        claimed_at, claim_owner, attempts
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        parsed.id,
                        parsed.robot,
                        parsed.capability,
                        _json_dumps(parsed.params),
                        parsed.reason,
                        _json_dumps(parsed.depends_on),
                        _json_dumps(parsed.metadata),
                        status,
                        _json_dumps({}),
                        self._next_action_seq_conn(conn),
                        timestamp,
                        timestamp,
                        None,
                        None,
                        0,
                    ),
                )
            else:
                conn.execute(
                    """
                    UPDATE actions
                    SET robot = ?,
                        capability = ?,
                        params = ?,
                        reason = ?,
                        depends_on = ?,
                        metadata = ?,
                        status = ?,
                        claimed_at = NULL,
                        claim_owner = NULL,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        parsed.robot,
                        parsed.capability,
                        _json_dumps(parsed.params),
                        parsed.reason,
                        _json_dumps(parsed.depends_on),
                        _json_dumps(parsed.metadata),
                        status,
                        timestamp,
                        parsed.id,
                    ),
                )
            self._upsert_document_conn(
                conn,
                "actions",
                {"metadata": self._metadata("actions", revision)},
                revision,
            )

    def _ensure_action_claim_columns(self, conn: sqlite3.Connection) -> None:
        existing = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(actions)").fetchall()
        }
        for name, definition in ACTION_CLAIM_COLUMNS.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE actions ADD COLUMN {name} {definition}")
        conn.execute("UPDATE actions SET attempts = 0 WHERE attempts IS NULL")
        conn.execute("UPDATE actions SET metadata = '{}' WHERE metadata IS NULL")

    def _update_action_metadata_conn(
        self,
        conn: sqlite3.Connection,
        action_id: str,
        metadata: dict[str, Any],
        *,
        updated_at: str,
    ) -> None:
        conn.execute(
            """
            UPDATE actions
            SET metadata = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (_json_dumps(metadata), updated_at, action_id),
        )

    def _ensure_memory_note_columns(self, conn: sqlite3.Connection) -> None:
        existing = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(memory_notes)").fetchall()
        }
        for name, definition in MEMORY_NOTE_COLUMNS.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE memory_notes ADD COLUMN {name} {definition}")
        conn.execute(
            "UPDATE memory_notes SET kind = 'note' WHERE kind IS NULL OR TRIM(kind) = ''"
        )
        conn.execute(
            "UPDATE memory_notes SET source = 'chat' WHERE source IS NULL OR TRIM(source) = ''"
        )
        conn.execute("UPDATE memory_notes SET tags = '[]' WHERE tags IS NULL OR tags = ''")
        conn.execute("UPDATE memory_notes SET importance = 0 WHERE importance IS NULL")

    def _ensure_upload_metadata_columns(self, conn: sqlite3.Connection) -> None:
        existing = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(upload_metadata)").fetchall()
        }
        for name, definition in UPLOAD_METADATA_COLUMNS.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE upload_metadata ADD COLUMN {name} {definition}")
        conn.execute(
            "UPDATE upload_metadata SET size_bytes = 0 WHERE size_bytes IS NULL"
        )
        conn.execute(
            "UPDATE upload_metadata SET truncated = 0 WHERE truncated IS NULL"
        )
        conn.execute(
            "UPDATE upload_metadata SET memory_note_created = 0 WHERE memory_note_created IS NULL"
        )
        conn.execute(
            "UPDATE upload_metadata SET tags = '[]' WHERE tags IS NULL OR tags = ''"
        )
        conn.execute(
            "UPDATE upload_metadata SET importance = 0 WHERE importance IS NULL"
        )

    def _ensure_memory_chunk_columns(self, conn: sqlite3.Connection) -> None:
        existing = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(memory_chunks)").fetchall()
        }
        for name, definition in MEMORY_CHUNK_COLUMNS.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE memory_chunks ADD COLUMN {name} {definition}")
        conn.execute(
            "UPDATE memory_chunks SET source_type = 'memory' WHERE source_type IS NULL OR TRIM(source_type) = ''"
        )
        conn.execute(
            "UPDATE memory_chunks SET source_id = COALESCE(NULLIF(source_id, ''), sha256, '') WHERE source_id IS NULL OR TRIM(source_id) = ''"
        )
        conn.execute(
            "UPDATE memory_chunks SET chunk_index = 0 WHERE chunk_index IS NULL"
        )
        conn.execute(
            "UPDATE memory_chunks SET tags = '[]' WHERE tags IS NULL OR tags = ''"
        )
        conn.execute(
            "UPDATE memory_chunks SET trust_level = 'untrusted' WHERE trust_level IS NULL OR TRIM(trust_level) = ''"
        )

    def _insert_memory_note_conn(
        self,
        conn: sqlite3.Connection,
        note: dict[str, Any],
    ) -> dict[str, Any]:
        normalized = normalize_memory_note(note)
        conn.execute(
            """
            INSERT INTO memory_notes(content, kind, source, tags, importance, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                normalized["content"],
                normalized["kind"],
                normalized["source"],
                _json_dumps(normalized["tags"]),
                normalized["importance"],
                normalized["created_at"],
            ),
        )
        return normalized

    def _insert_memory_note_chunks_conn(
        self,
        conn: sqlite3.Connection,
        note: dict[str, Any],
    ) -> None:
        if note.get("source") == "upload":
            return
        source_id = chunk_source_id_for_memory_note(note)
        chunks = make_chunks_for_text(
            note["content"],
            source_type="memory",
            source_id=source_id,
            tags=note["tags"],
            trust_level="trusted",
            created_at=note["created_at"],
        )
        for chunk in chunks:
            self._insert_memory_chunk_conn(conn, chunk)

    def _insert_memory_chunk_conn(
        self,
        conn: sqlite3.Connection,
        chunk: dict[str, Any],
    ) -> None:
        normalized = normalize_memory_chunk(chunk)
        conn.execute(
            """
            INSERT INTO memory_chunks(
                source_type, source_id, sha256, chunk_index,
                content, tags, trust_level, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_type, source_id, chunk_index) DO UPDATE SET
                sha256 = excluded.sha256,
                content = excluded.content,
                tags = excluded.tags,
                trust_level = excluded.trust_level,
                created_at = excluded.created_at
            """,
            (
                normalized["source_type"],
                normalized["source_id"],
                normalized["sha256"],
                normalized["chunk_index"],
                normalized["content"],
                _json_dumps(normalized["tags"]),
                normalized["trust_level"],
                normalized["created_at"],
            ),
        )

    def _insert_upload_metadata_conn(
        self,
        conn: sqlite3.Connection,
        metadata: dict[str, Any],
    ) -> None:
        normalized = _normalize_upload_metadata(metadata)
        conn.execute(
            """
            INSERT INTO upload_metadata(
                original_path, original_name, stored_path, stored_name,
                sha256, size_bytes, content_type, suffix, created_at,
                status, preview, truncated, memory_note_created,
                tags, importance, error
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                normalized["original_path"],
                normalized["original_name"],
                normalized["stored_path"],
                normalized["stored_name"],
                normalized["sha256"],
                normalized["size_bytes"],
                normalized["content_type"],
                normalized["suffix"],
                normalized["created_at"],
                normalized["status"],
                normalized["preview"],
                1 if normalized["truncated"] else 0,
                1 if normalized["memory_note_created"] else 0,
                _json_dumps(normalized["tags"]),
                normalized["importance"],
                normalized["error"],
            ),
        )

    def _recover_stale_actions_conn(
        self,
        conn: sqlite3.Connection,
        max_age_s: float,
        *,
        claim_owner: str | None = None,
    ) -> int:
        if max_age_s < 0:
            raise ValueError("max_age_s must be non-negative")
        timestamp = _now()
        cutoff = _seconds_ago(max_age_s)
        owner_clause = ""
        params: list[Any] = [timestamp, cutoff]
        if claim_owner is not None:
            owner_clause = " AND (claim_owner = ? OR claim_owner IS NULL)"
            params.append(claim_owner)
        cursor = conn.execute(
            f"""
            UPDATE actions
            SET status = 'pending',
                claimed_at = NULL,
                claim_owner = NULL,
                updated_at = ?
            WHERE status = 'in_progress'
              AND (claimed_at IS NULL OR claimed_at <= ?)
              {owner_clause}
            """,
            params,
        )
        recovered = int(cursor.rowcount or 0)
        if recovered:
            revision = self._next_revision_conn(conn, "actions")
            self._upsert_document_conn(
                conn,
                "actions",
                {"metadata": self._metadata("actions", revision)},
                revision,
            )
        return recovered

    def _replace_actions_with_revision(
        self,
        pending: list[Action | dict[str, Any]],
        completed: list[Action | dict[str, Any]],
        cancelled: list[Action | dict[str, Any]],
        *,
        revision: int,
    ) -> None:
        with self._connect() as conn:
            self._replace_actions_conn(conn, pending, completed, cancelled)
            self._upsert_document_conn(
                conn,
                "actions",
                {"metadata": self._metadata("actions", revision)},
                revision,
            )

    def _replace_chat_with_revision(
        self,
        messages: list[ChatMessage | dict[str, Any]],
        *,
        running_summary: str,
        revision: int,
    ) -> None:
        normalized = [
            item if isinstance(item, ChatMessage) else ChatMessage.model_validate(item)
            for item in messages
        ]
        with self._connect() as conn:
            conn.execute("DELETE FROM chat_messages")
            for item in normalized:
                conn.execute(
                    """
                    INSERT INTO chat_messages(role, content, created_at, metadata)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        item.role,
                        item.content,
                        item.created_at,
                        _json_dumps(item.metadata),
                    ),
                )
            self._upsert_document_conn(
                conn,
                "chat",
                {
                    "metadata": self._metadata("chat", revision),
                    "running_summary": running_summary,
                },
                revision,
            )

    def _replace_memory_with_revision(
        self,
        notes: list[dict[str, Any]],
        *,
        revision: int,
    ) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM memory_notes")
            conn.execute("DELETE FROM memory_chunks WHERE source_type = 'memory'")
            for note in notes:
                normalized = self._insert_memory_note_conn(conn, note)
                self._insert_memory_note_chunks_conn(conn, normalized)
            self._upsert_document_conn(
                conn,
                "memory",
                {"metadata": self._metadata("memory", revision)},
                revision,
            )

    def _replace_uploads_with_revision(
        self,
        uploads: list[dict[str, Any]],
        *,
        revision: int,
    ) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM upload_metadata")
            for upload in uploads:
                self._insert_upload_metadata_conn(conn, upload)
            self._upsert_document_conn(
                conn,
                "uploads",
                {"metadata": self._metadata("uploads", revision)},
                revision,
            )

    def _replace_log_entries(self, entries: list[dict[str, Any]], *, revision: int = 1) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM log_entries")
            for entry in entries:
                conn.execute(
                    """
                    INSERT INTO log_entries(ts, actor, message)
                    VALUES (?, ?, ?)
                    """,
                    (
                        entry.get("ts"),
                        entry.get("actor"),
                        str(entry.get("message") or ""),
                    ),
                )
            self._upsert_document_conn(
                conn,
                "log",
                {"metadata": self._metadata("log", revision)},
                revision,
            )

    def _read_log_document(self) -> dict[str, Any]:
        with self._connect() as conn:
            metadata = self._read_metadata_conn(conn, "log")
            rows = conn.execute(
                """
                SELECT id, ts, actor, message
                FROM log_entries
                ORDER BY id
                """
            ).fetchall()
        return {
            "metadata": metadata,
            "entries": [
                {
                    key: value
                    for key, value in {
                        "sequence": int(row["id"]),
                        "ts": row["ts"],
                        "actor": row["actor"],
                        "message": row["message"],
                    }.items()
                    if value is not None
                }
                for row in rows
            ],
        }

    def _read_actions_by_status(
        self,
        conn: sqlite3.Connection,
        status: str,
        *,
        capabilities: dict[str, Any],
        safety_rules: dict[str, Any],
    ) -> list[Action]:
        rows = conn.execute(
            """
            SELECT id, robot, capability, params, reason, depends_on, metadata
            FROM actions
            WHERE status = ?
            ORDER BY seq, id
            """,
            (status,),
        ).fetchall()
        return [
            _with_backend_approval_metadata(
                _action_from_row(row),
                capabilities=capabilities,
                safety_rules=safety_rules,
            )
            for row in rows
        ]

    def _read_document(self, name: str) -> dict[str, Any]:
        with self._connect() as conn:
            return self._read_document_conn(conn, name)

    def _read_document_conn(self, conn: sqlite3.Connection, name: str) -> dict[str, Any]:
        row = conn.execute(
            "SELECT revision, payload FROM doc_state WHERE name = ?",
            (name,),
        ).fetchone()
        if row is None:
            return {"metadata": self._metadata(name, 1)}
        payload = _json_loads(row["payload"], default={})
        if not isinstance(payload, dict):
            payload = {}
        metadata = dict(payload.get("metadata") or {})
        metadata.setdefault("schema", DOC_SCHEMAS.get(name, f"physical-agent/{name}/v1"))
        metadata.setdefault("owner", DOC_OWNERS.get(name, "system"))
        metadata["revision"] = int(row["revision"] or metadata.get("revision") or 1)
        payload["metadata"] = metadata
        return payload

    def _replace_document(
        self,
        name: str,
        payload: dict[str, Any],
        *,
        revision: int | None = None,
    ) -> None:
        with self._connect() as conn:
            self._upsert_document_conn(
                conn,
                name,
                payload,
                revision or self._revision_from_payload(payload) or 1,
            )

    def _upsert_document_conn(
        self,
        conn: sqlite3.Connection,
        name: str,
        payload: dict[str, Any],
        revision: int,
    ) -> None:
        value = _as_plain(payload)
        metadata = dict(value.get("metadata") or {})
        metadata.setdefault("schema", DOC_SCHEMAS.get(name, f"physical-agent/{name}/v1"))
        metadata.setdefault("owner", DOC_OWNERS.get(name, "system"))
        metadata["revision"] = revision
        value["metadata"] = metadata
        conn.execute(
            """
            INSERT INTO doc_state(name, revision, payload, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                revision = excluded.revision,
                payload = excluded.payload,
                updated_at = excluded.updated_at
            """,
            (name, revision, _json_dumps(value), _now()),
        )

    def _read_metadata_conn(self, conn: sqlite3.Connection, name: str) -> dict[str, Any]:
        return dict(self._read_document_conn(conn, name).get("metadata") or {})

    def _next_revision(self, name: str) -> int:
        with self._connect() as conn:
            return self._next_revision_conn(conn, name)

    def _next_revision_conn(self, conn: sqlite3.Connection, name: str) -> int:
        row = conn.execute(
            "SELECT revision FROM doc_state WHERE name = ?",
            (name,),
        ).fetchone()
        if row is None:
            return 1
        try:
            return int(row["revision"]) + 1
        except (TypeError, ValueError):
            return 1

    def _metadata(self, name: str, revision: int) -> dict[str, Any]:
        return {
            "schema": DOC_SCHEMAS.get(name, f"physical-agent/{name}/v1"),
            "owner": DOC_OWNERS.get(name, "system"),
            "revision": revision,
        }

    def _revision_from_payload(self, payload: dict[str, Any]) -> int | None:
        try:
            return int((payload.get("metadata") or {}).get("revision"))
        except (TypeError, ValueError):
            return None


def migrate_markdown_workspace_to_sqlite(
    workspace_path: str | Path,
    *,
    overwrite: bool = False,
) -> dict[str, Any]:
    from physical_agent.state.legacy_markdown import LegacyMarkdownWorkspaceReader

    source = LegacyMarkdownWorkspaceReader(workspace_path)
    if not source.exists():
        raise FileNotFoundError(f"Markdown workspace is not initialized at {source.path}.")

    task = source.read_task()
    capabilities = source.read_capabilities()
    world = source.read_world()
    actions = source.read_actions()
    feedback = source.read_feedback()
    source.read_safety()
    chat = source.read_chat()
    plan = source.read_plan()
    memory = source.read_memory()
    uploads = source.read_uploads()
    log_entries, log_metadata = read_markdown_log_entries(source.file("log"))

    target = SqliteStateStore(source.path)
    if target._database_files_exist():
        if not overwrite:
            raise FileExistsError(
                f"{target.db_path} already exists. Re-run with --overwrite to replace it."
            )
        target._unlink_database_files()

    target.initialize(overwrite=False)
    target._replace_document("task", task, revision=_payload_revision(task))
    target._replace_document("capabilities", capabilities, revision=_payload_revision(capabilities))
    target._replace_document("world", world, revision=_payload_revision(world))
    target._replace_actions_with_revision(
        actions["pending"],
        actions["completed"],
        actions["cancelled"],
        revision=_payload_revision(actions),
    )
    target._replace_document("feedback", feedback, revision=_payload_revision(feedback))
    target._replace_chat_with_revision(
        chat["messages"],
        running_summary=chat.get("running_summary", ""),
        revision=_payload_revision(chat),
    )
    target._replace_document("plan", plan, revision=_payload_revision(plan))
    target._replace_memory_with_revision(memory["notes"], revision=_payload_revision(memory))
    target._replace_uploads_with_revision(
        uploads.get("uploads", []),
        revision=_payload_revision(uploads),
    )
    target._replace_log_entries(log_entries, revision=_metadata_revision(log_metadata))

    return {
        "workspace_path": str(source.path),
        "db_path": str(target.db_path),
        "actions": {
            "pending": len(actions["pending"]),
            "completed": len(actions["completed"]),
            "cancelled": len(actions["cancelled"]),
        },
        "chat_messages": len(chat["messages"]),
        "memory_notes": len(memory["notes"]),
        "uploads": len(uploads.get("uploads", [])),
        "log_entries": len(log_entries),
    }


def _coerce_action(value: Action | dict[str, Any]) -> Action:
    action = value if isinstance(value, Action) else Action.model_validate(value)
    metadata = normalize_expected_metadata(action.metadata)
    if metadata == action.metadata:
        return action
    return action.model_copy(update={"metadata": metadata})


def _action_from_row(row: sqlite3.Row) -> Action:
    return _coerce_action(
        Action(
            id=str(row["id"]),
            robot=str(row["robot"]),
            capability=str(row["capability"]),
            params=_json_loads(row["params"], default={}),
            reason=row["reason"],
            depends_on=_json_loads(row["depends_on"], default=[]),
            metadata=_json_loads(_row_get(row, "metadata"), default={}),
        )
    )


def _row_get(row: sqlite3.Row, key: str) -> Any:
    return row[key] if key in row.keys() else None


def _with_backend_approval_metadata(
    action: Action,
    *,
    capabilities: dict[str, Any],
    safety_rules: dict[str, Any],
) -> Action:
    metadata = dict(action.metadata or {})
    approval = dict(metadata.get("approval") or {})
    required = _action_requires_approval(
        action,
        capabilities=capabilities,
        safety_rules=safety_rules,
    )
    previous_status = str(approval.get("status") or "").strip().lower()
    approval["required"] = required
    if required:
        if previous_status not in {"approved", "rejected"}:
            approval["status"] = "pending"
    else:
        if previous_status not in {"approved", "rejected"}:
            approval["status"] = "not_required"
    metadata["approval"] = approval
    return _replace_action_metadata(action, metadata)


def _replace_action_metadata(action: Action, metadata: dict[str, Any]) -> Action:
    data = action.model_dump(mode="json")
    data["metadata"] = _as_plain(normalize_expected_metadata(metadata))
    return Action.model_validate(data)


def _action_requires_approval(
    action: Action,
    *,
    capabilities: dict[str, Any],
    safety_rules: dict[str, Any],
) -> bool:
    robots = capabilities.get("robots") if isinstance(capabilities, dict) else {}
    robot = robots.get(action.robot) if isinstance(robots, dict) else None
    if not isinstance(robot, dict):
        return False
    if robot.get("requires_approval") and safety_rules.get(
        "require_human_approval_for_real_hardware",
        True,
    ):
        return True
    for capability in robot.get("capabilities") or []:
        if isinstance(capability, dict) and capability.get("name") == action.capability:
            return bool(capability.get("requires_approval"))
    return False


def _approval_required(action: Action) -> bool:
    approval = action.metadata.get("approval") if isinstance(action.metadata, dict) else None
    return bool(isinstance(approval, dict) and approval.get("required"))


def _approval_approved(action: Action) -> bool:
    approval = action.metadata.get("approval") if isinstance(action.metadata, dict) else None
    return bool(isinstance(approval, dict) and approval.get("status") == "approved")


def _memory_note_from_row(row: sqlite3.Row) -> dict[str, Any]:
    tags = _json_loads(row["tags"], default=[])
    return normalize_memory_note(
        {
            "content": row["content"],
            "kind": row["kind"],
            "source": row["source"],
            "tags": normalize_memory_tags(tags),
            "importance": row["importance"],
            "created_at": row["created_at"],
        }
    )


def _upload_metadata_from_row(row: sqlite3.Row) -> dict[str, Any]:
    tags = _json_loads(row["tags"], default=[])
    return _normalize_upload_metadata(
        {
            "original_path": row["original_path"],
            "original_name": row["original_name"],
            "stored_path": row["stored_path"],
            "stored_name": row["stored_name"],
            "sha256": row["sha256"],
            "size_bytes": row["size_bytes"],
            "content_type": row["content_type"],
            "suffix": row["suffix"],
            "created_at": row["created_at"],
            "status": row["status"],
            "preview": row["preview"],
            "truncated": bool(row["truncated"]),
            "memory_note_created": bool(row["memory_note_created"]),
            "tags": tags,
            "importance": row["importance"],
            "error": row["error"],
        }
    )


def _memory_chunk_from_row(row: sqlite3.Row) -> dict[str, Any]:
    tags = _json_loads(row["tags"], default=[])
    return normalize_memory_chunk(
        {
            "source_type": row["source_type"],
            "source_id": row["source_id"],
            "sha256": row["sha256"],
            "chunk_index": row["chunk_index"],
            "content": row["content"],
            "tags": tags,
            "trust_level": row["trust_level"],
            "created_at": row["created_at"],
        }
    )


def _normalize_upload_metadata(value: dict[str, Any]) -> dict[str, Any]:
    raw = dict(value)
    return {
        "original_path": _optional_str(raw.get("original_path")),
        "original_name": _optional_str(raw.get("original_name")),
        "stored_path": _optional_str(raw.get("stored_path")),
        "stored_name": _optional_str(raw.get("stored_name")),
        "sha256": _optional_str(raw.get("sha256")),
        "size_bytes": _nonnegative_int(raw.get("size_bytes")),
        "content_type": _optional_str(raw.get("content_type")),
        "suffix": _optional_str(raw.get("suffix")),
        "created_at": _optional_str(raw.get("created_at")),
        "status": _optional_str(raw.get("status")) or "stored",
        "preview": _optional_str(raw.get("preview")),
        "truncated": bool(raw.get("truncated")),
        "memory_note_created": bool(raw.get("memory_note_created")),
        "tags": normalize_memory_tags(raw.get("tags")),
        "importance": _int_or_zero(raw.get("importance")),
        "error": _optional_str(raw.get("error")),
    }


def _coerce_observation(value: Observation | dict[str, Any]) -> Observation:
    if isinstance(value, Observation):
        return value
    if "state" in value:
        state = value.get("state") or {}
        return Observation(
            summary=str(value.get("summary") or ""),
            robots=state.get("robots", {}),
            objects=state.get("objects", {}),
            environment=state.get("environment", {}),
            artifacts=state.get("artifacts", []),
            raw=state.get("raw", {}),
        )
    if "observation" in value:
        observation = value["observation"]
        return observation if isinstance(observation, Observation) else Observation.model_validate(observation)
    return Observation.model_validate(value)


def _payload_revision(payload: dict[str, Any]) -> int:
    try:
        return int((payload.get("metadata") or {}).get("revision") or 1)
    except (TypeError, ValueError):
        return 1


def _metadata_revision(metadata: dict[str, Any]) -> int:
    try:
        return int(metadata.get("revision") or 1)
    except (TypeError, ValueError):
        return 1


def _optional_str(value: Any) -> str:
    return "" if value is None else str(value)


def _int_or_zero(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _nonnegative_int(value: Any) -> int:
    return max(0, _int_or_zero(value))


def _as_plain(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", exclude_none=True)
    if isinstance(value, list):
        return [_as_plain(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _as_plain(item) for key, item in value.items()}
    if isinstance(value, Path):
        return str(value)
    return value


def _json_dumps(value: Any) -> str:
    return json.dumps(_as_plain(value), ensure_ascii=False, sort_keys=False)


def _json_loads(value: str | None, *, default: Any) -> Any:
    if value in (None, ""):
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _seconds_ago(seconds: float) -> str:
    value = datetime.now(UTC) - timedelta(seconds=seconds)
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _render_log_file() -> str:
    return (
        "---\n"
        "schema: physical-agent/log/v1\n"
        "owner: system\n"
        "revision: 1\n"
        "---\n"
        "# Physical Agent Log\n"
    )
