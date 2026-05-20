# Physical Agent

[English version](README.md)

Physical Agent 是一个面向安全物理世界 agent 的 Markdown 原生运行时。

它的第一版不是为了堆很多功能，而是为了把认知侧 agent、物理侧执行进程、driver 接入协议和安全边界拆清楚。核心原则是：

```text
Agent can propose actions. Watch decides whether and how they touch the physical world.
```

也就是说：agent 可以提出动作意图，但只有 watch 进程可以决定动作是否以及如何触达真实物理世界。

## 核心架构

Physical Agent v1 采用双进程架构：

```text
Terminal 1: physical-agent watch
Terminal 2: physical-agent run --task "..."
Workspace: Markdown files are the protocol between cognition and execution.
```

`physical-agent watch` 是物理侧守护进程，负责：

- 读取 `physical-agent.yaml`
- 初始化 workspace
- 加载机器人或硬件 driver
- 连接硬件或 simulator
- 发布 `CAPABILITIES.md`
- 持续更新 `WORLD.md`
- 监听 `ACTIONS.md`
- 在执行前进行安全校验
- 调用 driver 执行动作
- 写入 `FEEDBACK.md`
- 追加 `LOG.md`

`physical-agent run` 是认知侧 agent 主程序，负责：

- 写入当前任务到 `TASK.md`
- 读取 `CAPABILITIES.md`
- 读取 `WORLD.md`
- 读取 `FEEDBACK.md`
- 生成结构化动作意图
- 写入 `ACTIONS.md`
- 等待 watch 执行反馈
- 根据反馈继续、停止或调整计划

两个进程不直接调用彼此。它们之间唯一的 v1 通信协议是 `workspace/*.md`。

## 快速开始

这一节按“新手第一次打开项目”的顺序写。默认 quickstart 使用内置 `mock_arm` 模拟机械臂，不需要真实硬件，也不需要 LLM API key。

### 第 0 步：确认你有什么

你需要：

- Python 3.11 或更高版本
- 一个终端
- 当前仓库代码

先进入项目根目录：

```bash
cd Physical_Agent
```

如果你已经在仓库根目录，可以跳过这一步。仓库根目录应该能看到 `pyproject.toml`、`physical_agent/`、`examples/` 和 `README.zh-CN.md`。

### 第 1 步：安装并初始化项目

推荐新手直接运行 bootstrap：

```bash
python scripts/bootstrap.py
```

这条命令会自动完成：

- 创建本地虚拟环境 `.venv`
- 安装项目和开发依赖
- 运行测试
- 生成默认 `physical-agent.yaml`
- 初始化 `workspace/`
- 运行一次 smoke test，验证 mock 机械臂能把 `red_block` 放到 `tray`

如果你已经自己管理 Python 环境，也可以手动运行：

```bash
pip install -e .[dev]
physical-agent setup --smoke-test
```

看到类似下面的输出，就说明项目已经准备好了：

```text
Physical Agent project is ready.
Config: .../physical-agent.yaml
Workspace: .../workspace
Smoke test passed: executed 2 action(s), red_block location is tray.
```

### 第 2 步：先用 GUI 跑通一遍

对新手来说，GUI 是最容易理解 workspace 状态的入口：

```bash
physical-agent gui
```

浏览器会打开本地控制台。你可以在 GUI 里完成这些动作：

1. 点击 setup 或 reset，准备 workspace。
2. 点击 watch start，连接 mock robot。
3. 点击 quick demo，提交 pick/place 示例任务。
4. 点击 step 或 auto-step，让 watch 执行动作。
5. 查看 robots、world、actions、feedback 的变化。

如果浏览器没有自动打开，可以手动访问：

```text
http://127.0.0.1:8765
```

GUI 里最重要的理解点是：

```text
CAPABILITIES.md 告诉 agent 当前有哪些能力。
ACTIONS.md 是 agent 提交的动作队列。
FEEDBACK.md 是 watch 执行后的结果。
WORLD.md 是 watch 更新后的世界状态。
```

### 第 3 步：用 CLI 理解双进程模式

GUI 跑通后，再看 CLI 会更清楚。Physical Agent 的核心运行方式是两个终端：

