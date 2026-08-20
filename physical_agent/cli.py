from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Optional

import typer
import yaml

from physical_agent.agent.chat_runtime import ChatRuntime
from physical_agent.agent.driver_coder import DriverCodingAgent
from physical_agent.agent.onboarding import HardwareIntegrationAssistant
from physical_agent.agent.runtime import AgentRuntime
from physical_agent.agent.skills import SkillRouter
from physical_agent.config import DEFAULT_CONFIG_NAME, load_config, write_default_config
from physical_agent.doctor import doctor_ok, run_doctor
from physical_agent.drivers.templates import create_driver_template
from physical_agent.gui import run_gui
from physical_agent.ingest.files import FileIngestionError, ingest_file as ingest_local_file
from physical_agent.llm import OpenAICompatibleClient, OpenAICompatibleSettings
from physical_agent.quickstart import setup_project
from physical_agent.state import open_state_store
from physical_agent.state.check import run_state_check, state_check_ok
from physical_agent.state.sqlite import migrate_markdown_workspace_to_sqlite
from physical_agent.watch.runtime import WatchRuntime


app = typer.Typer(help="Physical Agent: safe runtime for physical-world agents.")
driver_app = typer.Typer(help="Driver utilities.")
app.add_typer(driver_app, name="driver")
skill_app = typer.Typer(help="Skill utilities.")
app.add_typer(skill_app, name="skill")


@app.command("init")
def init(
    config: Path = typer.Option(Path(DEFAULT_CONFIG_NAME), "--config", "-c", help="Config path."),
    force: bool = typer.Option(False, "--force", help="Overwrite existing config and workspace files."),
) -> None:
    config_path = write_default_config(config, overwrite=force)
    cfg = load_config(config_path)
    workspace = open_state_store(cfg, base_dir=config_path.parent)
    workspace.initialize(overwrite=force)
    typer.echo(f"Initialized Physical Agent project at {config_path.parent}")
    typer.echo(f"Config: {config_path}")
    typer.echo(f"Workspace: {workspace.path}")


@app.command("setup")
def setup(
    config: Path = typer.Option(Path(DEFAULT_CONFIG_NAME), "--config", "-c", help="Config path."),
    force: bool = typer.Option(False, "--force", help="Overwrite existing config and workspace files."),
    smoke_test: bool = typer.Option(
        False,
        "--smoke-test",
        help="Run an in-process pick/place smoke test after setup.",
    ),
) -> None:
    result = setup_project(config, force=force, publish=True, smoke_test=smoke_test)
    typer.echo("Physical Agent project is ready.")
    typer.echo(f"Config: {result['config_path']}")
    typer.echo(f"Workspace: {result['workspace_path']}")
    if result["smoke_test"] is not None:
        smoke = result["smoke_test"]
        status = "passed" if smoke["ok"] else "failed"
        typer.echo(
            f"Smoke test {status}: executed {smoke['executed_actions']} action(s), "
            f"red_block location is {smoke['red_block_location']}."
        )
    typer.echo("Next: run `physical-agent gui` or `physical-agent watch`.")


@app.command("doctor")
def doctor(
    config: Path = typer.Option(Path(DEFAULT_CONFIG_NAME), "--config", "-c", help="Config path."),
) -> None:
    checks = run_doctor(config)
    for check in checks:
        marker = "OK" if check.ok else "FAIL"
        typer.echo(f"[{marker}] {check.name}: {check.message}")
    if not doctor_ok(checks):
        raise typer.Exit(code=1)


