from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from physical_agent.agent.chat_runtime import ChatRuntime
from physical_agent.agent.code_patch import CodePatchError, FileEdit, apply_file_edits
from physical_agent.agent.code_router import CodeIntentRouter
from physical_agent.agent.code_runtime import CodeSkillRuntime, _normalize_test_command, _tests_passed
from physical_agent.agent.skills import SkillRouter
from physical_agent.cli import app
from physical_agent.protocol.schemas import CodeTaskIntent, CodeTaskResult
from physical_agent.protocol.workspace import Workspace
from physical_agent.quickstart import setup_project


class FakeCodeClient:
    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.calls: list[list[dict[str, str]]] = []

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> str:
        self.calls.append(messages)
        if not self.responses:
            raise AssertionError("No more fake LLM responses available.")
        return self.responses.pop(0)


class FakeCodeRuntime:
    def detect(self, message: str) -> CodeTaskIntent | None:
        return CodeTaskIntent(
            kind="code_edit",
            confidence=1.0,
            reason="fake test runtime",
            requested_files=[],
        )

    def run(self, message: str) -> CodeTaskResult:
        return CodeTaskResult(
            summary="Patched via chat code skill.",
            changed_files=["README.md"],
            tests_run=["pytest", "-q"],
            test_output="tests passed",
            lessons_written=["Recorded a chat code skill lesson."],
            rounds=1,
            ok=True,
            intent_kind="code_edit",
        )


def _response(summary: str, hello_value: str) -> str:
    return json.dumps(
        {
            "summary": summary,
            "files": [
                {
                    "path": "hello.py",
                    "content": f"def greet():\n    return {hello_value!r}\n",
                },
                {
                    "path": "tests/test_generated.py",
                    "content": (
                        "from hello import greet\n\n"
                        "def test_greet():\n"
                        "    assert greet() == 'hello'\n"
                    ),
                },
            ],
            "tests": ["pytest", "-q"],
        }
    )


def _single_string_test_response() -> str:
    return json.dumps(
        {
            "summary": "Use one shell-style test command.",
            "files": [
                {
                    "path": "tests/test_single_string_command.py",
                    "content": "def test_single_string_command():\n    assert True\n",
                }
            ],
            "tests": ["pytest -q"],
        }
    )


def test_code_intent_router_recognizes_code_and_skips_physical_tasks(tmp_path):
    router = CodeIntentRouter(tmp_path)

    assert router.route("please modify files and write tests").kind == "code_edit"
    assert router.route("请修改这个文件并补测试").kind == "code_edit"
    assert router.route("我想接入这个sdk").kind == "sdk_integration"
    assert router.route("pick the red block and place it on the tray") is None


def test_code_patch_refuses_to_escape_repo_root(tmp_path):
    with pytest.raises(CodePatchError):
        apply_file_edits(
            tmp_path,
            [FileEdit(path="../outside.py", content="print('nope')")],
        )


