# 小智机器人接入与操作说明

这份说明基于当前目录下的真实小智接入配置整理，目标是帮助你从进入虚拟环境开始，一步一步完成：

1. 激活项目环境
2. 更新小智连接信息
3. 启动 `watch`
4. 让 Physical Agent 控制小智做动作

## 1. 进入项目并激活虚拟环境

先进入项目根目录：

```bash
cd /home/houzhinan/Physical_Agent/Physical_Agent
```

再激活虚拟环境：

```bash
source .venv/bin/activate
```

如果终端前面出现 `(.venv)`，说明虚拟环境已经生效。

## 2. 确认当前示例目录

本次小智接入示例目录是：

```text
~/Physical_Agent/Physical_Agent/examples/xiaozhi_mcp_hardware
```

这个目录里最关键的几个文件是：

- `physical-agent.yaml`
- `.env`
- `physical_driver.yaml`
- `driver.py`
- `xiaozhi_mcp_driver.py`

其中：

- `physical-agent.yaml` 负责项目装配和机器人配置
- `.env` 负责保存小智的地址和连接参数
- `physical_agent/drivers/xiaozhi_mcp.py` 是当前项目真正使用的 driver 实现
- `xiaozhi_mcp_driver.py` 是开发者给的参考实现，主要用来说明小智局域网 MCP 的通信方式

## 3. 更新环境变量
### 接入真实的小智 MCP

当前这台小智走的是局域网 WebSocket MCP，不是 HTTP `/mcp`。
如果你的设备直接在局域网暴露 WebSocket MCP，例如 `ws://192.168.66.237:8080/ws`，推荐使用 `ws` 模式：

```yaml
robots:
  xiaozhi_1:
    driver: .
    config:
      mode: ws
      wait_for_responses: false
```

并在 `.env` 中填写：

```env
XIAOZHI_MCP_URL=ws://192.168.66.237:8080/ws
```

也可以拆成：

```env
XIAOZHI_MCP_HOST=192.168.66.237
XIAOZHI_MCP_PORT=8080
XIAOZHI_MCP_PATH=/ws
```

有些设备只接受工具调用，但不会对 `initialize` / `tools/list` 返回标准响应。遇到这种情况，保持
`wait_for_responses: false`，让 watch 使用“只发送不等待回包”的模式。

WebSocket reconnect 是可选能力，默认关闭。如需开启通信层重连，可以在 robot config 中写：

```yaml
reconnect_policy:
  enabled: true
  max_retries: 3
  backoff_base_ms: 250
  backoff_cap_ms: 5000
  jitter_ms: 0
```

reconnect 不会重放旧动作；transport 正在重连时提交的动作会 fail-fast 并写失败反馈。重连成功只说明通信恢复，之后仍要通过 `observe`/`health` 确认机器人状态。

从 D1 开始，`ws` 模式的底层连接、握手、frame 读写由共享的
`physical_agent.drivers.transport.WebSocketTransport` 提供。这个 transport
只在 watch/driver 侧使用；agent、API、GUI 仍然只写 proposal，不直接连接硬件。

如果你的接入方式是 HTTP JSON-RPC 网关，再使用 `http` 模式：

先把 `.env.example` 复制成 `.env`，再填写真实地址：

```env
XIAOZHI_MCP_ENDPOINT=http://你的MCP网关地址
XIAOZHI_MCP_TOKEN=如果需要鉴权就填
```

如果你的硬件是串口或其它非 WebSocket/HTTP 连接，本轮 D1 还没有实现
`SerialTransport`、`ServoBus`、硬件看门狗或 E-stop 策略。请先保持请求侧不变，
把协议适配放在 watch 侧 driver 或临时桥接层里。


## 4. 先做一次检查

建议先跑一次 `doctor`：

```bash
physical-agent doctor --config examples/xiaozhi_mcp_hardware/physical-agent.yaml
```

如果这里报错，先不要启动 `watch`，先检查：

- 虚拟环境是否已激活
- `.env` 是否写对
- `physical-agent.yaml` 是否仍是 `ws` 模式

## 5. 启动 watch

在终端 A 中运行：

```bash
cd ~/Physical_Agent/Physical_Agent
source .venv/bin/activate
physical-agent watch --config examples/xiaozhi_mcp_hardware/physical-agent.yaml
```

如果启动正常，终端会停在运行状态，不会立即退出。

`watch` 的职责是：

- 加载 driver
- 监听 workspace 中的新动作
- 把动作翻译成对小智的 MCP 调用

## 6. 查看当前机器人状态

新开终端 B，运行：

```bash
cd ~/Physical_Agent/Physical_Agent
source .venv/bin/activate
physical-agent inspect --config examples/xiaozhi_mcp_hardware/physical-agent.yaml
```

如果连接正常，通常会看到类似：

```text
xiaozhi-demo-device is connected over local MCP WebSocket in fire-and-forget mode.
```

## 7. 让小智做动作

再在终端 B 中通过自然语言下发任务。

### 推荐先测试这些明显动作

挥手：

```bash
physical-agent run --config examples/xiaozhi_mcp_hardware/physical-agent.yaml --task "wave"
```

停止当前动作：

```bash
physical-agent run --config examples/xiaozhi_mcp_hardware/physical-agent.yaml --task "stop"
```

向前走两步：

```bash
physical-agent run --config examples/xiaozhi_mcp_hardware/physical-agent.yaml --task "walk forward 2 steps"
```

向左转两步：

```bash
physical-agent run --config examples/xiaozhi_mcp_hardware/physical-agent.yaml --task "turn left 2 steps"
```

## 8. 用 GUI 测试和操控小智

