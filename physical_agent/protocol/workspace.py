from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import threading
from typing import Any

from physical_agent.protocol.markdown import parse_front_matter, render_front_matter
from physical_agent.protocol.chat_summary import compact_chat_messages
from physical_agent.protocol.memory import filter_memory_notes, normalize_memory_note
from physical_agent.protocol.parsers import (
    parse_actions,
    parse_capabilities,
    parse_chat,
    parse_feedback,
    parse_memory,
    parse_plan,
    parse_safety,
    parse_task,
    parse_world,
)
from physical_agent.protocol.renderers import (
    render_actions,
    render_capabilities,
    render_chat,
    render_feedback,
    render_log,
    render_memory,
    render_plan,
    render_safety,
    render_task,
    render_world,
)
from physical_agent.protocol.schemas import Action, ChatMessage, ChatPlan, Observation
from physical_agent.protocol.retrieval import (
    chunk_source_id_for_memory_note,
    make_chunks_for_text,
    normalize_memory_chunk,
    query_memory_chunks,
)


_LOG_LOCKS: dict[Path, threading.Lock] = {}
_LOG_LOCKS_GUARD = threading.Lock()


def _log_lock(path: Path) -> threading.Lock:
    key = path.resolve()
    with _LOG_LOCKS_GUARD:
        lock = _LOG_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _LOG_LOCKS[key] = lock
        return lock


