# Physical Agent

[Chinese version](README.zh-CN.md)

Physical Agent is a Markdown-native runtime for safe physical-world agents.

The core idea is deliberately small:

```text
Terminal 1: physical-agent watch
Terminal 2: physical-agent run --task "..."
Workspace: Markdown files are the protocol between cognition and execution.
```

The v1 principle is:

```text
Agent can propose actions. Watch decides whether and how they touch the physical world.
```

## Architecture

Physical Agent separates cognition from physical execution with a two-process runtime.

```text
physical-agent watch
  owns hardware or simulator
  owns driver lifecycle
  owns observation loop
  owns safety enforcement
  owns action execution

workspace/*.md
  Markdown protocol and blackboard

physical-agent run
  reads task, capabilities, world, and feedback
  writes structured action intent
```

`physical-agent run` never imports hardware drivers or SDKs. It only sees Markdown protocol documents. `physical-agent watch` is the only runtime that loads drivers and calls `driver.execute(action)`.

## Quick Start

One-command local bootstrap from a fresh clone:

```bash
python scripts/bootstrap.py
```

That creates `.venv`, installs the project with dev dependencies, runs tests, initializes the workspace, and runs a pick/place smoke test.

If you already have a Python environment:

```bash
pip install -e .[dev]
physical-agent setup --smoke-test
```

Start the GUI:

```bash
physical-agent gui
```

The GUI opens a local console for setup, watch start/step, task submission, quick demo execution, and workspace inspection.

You can still run the two-process CLI flow. Start the physical side in one terminal:

```bash
physical-agent watch
```

Submit a task from another terminal:

```bash
physical-agent run --task "pick the red block and place it on the tray"
```

Inspect the workspace state:

```bash
physical-agent inspect
```

Check project health:

```bash
physical-agent doctor
```

The default project uses the built-in `mock_arm` driver, so no hardware or API key is required.

## Local GUI

`physical-agent gui` starts a dependency-free local web console backed by Python's standard library HTTP server.

The console provides:

- project setup
- workspace reset
- watch runtime connection
- one-step action execution
- task submission
- pick/place quick demo
- doctor checks
- robot, world, action board, and feedback views

By default it binds to `127.0.0.1:8765`:

```bash
physical-agent gui --port 8765
```

Run without opening a browser automatically:

```bash
physical-agent gui --no-open
```

## Markdown Workspace Protocol

The workspace is dynamic protocol state. Each file uses YAML front matter, Markdown prose, and fenced YAML blocks for machine-readable data.

```text
workspace/
  TASK.md
  CAPABILITIES.md
  WORLD.md
  ACTIONS.md
  FEEDBACK.md
  SAFETY.md
  LOG.md
  artifacts/
```

`TASK.md` records the active task and human constraints.

`CAPABILITIES.md` is written by watch from loaded driver capabilities. The agent treats it as read-only.

`WORLD.md` is written by watch from driver observations. It contains robot state, objects, environment data, and artifact paths.

`ACTIONS.md` is written by the agent. It contains pending, completed, and cancelled action boards. Watch reads pending actions and moves them after execution or safety rejection.

`FEEDBACK.md` is written by watch. It records latest execution feedback and history for the agent to read.

`SAFETY.md` is owned by humans and enforced by watch. The agent can read it but cannot bypass it.

`LOG.md` is an audit log for human review.

Static configuration belongs in `physical-agent.yaml`. Dynamic state belongs in the Markdown workspace.

## Driver Contract

Two files are enough to connect a robot:

```text
my_robot_driver/
  physical_driver.yaml
  driver.py
```

`physical_driver.yaml` declares the adapter: name, version, entrypoint, robot kind, configuration schema, dependencies, and capability contract.

`driver.py` implements the adapter by subclassing `PhysicalDriver`. The driver turns structured `Action` objects into hardware or simulator calls, and turns device state into `Observation` objects.

Important boundaries:

- The driver only talks to `physical-agent watch`.
- The driver does not parse Markdown.
- The driver does not call the agent runtime.
- The agent only sees capabilities, world state, actions, and feedback through Markdown.

Create a new local driver scaffold:

```bash
physical-agent driver new my_arm_driver
```

Use it from `physical-agent.yaml`:

```yaml
robots:
  arm_1:
    driver: ./my_arm_driver
    config: {}
```

## Built-In Drivers

`mock_arm` supports:

- `observe`
- `move_to`
- `pick`
- `place`

It maintains a simulated pose, held object, and object map. The default quickstart includes `red_block` and `tray`.

`mock_rover` supports:

- `observe`
- `move_to`

It demonstrates that the driver protocol is not arm-specific.

## Safety Gate

Watch validates every action before execution:

- robot exists
- capability exists
- params satisfy the capability JSON schema
- capability constraints are satisfied
- workspace safety rules allow execution
- human approval requirements are respected
- action IDs are not duplicated
- dependencies are already completed

If validation fails, watch does not call the driver. It writes clear feedback, logs the rejection, and removes the action from pending.

## Rule-Based Planner

The first planner is intentionally local and deterministic:

- `observe`, `look`, or `scan` produces `observe`
- `move` or `go` produces `move_to`
- `pick` or `grasp` produces `pick`
- `place` or `drop` produces `place`

For example:

```text
pick the red block and place it on the tray
```

produces a `pick` action followed by a dependent `place` action.

## OpenAI-Compatible API Planner

Physical Agent can use an OpenAI-compatible Chat Completions endpoint for planning while keeping the same safety boundary: the LLM only writes proposed actions to `ACTIONS.md`; watch still validates and executes them.

Create a local `.env` file. It is ignored by git.

```bash
GPT_URL=https://your-provider.example/v1
GPT_KEY=your_api_key
GPT_MODEL=gpt-4o-mini
```

Supported variable names:

- API key: `GPT_KEY` or `OPENAI_API_KEY`
- Base URL: `GPT_URL` or `OPENAI_BASE_URL`
- Model: `GPT_MODEL` or `OPENAI_MODEL`

Test the API connection:

```bash
physical-agent llm-test
```

Use the LLM planner:

```bash
physical-agent setup --force
physical-agent run --planner llm --task "pick the red block and place it on the tray" --no-wait
physical-agent inspect
```

Execute the proposed actions by running watch in another terminal:

```bash
physical-agent watch
```

Or run one watch step in-process for a quick local check:

```bash
python -c "import asyncio; from physical_agent.watch.runtime import WatchRuntime; r=WatchRuntime('physical-agent.yaml'); asyncio.run(r.setup()); print('executed', asyncio.run(r.step(setup=False)))"
physical-agent inspect
```

You can also make LLM planning the project default by editing `physical-agent.yaml`:

```yaml
agent:
  planner: llm
  model: gpt-4o-mini
```

## Clean-Room Implementation

Physical Agent is an independent implementation. It uses general public architecture ideas such as embodied-agent layering, watchdog/runtime separation, declarative driver manifests, Markdown workspace protocols, and MCP-style tool facades. It does not include third-party competitor code, copied file contents, copied README wording, copied CLI design, copied example task suites, or copied implementation details.

## Development Checks

Run the full test suite:

```bash
pytest -q
```

Current coverage includes Markdown protocol parsing/rendering, workspace lifecycle, driver manifest and loader behavior, safety validation, mock drivers, rule-based planning, watch runtime stepping, the end-to-end Markdown loop, one-command setup, doctor checks, and GUI HTTP endpoints.