@app.command("state-check")
def state_check(
    config: Path = typer.Option(Path(DEFAULT_CONFIG_NAME), "--config", "-c", help="Config path."),
) -> None:
    cfg = load_config(config)
    result = run_state_check(cfg, base_dir=config.resolve().parent)

    typer.echo(f"Backend: {result['backend']}")
    typer.echo(f"Backend role: {result['backend_role']}")
    typer.echo(f"Source of truth: {result['source_of_truth']}")
    typer.echo(f"Payload format: {result['payload_format']}")
    typer.echo(f"Safety source: {result['safety_source']}")
    typer.echo(f"Recommendation: {result['recommendation']}")
    typer.echo(f"Workspace: {result['workspace_path']}")
    typer.echo(
        "Workspace initialized: "
        f"{'yes' if result['workspace_initialized'] else 'no'}"
    )
    typer.echo(
        "Retrieval enabled: "
        f"{'yes' if result['retrieval_enabled'] else 'no'}"
    )
    typer.echo(f"Retrieval max chunks: {result['retrieval_max_chunks']}")
    typer.echo(
        "Retrieval max chars per chunk: "
        f"{result['retrieval_max_chars_per_chunk']}"
    )
    sqlite_schema_complete = result["sqlite_schema_complete"]
    if sqlite_schema_complete is None:
        typer.echo("SQLite schema complete: n/a")
        typer.echo("SQLite chunk schema complete: n/a")
    else:
        typer.echo(
            "SQLite schema complete: "
            f"{'yes' if sqlite_schema_complete else 'no'}"
        )
        typer.echo(
            "SQLite chunk schema complete: "
            f"{'yes' if result['sqlite_chunk_schema_complete'] else 'no'}"
        )
        missing = (
            result["sqlite_missing_tables"]
            + result["sqlite_missing_action_columns"]
            + result["sqlite_missing_memory_columns"]
            + result["sqlite_missing_upload_columns"]
            + result["sqlite_missing_chunk_columns"]
        )
        if missing:
            typer.echo(f"SQLite missing: {', '.join(missing)}")
    typer.echo(f"Audit directory: {result['audit_dir']}")
    typer.echo(
        "Audit export writable: "
        f"{'yes' if result['audit_export_writable'] else 'no'}"
    )

    if not state_check_ok(result):
        raise typer.Exit(code=1)


@app.command("gui")
def gui(
    config: Path = typer.Option(Path(DEFAULT_CONFIG_NAME), "--config", "-c", help="Config path."),
    host: str = typer.Option("127.0.0.1", "--host", help="Host to bind."),
    port: int = typer.Option(8765, "--port", "-p", help="Port to bind."),
    no_open: bool = typer.Option(False, "--no-open", help="Do not open the browser automatically."),
) -> None:
    run_gui(config, host=host, port=port, open_browser=not no_open)


@app.command("api")
def api(
    config: Path = typer.Option(Path(DEFAULT_CONFIG_NAME), "--config", "-c", help="Config path."),
    host: str = typer.Option("127.0.0.1", "--host", help="Host to bind."),
    port: int = typer.Option(8766, "--port", "-p", help="Port to bind."),
    watch: bool = typer.Option(False, "--watch", help="Run the watch loop in the API process."),
    watch_interval_s: Optional[float] = typer.Option(
        None,
        "--watch-interval-s",
        help="Override the API watch loop interval in seconds.",
    ),
) -> None:
    try:
        create_app, uvicorn = _load_api_server()
        api_app = create_app(
            config,
            enable_watch=watch,
            watch_interval_s=watch_interval_s,
        )
    except Exception as exc:
        from physical_agent.api.server import MissingServerDependencyError

        if isinstance(exc, MissingServerDependencyError):
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=1) from exc
        raise
    uvicorn.run(api_app, host=host, port=port)


@app.command("watch")
def watch(
    config: Path = typer.Option(Path(DEFAULT_CONFIG_NAME), "--config", "-c", help="Config path."),
) -> None:
    runtime = WatchRuntime(config)
    typer.echo("Starting physical-agent watch. Press Ctrl+C to stop.")
    try:
        asyncio.run(runtime.run_forever())
    except KeyboardInterrupt:
        typer.echo("Watch stopped.")