def test_code_skill_runtime_retries_after_failed_tests(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    client = FakeCodeClient(
        [
            _response("First pass.", "oops"),
            _response("Second pass.", "hello"),
        ]
    )

    runtime = CodeSkillRuntime(root, client=client, max_rounds=2)
    result = runtime.run("please modify files and write tests")

    assert result.ok is True
    assert result.rounds == 2
    assert result.tests_run == ["pytest", "-q"]
    assert "__exitcode__:0" in result.test_output
    assert sorted(result.changed_files) == ["hello.py", "tests/test_generated.py"]
    assert (root / "hello.py").read_text(encoding="utf-8").strip().endswith("return 'hello'")
    lessons = (root / ".physical-agent" / "code" / "LESSONS.md").read_text(encoding="utf-8")
    assert "Code task succeeded" in lessons
    assert "Tests failed after code edit" in lessons
    assert "previous_error" in client.calls[1][1]["content"]


def test_code_skill_runtime_splits_shell_style_test_command(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    runtime = CodeSkillRuntime(
        root,
        client=FakeCodeClient([_single_string_test_response()]),
        max_rounds=1,
    )

    result = runtime.run("please write a small test")

    assert result.ok is True
    assert result.tests_run == ["pytest -q"]
    assert "__exitcode__:0" in result.test_output


def test_code_skill_runtime_executes_draw_circle_script(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    script = root / "scripts" / "draw_circle.py"
    script.parent.mkdir(parents=True)
    script.write_text(
        "from pathlib import Path\n"
        "import os\n"
        "target = Path(os.environ['PHYSICAL_AGENT_OUTPUT_PATH'])\n"
        "target.parent.mkdir(parents=True, exist_ok=True)\n"
        "target.write_text('<svg><circle cx=\"10\" cy=\"10\" r=\"10\" /></svg>', encoding='utf-8')\n",
        encoding="utf-8",
    )
    client = FakeCodeClient([])
    runtime = CodeSkillRuntime(root, client=client, max_rounds=1)

    result = runtime.run("帮我执行画圈的代码")

    assert result.ok is True
    assert result.intent_kind == "code_run"
    assert result.run_artifacts
    assert any(path.endswith("circle.svg") for path in result.run_artifacts)
    assert "<circle" in result.test_output or "stdout" in result.test_output or result.summary


def test_chat_runtime_formats_code_run_results(tmp_path):
    config_path = tmp_path / "physical-agent.yaml"
    setup_project(config_path, publish=True)
    runtime = ChatRuntime(config_path, planner_name="rule_based")

    class LocalCodeRuntime:
        def detect(self, message: str) -> CodeTaskIntent | None:
            return CodeTaskIntent(
                kind="code_run",
                confidence=1.0,
                reason="test",
                requested_files=["scripts/draw_circle.py"],
            )

        def run(self, message: str) -> CodeTaskResult:
            return CodeTaskResult(
                summary="Executed draw_circle.py.",
                changed_files=[],
                tests_run=["python scripts/draw_circle.py"],
                test_output="ok",
                lessons_written=[],
                rounds=1,
                ok=True,
                intent_kind="code_run",
                run_artifacts=[".physical-agent/code/artifacts/circle.svg"],
            )

    runtime.code_runtime = LocalCodeRuntime()  # type: ignore[assignment]

    result = runtime.respond("帮我执行画圈的代码")

    assert result["mode"] == "code"
    assert "代码执行任务" in result["reply"]
    assert "产物:" in result["reply"]
    assert result["code_result"]["run_artifacts"]
    assert "Command:" not in result["reply"]
    assert "Test output:" not in result["reply"]


def test_code_run_failure_summary_is_human_readable(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    script = root / "scripts" / "draw_circle.py"
    script.parent.mkdir(parents=True)
    script.write_text(
        "import sys\n"
        "print('starting circle run')\n"
        "print('permission denied: missing device', file=sys.stderr)\n"
        "raise SystemExit(1)\n",
        encoding="utf-8",
    )
    runtime = CodeSkillRuntime(root, client=FakeCodeClient([]), max_rounds=1)

    result = runtime.run("帮我执行画圈的代码")

    assert result.ok is False
    assert result.intent_kind == "code_run"
    assert "I tried running scripts/draw_circle.py" in result.summary
    assert "permission denied" in result.summary.lower()


def test_code_run_result_model_exposes_artifacts(tmp_path):
    result = CodeTaskResult(
        summary="done",
        intent_kind="code_run",
        run_artifacts=[".physical-agent/code/artifacts/circle.svg"],
    )

    assert result.run_artifacts == [".physical-agent/code/artifacts/circle.svg"]


def test_test_command_helpers_are_conservative_for_failures(tmp_path):
    runtime = CodeSkillRuntime(tmp_path)

    assert _normalize_test_command(["pytest -q"]) == ["pytest", "-q"]
    output = runtime._run_tests(["definitely-missing-physical-agent-test-command"])

    assert "Test command not found" in output
    assert "__exitcode__:127" in output
    assert _tests_passed(output) is False
    assert _tests_passed("Traceback (most recent call last):\nboom") is False


def test_chat_runtime_routes_code_task_and_persists_result(tmp_path, monkeypatch):
    config_path = tmp_path / "physical-agent.yaml"
    setup_project(config_path, publish=True)

    runtime = ChatRuntime(config_path, planner_name="rule_based")
    monkeypatch.setattr(runtime, "_code_runtime", lambda: FakeCodeRuntime())

    result = runtime.respond("请修改这个文件并补测试")

    assert result["mode"] == "code"
    assert result["code_result"]["summary"] == "Patched via chat code skill."
    assert "代码任务" in result["reply"]
    assert "改动文件: README.md." in result["reply"]
    workspace = Workspace(tmp_path / "workspace")
    messages = workspace.read_chat()["messages"]
    assert messages[-1].metadata["code_result"]["summary"] == "Patched via chat code skill."


def test_skill_router_discovers_repo_skill_files(tmp_path):
    (tmp_path / "skills" / "echo").mkdir(parents=True)
    (tmp_path / "skills" / "echo" / "SKILL.md").write_text(
        "---\n"
        "name: echo\n"
        "title: Echo Skill\n"
        "description: Repeat a short note.\n"
        "triggers:\n"
        "  - echo\n"
        "intents:\n"
        "  - chat\n"
        "priority: 3\n"
        "---\n"
        "\n"
        "# Echo Skill\n",
        encoding="utf-8",
    )

    router = SkillRouter(tmp_path)
    skills = router.list_skills()

    names = [skill.name for skill in skills]
    assert "echo" in names
    echo = next(skill for skill in skills if skill.name == "echo")
    assert echo.title == "Echo Skill"
    assert "echo" in echo.triggers


def test_chat_runtime_exposes_skills_in_response(tmp_path):
    config_path = tmp_path / "physical-agent.yaml"
    setup_project(config_path, publish=True)

    result = ChatRuntime(config_path, planner_name="rule_based").respond("hello there")

    assert result["skills"]
    assert any(skill["name"] == "code" for skill in result["skills"])


def test_code_router_recognizes_chinese_code_requests(tmp_path):
    router = CodeIntentRouter(tmp_path)

    assert router.route("你可以编写代码吗 能在test里面编写一个最简单的代码并运行吗") is not None
    assert router.route("帮我实现一个最简单的正方形程序").kind == "code_edit"
    assert router.route("运行这个脚本").kind == "code_run"


def test_code_skill_builtin_square_task_writes_and_tests_files(tmp_path):
    runtime = CodeSkillRuntime(tmp_path)

    result = runtime.run("在test里面编写一个最简单的正方形代码并运行")

    assert result.ok is True
    assert result.intent_kind == "code_edit"
    assert "test/draw_square.py" in result.changed_files
    assert "tests/test_draw_square.py" in result.changed_files
    assert "__exitcode__:0" in result.test_output


def test_chat_runtime_continues_chinese_code_followup_into_skill(tmp_path):
    config_path = tmp_path / "physical-agent.yaml"
    setup_project(config_path, publish=True)
    runtime = ChatRuntime(config_path, planner_name="rule_based")

    first = runtime.respond("你不能运行吗？我想在test里面编写一个最简单的正方形程序并运行")
    second = runtime.respond("可以，帮我实现一下")

    assert first["mode"] == "code"
    assert second["mode"] == "code"
    assert second["code_result"]["ok"] is True
    assert "test/draw_square.py" in second["code_result"]["changed_files"]
    assert "tests/test_draw_square.py" in second["code_result"]["changed_files"]
    assert (tmp_path / "test" / "draw_square.py").exists()
    assert (tmp_path / "tests" / "test_draw_square.py").exists()


def test_cli_chat_hides_structured_code_result_by_default(tmp_path, monkeypatch):
    config_path = tmp_path / "physical-agent.yaml"
    setup_project(config_path, publish=True)

    original = ChatRuntime._code_runtime
    monkeypatch.setattr(ChatRuntime, "_code_runtime", lambda self: FakeCodeRuntime())
    try:
        result = CliRunner().invoke(
            app,
            [
                "chat",
                "--config",
                str(config_path),
                "--planner",
                "rule_based",
                "--message",
                "please modify files and write tests",
            ],
        )
    finally:
        monkeypatch.setattr(ChatRuntime, "_code_runtime", original)

    assert result.exit_code == 0
    assert "Yes. I treated that as a code task" in result.output
    assert "Code skill result:" not in result.output


def test_cli_chat_accepts_prompt_argument_as_short_entrypoint(tmp_path, monkeypatch):
    config_path = tmp_path / "physical-agent.yaml"
    setup_project(config_path, publish=True)

    original = ChatRuntime._code_runtime
    monkeypatch.setattr(ChatRuntime, "_code_runtime", lambda self: FakeCodeRuntime())
    try:
        result = CliRunner().invoke(
            app,
            [
                "chat",
                "please modify files and write tests",
                "--config",
                str(config_path),
                "--planner",
                "rule_based",
            ],
        )
    finally:
        monkeypatch.setattr(ChatRuntime, "_code_runtime", original)

    assert result.exit_code == 0
    assert "Yes. I treated that as a code task" in result.output


def test_cli_chat_can_show_structured_code_result(tmp_path, monkeypatch):
    config_path = tmp_path / "physical-agent.yaml"
    setup_project(config_path, publish=True)

    original = ChatRuntime._code_runtime
    monkeypatch.setattr(ChatRuntime, "_code_runtime", lambda self: FakeCodeRuntime())
    try:
        result = CliRunner().invoke(
            app,
            [
                "chat",
                "--config",
                str(config_path),
                "--planner",
                "rule_based",
                "--show-code-result",
                "--message",
                "please modify files and write tests",
            ],
        )
    finally:
        monkeypatch.setattr(ChatRuntime, "_code_runtime", original)

    assert result.exit_code == 0
    assert "Code skill result:" in result.output
    assert "summary: Patched via chat code skill." in result.output
