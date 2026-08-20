# Xiaozhi MCP Hardware Example

This example shows how to connect a Xiaozhi MCP-style device to Physical Agent.

The important boundary is simple:

```text
agent writes intent into Markdown workspace files.
watch loads the driver, enforces safety, and talks to hardware or the MCP bridge.
```

This folder is a complete two-file driver example. It contains:

```text
physical_driver.yaml
driver.py
```

The example driver is `xiaozhi_mcp`. It supports:

- `mock` mode for local end-to-end testing without hardware
- `http` mode for a real MCP endpoint
- `ws` mode for a robot that exposes a local WebSocket MCP socket directly

In D1, `ws` mode uses the shared watch-side
`physical_agent.drivers.transport.WebSocketTransport`. The transport remains an
implementation detail of the driver/watch side; agent, API, and GUI flows still
submit proposals only.

## Layout

```text
examples/xiaozhi_mcp_hardware/
  physical_driver.yaml
  driver.py
  physical-agent.yaml
  .env.example
  README.md
```

## Quick Start

From the repository root:

```bash
physical-agent init
```

If you want to run this example as a standalone project, copy this folder into your own project and keep the same relative path, or change `driver:` in `physical-agent.yaml` to match where you place the folder.

Then initialize the workspace:

```bash
physical-agent init
```

## Run in Mock Mode First

The example config defaults to:

```yaml
robots:
  xiaozhi_1:
    driver: xiaozhi_mcp
    config:
      mode: mock
```

Start watch:

```bash
physical-agent watch
```

In another terminal, submit a task:

```bash
physical-agent run --task "ask the device to say hello"
```

Or:

```bash
physical-agent run --task "turn the light red"
```

The rule-based planner will turn the request into structured actions, and watch will execute them.

## Connect Real Xiaozhi MCP Hardware

If your robot exposes MCP directly over LAN WebSocket, such as
`ws://192.168.66.237:8080/ws`, prefer `mode: ws`:

```yaml
robots:
  xiaozhi_1:
    driver: .
    config:
      mode: ws
      wait_for_responses: false
```

Then set either a full URL:

```env
XIAOZHI_MCP_URL=ws://192.168.66.237:8080/ws
```

or split host/port/path values:

```env
XIAOZHI_MCP_HOST=192.168.66.237
XIAOZHI_MCP_PORT=8080
XIAOZHI_MCP_PATH=/ws
```

Some devices accept tool calls but do not return standard responses for
`initialize` or `tools/list`. In that case, keep `wait_for_responses: false`
so watch uses fire-and-forget control.

WebSocket reconnect is opt-in. To enable communication-level reconnect:

```yaml
reconnect_policy:
  enabled: true
  max_retries: 3
  backoff_base_ms: 250
  backoff_cap_ms: 5000
  jitter_ms: 0
```

Reconnect does not replay old actions. Commands attempted while the transport is
reconnecting fail fast, and after reconnect the next observe/health pass is still
the source of truth for robot state.

If your MCP bridge exposes an HTTP JSON-RPC endpoint instead, use `mode: http`
and keep the original endpoint-based configuration:

Copy `.env.example` to `.env` and fill in the real endpoint:

```env
XIAOZHI_MCP_ENDPOINT=http://your-mcp-bridge
XIAOZHI_MCP_TOKEN=if-needed
```

SerialTransport, ServoBus, hardware watchdog, and E-stop behavior are not part
of D1. For serial or other non-WebSocket hardware, keep the Physical Agent
request side unchanged and add a watch-side driver or bridge until those later
layers exist.

## What the Driver Does

`xiaozhi_mcp` handles:

- `observe` to inspect the device state
- `set_volume` to set the device speaker volume
- `otto_action` to run motions such as `hand_wave`, `walk`, `turn`, or `jump`
- `home` to return the robot to its home pose
- `stop` to stop the current motion

Those capabilities are published into `CAPABILITIES.md`, so the agent only sees Markdown and never touches hardware directly.

## What Integrators Should Remember

```text
1. Start from physical-agent.yaml.
2. Keep hardware logic in the watch-side driver.
3. Begin with mock mode.
4. Switch .env to the real MCP endpoint only after the mock flow works.
5. Keep transport usage on the watch/driver side.
6. The agent, API, and GUI only write workspace proposals.
```

## Troubleshooting Order

If execution does not happen, check:

1. `physical-agent doctor`
2. `physical-agent inspect`
3. `workspace/CAPABILITIES.md`
4. `workspace/ACTIONS.md`
5. `workspace/FEEDBACK.md`

Typical causes:

- `XIAOZHI_MCP_ENDPOINT` is missing
- the MCP bridge is not running
- the token is wrong
- the bridge is not HTTP JSON-RPC, so a thin adapter is needed

## Migrating This Example to Real Hardware

You can copy `examples/xiaozhi_mcp_hardware/` as a starting point and then:

1. Replace `xiaozhi_mcp` with your real driver name.
2. Update `tools` to match the MCP tool names your device exposes.
3. Replace `observe`, `set_volume`, `otto_action`, `home`, and `stop` with your actual capability set.
4. Keep any custom communication layer inside the watch-side driver. WebSocket mode already uses the shared `WebSocketTransport`.

In practice, integrators only need two files:

```text
physical_driver.yaml
driver.py
```

That is the Physical Agent Two-file Driver Protocol.
