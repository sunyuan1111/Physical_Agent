from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Literal

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.11 always has tomllib
    tomllib = None  # type: ignore[assignment]

from pydantic import Field

from physical_agent.drivers.templates import create_driver_scaffold
from physical_agent.protocol.schemas import Capability, StrictModel


SourceKind = Literal["local_path", "github_repo", "python_package"]


class SourceProfile(StrictModel):
    source: str
    resolved_path: Path
    source_kind: SourceKind
    name: str
    title: str
    description: str
    robot_kind: str
    transport: str
    supports_simulation: bool = True
    capabilities: list[Capability] = Field(default_factory=list)
    config_schema: dict[str, Any] = Field(default_factory=dict)
    evidence: list[str] = Field(default_factory=list)
    files_scanned: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)


class IntegrationResult(StrictModel):
    source: SourceProfile
    output_path: Path
    generated_files: list[str] = Field(default_factory=list)
    report_path: Path | None = None


class HardwareIntegrationAssistant:
    """Analyze a repo or SDK and scaffold a Physical Agent driver around it."""

    def __init__(
        self,
        source: str | Path,
        *,
        output_dir: str | Path | None = None,
        name: str | None = None,
        base_dir: str | Path | None = None,
    ):
        self.source = str(source)
        self.base_dir = Path(base_dir).resolve() if base_dir is not None else Path.cwd().resolve()
        self.output_dir = self._resolve_output_dir(output_dir)
        self.name = name
        self._resolved_source: tuple[Path, SourceKind] | None = None

    def _resolve_output_dir(self, output_dir: str | Path | None) -> Path | None:
        if output_dir is None:
            return None
        path = Path(output_dir).expanduser()
        if not path.is_absolute():
            path = self.base_dir / path
        return path.resolve()

    def analyze(self) -> SourceProfile:
        root, source_kind = self._resolve_source()
        title, description = self._read_project_metadata(root)
        files, combined_text = self._scan_text(root)
        transport = _infer_transport(combined_text, files)
        robot_kind = _infer_robot_kind(combined_text, title, files)
        capabilities = _infer_capabilities(combined_text, robot_kind, transport)
        config_schema = _infer_config_schema(transport, robot_kind)
        evidence = _collect_evidence(combined_text)
        name = self.name or _infer_name(root, title, self.source)
        supports_simulation = True
        next_steps = _next_steps(transport, robot_kind, bool(capabilities), source_kind)
        if not description:
            description = _default_description(title, transport)
        return SourceProfile(
            source=self.source,
            resolved_path=root,
            source_kind=source_kind,
            name=name,
            title=title or name,
            description=description,
            robot_kind=robot_kind,
            transport=transport,
            supports_simulation=supports_simulation,
            capabilities=capabilities,
            config_schema=config_schema,
            evidence=evidence,
            files_scanned=files,
            next_steps=next_steps,
        )

    def generate(self) -> IntegrationResult:
        profile = self.analyze()
        output_path = self.output_dir or _default_output_dir(profile.name, self.base_dir)
        output_path = output_path.resolve()
        readme = _render_readme_en(profile)
        readme_zh = _render_readme_zh(profile)
        scaffold = create_driver_scaffold(
            output_path,
            name=profile.name,
            description=profile.description,
            kind=profile.robot_kind,
            supports_simulation=profile.supports_simulation,
            config_schema=profile.config_schema,
            capabilities=[cap.model_dump(mode="python") for cap in profile.capabilities],
            readme=readme,
            readme_zh=readme_zh,
        )
        report_path = scaffold / "integration-report.md"
        report_path.write_text(_render_report(profile), encoding="utf-8")
        generated_files = [
            str((scaffold / "physical_driver.yaml").resolve()),
            str((scaffold / "driver.py").resolve()),
            str((scaffold / "README.md").resolve()),
            str((scaffold / "README.zh-CN.md").resolve()),
            str(report_path.resolve()),
        ]
        return IntegrationResult(
            source=profile,
            output_path=scaffold,
            generated_files=generated_files,
            report_path=report_path,
        )

    def _resolve_source(self) -> tuple[Path, SourceKind]:
        if self._resolved_source is not None:
            return self._resolved_source

        path = Path(self.source).expanduser()
        if path.exists():
            resolved = path.resolve()
            self._resolved_source = (resolved, "local_path")
            return self._resolved_source
        if not path.is_absolute():
            candidate = (self.base_dir / path).resolve()
            if candidate.exists():
                self._resolved_source = (candidate, "local_path")
                return self._resolved_source

        if _looks_like_github_repo(self.source):
            repo_url = _normalize_github_url(self.source)
            clone_dir = Path(tempfile.mkdtemp(prefix="physical-agent-source-"))
            try:
                subprocess.run(
                    ["git", "clone", "--depth", "1", repo_url, str(clone_dir)],
                    check=True,
                    capture_output=True,
                    text=True,
                )
            except FileNotFoundError as exc:
                raise RuntimeError("git is required to clone GitHub repositories.") from exc
            except subprocess.CalledProcessError as exc:
                raise RuntimeError(
                    f"Could not clone GitHub repository {repo_url}: "
                    f"{_short_text(exc.stderr or exc.stdout or str(exc))}"
                ) from exc
            self._resolved_source = (clone_dir.resolve(), "github_repo")
            return self._resolved_source

        spec = importlib.util.find_spec(self.source)
        if spec is not None:
            location = _package_root_from_spec(spec)
            self._resolved_source = (location, "python_package")
            return self._resolved_source

        raise FileNotFoundError(
            f"Could not resolve {self.source!r} as a local path, GitHub repo, or Python package."
        )

    def _read_project_metadata(self, root: Path) -> tuple[str, str]:
        title = root.name
        description = ""
        readme = _first_existing(root, ["README.md", "README.rst", "README.txt", "README.zh-CN.md"])
        if readme and readme.exists():
            text = _safe_read(readme)
            title = _extract_heading(text) or title
            description = _extract_first_sentence(text)
        pyproject = root / "pyproject.toml"
        if pyproject.exists() and tomllib is not None:
            try:
                data = tomllib.loads(_safe_read(pyproject))
                project = data.get("project", {})
                title = str(project.get("name") or title)
                description = str(project.get("description") or description)
            except Exception:
                pass
        package_json = root / "package.json"
        if package_json.exists():
            try:
                data = json.loads(_safe_read(package_json))
                title = str(data.get("name") or title)
                description = str(data.get("description") or description)
            except Exception:
                pass
        return title, description

    def _scan_text(self, root: Path, *, limit: int = 120) -> tuple[list[str], str]:
        files: list[str] = []
        texts: list[str] = []
        for path in _iter_text_files(root):
            if len(files) >= limit:
                break
            if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".pdf"}:
                continue
            try:
                text = _safe_read(path)
            except Exception:
                continue
            files.append(path.relative_to(root).as_posix())
            texts.append(text)
        return files, "\n\n".join(texts)


