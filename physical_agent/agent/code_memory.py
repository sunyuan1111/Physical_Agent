from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path


class CodeLessonsStore:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.path = self.root / ".physical-agent" / "code" / "LESSONS.md"

    def read(self) -> str:
        if not self.path.exists():
            return ""
        return self.path.read_text(encoding="utf-8")

    def append(self, lesson: str) -> str:
        lesson = lesson.strip()
        if not lesson:
            return ""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        existing = self.read().rstrip()
        if existing:
            existing += "\n\n"
        body = f"{existing}## {timestamp}\n\n{lesson}\n"
        self.path.write_text(body, encoding="utf-8")
        return lesson
