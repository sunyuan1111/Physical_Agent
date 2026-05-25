from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class FileEdit:
    path: str
    content: str


class CodePatchError(RuntimeError):
    pass


def apply_file_edits(root: str | Path, edits: Iterable[FileEdit]) -> list[str]:
    root_path = Path(root).resolve()
    changed: list[str] = []
    for edit in edits:
        target = _resolve_within_root(root_path, edit.path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(edit.content.rstrip() + "\n", encoding="utf-8")
        changed.append(str(target.relative_to(root_path).as_posix()))
    return changed


def _resolve_within_root(root: Path, relative: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute():
        raise CodePatchError(f"Refusing to write outside repository root: {relative}")
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise CodePatchError(f"Refusing to write outside repository root: {relative}") from exc
    if ".." in candidate.parts:
        raise CodePatchError(f"Refusing to write outside repository root: {relative}")
    return resolved
