from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from physical_agent.protocol.schemas import CodeTaskIntent


CODE_INTENT_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "code_run",
        (
            "执行代码",
            "执行脚本",
            "运行代码",
            "运行脚本",
            "跑一下代码",
            "跑一下脚本",
            "执行画圈",
            "运行画圈",
            "run code",
            "run script",
            "execute code",
            "execute script",
        ),
    ),
    (
        "code_edit",
        (
            "改代码",
            "改文件",
            "修改代码",
            "修改文件",
            "修改这个文件",
            "写测试",
            "补测试",
            "修 bug",
            "修复 bug",
            "修bug",
            "修复代码",
            "修复文件",
            "重构",
            "调整代码",
            "改一下",
            "refactor",
            "fix this bug",
            "fix bug",
            "edit the code",
            "modify files",
            "write tests",
            "add tests",
            "implement",
            "patch",
            "代码",
        ),
    ),
    (
        "sdk_integration",
        (
            "sdk",
            "接 sdk",
            "接入 sdk",
            "接入这个 sdk",
            "接入该 sdk",
            "接入硬件",
            "接入驱动",
            "接硬件",
            "sdk 接入",
            "driver",
            "integrate sdk",
            "integrate this sdk",
            "wire up sdk",
            "hardware integration",
        ),
    ),
)


CODE_TASK_HINTS: tuple[str, ...] = (
    "file",
    "files",
    "code",
    "sdk",
    "repo",
    "repository",
    "project",
    "test",
    "tests",
    "bug",
    "bugfix",
    "refactor",
    "implementation",
)


@dataclass(frozen=True)
class CodeIntentRouter:
    root: Path

    def route(self, message: str) -> CodeTaskIntent | None:
        text = message.lower().strip()
        if not text:
            return None

        if _looks_like_physical_task(text):
            return None

        matches: list[str] = []
        if _looks_like_code_execution(text):
            matches.append("code_run")
        for kind, phrases in CODE_INTENT_PATTERNS:
            if kind in matches:
                continue
            if any(phrase in text for phrase in phrases):
                matches.append(kind)

        if not matches and not _has_code_task_signal(text):
            return None

        if not matches and _looks_like_sdk_integration(text):
            matches.append("sdk_integration")

        requested_files = _extract_file_like_targets(message, self.root)
        return CodeTaskIntent(
            kind=matches[0] if matches else "code_edit",
            confidence=0.9 if matches else 0.6,
            reason="Matched code-editing or SDK-integration language.",
            requested_files=requested_files,
        )


def _has_code_task_signal(text: str) -> bool:
    if any(hint in text for hint in CODE_TASK_HINTS):
        return True
    if any(token in text for token in ("修改", "修复", "补测", "补测试", "写个测试", "改一下")):
        return True
    return bool(re.search(r"\b(fix|patch|refactor|rewrite|implement|modify|edit|test)\b", text))


def _looks_like_code_execution(text: str) -> bool:
    run_verbs = ("执行", "运行", "跑一下", "跑下", "run", "execute")
    code_targets = ("代码", "脚本", ".py", "script", "draw_circle", "circle", "画圈", "画圆")
    return any(verb in text for verb in run_verbs) and any(target in text for target in code_targets)


def _looks_like_physical_task(text: str) -> bool:
    physical_hints = (
        "pick the red block",
        "place it on the tray",
        "look around",
        "observe the world",
        "move to",
        "go to",
        "watch the robot",
        "请移动",
        "放到托盘",
        "看一下",
        "观察",
    )
    return any(hint in text for hint in physical_hints)


def _looks_like_sdk_integration(text: str) -> bool:
    sdk_hints = ("sdk", "driver", "integrate", "connect", "onboard", "接入", "接", "硬件", "适配")
    if "sdk" not in text:
        return False
    return any(hint in text for hint in sdk_hints if hint != "sdk")


def _extract_file_like_targets(message: str, root: Path) -> list[str]:
    candidates: list[str] = []
    pattern = r"""(?:[A-Za-z]:[\\/]|\.{1,2}[\\/]|/)[^\s`'"]+"""
    for match in re.finditer(pattern, message):
        path = match.group(0).rstrip(".,)")
        if path:
            candidates.append(path)
    for match in re.finditer(r"`([^`]+)`", message):
        candidate = match.group(1).strip()
        if "/" in candidate or "\\" in candidate or "." in candidate:
            candidates.append(candidate)
    resolved: list[str] = []
    for item in candidates:
        try:
            path = Path(item)
            if not path.is_absolute():
                path = (root / path).resolve()
            if _is_within_root(root, path):
                resolved.append(str(path.relative_to(root).as_posix()))
        except Exception:
            continue
    return _dedupe(resolved)


def _is_within_root(root: Path, path: Path) -> bool:
    try:
        path.relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result
