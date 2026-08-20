from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from physical_agent.config import DEFAULT_CONFIG_NAME, load_config
from physical_agent.drivers.loader import load_driver
from physical_agent.protocol.markdown import parse_front_matter
from physical_agent.state import open_state_store


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    ok: bool
    message: str

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "ok": self.ok, "message": self.message}


def run_doctor(config_path: str | Path = DEFAULT_CONFIG_NAME) -> list[DoctorCheck]:
    path = Path(config_path).resolve()
    checks: list[DoctorCheck] = []

    checks.append(
        DoctorCheck(
            "python",
            sys.version_info >= (3, 11),
            f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        )
    )

    if not path.exists():
        checks.append(
            DoctorCheck(
                "config",
                False,
                f"Missing {path.name}. Run `physical-agent setup`.",
            )
        )
        return checks

    checks.append(DoctorCheck("config", True, f"Found {path}"))

    try:
        config = load_config(path)
    except Exception as exc:
        checks.append(DoctorCheck("config-parse", False, str(exc)))
        return checks

    workspace = open_state_store(config, base_dir=path.parent)
    checks.append(
        DoctorCheck(
            "workspace",
            workspace.exists(),
            f"Workspace {'ready' if workspace.exists() else 'missing'} at {workspace.path}",
        )
    )

    if workspace.exists():
        for name in workspace.filenames:
            try:
                if name == "log":
                    parse_front_matter(workspace.file(name).read_text(encoding="utf-8"))
                else:
                    getattr(workspace, f"read_{name}")()
                checks.append(DoctorCheck(f"workspace:{name}", True, "Parsed successfully."))
            except Exception as exc:
                checks.append(DoctorCheck(f"workspace:{name}", False, str(exc)))

    for robot_id, robot_config in config.robots.items():
        try:
            load_driver(
                robot_id=robot_id,
                driver_ref=robot_config.driver,
                config=robot_config.config,
                workspace_path=workspace.path,
                artifacts_path=workspace.artifacts_path,
                base_dir=path.parent,
            )
            checks.append(
                DoctorCheck(
                    f"driver:{robot_id}",
                    True,
                    f"Driver `{robot_config.driver}` can be loaded.",
                )
            )
        except Exception as exc:
            checks.append(DoctorCheck(f"driver:{robot_id}", False, str(exc)))

    return checks


def doctor_ok(checks: list[DoctorCheck]) -> bool:
    return all(check.ok for check in checks)