```text
Terminal 1: physical-agent watch
Terminal 2: physical-agent run --task "..."
```

第一个终端启动物理侧 watch：

```bash
physical-agent watch
```

watch 会一直运行，负责加载 driver、发布能力、监听动作、执行动作。不要关闭这个终端。

第二个终端提交任务：

```bash
physical-agent run --task "pick the red block and place it on the tray"
```

如果 watch 正在运行，你会看到任务完成，并且有类似这样的反馈：

```text
Task completed.
Actions:
- act_001: arm_1.pick object_id: red_block
- act_002: arm_1.place target: tray
Feedback:
- act_001: completed - Picked red_block.
- act_002: completed - Placed red_block on tray.
```

### 第 4 步：查看 workspace 状态

执行后可以查看当前状态：

```bash
physical-agent inspect
```

你应该能看到：

```text
Robots:
- arm_1: arm via mock_arm (...)

World summary:
...

Pending actions:
- none

Completed actions:
- act_001: arm_1.pick
- act_002: arm_1.place

Latest feedback:
...
```

也可以直接打开 `workspace/` 目录里的 Markdown 文件：

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

这几个文件就是 agent 和 watch 之间的通信协议。

### 第 5 步：做健康检查

如果遇到问题，先运行：

```bash
physical-agent doctor
```

它会检查配置、workspace、driver、依赖等基础状态。

常见情况：

- `No capabilities are available yet`：还没有启动 `physical-agent watch`，或者 watch 没有成功发布 `CAPABILITIES.md`。
- `No feedback arrived before the timeout`：agent 已经写入动作，但 watch 没在运行，所以没人执行。
- `Workspace is not initialized`：先运行 `physical-agent setup` 或 `physical-agent gui` 里的 setup。
- 想重新开始：运行 `physical-agent setup --force --smoke-test`。

### 第 6 步：理解默认 quickstart 做了什么

默认 `physical-agent.yaml` 配置了一个 mock 机械臂：

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

所以这个任务：

```text
pick the red block and place it on the tray
```

会被本地 rule-based planner 转成两个 action：

```text
arm_1.pick(object_id=red_block)
arm_1.place(target=tray)
```

watch 会检查这两个 action 是否安全、参数是否满足 schema，然后调用 `mock_arm` driver 执行。整个过程不需要真实机械臂。

### 第 7 步：下一步看什么

跑通 quickstart 后，建议按这个顺序继续看：

1. 想理解 agent 和 watch 如何通信：看 `workspace/*.md`。
2. 想理解 driver 如何接入硬件：看“Driver Contract”章节。
3. 想看小智 MCP 接入：看 `docs/xiaozhi-driver-tutorial.zh-CN.md`。
4. 想接真实设备：先用 `physical-agent driver new my_driver` 生成模板。

## 本地 GUI

`physical-agent gui` 会启动一个零前端构建依赖的本地 Web 控制台，底层使用 Python 标准库 HTTP server。

GUI 提供：

- 项目 setup
- workspace reset
- watch runtime 连接
- 单步执行 pending actions
- 多轮 chat
- 中英文 UI 切换
- 提交任务
- pick/place quick demo
- doctor 健康检查
- robots、world、action board、feedback 状态视图

GUI 会在浏览器里记住你的语言选择。点击顶部的 `English` / `中文` 即可切换界面语言。

默认监听 `127.0.0.1:8765`：

```bash
physical-agent gui --port 8765
```

不自动打开浏览器：

```bash
physical-agent gui --no-open
```

## Markdown Workspace Protocol

workspace 是动态协议状态，不是普通调试输出。

默认结构：

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

所有协议 Markdown 文件都使用 YAML front matter。正文可以包含自然语言摘要，但所有机器可读数据都放在 fenced YAML code block 中。

`TASK.md` 记录当前任务和人类约束，由人类或 agent 写入。

`CAPABILITIES.md` 由 watch 根据 driver capabilities 自动生成，agent 只读。

`WORLD.md` 由 watch 持续更新，包含机器人状态、物体状态、环境状态和 artifact 路径。

`ACTIONS.md` 由 agent 写入，包含 pending、completed、cancelled 三个动作区。watch 从 pending 中读取动作，执行或拒绝后移动到 completed 或 cancelled。

