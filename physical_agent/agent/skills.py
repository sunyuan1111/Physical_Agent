from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from physical_agent.agent.code_runtime import CodeSkillRuntime
from physical_agent.protocol.schemas import CodeTaskIntent, CodeTaskResult


@dataclass(frozen=True)
class SkillManifest:
    name: str
    title: str
    summary: str
    triggers: tuple[str, ...] = ()
    intent_kinds: tuple[str, ...] = ()
    priority: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "summary": self.summary,
            "triggers": list(self.triggers),
            "intent_kinds": list(self.intent_kinds),
            "priority": self.priority,
        }


@dataclass(frozen=True)
class SkillMatch:
    manifest: SkillManifest
    intent: CodeTaskIntent


class SkillRouter:
    """Lightweight skill registry for repo-local chat abilities.

    The router keeps the current code skill explicit and exposes it as a
    discoverable capability, so the chat runtime can select it before falling
    back to regular conversation.
    """

    def __init__(
        self,
        root: str | Path,
        *,
        env_file: str | Path = ".env",
        model: str | None = None,
        code_runtime: CodeSkillRuntime | None = None,
    ):
        self.root = Path(root).resolve()
        self.env_file = Path(env_file)
        if not self.env_file.is_absolute():
            self.env_file = self.root / self.env_file
        self.model = model
        self._code_runtime = code_runtime
        self._builtins = (
            SkillManifest(
                name="code",
                title="Code Skill",
                summary="Edit repository files, write tests, and run local scripts.",
                triggers=(
                    "modify files",
                    "write tests",
                    "fix this bug",
                    "run script",
                    "execute code",
                ),
                intent_kinds=("code_edit", "code_run"),
                priority=10,
            ),
            SkillManifest(
                name="integration",
                title="Integration Skill",
                summary="Analyze an SDK or hardware repo and draft a driver scaffold.",
                triggers=(
                    "integrate",
                    "onboard",
                    "sdk",
                    "driver",
                    "hardware integration",
                ),
                intent_kinds=("sdk_integration",),
                priority=8,
            ),
        )

    def list_skills(self) -> list[SkillManifest]:
        loaded = self._load_repo_skills()
        merged: dict[str, SkillManifest] = {}
        for manifest in (*loaded, *self._builtins):
            merged[manifest.name] = manifest
        return sorted(merged.values(), key=lambda item: (item.priority, item.name), reverse=True)

    def match(self, message: str) -> SkillMatch | None:
        intent = self._code_runtime_impl().detect(message)
        if intent is None:
            return None
        manifest = self._manifest_for_intent(intent.kind)
        if manifest is None:
            return None
        return SkillMatch(manifest=manifest, intent=intent)

    def run(self, message: str) -> CodeTaskResult | None:
        match = self.match(message)
        if match is None:
            return None
        return self._code_runtime_impl().run(message)

    def _code_runtime_impl(self) -> CodeSkillRuntime:
        if self._code_runtime is None:
            self._code_runtime = CodeSkillRuntime(
                self.root,
                model=self.model,
                env_file=self.env_file,
            )
        return self._code_runtime

    def _manifest_for_intent(self, intent_kind: str) -> SkillManifest | None:
        for manifest in self.list_skills():
            if intent_kind in manifest.intent_kinds:
                return manifest
        return None

    def _load_repo_skills(self) -> list[SkillManifest]:
        skills_dir = self.root / "skills"
        if not skills_dir.exists():
            return []
        manifests: list[SkillManifest] = []
        for skill_md in sorted(skills_dir.glob("*/SKILL.md")):
            try:
                manifests.append(self._parse_skill_file(skill_md))
            except Exception:
                continue
        return manifests

    def _parse_skill_file(self, path: Path) -> SkillManifest:
        text = path.read_text(encoding="utf-8")
        front_matter, body = _split_front_matter(text)
        metadata = yaml.safe_load(front_matter) or {}
        if not isinstance(metadata, dict):
            raise ValueError(f"Skill metadata must be a mapping: {path}")
        name = str(metadata.get("name") or path.parent.name)
        summary = str(metadata.get("description") or "")
        title = str(metadata.get("title") or _heading_from_body(body) or name.replace("-", " ").title())
        triggers = tuple(_normalize_string_list(metadata.get("triggers")))
        intent_kinds = tuple(_normalize_string_list(metadata.get("intents") or metadata.get("intent_kinds")))
        priority = int(metadata.get("priority") or 0)
        return SkillManifest(
            name=name,
            title=title,
            summary=summary or title,
            triggers=triggers,
            intent_kinds=intent_kinds,
            priority=priority,
        )


def _split_front_matter(text: str) -> tuple[str, str]:
    match = re.match(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", text, re.DOTALL)
    if not match:
        raise ValueError("Skill files must begin with YAML front matter.")
    return match.group(1), match.group(2)


def _heading_from_body(body: str) -> str:
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()
    return ""


def _normalize_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            result.append(text)
    return result
