from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import typer
import yaml

from physical_agent.agent.chat_runtime import ChatRuntime
from physical_agent.agent.onboarding import HardwareIntegrationAssistant
from physical_agent.agent.runtime import AgentRuntime
from physical_agent.config import DEFAULT_CONFIG_NAME, load_config, write_default_config
from physical_agent.doctor import doctor_ok, run_doctor
from physical_agent.drivers.templates import create_driver_template
from physical_agent.gui import run_gui
from physical_agent.llm import OpenAICompatibleClient, OpenAICompatibleSettings
from physical_agent.protocol.workspace import Workspace
from physical_agent.quickstart import setup_project
from physical_agent.watch.runtime import WatchRuntime


app = typer.Typer(help="Physical Agent: Markdown-native runtime for safe physical-world agents.")
driver_app = typer.Typer(help="Driver utilities.")
app.add_typer(driver_app, name="driver")


@app.command("init")
def init(
    config: Path = typer.Option(Path(DEFAULT_CONFIG_NAME), "--config", "-c", help="Config path."),
    force: bool = typer.Option(False, "--force", help="Overwrite existing config and workspace files."),
) -> None:
    config_path = write_default_config(config, overwrite=force)
    cfg = load_config(config_path)
    workspace = Workspace(cfg.workspace_path(config_path.parent))
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


@app.command("gui")
def gui(
    config: Path = typer.Option(Path(DEFAULT_CONFIG_NAME), "--config", "-c", help="Config path."),
    host: str = typer.Option("127.0.0.1", "--host", help="Host to bind."),
    port: int = typer.Option(8765, "--port", "-p", help="Port to bind."),
    no_open: bool = typer.Option(False, "--no-open", help="Do not open the browser automatically."),
) -> None:
    run_gui(config, host=host, port=port, open_browser=not no_open)


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
    message: Optional[str] = typer.Option(None, "--message", "-m", help="Send one chat message and exit."),
    config: Path = typer.Option(Path(DEFAULT_CONFIG_NAME), "--config", "-c", help="Config path."),
    planner: Optional[str] = typer.Option("auto", "--planner", help="Chat brain: auto, llm, or rule_based."),
    model: Optional[str] = typer.Option(None, "--model", help="LLM model override for --planner llm."),
    auto_step: bool = typer.Option(
        False,
        "--auto-step",
        help="Run one watch step after proposed actions are written.",
    ),
) -> None:
    runtime = ChatRuntime(config, planner_name=planner, model=model)
    if message is not None:
        result = runtime.respond(message, auto_step=auto_step)
        typer.echo(result["reply"])
        if result["actions"]:
            typer.echo("Proposed actions:")
            for action in result["actions"]:
                typer.echo(f"- {action['id']}: {action['robot']}.{action['capability']}")
        if result["executed"]:
            typer.echo(f"Watch step executed {result['executed']} action(s).")
        return

    typer.echo("Physical Agent chat mode. Press Ctrl+C or submit an empty message to exit.")
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
        if result["actions"]:
            typer.echo("agent> Proposed actions:")
            for action in result["actions"]:
                typer.echo(f"  - {action['id']}: {action['robot']}.{action['capability']}")
        if result["executed"]:
            typer.echo(f"agent> Watch step executed {result['executed']} action(s).")


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
    workspace = Workspace(cfg.workspace_path(config.resolve().parent))
    if not workspace.exists():
        typer.echo("Workspace is not initialized. Run `physical-agent init` first.")
        raise typer.Exit(code=1)

    capabilities = workspace.read_capabilities()
    world = workspace.read_world()
    actions = workspace.read_actions()
    feedback = workspace.read_feedback()

    typer.echo("Robots:")
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

    typer.echo("\nCompleted actions:")
    if actions["completed"]:
        for action in actions["completed"]:
            typer.echo(f"- {action.id}: {action.robot}.{action.capability}")
    else:
        typer.echo("- none")

    typer.echo("\nLatest feedback:")
    latest = feedback.get("latest", {})
    if latest:
        typer.echo(yaml.safe_dump(latest, sort_keys=False).strip())
    else:
        typer.echo("- none")


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
) -> None:
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
