# Physical Agent

[English version](README.md)

Physical Agent is a Markdown-native runtime for safe physical-world agents.

Physical Agent 是一个面向安全物理世界 agent 的 Markdown 原生运行时。v1 的重点不是堆功能，而是把认知侧 agent、物理侧 watch、driver 接入协议和安全边界拆清楚。

核心原则：

```text
Agent can propose actions. Watch decides whether and how they touch the physical world.
```

也就是说，agent 可以提出动作意图，但只有 watch 进程可以决定这些动作是否以及如何触达真实物理世界。

## 核心架构

Physical Agent v1 采用双进程架构：

```text
Terminal 1: physical-agent watch
Terminal 2: physical-agent run --task "..."
Workspace: Markdown files are the protocol between cognition and execution.
```

`physical-agent watch` 是物理侧守护进程，负责：

- 读取 `physical-agent.yaml`
- 初始化 `workspace/`
- 加载机器人或硬件 driver
- 连接硬件或 simulator
- 发布 `CAPABILITIES.md`
- 更新 `WORLD.md`
- 监听 `ACTIONS.md`
- 在执行前做 safety gate 校验
- 调用 `driver.execute(action)`
- 写入 `FEEDBACK.md`
- 追加 `LOG.md`

`physical-agent run` 和 `physical-agent chat` 是认知侧入口，负责读取 Markdown workspace、理解任务、生成结构化 action intent，并写入 `ACTIONS.md`。

现在 `physical-agent chat` 也会自动识别代码类请求，比如“修改这个文件”“写测试”“修复这个 bug”“帮我接入这个 SDK”。命中后，它会切换到代码技能：在当前仓库根目录内直接写文件、运行测试、记录 lessons，并返回修改结果。这个能力仍然不改变物理执行边界，真正能接触硬件的只有 `physical-agent watch`。

硬边界：

- agent 不导入 driver
- agent 不直接调用硬件 SDK
- driver 不解析 Markdown
- driver 不调用 agent runtime
- watch 是唯一执行物理动作的路径
- safety gate 必须在 watch 侧执行

## 快速开始

默认 quickstart 使用内置 `mock_arm` simulator，不需要真实硬件，也不需要 LLM API key。

### 1. 安装和初始化

进入仓库根目录：

```bash
cd Physical_Agent
```

推荐一条命令完成环境配置、安装、测试、初始化和 smoke test：

```bash
python scripts/bootstrap.py
```

如果你已经自己管理 Python 环境，也可以手动执行：

```bash
pip install -e .[dev]
physical-agent setup --smoke-test
```

看到类似输出就说明项目可运行：

```text
Physical Agent project is ready.
Config: .../physical-agent.yaml
Workspace: .../workspace
Smoke test passed: executed 2 action(s), red_block location is tray.
```

### 2. 先用 GUI 跑通

GUI 是面向新用户最友好的入口：

```bash
physical-agent gui
```

默认地址：

```text
http://127.0.0.1:8765
```

GUI 里可以做这些事：

- setup / reset workspace
- start watch
- run step
- run pick/place demo
- 使用 chat agent 对话
- 切换 English / 中文
- 查看 robots、world、actions、feedback
- 输入 SDK 路径、GitHub 仓库或 Python 包名生成硬件 driver
- 选择“脚手架”或“LLM 草稿”硬件接入模式

如果不想自动打开浏览器：

```bash
physical-agent gui --no-open
```

### 3. 理解双终端 CLI 流程

Terminal 1 启动物理侧 watch：

```bash
physical-agent watch
```

保持它运行。watch 会加载 driver、发布能力、监听 action，并负责安全执行。

Terminal 2 提交任务：

```bash
physical-agent run --task "pick the red block and place it on the tray"
```

如果 watch 正在运行，你会看到 action 和 feedback。执行后可以检查 workspace：

```bash
physical-agent inspect
```

## Workspace 协议

`workspace/*.md` 不是普通日志，而是 v1 的核心通信协议。

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

每个协议 Markdown 文件都使用 YAML front matter。正文可以有自然语言摘要，机器可读数据放在 fenced YAML code block 中。

文件职责：

