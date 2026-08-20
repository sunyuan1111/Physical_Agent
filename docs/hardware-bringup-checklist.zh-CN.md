# 真实硬件 Bring-up 清单

本文面向准备把 Physical Agent 接到真实设备的人。它不是开发 session 记录，而是一份上电前、启动前和首轮低风险验证的操作清单。

## 先记住架构边界

推荐执行链路固定为：

```text
agent / gui / chat / api
  -> StateStore pending action
  -> watch
  -> SafetyGate
  -> driver.execute(action)
  -> hardware / simulator
```

含义：

- `agent`、`chat`、GUI 和 HTTP API 只提交 proposal 或 pending action。
- 请求侧不直接加载 driver，不直接调用硬件 SDK，不直接调用 `driver.execute()`。
- `watch` 是唯一硬件执行侧；它负责加载 driver、连接设备、运行 `SafetyGate`、调用 `driver.execute(action)`。
- API 如显式使用 `physical-agent api --watch`，后台执行仍走 watch service，不是 endpoint 直接执行 driver。
- watchdog、heartbeat、halt 也是 watch-side hook，不是请求侧硬件入口。

## 当前状态

- 新项目默认使用 SQLite backend，运行态状态写入 `workspace/state.db`。
- `workspace.backend: markdown` 已退役；显式配置会被拒绝，并提示先运行 `migrate-md-to-sqlite` 再改成 `workspace.backend: sqlite`。
- 如果配置省略 `workspace.backend`，且目标 workspace 已存在完整 legacy Markdown 协议文件，当前代码也会拒绝自动探测，不会打开旧 backend。
- `SAFETY.md` 仍是文件真源。即使默认状态 backend 是 SQLite，watch 执行前仍读取并强制执行 `SAFETY.md`。
- GUI/API/agent/chat 只提交动作提案，不直接执行硬件。
- 上传文件、memory、retrieval chunk 只能作为不可信上下文；它们不是安全事实，也不能替代 `SAFETY.md`、人工确认或硬件急停。
- 软件 reconnect 只是通信恢复能力，不等于机器人状态安全；reconnect 后首轮应先跑 `observe`/`health`，必要时人工确认。

## 环境准备命令

在仓库根目录执行。Windows PowerShell 示例：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -U pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev,server]"
```

如果要接串口设备，并且 driver 需要 `pyserial`：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,server,serial]"
```