`FEEDBACK.md` 由 watch 写入，记录最新 action 反馈和历史反馈。

`SAFETY.md` 由人类拥有，watch 读取并强制执行。agent 可以读取，但不能绕过。

`LOG.md` 是审计日志，watch 和 agent 都可以追加记录。

`CHAT.md` 保存人类和 agent 的多轮聊天历史。

`PLAN.md` 保存当前 chat intent、步骤和 proposed actions。

`MEMORY.md` 保存 chat agent 跨轮次记住的小型持久 notes。

静态启动配置放在 `physical-agent.yaml`。动态运行状态放在 Markdown workspace。

## Driver Contract

接入一个机器人或硬件 adapter 只需要两个核心文件：

```text
my_robot_driver/
  physical_driver.yaml
  driver.py
```

`physical_driver.yaml` 是 manifest，声明 driver 名称、版本、入口类、机器人类型、配置 schema、依赖和 capability contract。

`driver.py` 实现 adapter，需要继承 `PhysicalDriver`。driver 的职责是把结构化 `Action` 转换为硬件或 simulator 调用，并把设备状态转换为 `Observation`。

关键边界：

- driver 只和 `physical-agent watch` 交互
- driver 不解析 Markdown
- driver 不调用 agent runtime
- agent 不导入 driver
- agent 不调用硬件 SDK
- watch 是唯一能够执行物理动作的进程

生成本地 driver 模板：

```bash
physical-agent driver new my_arm_driver
```

在 `physical-agent.yaml` 中使用本地 driver：

```yaml
robots:
  arm_1:
    driver: ./my_arm_driver
    config: {}
```

## 内置 Drivers

`mock_arm` 是内置机械臂 simulator，支持：

- `observe`
- `move_to`
- `pick`
- `place`

它维护模拟状态，包括末端位姿、当前抓取物体和 workspace 中的物体。默认 quickstart 中包含 `red_block` 和 `tray`。

`mock_rover` 是内置 rover simulator，支持：

- `observe`
- `move_to`

它用于证明架构不只适用于机械臂，也可以支持其他类型设备。

“小智 MCP”式硬件接入：

```text
examples/xiaozhi_mcp_hardware/README.zh-CN.md
```

## Safety Gate

watch 在执行任何 action 前都会进行安全校验：

- action 指定的 robot 是否存在
- capability 是否存在于该 robot 的 capabilities 中
- params 是否满足 capability 的 JSON schema
- capability constraints 是否被满足
- `SAFETY.md` 是否允许执行
- 是否需要 human approval
- action id 是否重复执行
- `depends_on` 是否已经 completed

如果校验失败，watch 不会调用 driver，而是写入 `FEEDBACK.md`、追加 `LOG.md`，并将该 action 从 pending 移出。

## Rule-Based Planner

v1 默认 planner 是本地 deterministic planner，不需要 API key。

它支持简单任务映射：

- `observe`、`look`、`scan` -> `observe`
- `move`、`go` -> `move_to`
- `pick`、`grasp` -> `pick`
- `place`、`drop` -> `place`

例如任务：

```text
pick the red block and place it on the tray
```

会生成一个 `pick` action 和一个依赖前者完成的 `place` action。

## OpenAI 兼容 API Planner

Physical Agent 可以使用 OpenAI-compatible Chat Completions 接口做规划，同时保持原有安全边界：LLM 只负责把任务转换成 action intent 并写入 `ACTIONS.md`，真正执行仍然由 watch 侧 safety gate 和 driver 完成。

在项目根目录创建本地 `.env` 文件。该文件已被 git 忽略，不会提交到仓库。

```bash
GPT_URL=https://your-provider.example/v1
GPT_KEY=your_api_key
GPT_MODEL=gpt-4o-mini
```

支持的变量名：

- API key：`GPT_KEY` 或 `OPENAI_API_KEY`
- Base URL：`GPT_URL` 或 `OPENAI_BASE_URL`
- Model：`GPT_MODEL` 或 `OPENAI_MODEL`

测试 API 连通性：

```bash
physical-agent llm-test
```

在修改项目默认模型前，先单独测试某个模型：

