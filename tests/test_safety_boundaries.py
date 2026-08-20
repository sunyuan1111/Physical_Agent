from __future__ import annotations

import ast
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
SCAN_DIRS = [
    ROOT / "physical_agent" / "agent",
    ROOT / "physical_agent" / "llm",
    ROOT / "physical_agent" / "gui",
    ROOT / "physical_agent" / "api",
]

ALLOWLIST_REASONS = {
    (
        "physical_agent/agent/onboarding.py",
        "import",
        "physical_agent.drivers.templates",
    ): "Scaffold generation reuses inert driver file templates and does not load or execute hardware.",
    (
        "physical_agent/agent/driver_coder.py",
        "import",
        "physical_agent.drivers.loader",
    ): "LLM driver-coding validation loads a temporary candidate driver with mock config only.",
    (
        "physical_agent/agent/driver_coder.py",
        "call",
        "loaded.driver.execute",
    ): "Validation executes a mock observe action in a temporary workspace, outside request/planning paths.",
}


def test_agent_llm_gui_do_not_cross_driver_execution_boundary():
    findings = []
    for directory in SCAN_DIRS:
        for path in directory.rglob("*.py"):
            findings.extend(_boundary_findings(path))

    unexpected = [finding for finding in findings if finding not in ALLOWLIST_REASONS]
    assert unexpected == [], _format_boundary_failure(unexpected)

    missing_allowlist = set(ALLOWLIST_REASONS) - set(findings)
    assert missing_allowlist == set(), (
        "Safety boundary allowlist is stale; remove obsolete entries or update the "
        f"reason list: {sorted(missing_allowlist)!r}"
    )


def test_api_server_top_level_import_does_not_load_watch_or_drivers():
    code = """
import json
import sys

import physical_agent.api.server

names = [
    "physical_agent.watch.runtime",
    "physical_agent.drivers.loader",
]
print(json.dumps({name: name in sys.modules for name in names}, sort_keys=True))
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    loaded = json.loads(result.stdout)
    assert loaded == {
        "physical_agent.watch.runtime": False,
        "physical_agent.drivers.loader": False,
    }


def _boundary_findings(path: Path) -> list[tuple[str, str, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    relative = path.relative_to(ROOT).as_posix()
    findings: list[tuple[str, str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_driver_module(alias.name):
                    findings.append((relative, "import", alias.name))
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if _is_driver_module(module):
                findings.append((relative, "import", module))
        elif isinstance(node, ast.Call):
            target = _attribute_path(node.func)
            blocked_calls = {"driver.execute", "driver.heartbeat", "driver.halt"}
            if target in blocked_calls or (
                target
                and any(target.endswith(f".{call}") for call in blocked_calls)
            ):
                findings.append((relative, "call", target))
    return findings


def _is_driver_module(module: str) -> bool:
    return module == "physical_agent.drivers" or module.startswith("physical_agent.drivers.")


def _attribute_path(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _attribute_path(node.value)
        if not prefix:
            return node.attr
        return f"{prefix}.{node.attr}"
    return None


def _format_boundary_failure(findings: list[tuple[str, str, str]]) -> str:
    if not findings:
        return ""
    lines = [
        "Agent/LLM/GUI/API code must not directly import physical_agent.drivers "
        "or call driver execute/heartbeat/halt hooks.",
        "Move execution to watch-side code or add a narrow documented allowlist entry if it is validation-only.",
        "Unexpected findings:",
    ]
    lines.extend(f"- {item[0]} {item[1]} {item[2]}" for item in findings)
    lines.append("Current allowlist reasons:")
    lines.extend(
        f"- {item[0]} {item[1]} {item[2]}: {reason}"
        for item, reason in sorted(ALLOWLIST_REASONS.items())
    )
    return "\n".join(lines)