基础验证：

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\test_safety_boundaries.py tests\test_backend_matrix.py::test_load_config_rejects_legacy_markdown_workspace_when_backend_omitted
```

时间允许时再跑全量：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

## 只读检查命令

先确认配置和 workspace 状态：

```powershell
.\.venv\Scripts\physical-agent.exe state-check --config physical-agent.yaml
.\.venv\Scripts\physical-agent.exe doctor --config physical-agent.yaml
.\.venv\Scripts\physical-agent.exe inspect --config physical-agent.yaml
```

含义：

- `state-check` 检查 backend、workspace 初始化状态、SQLite schema、audit export 可写性。
- `doctor` 检查配置、workspace、driver manifest 和 driver load 健康状况。
- `inspect` 读取当前能力、世界状态和 pending actions，不执行动作。

如果这些检查失败，先修配置、路径、权限或 workspace，不要启动真实硬件 watch。

## Mock quickstart smoke

先用 mock 证明软件链路能跑通：

```powershell
New-Item -ItemType Directory .tmp\bringup-smoke -Force | Out-Null
.\.venv\Scripts\physical-agent.exe setup --config .tmp\bringup-smoke\physical-agent.yaml --force --smoke-test
.\.venv\Scripts\physical-agent.exe inspect --config .tmp\bringup-smoke\physical-agent.yaml
```

期望看到 pick/place smoke test 通过，且 pending actions 为空。这只验证 simulator 链路，不代表真实硬件已经安全。

## API 和 GUI 启动

GUI：

```powershell
.\.venv\Scripts\physical-agent.exe gui --config physical-agent.yaml --no-open --port 8765
```

FastAPI 后端，默认不启动 watch：

```powershell
.\.venv\Scripts\physical-agent.exe api --config physical-agent.yaml --host 127.0.0.1 --port 8766
```

如果显式要让 API 进程同时带后台 watch：

```powershell
.\.venv\Scripts\physical-agent.exe api --config physical-agent.yaml --host 127.0.0.1 --port 8766 --watch
```

建议真实硬件 bring-up 初期把 watch 放在单独终端运行，便于看日志和随时 Ctrl+C。

## Watch 启动

真实硬件前，先确认 `physical-agent.yaml` 指向正确 driver、workspace 和 backend。然后单独终端启动：

```powershell
.\.venv\Scripts\physical-agent.exe watch --config physical-agent.yaml
```

另开终端检查状态：

```powershell
.\.venv\Scripts\physical-agent.exe inspect --config physical-agent.yaml
```

不要在未确认电源、急停、空间和人员状态前，通过 GUI/API/CLI 提交运动动作。

## 真实硬件 bring-up 顺序

上电前：

1. 确认设备固定、运动空间清空，旁边有人值守。
2. 确认物理急停、断电方案、保险丝或电源开关可立即触达。
3. 确认电源电压、电流限制、地线、通信线、端口方向和机械限位。
4. 确认串口、USB、IP、WebSocket 或 HTTP endpoint 是当前设备，不是旧设备或 simulator。
5. 确认系统权限：Windows 设备管理器端口、Linux `dialout` 组、串口 by-id 路径或网络防火墙。
6. 确认 `.env` 和环境变量只包含连接信息或模型 key，不把它们提交到 Git。
7. 确认 `SAFETY.md` 内容符合当前硬件，不要沿用 mock workspace 的安全说明。

启动前：

1. 先跑 `doctor`。
2. 再跑 `state-check`。
3. 再跑 `inspect`。
4. 确认能力列表只包含你准备验证的能力。
5. 确认 pending actions 为空；如果有旧 pending action，先清理 workspace 或新建 workspace。

首轮执行：

1. 启动 `watch`。
2. 先只做 `observe`、`status`、`stop`、`health` 这类低风险能力。
3. 看 `inspect`、`FEEDBACK` 和日志，确认 watch 写回正常。
4. 再做小幅、单步、人工确认动作，例如单关节很小角度、夹爪小范围开合、音量/灯光/说话等低风险 tool。
5. 每次只提交一个动作，观察完成后再继续。
6. 禁止一上来跑大幅运动、复杂 pick/place、多步任务、自动循环任务或带不确定目标的自然语言任务。

## 小智 xiaozhi 准备小节

参考：

- `examples/xiaozhi_mcp_hardware/README.zh-CN.md`
- `docs/xiaozhi-driver-tutorial.zh-CN.md`

配置重点：

- `examples/xiaozhi_mcp_hardware/physical-agent.yaml` 当前示例 robot 是 `xiaozhi_1`。
- 配置 `device_name`，让 `inspect` 和日志中能辨认真实设备。
- `mode: ws` 适合局域网 WebSocket MCP，例如通过 `XIAOZHI_MCP_URL=ws://<ip>:8080/ws`。
- 也可以用 `XIAOZHI_MCP_HOST`、`XIAOZHI_MCP_PORT`、`XIAOZHI_MCP_PATH` 拆分配置。
- `mode: http` 适合 HTTP JSON-RPC 网关，使用 `XIAOZHI_MCP_ENDPOINT` 和可选 `XIAOZHI_MCP_TOKEN`。
- 如果设备只接受工具调用、不返回标准响应，保持 `wait_for_responses: false`。

建议顺序：

```powershell
.\.venv\Scripts\physical-agent.exe doctor --config examples\xiaozhi_mcp_hardware\physical-agent.yaml
.\.venv\Scripts\physical-agent.exe state-check --config examples\xiaozhi_mcp_hardware\physical-agent.yaml
.\.venv\Scripts\physical-agent.exe inspect --config examples\xiaozhi_mcp_hardware\physical-agent.yaml
.\.venv\Scripts\physical-agent.exe watch --config examples\xiaozhi_mcp_hardware\physical-agent.yaml
```