@app.command("run")
def run(
    task: Optional[str] = typer.Option(None, "--task", "-t", help="Task to run once."),
    config: Path = typer.Option(Path(DEFAULT_CONFIG_NAME), "--config", "-c", help="Config path."),
    planner: Optional[str] = typer.Option(None, "--planner", help="Planner override: rule_based or llm."),
    model: Optional[str] = typer.Option(None, "--model", help="LLM model override for --planner llm."),
    no_wait: bool = typer.Option(False, "--no-wait", help="Submit actions without waiting for feedback."),
) -> None:
    runtime = AgentRuntime(config, planner_name=planner, model=model)
    if task is None:
        asyncio.run(runtime.interactive())
        return
    result = asyncio.run(runtime.run_task(task, wait_for_feedback=not no_wait))
    typer.echo(result["message"])
    actions = result.get("actions", [])
    if actions:
        typer.echo("Actions:")
        for action in actions:
            typer.echo(
                f"- {action.id}: {action.robot}.{action.capability} "
                f"{yaml.safe_dump(action.params, sort_keys=False).strip()}"
            )
    feedback = result.get("feedback", [])
    if feedback:
        typer.echo("Feedback:")
        for item in feedback:
            typer.echo(f"- {item.get('action_id')}: {item.get('status')} - {item.get('message')}")
    elif actions and not no_wait:
        typer.echo("No feedback arrived before the timeout. Is `physical-agent watch` running?")


@app.command("chat")
def chat(
    prompt: Optional[str] = typer.Argument(
        None,
        help="Optional one-shot chat message. Omit it to start interactive chat.",
    ),
    message: Optional[str] = typer.Option(None, "--message", "-m", help="Send one chat message and exit."),
    config: Path = typer.Option(Path(DEFAULT_CONFIG_NAME), "--config", "-c", help="Config path."),
    planner: Optional[str] = typer.Option(
        "auto",
        "--planner",
        help="Chat brain: auto, llm, rule_based, tool_loop, or openai_tool_loop.",
    ),
    model: Optional[str] = typer.Option(None, "--model", help="LLM model override for --planner llm."),
    auto_step: bool = typer.Option(
        False,
        "--auto-step",
        help="Run one watch step after proposed actions are written.",
    ),
    show_code_result: bool = typer.Option(
        False,
        "--show-code-result",
        help="Print the structured code skill result after the natural chat reply.",
    ),
) -> None:
    runtime = ChatRuntime(config, planner_name=planner, model=model)
    one_shot = message if message is not None else prompt
    if one_shot is not None:
        result = runtime.respond(one_shot, auto_step=auto_step)
        typer.echo(result["reply"])
        if show_code_result and result.get("code_result"):
            _echo_code_result(dict(result["code_result"]))
        if result["actions"]:
            typer.echo("Proposed actions:")
            for action in result["actions"]:
                typer.echo(f"- {action['id']}: {action['robot']}.{action['capability']}")
        if result["executed"]:
            typer.echo(f"Watch step executed {result['executed']} action(s).")
        return

    typer.echo("Physical Agent chat mode. Ask normally; code tasks can edit files and run tests. Press Ctrl+C or submit an empty message to exit.")
    while True:
        text = input("you> ").strip()
        if not text:
            return
        try:
            result = runtime.respond(text, auto_step=auto_step)
        except Exception as exc:
            typer.echo(f"agent> Chat failed: {exc}")
            continue
        typer.echo(f"agent> {result['reply']}")
        if show_code_result and result.get("code_result"):
            _echo_code_result(dict(result["code_result"]), prefix="agent> ")
        if result["actions"]:
            typer.echo("agent> Proposed actions:")
            for action in result["actions"]:
                typer.echo(f"  - {action['id']}: {action['robot']}.{action['capability']}")
        if result["executed"]:
            typer.echo(f"agent> Watch step executed {result['executed']} action(s).")