def _infer_name(root: Path, title: str, source: str) -> str:
    candidate = title or root.name or source
    cleaned = re.sub(r"[^0-9A-Za-z]+", "_", candidate).strip("_").lower()
    if not cleaned:
        cleaned = "physical_agent_driver"
    if cleaned.endswith("_driver"):
        cleaned = cleaned.removesuffix("_driver")
    return cleaned or "physical_agent_driver"


def _infer_transport(text: str, files: list[str]) -> str:
    lower = text.lower()
    if "model context protocol" in lower or "mcp" in lower:
        return "mcp"
    if any(token in lower for token in ("serial", "uart", "ttyusb", "com3", "/dev/tty")):
        return "serial"
    if any(token in lower for token in ("websocket", " websocket", "ws://", "wss://")):
        return "websocket"
    if any(token in lower for token in ("mqtt", "mosquitto", "topic")):
        return "mqtt"
    if any(token in lower for token in ("grpc",)):
        return "grpc"
    if any(token in lower for token in ("http", "rest", "api", "endpoint", "json-rpc")):
        return "http"
    if any(name.endswith(".py") for name in files):
        return "sdk"
    return "generic"


def _infer_robot_kind(text: str, title: str, files: list[str]) -> str:
    lower = f"{title}\n{text}".lower()
    if any(token in lower for token in ("arm", "manipulator", "gripper")):
        return "arm"
    if any(token in lower for token in ("rover", "mobile", "wheel", "wheeled")):
        return "rover"
    if any(token in lower for token in ("camera", "vision", "image")):
        return "camera"
    if any(token in lower for token in ("speaker", "voice", "audio", "tts")):
        return "audio_device"
    if any(token in lower for token in ("light", "led", "rgb", "lamp")):
        return "light_controller"
    if any("mcp" in file.lower() for file in files):
        return "mcp_device"
    return "generic"


