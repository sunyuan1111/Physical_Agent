from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Protocol

from physical_agent.agent.driver_coder import DriverCodingAgent
from physical_agent.agent.onboarding import HardwareIntegrationAssistant
from physical_agent.agent.code_memory import CodeLessonsStore
from physical_agent.agent.code_patch import CodePatchError, FileEdit, apply_file_edits
from physical_agent.agent.code_router import CodeIntentRouter
from physical_agent.llm import OpenAICompatibleClient, OpenAICompatibleSettings
from physical_agent.protocol.schemas import CodeTaskResult


class CodeModelClient(Protocol):
    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> str:
        ...


class CodeSkillRuntime:
    def __init__(
        self,
        root: str | Path,
        *,
        settings: OpenAICompatibleSettings | None = None,
        client: CodeModelClient | None = None,
        env_file: str | Path = ".env",
        model: str | None = None,
        max_rounds: int = 2,
        tests: list[str] | None = None,
    ):
        self.root = Path(root).resolve()
        self.router = CodeIntentRouter(self.root)
        self.settings = settings
        self.client = client
        self.env_file = Path(env_file)
        if not self.env_file.is_absolute():
            self.env_file = self.root / self.env_file
        self.model = model
        self.max_rounds = max(1, max_rounds)
        self.tests = tests or ["pytest", "-q"]
        self.lessons = CodeLessonsStore(self.root)

    def run(self, message: str) -> CodeTaskResult:
        context = self._gather_context(message)
        if context is None:
            return CodeTaskResult(
                summary="No code task detected.",
                changed_files=[],
                tests_run=[],
                test_output="",
                lessons_written=[],
                rounds=0,
                ok=False,
                intent_kind="none",
            )

        intent = context["intent"]
        if intent.get("kind") == "sdk_integration":
            return self._run_integration_skill(message, intent=intent)
        if intent.get("kind") == "code_run":
            return self._run_code_execution(message, context=context, intent=intent)

        changed_files: list[str] = []
        test_output = ""
        tests_run: list[str] = []
        lessons_written: list[str] = []
        last_error = ""
        succeeded = False
        rounds = 0
        plan: dict[str, Any] = {"summary": ""}

        for round_index in range(1, self.max_rounds + 1):
            rounds = round_index
            plan = self._request_patch(context=context, previous_error=last_error)
            edits = [FileEdit(path=item["path"], content=item["content"]) for item in plan.get("files", [])]
            try:
                changed_files = apply_file_edits(self.root, edits)
            except CodePatchError as exc:
                last_error = str(exc)
                lessons_written.append(self.lessons.append(f"Patch rejected: {exc}"))
                continue

            tests_run = [str(item) for item in plan.get("tests", []) if str(item).strip()]
            test_output = self._run_tests(tests_run or self.tests)
            if _tests_passed(test_output):
                lesson = self.lessons.append(
                    f"Code task succeeded in {rounds} round(s). Changed files: {', '.join(changed_files) or 'none'}."
                )
                lessons_written.append(lesson)
                succeeded = True
                break
            last_error = test_output
            lessons_written.append(
                self.lessons.append(
                    "Tests failed after code edit. Feed the failure text back into the next round."
                )
            )

        summary = str(plan.get("summary") or "")
        if not summary:
            summary = "Updated the repository." if succeeded else "Code task did not converge."
        return CodeTaskResult(
            summary=summary,
            changed_files=changed_files,
            tests_run=tests_run,
            test_output=test_output,
            lessons_written=lessons_written,
            rounds=rounds,
            ok=succeeded,
            intent_kind=intent.get("kind", "code_edit"),
        )

    def detect(self, message: str):
        return self.router.route(message)

    def _gather_context(self, message: str) -> dict[str, Any] | None:
        intent = self.router.route(message)
        if intent is None:
            return None
        files = _scan_repo_files(self.root)
        lessons = self.lessons.read()
        git_status = _git_status(self.root)
        return {
            "intent": intent.model_dump(mode="json"),
            "message": message,
            "files": files,
            "git_status": git_status,
            "lessons": lessons,
        }

    def _run_integration_skill(self, message: str, *, intent: dict[str, Any]) -> CodeTaskResult:
        source = _extract_integration_source(message)
        if not source:
            lesson = self.lessons.append(
                "Integration request lacked a source. Ask for a local path, GitHub URL, or package name."
            )
            return CodeTaskResult(
                summary="Please provide a local SDK path, a GitHub repo URL, or a Python package name.",
                changed_files=[],
                tests_run=[],
                test_output="",
                lessons_written=[lesson],
                rounds=0,
                ok=False,
                intent_kind="sdk_integration",
            )

        use_llm = any(
            marker in message.lower()
            for marker in (
                "--llm",
                "llm",
                "write the driver",
                "implement the driver",
                "real sdk",
                "complete driver",
            )
        )
        if use_llm:
            result = DriverCodingAgent(
                source,
                base_dir=self.root,
                model=self.model,
                env_file=self.env_file,
            ).generate()
            validation = result.validation
        else:
            result = HardwareIntegrationAssistant(
                source,
                base_dir=self.root,
            ).generate()
            validation = {"ok": True, "errors": [], "checks": ["scaffold generated"]}

        changed_files = [
            str(Path(path).resolve().relative_to(self.root))
            for path in result.generated_files
            if Path(path).exists() and _is_within(self.root, Path(path).resolve())
        ]
        if not changed_files:
            changed_files = [
                str((result.output_path / name).resolve().relative_to(self.root))
                for name in ("physical_driver.yaml", "driver.py", "README.md", "README.zh-CN.md")
                if (result.output_path / name).exists()
            ]
        tests_run = ["mock validation"]
        if use_llm:
            tests_run.append("LLM driver coding validation")
        lessons_written = [
            self.lessons.append(
                f"Generated driver scaffold for {source} at {result.output_path}."
            )
        ]
        summary = (
            f"Generated a driver scaffold for {source}."
            if not use_llm
            else f"Generated an LLM-assisted driver draft for {source}."
        )
        return CodeTaskResult(
            summary=summary,
            changed_files=changed_files,
            tests_run=tests_run,
            test_output=str(validation),
            lessons_written=lessons_written,
            rounds=getattr(result, "attempts", 1) or 1,
            ok=bool(validation.get("ok", True)),
            intent_kind="sdk_integration",
            integration={
                "source": source,
                "output_path": str(result.output_path),
                "generated_files": result.generated_files,
                "validation": validation,
                "llm_used": bool(getattr(result, "llm_used", False)),
                "llm_error": getattr(result, "llm_error", None),
                "summary": getattr(result, "summary", summary),
                "next_steps": list(getattr(result, "next_steps", []) or []),
                "attempts": int(getattr(result, "attempts", 1) or 1),
            },
        )

    def _run_code_execution(self, message: str, *, context: dict[str, Any], intent: dict[str, Any]) -> CodeTaskResult:
        target = _resolve_execution_target(self.root, message, intent.get("requested_files") or [], context.get("files", []))
        if target is None:
            lesson = self.lessons.append(
                "Execution request did not identify a runnable script. Ask for a file path or a known script name."
            )
            return CodeTaskResult(
                summary="I could not find a runnable script in this repository. Tell me which file to execute.",
                changed_files=[],
                tests_run=[],
                test_output="",
                lessons_written=[lesson],
                rounds=0,
                ok=False,
                intent_kind="code_run",
                run_artifacts=[],
            )

        artifact_dir = self._execution_artifact_dir(target)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = _default_execution_artifact_path(target, artifact_dir, message)
        env = dict(os.environ)
        existing_pythonpath = env.get("PYTHONPATH", "")
        root_path = str(self.root)
        env["PYTHONPATH"] = (
            root_path if not existing_pythonpath else root_path + os.pathsep + existing_pythonpath
        )
        if artifact_path is not None:
            env["OUTPUT_PATH"] = str(artifact_path)
            env["PHYSICAL_AGENT_OUTPUT_PATH"] = str(artifact_path)

        command = [sys.executable, str(target)]
        try:
            completed = subprocess.run(
                command,
                cwd=self.root,
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )
        except FileNotFoundError as exc:
            lesson = self.lessons.append(f"Execution failed: {exc}")
            return CodeTaskResult(
                summary=f"Could not execute {target.relative_to(self.root).as_posix()}: {exc}",
                changed_files=[],
                tests_run=[" ".join(command)],
                test_output=f"{exc}\n__exitcode__:127",
                lessons_written=[lesson],
                rounds=0,
                ok=False,
                intent_kind="code_run",
                run_artifacts=[],
            )

        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        test_output = stdout
        if stdout and stderr:
            test_output += "\n"
        test_output += stderr
        test_output += f"\n__exitcode__:{completed.returncode}"

        artifacts = _collect_execution_artifacts(artifact_dir)
        if artifact_path is not None and artifact_path.exists() and str(artifact_path) not in artifacts:
            artifacts.append(str(artifact_path.relative_to(self.root).as_posix()))

        summary = (
            f"I ran {target.relative_to(self.root).as_posix()} with {command[0]} and it completed successfully."
            if completed.returncode == 0
            else (
                f"I tried running {target.relative_to(self.root).as_posix()} with {command[0]}, "
                f"but it exited with code {completed.returncode}. "
                f"The most relevant signal was: {_summarize_console_output(stdout, stderr)}"
            )
        )
        if artifacts and completed.returncode == 0:
            summary = (
                f"I ran {target.relative_to(self.root).as_posix()} with {command[0]} and it completed successfully. "
                f"It produced: {', '.join(artifacts)}."
            )

        lesson = self.lessons.append(
            f"Executed {target.relative_to(self.root).as_posix()} with exit code {completed.returncode}."
        )
        return CodeTaskResult(
            summary=summary,
            changed_files=[],
            tests_run=[" ".join(command)],
            test_output=test_output,
            lessons_written=[lesson],
            rounds=1,
            ok=completed.returncode == 0,
            intent_kind="code_run",
            run_artifacts=artifacts,
        )

    def _request_patch(self, *, context: dict[str, Any], previous_error: str) -> dict[str, Any]:
        client = self._client()
        content = client.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "You are the code skill for Physical Agent. "
                        "You may edit files only within the current repository root. "
                        "Return only JSON with shape {\"summary\":\"...\",\"files\":[{\"path\":\"relative/path.py\",\"content\":\"...\"}],\"tests\":[\"pytest -q\"]}. "
                        "Prefer minimal, targeted edits. Do not output Markdown. "
                        "If previous tests failed, use the failure text to repair the repository."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            **context,
                            "previous_error": previous_error,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            temperature=0.1,
            max_tokens=4000,
        )
        return _extract_json(content)

    def _client(self) -> CodeModelClient:
        if self.client is not None:
            return self.client
        settings = self.settings or OpenAICompatibleSettings.from_env(
            env_file=self.env_file,
            model=self.model,
        )
        self.client = OpenAICompatibleClient(settings)
        return self.client

    def _execution_artifact_dir(self, target: Path) -> Path:
        base = self.root / ".physical-agent" / "code" / "artifacts"
        base.mkdir(parents=True, exist_ok=True)
        target_name = target.relative_to(self.root).as_posix()
        slug = re.sub(r"[^A-Za-z0-9._-]+", "_", target_name).strip("._-") or "script"
        prefix = f"{slug}-"
        return Path(tempfile.mkdtemp(prefix=prefix, dir=str(base)))

    def _run_tests(self, tests: list[str]) -> str:
        command_parts = _normalize_test_command(tests or self.tests)
        if not command_parts:
            return "No test command configured.\n__exitcode__:0"
        try:
            env = dict(os.environ)
            existing_pythonpath = env.get("PYTHONPATH", "")
            root_path = str(self.root)
            env["PYTHONPATH"] = (
                root_path
                if not existing_pythonpath
                else root_path + os.pathsep + existing_pythonpath
            )
            executable = command_parts[0]
            args = command_parts[1:]
            if Path(executable).name.lower() in {"pytest", "pytest.exe"}:
                command_parts = [sys.executable, "-m", "pytest", *(args or ["-q"])]
            completed = subprocess.run(
                command_parts,
                cwd=self.root,
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )
        except FileNotFoundError as exc:
            return f"Test command not found: {command_parts[0]}\n{exc}\n__exitcode__:127"
        output = (completed.stdout or "") + ("\n" if completed.stdout and completed.stderr else "") + (completed.stderr or "")
        return f"{output}\n__exitcode__:{completed.returncode}"