@app.command("ingest-file")
def ingest_file_command(
    path: Path = typer.Argument(..., help="Text file to ingest into workspace/uploads."),
    config: Path = typer.Option(Path(DEFAULT_CONFIG_NAME), "--config", "-c", help="Config path."),
    tag: Optional[list[str]] = typer.Option(
        None,
        "--tag",
        help="Optional tag to attach to the upload memory note. May be repeated.",
    ),
    importance: int = typer.Option(0, "--importance", help="Structured memory importance."),
) -> None:
    config_root = config.resolve().parent
    cfg = load_config(config)
    workspace = open_state_store(cfg, base_dir=config_root)
    workspace.initialize()
    try:
        result = ingest_local_file(
            path,
            workspace,
            tags=tag,
            importance=importance,
            max_chars_per_chunk=cfg.memory.retrieval.max_chars_per_chunk,
        )
    except FileIngestionError as exc:
        if exc.metadata:
            typer.echo(f"Upload status: {exc.metadata.get('status')}")
            typer.echo(f"SHA256: {exc.metadata.get('sha256')}")
        typer.echo(f"File ingestion failed: {exc}")
        raise typer.Exit(code=1) from exc

    metadata = result["metadata"]
    typer.echo("File ingested.")
    typer.echo(f"Stored path: {metadata['stored_path']}")
    typer.echo(f"SHA256: {metadata['sha256']}")
    typer.echo(f"Memory written: {'yes' if result['memory_written'] else 'no'}")
    typer.echo(f"Chunks written: {result['chunks_written']}")
    typer.echo(f"Truncated: {'yes' if result['truncated'] else 'no'}")


@app.command("search-memory")
def search_memory(
    query: str = typer.Argument(..., help="Local keyword query for indexed memory/upload chunks."),
    config: Path = typer.Option(Path(DEFAULT_CONFIG_NAME), "--config", "-c", help="Config path."),
    limit: int = typer.Option(5, "--limit", "-n", help="Maximum chunks to return."),
    tag: Optional[list[str]] = typer.Option(
        None,
        "--tag",
        help="Require a tag on returned chunks. May be repeated.",
    ),
    source_type: Optional[str] = typer.Option(
        None,
        "--source-type",
        help="Restrict to upload or memory chunks.",
    ),
) -> None:
    config_root = config.resolve().parent
    cfg = load_config(config)
    workspace = open_state_store(cfg, base_dir=config_root)
    if not workspace.exists():
        typer.echo("Workspace is not initialized. Run `physical-agent init` first.")
        raise typer.Exit(code=1)

    results = workspace.query_memory_chunks(
        query,
        limit=limit,
        tags=tag,
        source_type=source_type,
    )
    typer.echo(f"Found {len(results)} chunk(s).")
    for item in results:
        tags = ", ".join(item.get("tags", [])) or "-"
        typer.echo(
            f"- score={item.get('score', 0)} "
            f"{item.get('source_type')}:{item.get('source_id')}#"
            f"{item.get('chunk_index')} "
            f"trust={item.get('trust_level')} tags={tags}"
        )
        typer.echo(_indent_text(_truncate_text(item.get("content", ""), 320)))


def _echo_code_result(code_result: dict[str, Any], *, prefix: str = "") -> None:
    typer.echo(f"{prefix}Code skill result:")
    if code_result.get("intent_kind") == "code_run":
        typer.echo(f"{prefix}Summary: {code_result.get('summary', '')}")
        typer.echo(f"{prefix}Status: {'succeeded' if code_result.get('ok') else 'failed'}")
        typer.echo(f"{prefix}Command: {', '.join(code_result.get('tests_run') or []) or 'none'}")
        typer.echo(f"{prefix}Artifacts: {', '.join(code_result.get('run_artifacts') or []) or 'none'}")
    else:
        text = yaml.safe_dump(code_result, sort_keys=False).strip()
        for line in text.splitlines():
            typer.echo(f"{prefix}{line}")


def _truncate_text(text: Any, limit: int) -> str:
    value = " ".join(str(text or "").split())
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 3)].rstrip() + "..."


def _indent_text(text: str) -> str:
    return "\n".join(f"  {line}" for line in (text or "").splitlines() or [""])


def _load_api_server():
    from physical_agent.api.server import (
        MissingServerDependencyError,
        SERVER_EXTRA_HINT,
        create_app,
    )

    try:
        import uvicorn
    except ImportError as exc:
        raise MissingServerDependencyError(SERVER_EXTRA_HINT) from exc
    return create_app, uvicorn