def _infer_capabilities(text: str, robot_kind: str, transport: str) -> list[Capability]:
    lower = text.lower()
    capabilities: list[Capability] = [
        Capability(
            name="observe",
            description="Observe the current device or bridge state.",
            params_schema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        )
    ]
    if any(token in lower for token in ("say", "speak", "tts", "voice", "announce")):
        capabilities.append(
            Capability(
                name="say",
                description="Speak a short sentence through the device or bridge.",
                params_schema={
                    "type": "object",
                    "required": ["text"],
                    "properties": {
                        "text": {"type": "string", "minLength": 1, "maxLength": 120}
                    },
                    "additionalProperties": False,
                },
            )
        )
    if any(token in lower for token in ("light", "led", "rgb", "lamp", "color")):
        capabilities.append(
            Capability(
                name="set_light",
                description="Set the device light or indicator color.",
                params_schema={
                    "type": "object",
                    "required": ["r", "g", "b"],
                    "properties": {
                        "r": {"type": "integer", "minimum": 0, "maximum": 255},
                        "g": {"type": "integer", "minimum": 0, "maximum": 255},
                        "b": {"type": "integer", "minimum": 0, "maximum": 255},
                    },
                    "additionalProperties": False,
                },
            )
        )
    if any(token in lower for token in ("move", "go", "navigate", "drive", "pose", "locomotion")):
        if robot_kind == "rover":
            params_schema = {
                "type": "object",
                "required": ["x", "y"],
                "properties": {
                    "x": {"type": "number"},
                    "y": {"type": "number"},
                },
                "additionalProperties": False,
            }
        else:
            params_schema = {
                "type": "object",
                "required": ["x", "y", "z"],
                "properties": {
                    "x": {"type": "number"},
                    "y": {"type": "number"},
                    "z": {"type": "number"},
                },
                "additionalProperties": False,
            }
        capabilities.append(
            Capability(
                name="move_to",
                description="Move the robot to a target pose or waypoint.",
                params_schema=params_schema,
            )
        )
    if any(token in lower for token in ("pick", "grasp", "grab", "gripper", "clamp")):
        capabilities.append(
            Capability(
                name="pick",
                description="Pick an object by object_id.",
                params_schema={
                    "type": "object",
                    "required": ["object_id"],
                    "properties": {"object_id": {"type": "string"}},
                    "additionalProperties": False,
                },
            )
        )
    if any(token in lower for token in ("place", "drop", "release")):
        capabilities.append(
            Capability(
                name="place",
                description="Place the held object at a named target.",
                params_schema={
                    "type": "object",
                    "required": ["target"],
                    "properties": {"target": {"type": "string"}},
                    "additionalProperties": False,
                },
            )
        )
    if transport == "mcp" and len(capabilities) == 1:
        capabilities.append(
            Capability(
                name="say",
                description="Send a short text command or utterance through the bridge.",
                params_schema={
                    "type": "object",
                    "required": ["text"],
                    "properties": {"text": {"type": "string", "minLength": 1, "maxLength": 120}},
                    "additionalProperties": False,
                },
            )
        )
    return capabilities


