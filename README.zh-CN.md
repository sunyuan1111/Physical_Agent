# Physical Agent

[English version](README.md)

Physical Agent is a Markdown-native runtime for safe physical-world agents.

Physical Agent 是一个面向安全物理世界 agent 的 Markdown 原生运行时。第一版的重点不是堆很多功能，而是把认知侧 agent、物理侧 watch、driver 接入协议和安全边界拆清楚。

核心原则：

```text
Agent can propose actions. Watch decides whether and how they touch the physical world.
```

也就是说：agent 可以提出动作意图，但只有 watch 进程可以决定这些动作是否以及如何触达真实物理世界。

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

硬边界：

- agent 不导入 driver
- agent 不调用硬件 SDK
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

GUI 是给新同事最友好的入口：

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
- 输入 SDK 路径或 GitHub 仓库生成硬件 driver 脚手架

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

如果你的同事已经有 GitHub 仓库、本地 SDK checkout，或者成熟 Python 包，可以让 Physical Agent 先生成第一版接入脚手架：

```bash
physical-agent integrate ./vendor_sdk --name my_device_driver
physical-agent integrate https://github.com/org/device-sdk --name my_device_driver
physical-agent chat --message "帮我接入 ./vendor_sdk"
```

GUI 里也有 “硬件接入” 区域，输入本地路径、GitHub URL 或 Python 包名后点击“生成驱动”即可。

接入助手会扫描 README、`pyproject.toml`、`package.json` 和文本源码，推断：

- source kind：本地路径、GitHub repo 或 Python package
- transport：serial、HTTP、WebSocket、MQTT、gRPC、MCP、SDK 或 generic
- robot kind：arm、rover、camera、audio device 等
- 初始 capability 列表
- config schema
- 下一步人工完善建议

默认输出：

```text
physical-agent-integration/my_device_driver/
  physical_driver.yaml
  driver.py
  README.md
  README.zh-CN.md
  integration-report.md
```

生成的 driver 默认先保持 `mode: mock` 可运行。工程师需要把 `driver.py` 里的 TODO 分支替换成真实 SDK 或服务调用，并为每个保留的 capability 增加聚焦测试。

这不是让 agent 绕过安全边界。接入助手只帮助写 watch 侧 driver 草稿和文档；真正执行时仍然必须经过：

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

会被 rule-based planner 转换为：

```text
arm_1.pick(object_id=red_block)
arm_1.place(target=tray)
```

`mock_rover` 支持：

- `observe`
- `move_to`

它用于证明架构不只适用于机械臂，也可以接入其他设备。

## Safety Gate

watch 在执行任何 action 前都会检查：

- robot 是否存在
- capability 是否存在
- params 是否满足 capability JSON schema
- capability constraints 是否被满足
- `SAFETY.md` 是否允许执行
- 是否需要 human approval
- action id 是否重复执行
- `depends_on` 是否已经 completed

如果校验失败，watch 不会调用 driver，而是写入 `FEEDBACK.md`、追加 `LOG.md`，并将该 action 从 pending 移出。

## Rule-Based Planner

默认 planner 是本地 deterministic planner，不需要 API key。

简单映射：

- `observe` / `look` / `scan` -> `observe`
- `move` / `go` -> `move_to`
- `pick` / `grasp` -> `pick`
- `place` / `drop` -> `place`

## OpenAI 兼容 API 和 Chat Agent

Physical Agent 可以使用 OpenAI-compatible Chat Completions 接口做规划和对话，同时保持同样安全边界：LLM 只写 proposed actions，watch 仍然负责校验和执行。

在项目根目录创建 `.env`，该文件已被 git 忽略：

```bash
GPT_URL=https://your-provider.example/v1
GPT_KEY=your_api_key
GPT_MODEL=gpt-5.4
```

也支持这些变量名：

- API key：`GPT_KEY` 或 `OPENAI_API_KEY`
- Base URL：`GPT_URL` 或 `OPENAI_BASE_URL`
- Model：`GPT_MODEL` 或 `OPENAI_MODEL`

测试连通性：

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
