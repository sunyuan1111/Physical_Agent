from __future__ import annotations

import os
from pathlib import Path
import sqlite3
from typing import Any

from physical_agent.config import PhysicalAgentConfig
from physical_agent.state.factory import open_state_store
from physical_agent.state.sqlite import (
    ACTION_CLAIM_COLUMNS,
    MEMORY_CHUNK_COLUMNS,
    MEMORY_NOTE_COLUMNS,
    SQLITE_SCHEMA_TABLES,
    SqliteStateStore,
    UPLOAD_METADATA_COLUMNS,
)


def run_state_check(
    config: PhysicalAgentConfig,
    *,
    base_dir: str | Path,
) -> dict[str, Any]:
    """Inspect state backend readiness without initializing or mutating state."""

    root = Path(base_dir).resolve()
    backend = (config.workspace.backend or "sqlite").strip().lower()
    workspace = open_state_store(config, base_dir=root)
    initialized = workspace.exists()
    audit_dir = workspace.path / "audit"
    audit_parent = audit_dir if audit_dir.exists() else audit_dir.parent
    result: dict[str, Any] = {
        "backend": backend,
        **_backend_guidance(backend, workspace),
        "workspace_path": str(workspace.path),
        "workspace_initialized": initialized,
        "retrieval_enabled": bool(config.memory.retrieval.enabled),
        "retrieval_max_chunks": config.memory.retrieval.max_chunks,
        "retrieval_max_chars_per_chunk": config.memory.retrieval.max_chars_per_chunk,
        "audit_dir": str(audit_dir),
        "audit_export_writable": _path_writable(audit_parent),
        "sqlite_schema_complete": None,
        "sqlite_missing_tables": [],
        "sqlite_missing_action_columns": [],
        "sqlite_missing_memory_columns": [],
        "sqlite_missing_upload_columns": [],
        "sqlite_missing_chunk_columns": [],
        "sqlite_chunk_schema_complete": None,
    }
    if isinstance(workspace, SqliteStateStore):
        result.update(_sqlite_schema_status(workspace.db_path))
    return result


def state_check_ok(result: dict[str, Any]) -> bool:
    if not result.get("workspace_initialized"):
        return False
    if not result.get("audit_export_writable"):
        return False
    sqlite_complete = result.get("sqlite_schema_complete")
    if sqlite_complete is False:
        return False
    return True


def _sqlite_schema_status(db_path: Path) -> dict[str, Any]:
    if not db_path.exists():
        return {
            "sqlite_schema_complete": False,
            "sqlite_missing_tables": sorted(SQLITE_SCHEMA_TABLES),
            "sqlite_missing_action_columns": sorted(ACTION_CLAIM_COLUMNS),
            "sqlite_missing_memory_columns": sorted(MEMORY_NOTE_COLUMNS),
            "sqlite_missing_upload_columns": sorted(UPLOAD_METADATA_COLUMNS),
            "sqlite_missing_chunk_columns": sorted(MEMORY_CHUNK_COLUMNS),
            "sqlite_chunk_schema_complete": False,
        }
    try:
        with sqlite3.connect(db_path) as conn:
            table_rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            tables = {str(row[0]) for row in table_rows}
            action_columns: set[str] = set()
            if "actions" in tables:
                action_columns = {
                    str(row[1])
                    for row in conn.execute("PRAGMA table_info(actions)").fetchall()
                }
            memory_columns: set[str] = set()
            if "memory_notes" in tables:
                memory_columns = {
                    str(row[1])
                    for row in conn.execute("PRAGMA table_info(memory_notes)").fetchall()
                }
            upload_columns: set[str] = set()
            if "upload_metadata" in tables:
                upload_columns = {
                    str(row[1])
                    for row in conn.execute("PRAGMA table_info(upload_metadata)").fetchall()
                }
            chunk_columns: set[str] = set()
            if "memory_chunks" in tables:
                chunk_columns = {
                    str(row[1])
                    for row in conn.execute("PRAGMA table_info(memory_chunks)").fetchall()
                }
    except sqlite3.Error:
        return {
            "sqlite_schema_complete": False,
            "sqlite_missing_tables": sorted(SQLITE_SCHEMA_TABLES),
            "sqlite_missing_action_columns": sorted(ACTION_CLAIM_COLUMNS),
            "sqlite_missing_memory_columns": sorted(MEMORY_NOTE_COLUMNS),
            "sqlite_missing_upload_columns": sorted(UPLOAD_METADATA_COLUMNS),
            "sqlite_missing_chunk_columns": sorted(MEMORY_CHUNK_COLUMNS),
            "sqlite_chunk_schema_complete": False,
        }

    missing_tables = sorted(SQLITE_SCHEMA_TABLES - tables)
    missing_action_columns = sorted(set(ACTION_CLAIM_COLUMNS) - action_columns)
    missing_memory_columns = sorted(set(MEMORY_NOTE_COLUMNS) - memory_columns)
    missing_upload_columns = sorted(set(UPLOAD_METADATA_COLUMNS) - upload_columns)
    missing_chunk_columns = sorted(set(MEMORY_CHUNK_COLUMNS) - chunk_columns)
    chunk_table_present = "memory_chunks" in tables
    return {
        "sqlite_schema_complete": not missing_tables
        and not missing_action_columns
        and not missing_memory_columns
        and not missing_upload_columns
        and not missing_chunk_columns,
        "sqlite_missing_tables": missing_tables,
        "sqlite_missing_action_columns": missing_action_columns,
        "sqlite_missing_memory_columns": missing_memory_columns,
        "sqlite_missing_upload_columns": missing_upload_columns,
        "sqlite_missing_chunk_columns": missing_chunk_columns,
        "sqlite_chunk_schema_complete": chunk_table_present and not missing_chunk_columns,
    }


def _backend_guidance(backend: str, workspace: Any) -> dict[str, Any]:
    safety_source = str(workspace.file("safety"))
    if backend == "sqlite":
        return {
            "backend_role": "recommended",
            "backend_label": "SQLite recommended backend",
            "source_of_truth": str(workspace.path / "state.db"),
            "payload_format": "JSON payloads inside SQLite tables",
            "human_view": "export-audit creates a read-only audit view",
            "safety_source": safety_source,
            "runtime_switch_supported": False,
            "switching_model": (
                "Change workspace.backend in config and restart the process; "
                "there is no GUI live backend switch."
            ),
            "recommendation": (
                "Use workspace/state.db as the state source of truth; "
                "SAFETY.md remains the file source for safety rules."
            ),
        }
    return {
        "backend_role": "unsupported",
        "backend_label": f"Unsupported backend: {backend}",
        "source_of_truth": "",
        "payload_format": "",
        "human_view": "",
        "safety_source": safety_source,
        "runtime_switch_supported": False,
        "switching_model": "",
        "recommendation": "Use workspace.backend: sqlite.",
    }


def _path_writable(path: Path) -> bool:
    return path.exists() and path.is_dir() and os.access(path, os.W_OK)
