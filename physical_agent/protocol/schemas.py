from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, populate_by_name=True)


class Action(StrictModel):
    id: str
    robot: str
    capability: str
    params: dict[str, Any] = Field(default_factory=dict)
    reason: str | None = None
    depends_on: list[str] = Field(default_factory=list)


class ActionResult(StrictModel):
    status: Literal["completed", "failed", "cancelled"]
    message: str
    result: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[str] = Field(default_factory=list)


class Observation(StrictModel):
    summary: str
    robots: dict[str, Any] = Field(default_factory=dict)
    objects: dict[str, Any] = Field(default_factory=dict)
    environment: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[str] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


class Capability(StrictModel):
    name: str
    description: str
    params_schema: dict[str, Any]
    returns_schema: dict[str, Any] | None = None
    constraints: dict[str, Any] = Field(default_factory=dict)
    requires_approval: bool = False
    timeout_s: int | None = None


class HealthStatus(StrictModel):
    ok: bool
    message: str = ""
    details: dict[str, Any] = Field(default_factory=dict)


class DriverContext(StrictModel):
    robot_id: str
    robot_name: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    workspace_path: Path
    artifacts_path: Path


class RobotRuntimeProfile(StrictModel):
    robot_id: str
    kind: str
    driver: str
    status: str = "disconnected"
    capabilities: list[Capability] = Field(default_factory=list)
    requires_approval: bool = False


class DriverEntrypoint(StrictModel):
    module: str
    class_name: str = Field(alias="class")


class DriverRobotInfo(StrictModel):
    kind: str
    supports_simulation: bool = True


class DriverManifest(StrictModel):
    schema_: str = Field(default="physical-agent/driver/v1", alias="schema")
    name: str
    version: str
    description: str = ""
    entrypoint: DriverEntrypoint
    robot: DriverRobotInfo
    config_schema: dict[str, Any] = Field(default_factory=lambda: {"type": "object"})
    dependencies: dict[str, Any] = Field(default_factory=dict)
    capability_contract: dict[str, Any] = Field(default_factory=lambda: {"source": "runtime"})

    @property
    def schema(self) -> str:
        return self.schema_


class WorkspaceDocument(StrictModel):
    metadata: dict[str, Any]
    body: str

    @property
    def schema(self) -> str | None:
        value = self.metadata.get("schema")
        return str(value) if value is not None else None

    @property
    def owner(self) -> str | None:
        value = self.metadata.get("owner")
        return str(value) if value is not None else None

    @property
    def revision(self) -> int:
        value = self.metadata.get("revision", 0)
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0


class CodeTaskIntent(StrictModel):
    kind: str
    confidence: float = 0.0
    reason: str = ""
    requested_files: list[str] = Field(default_factory=list)


class CodeTaskResult(StrictModel):
    summary: str
    changed_files: list[str] = Field(default_factory=list)
    tests_run: list[str] = Field(default_factory=list)
    test_output: str = ""
    lessons_written: list[str] = Field(default_factory=list)
    rounds: int = 0
    ok: bool = True
    intent_kind: str = "code_edit"
    run_artifacts: list[str] = Field(default_factory=list)
    integration: dict[str, Any] = Field(default_factory=dict)


class ChatMessage(StrictModel):
    role: Literal["user", "assistant", "system"]
    content: str
    created_at: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChatPlan(StrictModel):
    status: Literal["idle", "thinking", "proposed_actions", "answered", "needs_watch", "error"] = "idle"
    intent: str = ""
    summary: str = ""
    steps: list[str] = Field(default_factory=list)
    actions: list[Action] = Field(default_factory=list)
    needs_watch: bool = False