- `TASK.md`：当前任务和人类约束
- `CAPABILITIES.md`：watch 根据 driver capabilities 自动生成，agent 只读
- `WORLD.md`：watch 写入的当前世界状态
- `ACTIONS.md`：agent 写入的 pending / completed / cancelled action board
- `FEEDBACK.md`：watch 写入的执行反馈
- `SAFETY.md`：人类拥有，watch 强制执行
- `LOG.md`：审计日志
- `CHAT.md`：人类和 agent 的对话历史
- `PLAN.md`：chat agent 当前意图、步骤和 proposed actions
- `MEMORY.md`：chat agent 跨轮次保留的小型记忆

静态启动配置放在 `physical-agent.yaml`。动态运行状态放在 Markdown workspace。

## Driver Contract

接入一个机器人或硬件 adapter，只需要两个核心文件：

```text
my_robot_driver/
  physical_driver.yaml
  driver.py
```

`physical_driver.yaml` 是 manifest，声明 adapter 名称、版本、入口类、设备类型、配置 schema、依赖和 capability contract。

`driver.py` 实现 `PhysicalDriver`。driver 的职责是把标准 `Action` 转换成硬件或 simulator 调用，并把设备状态转换成 `Observation`。

关键边界：

- driver 只和 `physical-agent watch` 交互
- driver 不解析 Markdown
- driver 不调用 agent runtime
- agent 只通过 Markdown 看见 capabilities、world、actions 和 feedback
- agent 不直接调用硬件 SDK

生成一个空 driver 模板：

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

## 硬件接入助手

如果一个硬件项目已经有 GitHub 仓库、本地 SDK checkout，或者成熟 Python 包，Physical Agent 可以先生成 watch 侧接入草稿。默认的 `integrate` 是确定性的脚手架模式：

```bash
physical-agent integrate ./vendor_sdk --name my_device_driver
physical-agent integrate https://github.com/org/device-sdk --name my_device_driver
physical-agent chat --message "帮我接入 ./vendor_sdk"
```

脚手架模式会扫描 README、`pyproject.toml`、`package.json` 和文本源码，推断 source kind、transport、robot kind、capability 列表和 config schema，然后在 `physical-agent-integration/<driver-name>/` 下写入：

```text
physical_driver.yaml
driver.py
README.md
README.zh-CN.md
integration-report.md
```

如果希望让 OpenAI 兼容模型读取 SDK 上下文，并尝试把真实 SDK 调用写进 watch 侧 `driver.py`，启用 LLM coding：

```bash
physical-agent integrate ./vendor_sdk --name my_device_driver --llm
physical-agent integrate ./vendor_sdk --name my_device_driver --llm --model gpt-5.4
physical-agent chat --planner llm --message "帮我接入这个 SDK ./vendor_sdk"
physical-agent chat --message "帮我接入 ./vendor_sdk --llm"
```

GUI 的“硬件接入”区域也支持同样能力：选择“脚手架”会生成安全模板；选择“LLM 草稿”会读取 SDK 上下文、让模型更新 `driver.py`，并在 mock 模式下验证候选 driver。模型名可以在 GUI 输入框里临时覆盖，也可以通过 `.env` 的 `GPT_MODEL` / `OPENAI_MODEL` 设置。

LLM coding 会先生成安全脚手架，再把 SDK 片段和脚手架发给模型；它只接受少量允许文件的更新，例如 `driver.py`、`physical_driver.yaml`、README、`integration-report.md` 和聚焦测试文件。候选 driver 必须通过 Python 编译、`load_driver`、`connect`、`health`、`observe` 和 `driver.execute(observe)` 的 mock 验证后才会写回真实输出目录。每次都会生成 `llm-coding-report.md`。如果 API 失败或草稿没有通过验证，安全脚手架会保留下来。

这不代表 LLM 可以绕过安全边界。接入助手只帮助写 watch 侧 driver 草稿和文档；真正执行动作时仍然必须经过：

```text
agent -> ACTIONS.md -> watch safety gate -> driver.execute(action)
```

小智 MCP 风格硬件接入示例：

```text
examples/xiaozhi_mcp_hardware/README.zh-CN.md
docs/xiaozhi-driver-tutorial.zh-CN.md
```

## 内置 Drivers

`mock_arm` 支持：

- `observe`
- `move_to`
- `pick`
- `place`

默认 quickstart 里有 `red_block` 和 `tray`，所以这条任务：

```text
pick the red block and place it on the tray
```

