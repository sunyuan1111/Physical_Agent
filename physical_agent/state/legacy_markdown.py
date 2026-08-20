from __future__ import annotations

from pathlib import Path
from typing import Any

from physical_agent.protocol.workspace import Workspace


class LegacyMarkdownWorkspaceReader:
    """Read retired Markdown workspaces for one-way SQLite migration only."""

    filenames = Workspace.filenames

    def __init__(self, path: str | Path):
        self.workspace = Workspace(path)

    @property
    def path(self) -> Path:
        return self.workspace.path

    def file(self, name: str) -> Path:
        return self.workspace.file(name)

    def exists(self) -> bool:
        return self.workspace.exists()

    def read_task(self) -> dict[str, Any]:
        return self.workspace.read_task()

    def read_capabilities(self) -> dict[str, Any]:
        return self.workspace.read_capabilities()

    def read_world(self) -> dict[str, Any]:
        return self.workspace.read_world()

    def read_actions(self) -> dict[str, Any]:
        return self.workspace.read_actions()

    def read_feedback(self) -> dict[str, Any]:
        return self.workspace.read_feedback()

    def read_safety(self) -> dict[str, Any]:
        return self.workspace.read_safety()

    def read_chat(self) -> dict[str, Any]:
        return self.workspace.read_chat()

    def read_plan(self) -> dict[str, Any]:
        return self.workspace.read_plan()

    def read_memory(self) -> dict[str, Any]:
        return self.workspace.read_memory()

    def read_uploads(self) -> dict[str, Any]:
        return self.workspace.read_uploads()
