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

This section is written for a first-time user. The default quickstart uses the built-in `mock_arm` simulator, so you do not need real hardware or an LLM API key.

### Step 0: Check What You Need

You need:

- Python 3.11 or newer
- a terminal
- this repository

Enter the repository root:

```bash
cd Physical_Agent
```

If you are already in the repository root, you can skip that. The root should contain `pyproject.toml`, `physical_agent/`, `examples/`, and this README.

### Step 1: Install and Initialize

For a fresh clone, run the bootstrap script:

```bash
python scripts/bootstrap.py
```

This command will:

- create a local `.venv`
- install the project with development dependencies
- run the test suite
- create the default `physical-agent.yaml`
- initialize `workspace/`
- run a smoke test that verifies the mock arm can place `red_block` on `tray`

If you already manage your own Python environment, you can run the manual path:

```bash
pip install -e .[dev]
physical-agent setup --smoke-test
```

You are ready when you see output like:

```text
Physical Agent project is ready.
Config: .../physical-agent.yaml
Workspace: .../workspace
Smoke test passed: executed 2 action(s), red_block location is tray.
```

### Step 2: Run the GUI First

The GUI is the easiest way to see the workspace state change:

```bash
physical-agent gui
```

The browser will open a local console. In the GUI you can:

1. click setup or reset to prepare the workspace
2. click watch start to connect the mock robot
3. click quick demo to submit the pick/place task
4. click step or auto-step to let watch execute actions
5. inspect robots, world, actions, and feedback

If the browser does not open automatically, visit:

```text
http://127.0.0.1:8765
```

The main idea to watch for:

```text
CAPABILITIES.md tells the agent what the robot can do.
ACTIONS.md is the action queue proposed by the agent.
FEEDBACK.md records what watch executed.
WORLD.md stores the latest observed world state.
```

### Step 3: Run the Two-Terminal CLI Flow

After the GUI path works, the CLI flow is easier to understand. Physical Agent's core runtime uses two terminals:

```text
Terminal 1: physical-agent watch
Terminal 2: physical-agent run --task "..."
```

In the first terminal, start the physical-side watch process:

```bash
physical-agent watch
```

Keep this terminal running. It loads drivers, publishes capabilities, watches actions, and executes them.

In a second terminal, submit a task:

```bash
physical-agent run --task "pick the red block and place it on the tray"
```

If watch is running, you should see a completed task and feedback similar to:

```text
Task completed.
Actions:
- act_001: arm_1.pick object_id: red_block
- act_002: arm_1.place target: tray
Feedback:
- act_001: completed - Picked red_block.
- act_002: completed - Placed red_block on tray.
```

### Step 4: Inspect the Workspace

After running a task, inspect the current state:

```bash
physical-agent inspect
```

You should see the connected mock robot, no pending actions, completed actions, and latest feedback.

You can also open the Markdown protocol files directly:

```text
workspace/
  TASK.md
  CAPABILITIES.md
  WORLD.md
  ACTIONS.md
  FEEDBACK.md
  SAFETY.md
  LOG.md
```

Those files are the communication protocol between the agent and watch.

### Step 5: Run Health Checks

If something does not work, start with:

```bash
physical-agent doctor
```

Common cases:

- `No capabilities are available yet`: `physical-agent watch` has not started or did not publish `CAPABILITIES.md`.
- `No feedback arrived before the timeout`: the agent wrote actions, but watch is not running to execute them.
- `Workspace is not initialized`: run `physical-agent setup` or use setup in the GUI.
- To start over: run `physical-agent setup --force --smoke-test`.

### Step 6: Understand the Default Demo

The default `physical-agent.yaml` configures one mock arm:

```yaml
robots:
  arm_1:
    driver: mock_arm
    config:
      objects:
        red_block:
          type: block
          color: red
          location: table
        tray:
          type: tray
          location: table
```

So this task:

```text
pick the red block and place it on the tray
```

is turned by the local rule-based planner into two actions:

```text
arm_1.pick(object_id=red_block)
arm_1.place(target=tray)
```

watch validates both actions and then calls the `mock_arm` driver. No real robot is involved.

### Step 7: Where to Go Next

After quickstart works:

1. To understand communication, inspect `workspace/*.md`.
2. To understand hardware onboarding, read the "Driver Contract" section.
3. To see a Xiaozhi MCP bridge example, read `docs/xiaozhi-driver-tutorial.zh-CN.md`.
4. To start from an SDK or GitHub repo, run `physical-agent integrate ./vendor_sdk`.

## Local GUI

`physical-agent gui` starts a dependency-free local web console backed by Python's standard library HTTP server.

The console provides:

- project setup
- workspace reset
- watch runtime connection
- one-step action execution
- multi-turn chat
- English and Chinese UI switching
- hardware integration scaffold generation
- task submission
- pick/place quick demo
- doctor checks
- robot, world, action board, and feedback views

The GUI remembers your language choice in the browser. Use the `English` / `中文` buttons in the top bar to switch modes.

By default it binds to `127.0.0.1:8765`:

```bash
physical-agent gui --port 8765
```

Run without opening a browser automatically:

```bash
physical-agent gui --no-open
```

The Hardware integration panel accepts a local SDK path, a GitHub repository URL, or an importable Python package name. It generates a watch-side driver scaffold and integration notes; it does not execute hardware from the browser.

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
  CHAT.md
  PLAN.md
  MEMORY.md
  artifacts/