会生成 pick + place 两个 action，并让 `red_block.location = tray`。

`mock_rover` 支持：

- `observe`
- `move_to`

它证明 driver protocol 不只面向机械臂，也可以接入移动设备、相机、语音设备或桥接服务。

## Safety Gate

watch 在执行每个 action 前都会校验：

- robot 是否存在
- capability 是否存在
- params 是否满足 capability JSON schema
- capability constraints 是否满足
- workspace safety rules 是否允许
- 是否需要 human approval
- action id 是否重复执行
- depends_on 是否已经完成

如果校验失败，watch 不会调用 driver。它会写入清晰的 feedback，追加日志，并把 action 从 pending 中移走。

## Rule-Based Planner

v1 的第一个 planner 是本地、确定性的：

- `observe` / `look` / `scan` 生成 `observe`
- `move` / `go` 生成 `move_to`
- `pick` / `grasp` 生成 `pick`
- `place` / `drop` 生成 `place`

这样没有 API key 也能跑通完整 Markdown loop。

## OpenAI 兼容 API 和 Chat Agent

Physical Agent 可以使用 OpenAI-compatible Chat Completions 接口做规划和对话，同时保持同样安全边界：LLM 只写 proposed actions 或 watch 侧 driver 草稿，watch 仍然负责校验和执行。

创建本地 `.env` 文件。它会被 git 忽略：

```bash
GPT_URL=https://your-provider.example/v1
GPT_KEY=your_api_key
GPT_MODEL=gpt-5.4
```

支持的变量名：

- API key：`GPT_KEY` 或 `OPENAI_API_KEY`
- Base URL：`GPT_URL` 或 `OPENAI_BASE_URL`
- Model：`GPT_MODEL` 或 `OPENAI_MODEL`

测试 API 连接：

```bash
physical-agent llm-test
physical-agent llm-test --model gpt-5.4
```

使用完整 chat agent：

```bash
physical-agent setup --force
physical-agent chat
```

单条消息模式：

```bash
physical-agent chat --message "What can you see right now?"
physical-agent chat --planner llm --auto-step --message "Please pick the red block and place it on the tray."
```

默认 `--planner auto` 会优先尝试 `.env` 里的 LLM，失败时回退到本地 rule-based chat。看到 `LLM chat was unavailable` 不代表框架崩了，常见原因是：

- `HTTP 503`：上游服务暂时不可用
- `HTTP 429`：被限流
- `model not found`：模型名不是该服务商实际支持的名字
- TLS / gateway 错误：兼容服务网关不稳定或 route 不支持

如果希望 API 失败时直接报错，用：

```bash
physical-agent chat --planner llm
```

如果希望默认使用 LLM planner，可以编辑 `physical-agent.yaml`：

```yaml
agent:
  planner: llm
  model: gpt-5.4
```

## MCP 扩展点

项目里包含一个轻量 MCP-shaped facade：

```text
physical_agent/mcp/server.py
```

目前提供可扩展结构：

- `submit_task`
- `get_state`
- `list_robots`
- `run_action`

v1 不把完整 MCP 依赖放进核心运行时，避免影响 watch / agent / Markdown loop 的稳定性。

## 开发和测试

安装开发依赖：

```bash
pip install -e .[dev]
```

运行测试：

```bash
pytest -q
```

测试覆盖：

- Markdown front matter 和 fenced YAML parser / renderer
- workspace 初始化、revision 递增、log append
- driver manifest 和 config schema 校验
- built-in driver 与本地 driver loader
- 硬件接入助手生成可加载 driver scaffold
- LLM driver coding、mock 验证、CLI/chat/GUI 入口
- safety gate 拒绝路径
- mock arm pick/place 状态变化
- rule-based planner
- watch runtime step
- 端到端 Markdown loop
- 一条命令 setup 和 smoke test
- doctor 健康检查
- GUI HTTP endpoints
- chat protocol、memory、action proposal 和 auto-step

## Clean-Room 声明

Physical Agent 是一个独立实现。它使用公开、通用的架构思想，例如 embodied-agent 分层、watch/runtime 分离、声明式 driver manifest、Markdown workspace protocol 和 MCP-style tool facade。

本项目不包含第三方竞品代码、文件内容复制、README 表述复刻、CLI 设计复刻、示例任务复刻或具体实现复制。