除了命令行，你也可以直接用这个项目自带的 GUI 做测试。

先在终端中启动 GUI：

```bash
cd /home/houzhinan/Physical_Agent/Physical_Agent
source .venv/bin/activate
physical-agent gui --config examples/xiaozhi_mcp_hardware/physical-agent.yaml
```

默认会启动一个本地网页服务，通常地址类似：

```text
http://127.0.0.1:8765
```

如果浏览器没有自动打开，就手动访问这个地址。

### GUI 里怎么操作

进入页面后，建议按下面顺序测试：

1. 点击右上角 `中文`，切换到中文界面
2. 点击 `初始化`
3. 点击 `启动 watch`
4. 在左侧 `对话` 输入框里输入动作指令
5. 勾选 `执行一次 watch step`
6. 点击 `发送`

推荐先测试这些指令：

- `wave`
- `go home`
- `stop`
- `walk forward 2 steps`
- `turn left 2 steps`
- `set volume to 35`

### GUI 里能看到什么

GUI 里你可以同时看到：

- `世界状态`
- 当前机器人能力
- `动作`
- `反馈`
- `系统详情`

这对排查“命令有没有发出去”很有帮助。

## 9. 当前可用的主要能力

这台小智当前已经确认走的是动作能力，不是 `say` 和 `set_light`。

当前接入里主要使用这些 capability：

- `observe`
- `set_volume`
- `otto_action`
- `home`
- `stop`

它们和底层 tool 的对应关系是：

- `observe -> self.get_device_status`
- `set_volume -> self.audio_speaker.set_volume`
- `otto_action -> self.otto.action`
- `home -> self.otto.action`
- `stop -> self.otto.stop`

其中 `otto_action` 下面可以继续承载具体动作，例如：

- `hand_wave`
- `walk`
- `turn`
- `jump`
- `greeting`

## 10. 常用查看命令

查看最近状态：

```bash
physical-agent inspect --config examples/xiaozhi_mcp_hardware/physical-agent.yaml
```

如果你想重新初始化 workspace，清掉旧的 mock 或旧动作历史，可以执行：

```bash
physical-agent setup --config examples/xiaozhi_mcp_hardware/physical-agent.yaml --force
```

然后重新启动 `watch`。

## 11. 一个完整的最小流程

### 终端 A

```bash
cd /home/houzhinan/Physical_Agent/Physical_Agent
source .venv/bin/activate
physical-agent watch --config examples/xiaozhi_mcp_hardware/physical-agent.yaml
```

### 终端 B

```bash
cd /home/houzhinan/Physical_Agent/Physical_Agent
source .venv/bin/activate
physical-agent inspect --config examples/xiaozhi_mcp_hardware/physical-agent.yaml
physical-agent run --config examples/xiaozhi_mcp_hardware/physical-agent.yaml --task "wave"
physical-agent run --config examples/xiaozhi_mcp_hardware/physical-agent.yaml --task "go home"
physical-agent run --config examples/xiaozhi_mcp_hardware/physical-agent.yaml --task "stop"
```

如果机器人有真实动作，说明接入已经成功。

### 终端 C（可选，GUI）

```bash
cd /home/houzhinan/Physical_Agent/Physical_Agent
source .venv/bin/activate
physical-agent gui --config examples/xiaozhi_mcp_hardware/physical-agent.yaml
```

然后在浏览器里输入：

- `wave`
- `go home`
- `stop`

如果机器人有真实动作，说明 GUI 方式也已经接入成功。

## 12. 常见问题

### 1. `watch` 启动时报错

先检查：

- 小智是否开机并连到和电脑相同的 Wi-Fi
- `.env` 里的 IP 是否正确
- 是否仍然使用 `/ws`
- 是否有另一个 `watch` 进程已经占用同一套 workspace

### 2. `run` 显示 completed，但机器人没反应

这通常说明：

- 命令已经发出
- 但底层 tool 名或参数可能和设备实际支持的不一致

这时优先检查：

- `physical-agent.yaml` 中的 `tools` 映射
- 当前任务是否命中了正确 capability

### 3. `inspect` 里出现旧的 mock 记录

这是因为 workspace 里还留着旧历史。执行：

```bash
physical-agent setup --config examples/xiaozhi_mcp_hardware/physical-agent.yaml --force
```

再重新启动 `watch` 即可。

### 4. GUI 打开了，但机器人没反应

先检查：

- 页面里是否已经点了 `启动 watch`
- 发送消息时是否勾选了 `执行一次 watch step`
- `physical-agent.yaml` 是否仍然指向当前小智配置
- 终端里的 `watch` 或 GUI 后台是否有报错


## 排查顺序

如果任务没有执行，先检查：

1. `physical-agent doctor`
2. `physical-agent inspect`
3. `workspace/CAPABILITIES.md`
4. `workspace/ACTIONS.md`
5. `workspace/FEEDBACK.md`

常见原因：

- `XIAOZHI_MCP_ENDPOINT` 没配置
- MCP 网关没启动
- token 不正确
- 你的网关不是 HTTP JSON-RPC，需要一个桥接层

## 从这个示例迁移到真实硬件

你可以直接复制 `examples/xiaozhi_mcp_hardware/` 作为新项目起点，然后：

1. 保持 `physical_driver.yaml` 和 `driver.py` 这两个核心文件。
2. 修改 `tools`，让它匹配你的设备真实能力。
3. 修改 `observe`、`set_volume`、`otto_action`、`home`、`stop` 为你的动作集合。
4. 如果需要自定义通信层，也要放在 watch 侧 driver 内；当前 WebSocket 路径已经复用共享 `WebSocketTransport`。

这就是 Physical Agent 的 Two-file Driver Protocol。
