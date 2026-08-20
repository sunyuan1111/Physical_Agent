from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
from typing import Any

from physical_agent.protocol.markdown import parse_front_matter


AUDIT_DOCUMENTS = (
    "task",
    "capabilities",
    "world",
    "actions",
    "feedback",
    "chat",
    "plan",
    "memory",
    "uploads",
    "chunks",
    "log",
)


def export_audit_documents(
    *,
    backend: str,
    workspace_path: Path,
    documents: dict[str, Any],
    safety_source: Path,
    out_dir: Path | None = None,
) -> dict[str, Any]:
    target_dir = (out_dir or workspace_path / "audit").resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    written: dict[str, str] = {}
    for name in AUDIT_DOCUMENTS:
        path = target_dir / f"{name}.json"
        _write_json(path, documents.get(name, {}))
        written[name] = str(path)

    safety_result: dict[str, str] = {"source_path": str(safety_source)}
    if safety_source.exists():
        safety_target = target_dir / "SAFETY.md"
        shutil.copyfile(safety_source, safety_target)
        safety_result["audit_path"] = str(safety_target)

    manifest = {
        "schema": "physical-agent/audit-export/v1",
        "backend": backend,
        "workspace_path": str(workspace_path),
        "documents": {name: f"{name}.json" for name in AUDIT_DOCUMENTS},
        "safety": {
            key: _relative_or_absolute(Path(value), target_dir)
            for key, value in safety_result.items()
        },
    }
    manifest_path = target_dir / "manifest.json"
    _write_json(manifest_path, manifest)

    return {
        "backend": backend,
        "workspace_path": str(workspace_path),
        "out_dir": str(target_dir),
        "documents": written,
        "safety": safety_result,
        "manifest": str(manifest_path),
    }


def read_markdown_log_document(path: Path) -> dict[str, Any]:
    entries, metadata = read_markdown_log_entries(path)
    return {"metadata": metadata, "entries": entries}


def read_markdown_log_entries(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    default_metadata = {
        "schema": "physical-agent/log/v1",
        "owner": "system",
        "revision": 1,
    }
    if not path.exists():
        return [], default_metadata

    text = path.read_text(encoding="utf-8")
    try:
        doc = parse_front_matter(text)
        body = doc.body
        metadata = dict(doc.metadata)
    except Exception:
        body = text
        metadata = default_metadata

    headings = list(re.finditer(r"^##\s+(.+?)\s*$", body, re.MULTILINE))
    entries: list[dict[str, Any]] = []
    for index, match in enumerate(headings):
        start = match.end()
        end = headings[index + 1].start() if index + 1 < len(headings) else len(body)
        message = body[start:end].strip()
        actor = None
        actor_match = re.match(r"^\*\*(.+?)\*\*:\s*(.*)$", message, re.DOTALL)
        if actor_match:
            actor = actor_match.group(1)
            message = actor_match.group(2).strip()
        entries.append(
            {
                key: value
                for key, value in {
                    "sequence": index + 1,
                    "ts": match.group(1).strip(),
                    "actor": actor,
                    "message": message,
                }.items()
                if value is not None
            }
        )
    return entries, metadata


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(_as_audit_plain(value), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def _as_audit_plain(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", exclude_none=True)
    if isinstance(value, list):
        return [_as_audit_plain(item) for item in value]
    if isinstance(value, tuple):
        return [_as_audit_plain(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _as_audit_plain(item) for key, item in value.items()}
    if isinstance(value, Path):
        return str(value)
    return value


def _relative_or_absolute(path: Path, base_dir: Path) -> str:
    try:
        return str(path.resolve().relative_to(base_dir.resolve()))
    except ValueError:
        return str(path)
