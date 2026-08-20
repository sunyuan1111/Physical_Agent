from __future__ import annotations

from typing import Any


def normalize_memory_note(
    value: Any,
    *,
    kind: str = "note",
    source: str = "chat",
    tags: list[str] | str | None = None,
    importance: int = 0,
    created_at: str | None = None,
) -> dict[str, Any]:
    raw = dict(value) if isinstance(value, dict) else {"content": value}
    timestamp = raw.get("created_at", created_at)
    return {
        "content": "" if raw.get("content") is None else str(raw.get("content")),
        "kind": _clean_text(raw.get("kind"), default=kind),
        "source": _clean_text(raw.get("source"), default=source),
        "tags": normalize_memory_tags(raw.get("tags", tags)),
        "importance": _normalize_importance(raw.get("importance", importance)),
        "created_at": None if timestamp is None else str(timestamp),
    }


def normalize_memory_notes(notes: Any) -> list[dict[str, Any]]:
    if notes is None:
        return []
    if not isinstance(notes, list):
        notes = [notes]
    return [normalize_memory_note(note) for note in notes]


def filter_memory_notes(
    notes: Any,
    *,
    kind: str | None = None,
    source: str | None = None,
    limit: int | None = None,
    tags: list[str] | str | None = None,
) -> list[dict[str, Any]]:
    normalized = normalize_memory_notes(notes)
    wanted_kind = _optional_clean_text(kind)
    wanted_source = _optional_clean_text(source)
    wanted_tags = set(normalize_memory_tags(tags))

    if wanted_kind is not None:
        normalized = [note for note in normalized if note["kind"] == wanted_kind]
    if wanted_source is not None:
        normalized = [note for note in normalized if note["source"] == wanted_source]
    if wanted_tags:
        normalized = [
            note for note in normalized if wanted_tags.issubset(set(note["tags"]))
        ]

    if limit is None:
        return normalized
    count = _normalize_limit(limit)
    if count == 0:
        return []
    return normalized[-count:]


def normalize_memory_tags(value: list[str] | str | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        values: list[Any] = [value]
    elif isinstance(value, (list, tuple, set)):
        values = list(value)
    else:
        values = [value]

    tags: list[str] = []
    seen: set[str] = set()
    for item in values:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        tags.append(text)
    return tags


def _clean_text(value: Any, *, default: str) -> str:
    text = "" if value is None else str(value).strip()
    return text or default


def _optional_clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_importance(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _normalize_limit(value: int) -> int:
    try:
        count = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("memory limit must be an integer") from exc
    if count < 0:
        raise ValueError("memory limit must be non-negative")
    return count