先测低风险能力：

- `observe` 或设备状态查询。
- `stop`，前提是 tool 映射确认是安全停止能力。
- `say`、`set_volume`、低风险灯光或当前设备已知安全 tool。

不要第一步就测试 `walk`、`turn`、`wave` 或复杂组合动作。只有在确认空间、电源、急停、tool 映射和 feedback 都正常后，再用小幅、单步、人工确认动作。

## Moce / MomoAgent 准备小节

参考：

- `examples/moce_arm/README.md`
- `examples/moce_arm/README.zh-CN.md`
- `examples/moce_arm/physical-agent.yaml`
- `examples/moce_arm/physical-agent.partial-hardware.yaml`

配置重点：

- mock 配置使用 `mode: mock`，适合先验证 driver load、capabilities、observe 和 action proposal。
- partial hardware 配置使用 `mode: hardware` 与 `hardware_profile: partial`，当前示例面向 `wrist_roll` 和 `gripper`。
- 确认 MomoAgent SDK checkout 路径，例如 `sdk_repo`。
- 确认 runtime YAML 路径，例如 `runtime_config`。
- 确认串口路径，优先使用稳定的 `/dev/serial/by-id/...`，再确认它实际指向的 `/dev/ttyACM*` 或 `/dev/ttyUSB*`。
- Linux 下确认当前用户在 `dialout` 组内；不要把 `sudo chmod 777` 当成长期方案。
- mock 到 real mode 的切换点是 config 中的 `mode`、`hardware_profile`、`serial_port`、`runtime_config` 和 SDK 路径。

先跑 mock：

```powershell
.\.venv\Scripts\physical-agent.exe doctor --config examples\moce_arm\physical-agent.yaml
.\.venv\Scripts\physical-agent.exe state-check --config examples\moce_arm\physical-agent.yaml
.\.venv\Scripts\physical-agent.exe inspect --config examples\moce_arm\physical-agent.yaml
```

准备真实 partial hardware 前：

```powershell
.\.venv\Scripts\physical-agent.exe doctor --config examples\moce_arm\physical-agent.partial-hardware.yaml
.\.venv\Scripts\physical-agent.exe state-check --config examples\moce_arm\physical-agent.partial-hardware.yaml
.\.venv\Scripts\physical-agent.exe inspect --config examples\moce_arm\physical-agent.partial-hardware.yaml
```

首轮真实设备只做：

- `observe`
- `stop`
- 小范围 `open_gripper` / `close_gripper`，前提是 raw 值窗口已人工确认安全
- 单关节小角度动作，前提是限位、方向和减速比已确认

不要第一步做完整机械臂 `move_joints`、大角度回零、笛卡尔运动、抓取任务或多步自然语言任务。

## 安全限制

- 软件 watchdog、heartbeat 和 halt 不是硬件急停。
- 软件 reconnect 不能替代硬件急停、断电方案或现场值守；它恢复的是连接，不证明上一条动作安全完成。
- 如果 Python 进程、操作系统、USB、网络、SDK 或固件卡死，软件 halt 可能无法生效。
- 真实机械系统必须有人值守。
- 必须有物理急停或断电方案，且值守人员知道如何使用。
- `SAFETY.md` 是软件安全规则，不替代机械限位、电气保护、固件限速或硬件急停。
- 上传文件、memory、retrieval、聊天历史和模型输出都是不可信上下文，不是安全事实。
- LLM 只能帮助生成 proposal 或 driver 草稿；真实执行仍必须经过 watch 和 `SafetyGate`。

## 可以进入低风险 bring-up 的条件

同时满足以下条件后，才建议进入真实硬件低风险 bring-up：

- 指定 pytest 通过。
- `git diff --check` 通过，当前改动没有格式问题。
- mock quickstart smoke 通过。
- 目标真实配置的 `doctor`、`state-check`、`inspect` 结果可解释。
- `SAFETY.md` 已按真实设备检查。
- 电源、急停、断电、端口、权限和环境变量已确认。
- 现场有人值守，且第一批动作只包含 observe/status/stop 或小幅单步动作。