```

`TASK.md` records the active task and human constraints.

`CAPABILITIES.md` is written by watch from loaded driver capabilities. The agent treats it as read-only.

`WORLD.md` is written by watch from driver observations. It contains robot state, objects, environment data, and artifact paths.

`ACTIONS.md` is written by the agent. It contains pending, completed, and cancelled action boards. Watch reads pending actions and moves them after execution or safety rejection.

`FEEDBACK.md` is written by watch. It records latest execution feedback and history for the agent to read.

`SAFETY.md` is owned by humans and enforced by watch. The agent can read it but cannot bypass it.

`LOG.md` is an audit log for human review.

`CHAT.md` stores chat history between the human and the agent.

`PLAN.md` stores the current chat intent, proposed steps, and proposed actions.

`MEMORY.md` stores small persistent notes that the chat agent should remember across turns.

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

If your teammate already has a GitHub repo, local SDK checkout, or mature Python package, let Physical Agent create the first integration draft:

```bash
physical-agent integrate ./vendor_sdk --name my_device_driver
physical-agent integrate https://github.com/org/device-sdk --name my_device_driver
physical-agent chat --message "帮我接入 ./vendor_sdk"
```

The integration assistant scans docs and project metadata, infers a transport such as serial, HTTP, WebSocket, MQTT, gRPC, MCP, or SDK, then generates:

```text
physical-agent-integration/my_device_driver/
  physical_driver.yaml
  driver.py
  README.md
  README.zh-CN.md
  integration-report.md
```

The generated driver stays in mock mode first. A human engineer still needs to replace the TODO branches in `driver.py` with the real SDK calls and add focused tests for the hardware. The agent can help write that code, but the runtime boundary stays the same: the generated driver is loaded only by watch, and actions still go through `ACTIONS.md`, safety validation, and `driver.execute(action)`.

For a hardware onboarding example based on a Xiaozhi MCP bridge, see:

```text
examples/xiaozhi_mcp_hardware/
```

Use it from `physical-agent.yaml`:

```yaml
robots:
  arm_1:
    driver: ./my_arm_driver
    config: {}
```

The example shows a safe path from `mode: mock` to `mode: http`, with a `.env.example` file for `XIAOZHI_MCP_ENDPOINT` and optional `XIAOZHI_MCP_TOKEN`.

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

If you are onboarding a teammate to a Xiaozhi MCP-style hardware bridge, start with:

```text
examples/xiaozhi_mcp_hardware/README.md
```

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
GPT_MODEL=gpt-5.4
```

Supported variable names:

- API key: `GPT_KEY` or `OPENAI_API_KEY`
- Base URL: `GPT_URL` or `OPENAI_BASE_URL`
- Model: `GPT_MODEL` or `OPENAI_MODEL`

Test the API connection:

```bash
physical-agent llm-test
```

Test a specific model before changing your project defaults:

```bash
physical-agent llm-test --model gpt-5.4
physical-agent chat --planner llm --model gpt-5.4 --message "Say hello in one sentence."
```

If a model test fails but another model works, keep `GPT_MODEL` on the working model. OpenAI-compatible providers do not always expose every model name, even when their HTTP shape is compatible.

Use the LLM planner:

```bash
physical-agent setup --force
physical-agent run --planner llm --task "pick the red block and place it on the tray" --no-wait
physical-agent inspect
```

Use the full chat agent:

```bash
physical-agent setup --force
physical-agent chat
```

Or send one message and exit:

```bash
physical-agent chat --message "What can you see right now?"
physical-agent chat --planner llm --auto-step --message "Please pick the red block and place it on the tray."
```

The chat command defaults to `--planner auto`: it uses the LLM planner when `.env` contains API settings and falls back to rule-based chat otherwise. The chat agent reads `CHAT.md`, `MEMORY.md`, `CAPABILITIES.md`, `WORLD.md`, and `FEEDBACK.md`. It writes replies back to `CHAT.md`, writes its current intent to `PLAN.md`, and writes proposed actions to `ACTIONS.md`. Watch still validates and executes those actions.

When chat prints `LLM chat was unavailable`, the framework did not crash. It means `--planner auto` tried the API first and then used the local rule-based fallback. Common causes:

- `HTTP 503`: the upstream provider is temporarily unavailable.
- `HTTP 429`: the provider is rate limiting the key or upstream model.
- `SSL: UNEXPECTED_EOF_WHILE_READING`: the provider closed the TLS connection early, often due to gateway instability or an unsupported route/model.
- `model not found` or provider-specific errors: set `GPT_MODEL` to a model name your provider actually supports.

Use `physical-agent llm-test --model <model-name>` to verify a candidate model. If you want strict API behavior with no fallback, run chat with `--planner llm`; if you want the CLI to stay usable during API outages, keep the default `--planner auto`.

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
  model: gpt-5.4
```

## Clean-Room Implementation

Physical Agent is an independent implementation. It uses general public architecture ideas such as embodied-agent layering, watchdog/runtime separation, declarative driver manifests, Markdown workspace protocols, and MCP-style tool facades. It does not include third-party competitor code, copied file contents, copied README wording, copied CLI design, copied example task suites, or copied implementation details.

## Development Checks

Run the full test suite:

```bash
pytest -q
```

Current coverage includes Markdown protocol parsing/rendering, workspace lifecycle, driver manifest and loader behavior, hardware onboarding scaffold generation, safety validation, mock drivers, rule-based planning, watch runtime stepping, the end-to-end Markdown loop, one-command setup, doctor checks, and GUI HTTP endpoints.

It also covers the chat protocol, chat memory, chat action proposals, chat auto-step execution, and the GUI chat endpoint.
