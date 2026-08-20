from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar, Protocol, runtime_checkable

from physical_agent.protocol.schemas import Action, ChatMessage, ChatPlan, Observation


@runtime_checkable
class StateStore(Protocol):
    filenames: ClassVar[dict[str, str]]
    path: Path
    artifacts_path: Path
    uploads_path: Path

    def file(self, name: str) -> Path: ...

    def initialize(self, *, overwrite: bool = False) -> None: ...

    def exists(self) -> bool: ...

    def write_task(
        self,
        task: str,
        constraints: list[str] | None = None,
        *,
        owner: str = "human",
        status: str = "active",
    ) -> None: ...

    def read_task(self) -> dict[str, Any]: ...

    def write_capabilities(self, robots: dict[str, Any]) -> None: ...

    def read_capabilities(self) -> dict[str, Any]: ...

    def write_world(self, observation: Observation | dict[str, Any]) -> None: ...

    def read_world(self) -> dict[str, Any]: ...

    def write_actions(
        self,
        pending: list[Action | dict[str, Any]] | None = None,
        completed: list[Action | dict[str, Any]] | None = None,
        cancelled: list[Action | dict[str, Any]] | None = None,
    ) -> None: ...

    def read_actions(self) -> dict[str, Any]: ...

    def append_pending_action(self, action: Action | dict[str, Any]) -> Action: ...

    def approve_action(
        self,
        action_id: str,
        *,
        actor: str = "local_user",
        reason: str | None = None,
    ) -> tuple[Action, bool]: ...

    def reject_action(
        self,
        action_id: str,
        *,
        actor: str = "local_user",
        reason: str | None = None,
    ) -> Action: ...

    def claim_next_ready_action(self, *, claim_owner: str = "watch") -> Action | None: ...

    def recover_stale_actions(
        self,
        max_age_s: float,
        *,
        claim_owner: str | None = None,
    ) -> int: ...

    def mark_action_completed(self, action: Action | dict[str, Any]) -> None: ...

    def mark_action_cancelled(self, action: Action | dict[str, Any]) -> None: ...

    def write_feedback(
        self,
        latest: dict[str, Any] | None = None,
        history: list[dict[str, Any]] | None = None,
    ) -> None: ...

    def read_feedback(self) -> dict[str, Any]: ...

    def write_safety(self, rules: dict[str, Any] | None = None) -> None: ...

    def read_safety(self) -> dict[str, Any]: ...

    def write_chat(
        self,
        messages: list[ChatMessage | dict[str, Any]],
        *,
        running_summary: str | None = None,
        compact: bool = True,
    ) -> None: ...

    def read_chat(self) -> dict[str, Any]: ...

    def append_chat_message(
        self,
        role: str,
        content: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> ChatMessage: ...

    def write_plan(self, plan: ChatPlan | dict[str, Any]) -> None: ...

    def read_plan(self) -> dict[str, Any]: ...

    def write_memory(self, notes: list[dict[str, Any]]) -> None: ...

    def read_memory(
        self,
        *,
        kind: str | None = None,
        source: str | None = None,
        limit: int | None = None,
        tags: list[str] | str | None = None,
    ) -> dict[str, Any]: ...

    def append_memory_note(
        self,
        content: str,
        *,
        source: str = "chat",
        kind: str = "note",
        tags: list[str] | str | None = None,
        importance: int = 0,
    ) -> dict[str, Any]: ...

    def read_uploads(self) -> dict[str, Any]: ...

    def append_upload_metadata(self, metadata: dict[str, Any]) -> dict[str, Any]: ...

    def read_memory_chunks(self) -> dict[str, Any]: ...

    def append_memory_chunk(self, chunk: dict[str, Any]) -> dict[str, Any]: ...

    def query_memory_chunks(
        self,
        query: str,
        *,
        limit: int = 5,
        tags: list[str] | str | None = None,
        source_type: str | None = None,
    ) -> list[dict[str, Any]]: ...

    def append_log(self, message: str, *, actor: str | None = None) -> None: ...

    def export_human_view(self, out_dir: Path | None = None) -> dict[str, Any]: ...