def _infer_config_schema(transport: str, robot_kind: str) -> dict[str, Any]:
    if transport in {"serial", "http", "websocket", "mqtt", "grpc", "mcp"}:
        schema: dict[str, Any] = {
            "type": "object",
            "properties": {
                "mode": {"type": "string", "enum": ["mock", "hardware"], "default": "mock"},
                "mock_state": {"type": "object"},
            },
            "required": [],
            "additionalProperties": False,
        }
        if transport == "serial":
            schema["properties"].update(
                {
                    "port": {"type": "string", "description": "Serial port, e.g. COM3 or /dev/ttyUSB0."},
                    "baudrate": {"type": "integer", "default": 115200},
                }
            )
        elif transport in {"http", "mcp", "websocket", "grpc"}:
            schema["properties"].update(
                {
                    "endpoint": {"type": "string", "description": "Service or bridge endpoint."},
                    "token_env": {"type": "string", "default": "OPENAI_API_KEY"},
                    "timeout_s": {"type": "integer", "minimum": 1, "default": 10},
                }
            )
        elif transport == "mqtt":
            schema["properties"].update(
                {
                    "broker_url": {"type": "string"},
                    "topic_prefix": {"type": "string", "default": "physical-agent"},
                    "client_id": {"type": "string"},
                }
            )
        if robot_kind == "arm":
            schema["properties"]["bounds"] = {
                "type": "object",
                "properties": {
                    "x": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2},
                    "y": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2},
                    "z": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2},
                },
                "additionalProperties": False,
            }
        return schema
    return {
        "type": "object",
        "properties": {
            "mode": {"type": "string", "enum": ["mock", "hardware"], "default": "mock"},
            "mock_state": {"type": "object"},
        },
        "additionalProperties": True,
    }


def _collect_evidence(text: str) -> list[str]:
    evidence: list[str] = []
    for label, pattern in [
        ("MCP bridge", r"\bmcp\b"),
        ("serial transport", r"\b(serial|uart|ttyusb|com\d+)\b"),
        ("HTTP API", r"\b(http|rest|endpoint|json-rpc)\b"),
        ("voice features", r"\b(say|speak|tts|voice)\b"),
        ("light control", r"\b(light|led|rgb|lamp)\b"),
        ("movement", r"\b(move|go|navigate|drive)\b"),
        ("manipulation", r"\b(pick|grasp|grab|place|drop)\b"),
    ]:
        if re.search(pattern, text, re.IGNORECASE):
            evidence.append(label)
    return evidence


def _next_steps(transport: str, robot_kind: str, has_capabilities: bool, source_kind: SourceKind) -> list[str]:
    steps = [
        "Keep the driver logic on the watch side.",
        "Move hardware SDK calls into driver.py.",
        "Run mock mode first, then switch to the real bridge or device.",
        "Add a focused pytest for each capability you keep.",
    ]
    if transport == "serial":
        steps.insert(1, "Wire the serial port, baudrate, and any bounds into physical_driver.yaml.")
    elif transport in {"http", "mcp", "websocket", "grpc"}:
        steps.insert(1, "Wire the endpoint, token, and timeout settings into physical_driver.yaml.")
    if robot_kind == "arm":
        steps.append("Keep pick and place actions dependent on the gripper state.")
    if not has_capabilities:
        steps.append("Add the device-specific capabilities once you know the SDK surface.")
    if source_kind == "github_repo":
        steps.append("If the repo already has an integration script, copy the transport logic, not the README wording.")
    return steps