@app.command("llm-test")
def llm_test(
    env_file: Path = typer.Option(Path(".env"), "--env-file", help="Path to .env file."),
    model: Optional[str] = typer.Option(None, "--model", help="Model override."),
    prompt: str = typer.Option("Reply with exactly: pong", "--prompt", help="Connectivity test prompt."),
) -> None:
    try:
        settings = OpenAICompatibleSettings.from_env(env_file=env_file, model=model)
        typer.echo("OpenAI-compatible settings:")
        typer.echo(yaml.safe_dump(settings.public_summary(), sort_keys=False).strip())
        result = OpenAICompatibleClient(settings).test_connection(prompt=prompt)
    except Exception as exc:
        typer.echo(f"LLM API test failed: {exc}")
        raise typer.Exit(code=1) from exc
    typer.echo("LLM API test passed.")
    typer.echo(f"Response: {result['content']}")


@app.command("inspect")
def inspect(
    config: Path = typer.Option(Path(DEFAULT_CONFIG_NAME), "--config", "-c", help="Config path."),
) -> None:
    cfg = load_config(config)
    workspace = open_state_store(cfg, base_dir=config.resolve().parent)
    if not workspace.exists():
        typer.echo("Workspace is not initialized. Run `physical-agent init` first.")
        raise typer.Exit(code=1)

    capabilities = workspace.read_capabilities()
    world = workspace.read_world()
    actions = workspace.read_actions()
    feedback = workspace.read_feedback()

    typer.echo(f"Backend: {cfg.workspace.backend}")
    typer.echo(f"Workspace: {workspace.path}")

    typer.echo("\nRobots:")
    robots = capabilities.get("robots", {})
    if robots:
        for robot_id, robot in robots.items():
            names = [cap.get("name") for cap in robot.get("capabilities", [])]
            typer.echo(f"- {robot_id}: {robot.get('kind')} via {robot.get('driver')} ({', '.join(names)})")
    else:
        typer.echo("- none published yet")

    typer.echo("\nWorld summary:")
    typer.echo(world.get("summary") or "No world summary.")

    typer.echo("\nPending actions:")
    if actions["pending"]:
        for action in actions["pending"]:
            typer.echo(f"- {action.id}: {action.robot}.{action.capability}")
    else:
        typer.echo("- none")


@app.command("export-audit")
def export_audit(
    config: Path = typer.Option(Path(DEFAULT_CONFIG_NAME), "--config", "-c", help="Config path."),
    out: Optional[Path] = typer.Option(
        None,
        "--out",
        "-o",
        help="Audit output directory. Defaults to workspace/audit.",
    ),
) -> None:
    config_root = config.resolve().parent
    cfg = load_config(config)
    workspace = open_state_store(cfg, base_dir=config_root)
    if not workspace.exists():
        typer.echo("Workspace is not initialized. Run `physical-agent init` first.")
        raise typer.Exit(code=1)

    out_dir = None
    if out is not None:
        out_dir = out if out.is_absolute() else config_root / out
    result = workspace.export_human_view(out_dir)

    typer.echo("Exported audit view.")
    typer.echo(f"Backend: {result['backend']}")
    typer.echo(f"Workspace: {result['workspace_path']}")
    typer.echo(f"Audit: {result['out_dir']}")
    typer.echo(f"Manifest: {result['manifest']}")