```bash
physical-agent llm-test --model gpt-5.4
physical-agent chat --planner llm --model gpt-5.4 --message "Say hello in one sentence."
```

如果某个模型失败，但另一个模型能正常返回，就把 `GPT_MODEL` 保持在可用模型上。OpenAI-compatible 服务只代表 HTTP 接口形状兼容，并不代表它一定支持所有模型名。

使用 LLM planner：

```bash
physical-agent setup --force
physical-agent run --planner llm --task "pick the red block and place it on the tray" --no-wait
physical-agent inspect
```

使用完整 chat agent：

```bash
physical-agent setup --force
physical-agent chat
```

也可以发送一条消息后退出：

```bash
physical-agent chat --message "What can you see right now?"
physical-agent chat --planner llm --auto-step --message "Please pick the red block and place it on the tray."
```

chat 命令默认使用 `--planner auto`：如果 `.env` 里有 API 配置就使用 LLM planner，否则回退到 rule-based chat。chat agent 会读取 `CHAT.md`、`MEMORY.md`、`CAPABILITIES.md`、`WORLD.md` 和 `FEEDBACK.md`。它会把回复写回 `CHAT.md`，把当前意图写入 `PLAN.md`，把 proposed actions 写入 `ACTIONS.md`。真正执行仍然由 watch 校验并完成。

如果 chat 打印 `LLM chat was unavailable`，不是框架崩了，而是 `--planner auto` 先尝试 API，失败后自动使用了本地 rule-based fallback。常见原因：

- `HTTP 503`：上游服务商临时不可用。
- `HTTP 429`：服务商对 key 或上游模型限流。
- `SSL: UNEXPECTED_EOF_WHILE_READING`：服务商提前关闭 TLS 连接，常见于网关不稳定或 route/model 不支持。
- `model not found` 或服务商自定义错误：把 `GPT_MODEL` 改成该服务商实际支持的模型名。

使用 `physical-agent llm-test --model <model-name>` 验证候选模型。如果你希望 API 失败时直接报错，用 `--planner llm`；如果希望 API 波动时 CLI 仍然可用，保留默认 `--planner auto`。

在另一个终端运行 watch 执行动作：

```bash
physical-agent watch
```

也可以用单步模式做本地快速检查：

```bash
python -c "import asyncio; from physical_agent.watch.runtime import WatchRuntime; r=WatchRuntime('physical-agent.yaml'); asyncio.run(r.setup()); print('executed', asyncio.run(r.step(setup=False)))"
physical-agent inspect
```

如果希望默认使用 LLM planner，可以编辑 `physical-agent.yaml`：

```yaml
agent:
  planner: llm
  model: gpt-4o-mini
```

## MCP 扩展点

项目中包含一个轻量的 MCP-shaped facade：

```text
physical_agent/mcp/server.py
```

它提供可扩展结构：

- `submit_task`
- `get_state`
- `list_robots`
- `run_action`

v1 不把完整 MCP 依赖放进核心运行时，避免影响 watch/agent/Markdown loop 的稳定性。后续可以在此基础上接入真实 MCP server 库。

## 开发与测试

安装开发依赖：

```bash
pip install -e .[dev]
```

运行测试：

```bash
pytest -q
```

测试覆盖包括：

- Markdown front matter 和 fenced YAML parser/renderer
- workspace 初始化、revision 递增、log append
- driver manifest 和 config schema 校验
- built-in driver 与本地 driver loader
- safety gate 拒绝路径
- mock arm pick/place 状态变化
- rule-based planner
- watch runtime step
- 端到端 Markdown loop
- 一键 setup 与 smoke test
- doctor 健康检查
- GUI HTTP endpoints
- chat protocol、chat memory、chat action proposals
- chat auto-step execution 和 GUI chat endpoint

## Clean-Room 声明

Physical Agent 是一个独立实现。它使用了公开、通用的架构思想，例如 embodied-agent 分层、watch/runtime 分离、声明式 driver manifest、Markdown workspace protocol 和 MCP-style tool facade。

本项目不包含第三方竞品代码、文件内容复制、README 表述复刻、CLI 设计复刻、示例任务复刻或具体实现复制。
