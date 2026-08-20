from __future__ import annotations

from pathlib import Path

from physical_agent.config import (
    DEFAULT_CONFIG_NAME,
    RETIRED_MARKDOWN_BACKEND_GUIDANCE,
    PhysicalAgentConfig,
    load_config,
)
from physical_agent.state.base import StateStore
from physical_agent.state.sqlite import SqliteStateStore


def open_state_store(
    config_or_path: PhysicalAgentConfig | str | Path | None = None,
    *,
    config_path: str | Path | None = None,
    base_dir: str | Path | None = None,
) -> StateStore:
    if config_or_path is not None and config_path is not None:
        raise ValueError("Pass either config_or_path or config_path, not both.")

    if isinstance(config_or_path, PhysicalAgentConfig):
        config = config_or_path
        root = Path(base_dir).resolve() if base_dir is not None else Path.cwd().resolve()
    else:
        path_value = config_path if config_path is not None else config_or_path
        config_file = Path(path_value or DEFAULT_CONFIG_NAME).resolve()
        config = load_config(config_file)
        root = Path(base_dir).resolve() if base_dir is not None else config_file.parent

    backend = (config.workspace.backend or "sqlite").strip().lower()
    if backend == "markdown":
        raise ValueError(RETIRED_MARKDOWN_BACKEND_GUIDANCE)
    if backend == "sqlite":
        return SqliteStateStore(config.workspace_path(root))
    raise ValueError(
        f"Unsupported workspace backend `{config.workspace.backend}`. "
        "Supported backend: sqlite."
    )