def _extract_json(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        for start in _json_candidate_starts(stripped):
            try:
                value, _ = decoder.raw_decode(stripped[start:])
                break
            except json.JSONDecodeError:
                continue
        else:
            match = re.search(r"\{.*\}", stripped, re.DOTALL)
            if not match:
                raise
            value = json.loads(match.group(0))
    if not isinstance(value, dict):
        raise ValueError("Code skill response must be a JSON object.")
    return value


def _scan_repo_files(root: Path, *, limit: int = 120) -> list[str]:
    ignored = {".git", ".venv", "node_modules", "__pycache__", "dist", "build", ".physical-agent"}
    files: list[str] = []
    for path in root.rglob("*"):
        if any(part in ignored for part in path.parts):
            continue
        if not path.is_file():
            continue
        try:
            files.append(str(path.relative_to(root).as_posix()))
        except ValueError:
            continue
        if len(files) >= limit:
            break
    return files


def _git_status(root: Path) -> str:
    try:
        completed = subprocess.run(
            ["git", "status", "--short"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return "git unavailable"
    return completed.stdout.strip()


def _tests_passed(output: str) -> bool:
    match = re.search(r"__exitcode__:(-?\d+)", output)
    if match:
        return int(match.group(1)) == 0
    text = output.lower()
    if "test command not found" in text or "command not found" in text:
        return False
    if "traceback" in text or "no module named" in text:
        return False
    if re.search(r"\b[1-9]\d*\s+failed\b", text):
        return False
    if "failed" in text and "passed" not in text:
        return False
    if re.search(r"\b(error|errors)\b", text) and "passed" not in text:
        return False
    return True


def _normalize_test_command(tests: list[str]) -> list[str]:
    parts = [str(item).strip() for item in tests if str(item).strip()]
    if len(parts) == 1:
        return shlex.split(parts[0], posix=os.name != "nt")
    return parts


def _json_candidate_starts(text: str) -> list[int]:
    starts: list[int] = []
    for token in ("{", "["):
        index = text.find(token)
        if index != -1:
            starts.append(index)
    return sorted(set(starts))


def _resolve_execution_target(root: Path, message: str, requested_files: list[str], files: list[str]) -> Path | None:
    candidate_paths: list[Path] = []

    def add_candidate(path_text: str) -> None:
        path = Path(path_text)
        if not path.is_absolute():
            path = (root / path).resolve()
        if _is_within(root, path) and path.exists() and path.suffix == ".py":
            candidate_paths.append(path)

    for requested in requested_files:
        add_candidate(str(requested))

    execution_hint_paths: list[str] = []
    lowered = message.lower()
    if any(keyword in lowered for keyword in ("circle", "画圈", "画圆")):
        execution_hint_paths.extend(
            [
                "scripts/draw_circle.py",
                "draw_circle.py",
            ]
        )
    if any(keyword in lowered for keyword in ("execute", "运行", "执行", "run")):
        execution_hint_paths.extend(
            [
                "scripts/run.py",
                "run.py",
                "main.py",
            ]
        )
    for relative in execution_hint_paths:
        if candidate_paths:
            break
        candidate = (root / relative).resolve()
        if candidate.exists():
            candidate_paths.append(candidate)

    if not candidate_paths:
        for file_path in files:
            if not file_path.endswith(".py"):
                continue
            if any(key in file_path.lower() for key in ("draw_circle", "circle")):
                add_candidate(file_path)

    if not candidate_paths and any(keyword in lowered for keyword in ("circle", "画圈", "画圆")):
        for relative in (
            "scripts/draw_circle.py",
            "draw_circle.py",
        ):
            candidate = (root / relative).resolve()
            if candidate.exists():
                candidate_paths.append(candidate)
                break

    if not candidate_paths and len([f for f in files if f.endswith(".py")]) == 1:
        only_file = Path(root / next(f for f in files if f.endswith(".py"))).resolve()
        if only_file.exists():
            candidate_paths.append(only_file)

    return candidate_paths[0] if candidate_paths else None


def _default_execution_artifact_path(target: Path, artifact_dir: Path, message: str) -> Path | None:
    lowered = message.lower()
    if any(keyword in lowered for keyword in ("circle", "画圈", "画圆")) or "draw_circle" in target.name:
        return artifact_dir / "circle.svg"
    if target.suffix == ".py":
        return artifact_dir / f"{target.stem}.out"
    return None


def _collect_execution_artifacts(artifact_dir: Path) -> list[str]:
    if not artifact_dir.exists():
        return []
    artifacts: list[str] = []
    for path in sorted(artifact_dir.rglob("*")):
        if path.is_file():
            artifacts.append(str(path.resolve()))
    return artifacts


def _summarize_console_output(stdout: str, stderr: str, *, limit: int = 160) -> str:
    lines = [
        line.strip()
        for line in (stdout + "\n" + stderr).splitlines()
        if line.strip()
    ]
    if not lines:
        return "No console output was produced."

    priority_terms = ("traceback", "error", "exception", "failed", "not found", "permission denied")
    for line in reversed(lines):
        lowered = line.lower()
        if any(term in lowered for term in priority_terms):
            return _truncate(line, limit)
    return _truncate(lines[-1], limit)


def _truncate(text: str, limit: int) -> str:
    clean = re.sub(r"\s+", " ", text).strip()
    if len(clean) <= limit:
        return clean
    return clean[: max(0, limit - 1)].rstrip() + "…"


def _extract_integration_source(message: str) -> str | None:
    url_match = re.search(
        r"(https?://[^\s]+github\.com/[^\s]+|git@github\.com:[^\s]+)",
        message,
        re.IGNORECASE,
    )
    if url_match:
        return url_match.group(1).rstrip(".,)")
    path_match = re.search(r"(?:(?:[A-Za-z]:[\\/])|(?:\./)|(?:\.\\/)|(?:~/)|(?:/))[^\s]+", message)
    if path_match:
        return path_match.group(0).rstrip(".,)")
    package_match = re.search(
        r"(?:package|sdk|repo|仓库|项目|路径)\s*[:：]?\s*([A-Za-z0-9_.-]+)",
        message,
        re.IGNORECASE,
    )
    if package_match:
        return package_match.group(1).strip()
    return None


def _is_within(root: Path, path: Path) -> bool:
    try:
        path.relative_to(root.resolve())
        return True
    except ValueError:
        return False