class Workspace:
    filenames = {
        "task": "TASK.md",
        "capabilities": "CAPABILITIES.md",
        "world": "WORLD.md",
        "actions": "ACTIONS.md",
        "feedback": "FEEDBACK.md",
        "safety": "SAFETY.md",
        "log": "LOG.md",
        "chat": "CHAT.md",
        "plan": "PLAN.md",
        "memory": "MEMORY.md",
    }

    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()
        self.artifacts_path = self.path / "artifacts"
        self.uploads_path = self.path / "uploads"

    def file(self, name: str) -> Path:
        return self.path / self.filenames[name]

    def initialize(self, *, overwrite: bool = False) -> None:
        self.path.mkdir(parents=True, exist_ok=True)
        self.artifacts_path.mkdir(parents=True, exist_ok=True)
        self.uploads_path.mkdir(parents=True, exist_ok=True)
        defaults = {
            "task": render_task("No active task."),
            "capabilities": render_capabilities({}),
            "world": render_world(Observation(summary="No observation has been recorded yet.")),
            "actions": render_actions(),
            "feedback": render_feedback(),
            "safety": render_safety(),
            "log": render_log(),
            "chat": render_chat(),
            "plan": render_plan(),
            "memory": render_memory(),
        }
        for name, content in defaults.items():
            target = self.file(name)
            if overwrite or not target.exists():
                target.write_text(content, encoding="utf-8")

    def exists(self) -> bool:
        return self.path.exists() and all(self.file(name).exists() for name in self.filenames)

    def _next_revision(self, target: Path) -> int:
        if not target.exists():
            return 1
        try:
            return parse_front_matter(target.read_text(encoding="utf-8")).revision + 1
        except Exception:
            return 1

    def write_task(
        self,
        task: str,
        constraints: list[str] | None = None,
        *,
        owner: str = "human",
        status: str = "active",
    ) -> None:
        target = self.file("task")
        target.write_text(
            render_task(
                task,
                constraints,
                owner=owner,
                status=status,
                revision=self._next_revision(target),
            ),
            encoding="utf-8",
        )

    def read_task(self) -> dict[str, Any]:
        return parse_task(self.file("task").read_text(encoding="utf-8"))

    def write_capabilities(self, robots: dict[str, Any]) -> None:
        target = self.file("capabilities")
        target.write_text(
            render_capabilities(robots, revision=self._next_revision(target)),
            encoding="utf-8",
        )

    def read_capabilities(self) -> dict[str, Any]:
        return parse_capabilities(self.file("capabilities").read_text(encoding="utf-8"))

    def write_world(self, observation: Observation | dict[str, Any]) -> None:
        target = self.file("world")
        target.write_text(
            render_world(observation, revision=self._next_revision(target)),
            encoding="utf-8",
        )

    def read_world(self) -> dict[str, Any]:
        return parse_world(self.file("world").read_text(encoding="utf-8"))

    def write_actions(
        self,
        pending: list[Action | dict[str, Any]] | None = None,
        completed: list[Action | dict[str, Any]] | None = None,
        cancelled: list[Action | dict[str, Any]] | None = None,
    ) -> None:
        target = self.file("actions")
        target.write_text(
            render_actions(
                pending,
                completed,
                cancelled,
                revision=self._next_revision(target),
            ),
            encoding="utf-8",
        )

    def read_actions(self) -> dict[str, Any]:
        return parse_actions(self.file("actions").read_text(encoding="utf-8"))

    def write_feedback(
        self,
        latest: dict[str, Any] | None = None,
        history: list[dict[str, Any]] | None = None,
    ) -> None:
        target = self.file("feedback")
        target.write_text(
            render_feedback(latest, history, revision=self._next_revision(target)),
            encoding="utf-8",
        )

    def read_feedback(self) -> dict[str, Any]:
        return parse_feedback(self.file("feedback").read_text(encoding="utf-8"))

    def write_safety(self, rules: dict[str, Any] | None = None) -> None:
        target = self.file("safety")
        target.write_text(
            render_safety(rules, revision=self._next_revision(target)),
            encoding="utf-8",
        )

    def read_safety(self) -> dict[str, Any]:
        return parse_safety(self.file("safety").read_text(encoding="utf-8"))

    def write_chat(
        self,
        messages: list[ChatMessage | dict[str, Any]],
        *,
        running_summary: str | None = None,
        compact: bool = True,
    ) -> None:
        target = self.file("chat")
        if running_summary is None and target.exists():
            try:
                running_summary = self.read_chat().get("running_summary", "")
            except Exception:
                running_summary = ""
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
        target.write_text(
            render_chat(
                output_messages,
                running_summary=summary,
                revision=self._next_revision(target),
            ),
            encoding="utf-8",
        )

    def read_chat(self) -> dict[str, Any]:
        return parse_chat(self.file("chat").read_text(encoding="utf-8"))

    def append_chat_message(
        self,
        role: str,
        content: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> ChatMessage:
        messages = list(self.read_chat()["messages"])
        timestamp = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        message = ChatMessage(
            role=role,
            content=content,
            created_at=timestamp,
            metadata=metadata or {},
        )
        messages.append(message)
        self.write_chat(messages)
        return message

    def write_plan(self, plan: ChatPlan | dict[str, Any]) -> None:
        target = self.file("plan")
        target.write_text(
            render_plan(plan, revision=self._next_revision(target)),
            encoding="utf-8",
        )

    def read_plan(self) -> dict[str, Any]:
        return parse_plan(self.file("plan").read_text(encoding="utf-8"))

    def write_memory(self, notes: list[dict[str, Any]]) -> None:
        target = self.file("memory")
        target.write_text(
            render_memory(notes, revision=self._next_revision(target)),
            encoding="utf-8",
        )
        self._replace_memory_note_chunks(notes)

    def read_memory(
        self,
        *,
        kind: str | None = None,
        source: str | None = None,
        limit: int | None = None,
        tags: list[str] | str | None = None,
    ) -> dict[str, Any]:
        payload = parse_memory(self.file("memory").read_text(encoding="utf-8"))
        payload["notes"] = filter_memory_notes(
            payload.get("notes", []),
            kind=kind,
            source=source,
            limit=limit,
            tags=tags,
        )
        return payload

    def append_memory_note(
        self,
        content: str,
        *,
        source: str = "chat",
        kind: str = "note",
        tags: list[str] | str | None = None,
        importance: int = 0,
    ) -> dict[str, Any]:
        notes = list(self.read_memory()["notes"])
        timestamp = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        note = normalize_memory_note(
            {
                "content": content,
                "source": source,
                "kind": kind,
                "tags": tags,
                "importance": importance,
                "created_at": timestamp,
            }
        )
        notes.append(note)
        self.write_memory(notes)
        return note

    def read_uploads(self) -> dict[str, Any]:
        manifest = self.uploads_path / "manifest.json"
        default = {
            "metadata": {
                "schema": "physical-agent/uploads/v1",
                "owner": "human",
                "revision": 1,
            },
            "uploads": [],
        }
        if not manifest.exists():
            return default
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return default
        if not isinstance(payload, dict):
            return default
        metadata = dict(payload.get("metadata") or {})
        metadata.setdefault("schema", "physical-agent/uploads/v1")
        metadata.setdefault("owner", "human")
        try:
            metadata["revision"] = int(metadata.get("revision") or 1)
        except (TypeError, ValueError):
            metadata["revision"] = 1
        uploads = payload.get("uploads")
        if not isinstance(uploads, list):
            uploads = []
        return {"metadata": metadata, "uploads": [item for item in uploads if isinstance(item, dict)]}

    def append_upload_metadata(self, metadata: dict[str, Any]) -> dict[str, Any]:
        self.uploads_path.mkdir(parents=True, exist_ok=True)
        current = self.read_uploads()
        upload = dict(metadata)
        uploads = list(current.get("uploads", []))
        uploads.append(upload)
        doc_metadata = dict(current.get("metadata") or {})
        try:
            revision = int(doc_metadata.get("revision") or 1) + 1
        except (TypeError, ValueError):
            revision = 2
        doc_metadata.update(
            {
                "schema": "physical-agent/uploads/v1",
                "owner": "human",
                "revision": revision,
            }
        )
        manifest = self.uploads_path / "manifest.json"
        manifest.write_text(
            json.dumps(
                {"metadata": doc_metadata, "uploads": uploads},
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return upload

    def read_memory_chunks(self) -> dict[str, Any]:
        manifest = self.uploads_path / "chunks.json"
        default = {
            "metadata": {
                "schema": "physical-agent/retrieval-chunks/v1",
                "owner": "agent",
                "revision": 1,
            },
            "chunks": [],
        }
        if not manifest.exists():
            return default
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return default
        if not isinstance(payload, dict):
            return default
        metadata = dict(payload.get("metadata") or {})
        metadata.setdefault("schema", "physical-agent/retrieval-chunks/v1")
        metadata.setdefault("owner", "agent")
        try:
            metadata["revision"] = int(metadata.get("revision") or 1)
        except (TypeError, ValueError):
            metadata["revision"] = 1
        chunks = payload.get("chunks")
        if not isinstance(chunks, list):
            chunks = []
        return {
            "metadata": metadata,
            "chunks": [
                normalize_memory_chunk(item)
                for item in chunks
                if isinstance(item, dict)
            ],
        }

    def append_memory_chunk(self, chunk: dict[str, Any]) -> dict[str, Any]:
        self.uploads_path.mkdir(parents=True, exist_ok=True)
        normalized = normalize_memory_chunk(chunk)
        current = self.read_memory_chunks()
        chunks = [
            item
            for item in current.get("chunks", [])
            if not _same_chunk_identity(item, normalized)
        ]
        chunks.append(normalized)
        self._write_chunks_manifest(chunks, current.get("metadata", {}))
        return normalized

    def query_memory_chunks(
        self,
        query: str,
        *,
        limit: int = 5,
        tags: list[str] | str | None = None,
        source_type: str | None = None,
    ) -> list[dict[str, Any]]:
        return query_memory_chunks(
            self.read_memory_chunks().get("chunks", []),
            query,
            limit=limit,
            tags=tags,
            source_type=source_type,
        )

    def append_log(self, message: str, *, actor: str | None = None) -> None:
        target = self.file("log")
        with _log_lock(target):
            if target.exists():
                doc = parse_front_matter(target.read_text(encoding="utf-8"))
                metadata = dict(doc.metadata)
                body = doc.body.rstrip() + "\n\n"
                metadata["revision"] = doc.revision + 1
            else:
                metadata = {"schema": "physical-agent/log/v1", "owner": "system", "revision": 1}
                body = "# Physical Agent Log\n\n"
            timestamp = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            prefix = f"**{actor}**: " if actor else ""
            body += f"## {timestamp}\n\n{prefix}{message}\n"
            target.write_text(render_front_matter(metadata, body), encoding="utf-8")

    def _replace_memory_note_chunks(self, notes: list[dict[str, Any]]) -> None:
        current = self.read_memory_chunks()
        preserved = [
            item
            for item in current.get("chunks", [])
            if item.get("source_type") != "memory"
        ]
        memory_chunks: list[dict[str, Any]] = []
        for note in notes:
            normalized_note = normalize_memory_note(note)
            if normalized_note.get("source") == "upload":
                continue
            source_id = chunk_source_id_for_memory_note(normalized_note)
            memory_chunks.extend(
                make_chunks_for_text(
                    normalized_note["content"],
                    source_type="memory",
                    source_id=source_id,
                    tags=normalized_note["tags"],
                    trust_level="trusted",
                    created_at=normalized_note["created_at"],
                )
            )
        self._write_chunks_manifest(preserved + memory_chunks, current.get("metadata", {}))

    def _write_chunks_manifest(
        self,
        chunks: list[dict[str, Any]],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.uploads_path.mkdir(parents=True, exist_ok=True)
        doc_metadata = dict(metadata or {})
        try:
            revision = int(doc_metadata.get("revision") or 1) + 1
        except (TypeError, ValueError):
            revision = 2
        doc_metadata.update(
            {
                "schema": "physical-agent/retrieval-chunks/v1",
                "owner": "agent",
                "revision": revision,
            }
        )
        manifest = self.uploads_path / "chunks.json"
        manifest.write_text(
            json.dumps(
                {
                    "metadata": doc_metadata,
                    "chunks": [normalize_memory_chunk(item) for item in chunks],
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )


def _same_chunk_identity(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return (
        left.get("source_type") == right.get("source_type")
        and left.get("source_id") == right.get("source_id")
        and left.get("chunk_index") == right.get("chunk_index")
    )