@app.command("migrate-md-to-sqlite")
def migrate_md_to_sqlite(
    config: Path = typer.Option(Path(DEFAULT_CONFIG_NAME), "--config", "-c", help="Config path."),
    overwrite: bool = typer.Option(
        False,
        "--overwrite",
        help="Replace an existing workspace/state.db file.",
    ),
) -> None:
    cfg = load_config(config, allow_retired_markdown=True)
    workspace_path = cfg.workspace_path(config.resolve().parent)
    try:
        result = migrate_markdown_workspace_to_sqlite(
            workspace_path,
            overwrite=overwrite,
        )
    except FileExistsError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc
    except FileNotFoundError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc

    typer.echo("Migrated Markdown workspace to SQLite.")
    typer.echo(f"Workspace: {result['workspace_path']}")
    typer.echo(f"SQLite DB: {result['db_path']}")
    typer.echo(
        "Actions: "
        f"{result['actions']['pending']} pending, "
        f"{result['actions']['completed']} completed, "
        f"{result['actions']['cancelled']} cancelled"
    )
    typer.echo(
        f"Chat messages: {result['chat_messages']}; "
        f"memory notes: {result['memory_notes']}; "
        f"uploads: {result['uploads']}; "
        f"log entries: {result['log_entries']}"
    )
    typer.echo(
        "Config was not changed. To use this SQLite database, set "
        "`workspace.backend: sqlite` in physical-agent.yaml before starting "
        "CLI/API/GUI/watch."
    )


@skill_app.command("list")
def skill_list(
    config: Path = typer.Option(Path(DEFAULT_CONFIG_NAME), "--config", "-c", help="Config path."),
) -> None:
    cfg = load_config(config)
    router = SkillRouter(
        config.resolve().parent,
        model=cfg.agent.model if cfg.agent.model != "fake/local" else None,
        env_file=config.resolve().parent / ".env",
    )
    typer.echo("Available skills:")
    for skill in router.list_skills():
        typer.echo(f"- {skill.name}: {skill.title}")
        typer.echo(f"  {skill.summary}")
        if skill.triggers:
            typer.echo(f"  Triggers: {', '.join(skill.triggers)}")


@app.command("integrate")
def integrate(
    source: str = typer.Argument(..., help="Local path, GitHub repo URL, or Python package to analyze."),
    config: Path = typer.Option(Path(DEFAULT_CONFIG_NAME), "--config", "-c", help="Config path."),
    output: Optional[Path] = typer.Option(
        None,
        "--output",
        "-o",
        help="Target driver directory. Default: ./physical-agent-integration/<driver-name>.",
    ),
    name: Optional[str] = typer.Option(None, "--name", help="Override the generated driver name."),
    llm: bool = typer.Option(False, "--llm", help="Use the configured LLM to draft driver.py from SDK context."),
    model: Optional[str] = typer.Option(None, "--model", help="LLM model override for --llm."),
) -> None:
    if llm:
        result = DriverCodingAgent(
            source,
            output_dir=output,
            name=name,
            base_dir=config.resolve().parent,
            model=model,
        ).generate()
        typer.echo("Physical Agent LLM driver coding completed.")
        typer.echo(f"Source: {result.integration.source.source}")
        typer.echo(f"Output: {result.output_path}")
        typer.echo(f"LLM used: {result.llm_used}")
        if result.llm_error:
            typer.echo(f"LLM note: {result.llm_error}")
        typer.echo(f"Summary: {result.summary}")
        typer.echo("Validation:")
        typer.echo(yaml.safe_dump(result.validation, sort_keys=False).strip())
        typer.echo("Generated files:")
        for file_path in result.generated_files:
            typer.echo(f"- {file_path}")
        if result.next_steps:
            typer.echo("\nNext steps:")
            for step in result.next_steps:
                typer.echo(f"- {step}")
        return

    assistant = HardwareIntegrationAssistant(
        source,
        output_dir=output,
        name=name,
        base_dir=config.resolve().parent,
    )
    result = assistant.generate()
    typer.echo("Physical Agent integration scaffold created.")
    typer.echo(f"Source: {result.source.source}")
    typer.echo(f"Output: {result.output_path}")
    typer.echo("Generated files:")
    for file_path in result.generated_files:
        typer.echo(f"- {file_path}")
    typer.echo("\nNext steps:")
    for step in result.source.next_steps:
        typer.echo(f"- {step}")


@driver_app.command("new")
def driver_new(name: str = typer.Argument(..., help="Directory/name for the new driver.")) -> None:
    path = create_driver_template(name)
    typer.echo(f"Created driver template at {path}")
    typer.echo("Files: physical_driver.yaml, driver.py, README.md, README.zh-CN.md")


if __name__ == "__main__":
    app()
