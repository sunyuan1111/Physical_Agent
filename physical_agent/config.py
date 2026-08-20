from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


DEFAULT_CONFIG_NAME = "physical-agent.yaml"
RETIRED_MARKDOWN_BACKEND_GUIDANCE = (
    "Runtime Markdown backend has been retired. This workspace cannot be "
    "opened as an active backend. To convert a legacy Markdown workspace, run "
    "`physical-agent migrate-md-to-sqlite --config physical-agent.yaml`, then "
    "set `workspace.backend: sqlite` in physical-agent.yaml."
)
LEGACY_MARKDOWN_WORKSPACE_FILES = (
    "TASK.md",
    "CAPABILITIES.md",
    "WORLD.md",
    "ACTIONS.md",
    "FEEDBACK.md",
    "SAFETY.md",
    "LOG.md",
    "CHAT.md",
    "PLAN.md",
    "MEMORY.md",
)


class ProjectConfig(BaseModel):
    name: str = "quickstart"


class WorkspaceConfig(BaseModel):
    path: str = "./workspace"
    backend: str = "sqlite"


class WatchConfig(BaseModel):
    tick_ms: int = 500
    observe_interval_ms: int | None = Field(default=None, gt=0)
    require_human_approval: bool = False
    heartbeat_enabled: bool = True
    halt_on_shutdown: bool = True
    heartbeat_failure_threshold: int = Field(default=3, ge=1)
    halt_on_heartbeat_failure: bool = True
    action_timeout_s: float = Field(default=30.0, gt=0)
    observe_timeout_s: float = Field(default=10.0, gt=0)
    heartbeat_timeout_s: float = Field(default=5.0, gt=0)
    halt_timeout_s: float = Field(default=5.0, gt=0)


class AgentConfig(BaseModel):
    planner: str = "rule_based"
    model: str = "fake/local"
    max_steps: int = 8
    feedback_timeout_s: int = 30


class RetrievalConfig(BaseModel):
    enabled: bool = False
    max_chunks: int = 5
    max_chars_per_chunk: int = 2000


class MemoryConfig(BaseModel):
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)


class RobotConfig(BaseModel):
    driver: str
    config: dict[str, Any] = Field(default_factory=dict)


class PhysicalAgentConfig(BaseModel):
    project: ProjectConfig = Field(default_factory=ProjectConfig)
    workspace: WorkspaceConfig = Field(default_factory=WorkspaceConfig)
    watch: WatchConfig = Field(default_factory=WatchConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    robots: dict[str, RobotConfig] = Field(default_factory=dict)

    def workspace_path(self, base_dir: Path) -> Path:
        path = Path(self.workspace.path)
        if not path.is_absolute():
            path = base_dir / path
        return path.resolve()


def default_config_dict() -> dict[str, Any]:
    return {
        "project": {"name": "quickstart"},
        "workspace": {"path": "./workspace", "backend": "sqlite"},
        "watch": {
            "tick_ms": 500,
            "observe_interval_ms": None,
            "require_human_approval": False,
            "heartbeat_enabled": True,
            "halt_on_shutdown": True,
            "heartbeat_failure_threshold": 3,
            "halt_on_heartbeat_failure": True,
            "action_timeout_s": 30.0,
            "observe_timeout_s": 10.0,
            "heartbeat_timeout_s": 5.0,
            "halt_timeout_s": 5.0,
        },
        "agent": {
            "planner": "rule_based",
            "model": "fake/local",
            "max_steps": 8,
            "feedback_timeout_s": 30,
        },
        "memory": {
            "retrieval": {
                "enabled": False,
                "max_chunks": 5,
                "max_chars_per_chunk": 2000,
            }
        },
        "robots": {
            "arm_1": {
                "driver": "mock_arm",
                "config": {
                    "bounds": {
                        "x": [-1.0, 1.0],
                        "y": [-1.0, 1.0],
                        "z": [0.0, 1.0],
                    },
                    "objects": {
                        "red_block": {
                            "type": "block",
                            "color": "red",
                            "location": "table",
                            "pose": {"x": 0.3, "y": 0.1, "z": 0.0},
                        },
                        "tray": {
                            "type": "tray",
                            "location": "table",
                            "pose": {"x": -0.2, "y": 0.2, "z": 0.0},
                        },
                    },
                },
            }
        },
    }


def load_config(
    path: str | Path = DEFAULT_CONFIG_NAME,
    *,
    allow_retired_markdown: bool = False,
) -> PhysicalAgentConfig:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(
            f"Could not find {config_path}. Run `physical-agent init` first."
        )
    with config_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not allow_retired_markdown:
        _reject_retired_markdown_backend(data, config_path)
    return PhysicalAgentConfig.model_validate(data)


def write_default_config(path: str | Path = DEFAULT_CONFIG_NAME, *, overwrite: bool = False) -> Path:
    config_path = Path(path)
    if config_path.exists() and not overwrite:
        return config_path.resolve()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with config_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(default_config_dict(), handle, sort_keys=False)
    return config_path.resolve()


def _reject_retired_markdown_backend(data: Any, config_path: Path) -> None:
    if not isinstance(data, dict):
        return
    workspace_data = data.get("workspace")
    if workspace_data is not None and not isinstance(workspace_data, dict):
        return
    backend = (workspace_data or {}).get("backend")
    if isinstance(backend, str) and backend.strip().lower() == "markdown":
        raise ValueError(RETIRED_MARKDOWN_BACKEND_GUIDANCE)
    if workspace_data is not None and "backend" in workspace_data:
        return

    workspace_path = Path(
        (workspace_data or {}).get("path", WorkspaceConfig().path)
    )
    if not workspace_path.is_absolute():
        workspace_path = config_path.resolve().parent / workspace_path
    workspace_path = workspace_path.resolve()
    if _looks_like_legacy_markdown_workspace(workspace_path):
        raise ValueError(RETIRED_MARKDOWN_BACKEND_GUIDANCE)


def _looks_like_legacy_markdown_workspace(workspace_path: Path) -> bool:
    return workspace_path.exists() and all(
        (workspace_path / filename).exists()
        for filename in LEGACY_MARKDOWN_WORKSPACE_FILES
    )