def _render_readme_en(profile: SourceProfile) -> str:
    capabilities = ", ".join(cap.name for cap in profile.capabilities)
    capability_list = "\n".join(f"- `{cap.name}`" for cap in profile.capabilities)
    config_example = _render_config_example(profile)
    return (
        f"# {profile.title} Physical Agent Driver\n\n"
        f"This scaffold was generated by Physical Agent from `{profile.source}`.\n\n"
        "## What Physical Agent Detected\n\n"
        f"- Source kind: `{profile.source_kind}`\n"
        f"- Robot kind: `{profile.robot_kind}`\n"
        f"- Transport: `{profile.transport}`\n"
        f"- Simulation-friendly: `{str(profile.supports_simulation).lower()}`\n"
        f"- Capabilities: {capabilities or 'none yet'}\n\n"
        "## Driver Contract\n\n"
        "Two files are enough to connect a device to Physical Agent:\n\n"
        "```text\n"
        "physical_driver.yaml\n"
        "driver.py\n"
        "```\n\n"
        "The manifest declares the adapter and validates configuration.\n"
        "The driver implements `PhysicalDriver` and stays on the watch side.\n\n"
        "## Capabilities in This Scaffold\n\n"
        f"{capability_list or '- `observe`'}\n\n"
        "## Suggested Config\n\n"
        f"```yaml\n{config_example}\n```\n\n"
        "## How to Finish the Integration\n\n"
        + "\n".join(f"{index}. {step}" for index, step in enumerate(profile.next_steps, start=1))
        + "\n\n"
        "## Suggested Run Order\n\n"
        "```bash\n"
        "physical-agent watch --config physical-agent.yaml\n"
        "physical-agent run --task \"look around\"\n"
        "physical-agent run --task \"pick the red block and place it on the tray\"\n"
        "```\n"
    )


def _render_readme_zh(profile: SourceProfile) -> str:
    capabilities = "、".join(f"`{cap.name}`" for cap in profile.capabilities)
    config_example = _render_config_example(profile)
    next_steps = _next_steps_zh(profile)
    return (
        f"# {profile.title} Physical Agent 驱动接入说明\n\n"
        f"这个脚手架由 Physical Agent 根据 `{profile.source}` 自动生成。\n\n"
        "## 识别结果\n\n"
        f"- 源类型：`{profile.source_kind}`\n"
        f"- 设备类型：`{profile.robot_kind}`\n"
        f"- 通信方式：`{profile.transport}`\n"
        f"- 支持模拟：`{str(profile.supports_simulation).lower()}`\n"
        f"- 能力：{capabilities or '`observe`'}\n\n"
        "## 驱动协议\n\n"
        "接入一个硬件，只需要两个核心文件：\n\n"
        "```text\n"
        "physical_driver.yaml\n"
        "driver.py\n"
        "```\n\n"
        "`physical_driver.yaml` 负责声明适配器与配置校验。\n"
        "`driver.py` 负责实现 `PhysicalDriver`，并只在 watch 侧运行。\n\n"
        "## 本脚手架包含的能力\n\n"
        + "\n".join(f"- `{cap.name}`" for cap in profile.capabilities)
        + "\n\n"
        "## 建议配置\n\n"
        f"```yaml\n{config_example}\n```\n\n"
        "## 收尾步骤\n\n"
        + "\n".join(f"{index}. {step}" for index, step in enumerate(next_steps, start=1))
        + "\n\n"
        "## 推荐执行顺序\n\n"
        "```bash\n"
        "physical-agent watch --config physical-agent.yaml\n"
        "physical-agent run --task \"look around\"\n"
        "physical-agent run --task \"pick the red block and place it on the tray\"\n"
        "```\n"
    )


def _render_report(profile: SourceProfile) -> str:
    evidence = "\n".join(f"- {item}" for item in profile.evidence) or "- none"
    files = "\n".join(f"- {item}" for item in profile.files_scanned[:20]) or "- none"
    capabilities = "\n".join(
        f"- {cap.name}: {cap.description}" for cap in profile.capabilities
    )
    return (
        "# Integration Report\n\n"
        f"Source: `{profile.source}`\n\n"
        "## Evidence\n\n"
        f"{evidence}\n\n"
        "## Scanned Files\n\n"
        f"{files}\n\n"
        "## Capabilities\n\n"
        f"{capabilities or '- observe'}\n\n"
        "## Next Steps\n\n"
        + "\n".join(f"- {step}" for step in profile.next_steps)
        + "\n"
    )


def _render_config_example(profile: SourceProfile) -> str:
    if profile.transport == "serial":
        return (
            "robots:\n"
            f"  {profile.name}_1:\n"
            f"    driver: ./{profile.name}\n"
            "    config:\n"
            "      mode: mock\n"
            "      port: COM3\n"
            "      baudrate: 115200\n"
            "      bounds:\n"
            "        x: [-1.0, 1.0]\n"
            "        y: [-1.0, 1.0]\n"
            "        z: [0.0, 1.0]\n"
        )
    if profile.transport in {"http", "mcp", "websocket", "grpc"}:
        return (
            "robots:\n"
            f"  {profile.name}_1:\n"
            f"    driver: ./{profile.name}\n"
            "    config:\n"
            "      mode: mock\n"
            "      endpoint: http://localhost:8000\n"
            "      timeout_s: 10\n"
        )
    return (
        "robots:\n"
        f"  {profile.name}_1:\n"
        f"    driver: ./{profile.name}\n"
        "    config:\n"
        "      mode: mock\n"
        "      mock_state: {}\n"
    )


def _default_description(title: str, transport: str) -> str:
    return f"{title} driver scaffold generated by Physical Agent using {transport} signals."


def _next_steps_zh(profile: SourceProfile) -> list[str]:
    steps = ["保持硬件 SDK 调用只在 watch 侧 driver 中运行。"]
    if profile.transport == "serial":
        steps.append("把串口、波特率和运动边界写进 `physical-agent.yaml` 的 robot config。")
    elif profile.transport in {"http", "mcp", "websocket", "grpc"}:
        steps.append("把 endpoint、token 环境变量和 timeout 写进 `physical-agent.yaml` 的 robot config。")
    elif profile.transport == "mqtt":
        steps.append("把 broker、topic 前缀和 client id 写进 `physical-agent.yaml` 的 robot config。")
    steps.extend(
        [
            "先保留 `mode: mock` 跑通 observe 和每个能力的测试。",
            "再把 `driver.py` 中 TODO 分支替换成真实 SDK 或服务调用。",
            "为每个保留的 capability 增加一个聚焦 pytest。",
        ]
    )
    if profile.robot_kind == "arm":
        steps.append("让 pick/place 明确依赖夹爪或 holding 状态，避免空放或重复抓取。")
    if profile.source_kind == "github_repo":
        steps.append("如果仓库里已有示例脚本，只借鉴通信方式，不复制 README 表述或第三方实现。")
    return steps


def _default_output_dir(name: str, base_dir: Path) -> Path:
    return base_dir / "physical-agent-integration" / name


def _iter_text_files(root: Path):
    ignored = {".git", ".venv", "node_modules", "__pycache__", "dist", "build"}
    for path in root.rglob("*"):
        if any(part in ignored for part in path.parts):
            continue
        if path.is_file():
            yield path


def _safe_read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def _first_existing(root: Path, names: list[str]) -> Path | None:
    for name in names:
        path = root / name
        if path.exists():
            return path
    return None


def _extract_heading(text: str) -> str:
    match = re.search(r"^#\s+(.+)$", text, flags=re.MULTILINE)
    return match.group(1).strip() if match else ""


def _extract_first_sentence(text: str) -> str:
    text = " ".join(line.strip() for line in text.splitlines() if line.strip())
    if not text:
        return ""
    text = re.sub(r"^#+\s*", "", text)
    match = re.search(r"(.+?[.!?。！？])\s", text)
    if match:
        return match.group(1).strip()
    if len(text) > 180:
        return text[:177].rstrip() + "..."
    return text


def _looks_like_github_repo(source: str) -> bool:
    return "github.com/" in source or source.startswith("git@github.com:")


def _normalize_github_url(source: str) -> str:
    if source.startswith("git@github.com:"):
        return source
    if source.startswith("http://") or source.startswith("https://"):
        return source
    if source.startswith("github.com/"):
        return "https://" + source
    return f"https://{source}"


def _package_root_from_spec(spec: importlib.machinery.ModuleSpec) -> Path:
    if spec.submodule_search_locations:
        return Path(list(spec.submodule_search_locations)[0]).resolve()
    if spec.origin:
        return Path(spec.origin).resolve().parent
    raise FileNotFoundError("Could not resolve package location.")


def _short_text(text: str, *, limit: int = 300) -> str:
    compact = " ".join(text.split())
    if len(compact) > limit:
        return compact[: limit - 3] + "..."
    return compact
