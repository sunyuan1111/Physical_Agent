# 小智 MCP Driver 接入教程

本文用 `examples/xiaozhi_mcp_hardware` 里的小智示例解释 Physical Agent 是如何工作的，以及为什么一个 `physical_driver.yaml` 加一个 `driver.py` 就能让 agent 接入新的硬件能力。

核心结论先放在前面：

```text
Agent 不直接操作硬件。
Agent 只根据能力清单生成动作。
Watch 进程负责安全检查和执行动作。
Driver 负责把统一动作翻译成具体硬件或 MCP 调用。
```

也就是说，小智能力不是被大模型“魔法识别”出来的，而是通过一套固定的 driver 插件协议接入进来的。

## 整体架构

Physical Agent 可以理解成一个三段式系统：

```text
用户任务
  |
  v
AgentRuntime
读取 CAPABILITIES.md / WORLD.md
生成 ACTIONS.md
  |
  v
WatchRuntime
轮询 ACTIONS.md
安全检查
调用对应 robot 的 driver.execute(action)
  |
  v
XiaozhiMcpDriver
mock 模式：本地模拟
http 模式：发送 JSON-RPC 到小智 MCP endpoint
  |
  v
小智设备 / 小智 MCP 服务
  |
  v
WatchRuntime 写回 FEEDBACK.md / WORLD.md / LOG.md
```

这里有两层通信：

```text
Agent <-> Watch：
  通过 workspace 里的 Markdown 文件通信

Watch <-> 小智 MCP：
  通过 JSON-RPC tools/call 通信
```

这个分层非常重要。agent 只负责“想做什么”，watch 和 driver 负责“能不能做、怎么做、做完之后结果是什么”。

## 示例文件位置

小智示例主要由这几个文件组成：

```text
examples/xiaozhi_mcp_hardware/physical-agent.yaml
examples/xiaozhi_mcp_hardware/physical_driver.yaml
examples/xiaozhi_mcp_hardware/driver.py
physical_agent/drivers/xiaozhi_mcp.py
```

它们的职责不同：

```text
physical-agent.yaml：
  当前项目怎么运行，有哪些 robot，每个 robot 用哪个 driver。

physical_driver.yaml：
  当前 driver 怎么被加载，入口类在哪里，配置如何校验。

driver.py：
  暴露一个 PhysicalDriver 子类给 loader 加载。

physical_agent/drivers/xiaozhi_mcp.py：
  小智 MCP driver 的真实实现。
```

## `physical-agent.yaml`：项目装配文件

小智示例的 `physical-agent.yaml` 里最关键的是 `robots`：

```yaml
robots:
  xiaozhi_1:
    driver: .
    config:
      mode: mock
      device_name: xiaozhi-demo-device
      tool_prefix: self.device
      endpoint_env: XIAOZHI_MCP_ENDPOINT
      token_env: XIAOZHI_MCP_TOKEN
      tools:
        observe: self.device.observe
        say: self.audio.speaker.speak
        set_light: self.light.set_rgb
```

这段配置声明：

```text
我有一个 robot，ID 是 xiaozhi_1。
它的 driver 在当前目录，也就是 driver: .
它使用 mock 模式运行。
它把 Physical Agent 里的能力名映射到小智 MCP tool：
  observe   -> self.device.observe
  say       -> self.audio.speaker.speak
  set_light -> self.light.set_rgb
```

`driver: .` 的意思不是“当前目录有硬件能力”，而是告诉 loader：

```text
去当前目录读取 physical_driver.yaml。
```

## `physical_driver.yaml`：driver 说明书

`physical_driver.yaml` 是 driver manifest，也就是插件说明书。它告诉 Physical Agent 这个 driver 怎么加载、怎么配置、属于什么设备类型。

关键配置如下：

```yaml
schema: physical-agent/driver/v1

name: xiaozhi_mcp_hardware
version: 0.1.0
description: Local hardware example for a Xiaozhi MCP bridge.

entrypoint:
  module: driver
  class: XiaozhiMcpDriver
```

`entrypoint` 的含义是：

```text
加载当前 driver 目录下的 driver.py。
从 driver.py 里找到 XiaozhiMcpDriver 这个类。
```

manifest 还定义了 `config_schema`：

```yaml
config_schema:
  type: object
  properties:
    mode:
      type: string
      enum: [mock, http]
      default: mock
    endpoint_env:
      type: string
      default: XIAOZHI_MCP_ENDPOINT
    token_env:
      type: string
      default: XIAOZHI_MCP_TOKEN
    timeout_s:
      type: number
      minimum: 1
      default: 10
    device_name:
      type: string
      default: xiaozhi-device
    tool_prefix:
      type: string
      default: self.device
    tools:
      type: object
      properties:
        observe:
          type: string
        say:
          type: string
        set_light:
          type: string
      additionalProperties:
        type: string
    mock_state:
      type: object
  additionalProperties: false
```

这部分的作用是校验 `physical-agent.yaml` 里传给 driver 的 `config` 是否合法。

例如，如果配置里出现了 schema 不允许的字段，driver 加载时会直接失败。这可以避免拼错字段、传错类型、或者把不受支持的配置悄悄带进运行时。

所以 `physical_driver.yaml` 的职责是：

```text
声明 driver 名称和版本
声明 driver 入口 module/class
声明 robot 类型
声明是否支持 simulation
声明 config schema
声明能力合同来源
```

它本身不执行硬件操作。它只是让系统知道“怎么找到并安全加载这个 driver”。

## `driver.py`：本地 driver 入口

小智示例里的 `driver.py` 非常短：

```python
from physical_agent.drivers.xiaozhi_mcp import XiaozhiMcpDriver

__all__ = ["XiaozhiMcpDriver"]
```

这是一个薄入口。因为小智 MCP 的真实实现已经放在内置模块：

```text
physical_agent/drivers/xiaozhi_mcp.py
```

loader 根据 manifest 里的配置：

```yaml
entrypoint:
  module: driver
  class: XiaozhiMcpDriver
```

会执行类似这样的加载逻辑：

```text
导入 examples/xiaozhi_mcp_hardware/driver.py
读取 driver.py 里的 XiaozhiMcpDriver
检查它是不是 PhysicalDriver 的子类
实例化它
```

如果你以后接入一个全新的硬件，也可以在 `driver.py` 里自己实现完整的 driver，而不是从内置模块导入。

## `PhysicalDriver`：统一设备接口

所有硬件 driver 都必须继承 `PhysicalDriver`，并实现这几个方法：

```python
class PhysicalDriver(ABC):
    async def connect(self) -> None
    async def disconnect(self) -> None
    async def health(self) -> HealthStatus
    async def observe(self) -> Observation
    def capabilities(self) -> list[Capability]
    async def execute(self, action: Action) -> ActionResult
```

这就是 Physical Agent 能接不同硬件的原因。

系统不需要提前知道“小智怎么说话”、“机械臂怎么抓取”、“小车怎么移动”。它只要求每个 driver 都回答同一组问题：

```text
connect：
  你怎么连接？

disconnect：
  你怎么断开？

health：
  你现在健康吗？

observe：
  你现在观察到什么状态？

capabilities：
  你能做什么？每个能力需要什么参数？

execute：
  给你一个标准 Action，你怎么执行？
```

只要新的硬件实现这套接口，watch 就能统一调用它。

## Driver 加载流程

driver 加载逻辑在 `physical_agent/drivers/loader.py`。

当配置里写：

```yaml
robots:
  xiaozhi_1:
    driver: .
    config:
      mode: mock
```

watch 启动时会调用 `load_driver(...)`，整体流程是：

```text
1. 判断 driver_ref 是内置 driver 还是本地目录。
2. 如果是本地目录，读取 physical_driver.yaml。
3. 根据 entrypoint.module 找到 driver.py。
4. 根据 entrypoint.class 找到 XiaozhiMcpDriver。
5. 检查 XiaozhiMcpDriver 是否继承 PhysicalDriver。
6. 用 config_schema 校验 config。
7. 创建 DriverContext。
8. 实例化 driver_class(context)。
```

伪代码如下：

```python
manifest = load_driver_manifest(driver_dir)
driver_class = _load_local_driver_class(driver_dir, manifest, robot_id)
validate_driver_config(manifest, config)
context = DriverContext(...)
driver = driver_class(context)
```

所以，一个 `physical_driver.yaml` 加一个 `driver.py` 能接入能力，是因为 loader 和 driver 之间已经有固定协议：

```text
目录里有 physical_driver.yaml
manifest 里声明 module/class
module/class 能被 Python 动态导入
class 继承 PhysicalDriver
class 实现 connect / observe / capabilities / execute
```

这就是插件机制。

## 小智能力是怎么暴露给 agent 的

小智 driver 的 `capabilities()` 会返回三个能力：

```text
observe
say
set_light
```

概念上类似：

```python
Capability(
    name="say",
    description="Ask the Xiaozhi MCP device to speak a short sentence.",
    params_schema={
        "type": "object",
        "required": ["text"],
        "properties": {
            "text": {
                "type": "string",
                "minLength": 1,
                "maxLength": 120,
            },
        },
        "additionalProperties": False,
    },
)
```

watch 启动时会：

```text
1. 加载 XiaozhiMcpDriver。
2. 调用 driver.connect()。
3. 调用 driver.capabilities()。
4. 把能力写入 CAPABILITIES.md。
```

agent 之后不是通过读源码知道小智能力，而是通过读取 `CAPABILITIES.md` 知道：

```text
xiaozhi_1 可以 observe。
xiaozhi_1 可以 say(text)。
xiaozhi_1 可以 set_light(r, g, b)。
```

这让 agent 的认知侧和硬件实现侧保持解耦。

## Agent 和 Watch 的 Markdown 通信

Physical Agent v1 使用 workspace 里的 Markdown 文件作为 agent 和 watch 之间的协议。

主要文件包括：

```text
TASK.md
CAPABILITIES.md
WORLD.md
ACTIONS.md
FEEDBACK.md
SAFETY.md
LOG.md
```

它们的职责如下：

```text
TASK.md：
  当前用户任务。

CAPABILITIES.md：
  当前可用 robot 和能力清单。

WORLD.md：
  当前观察到的世界状态。

ACTIONS.md：
  agent 提交的待执行动作。

FEEDBACK.md：
  watch 执行动作后的结果。

SAFETY.md：
  安全规则。

LOG.md：
  运行日志。
```

通信流程是：

```text
watch 启动后：
  连接 driver
  调用 driver.capabilities()
  写 CAPABILITIES.md
  调用 driver.observe()
  写 WORLD.md

agent 收到用户任务后：
  写 TASK.md
  读 CAPABILITIES.md
  读 WORLD.md
  规划动作
  写 ACTIONS.md

watch 循环运行：
  读 ACTIONS.md
  做安全检查
  调用 driver.execute(action)
  写 FEEDBACK.md
  更新 WORLD.md
```

这意味着 agent 和 watch 不需要在同一个进程里直接互调。只要双方遵守 Markdown 文件格式，就能协作。

## 完整例子：让小智说话并设置灯光

假设用户输入：

```text
让小智说“你好，我准备好了”，然后把灯调成蓝色
```

agent 读取 `CAPABILITIES.md` 后知道 `xiaozhi_1` 有 `say` 和 `set_light` 两个能力。于是它会生成类似这样的动作：

```yaml
pending:
  - id: act_001
    robot: xiaozhi_1
    capability: say
    params:
      text: 你好，我准备好了
    reason: The task asks the device to speak.

  - id: act_002
    robot: xiaozhi_1
    capability: set_light
    params:
      r: 0
      g: 90
      b: 255
    reason: The task asks to change a light.
```

watch 看到 `ACTIONS.md` 里有 pending action 后，会找到 `xiaozhi_1` 对应的 driver：

```python
loaded = self.loaded_drivers[action.robot]
result = await loaded.driver.execute(action)
```

当 action 是：

```python
Action(
    robot="xiaozhi_1",
    capability="say",
    params={"text": "你好，我准备好了"},
)
```

小智 driver 的 `execute()` 会进入 `say` 分支：

```python
if action.capability == "say":
    text = str(action.params["text"])
    if self.mode == "http":
        response = await self._call_tool(self.tools["say"], {"text": text})
    else:
        response = {"spoken": text, "mode": "mock"}
```

如果是 `mode: mock`，它只会本地模拟执行。

如果是 `mode: http`，它会调用小智 MCP tool。

## 小智 MCP 的 JSON-RPC 通信

当小智 driver 运行在 `http` 模式时，它会把 Physical Agent 的标准 action 转成 MCP `tools/call` 请求。

调用工具时的 JSON-RPC payload 结构是：

```python
payload = {
    "jsonrpc": "2.0",
    "id": self._next_request_id(tool_name),
    "method": "tools/call",
    "params": {
        "name": tool_name,
        "arguments": arguments,
    },
}
```

例如让小智说话：

```json
{
  "jsonrpc": "2.0",
  "id": "pa:xiaozhi_1:self.audio.speaker.speak",
  "method": "tools/call",
  "params": {
    "name": "self.audio.speaker.speak",
    "arguments": {
      "text": "你好，我准备好了"
    }
  }
}
```

设置灯光：

```json
{
  "jsonrpc": "2.0",
  "id": "pa:xiaozhi_1:self.light.set_rgb",
  "method": "tools/call",
  "params": {
    "name": "self.light.set_rgb",
    "arguments": {
      "r": 0,
      "g": 90,
      "b": 255
    }
  }
}
```

其中 `name` 来自 `physical-agent.yaml` 里的 tool 映射：

```yaml
tools:
  say: self.audio.speaker.speak
  set_light: self.light.set_rgb
```

所以完整转换关系是：

```text
用户自然语言任务
  -> Agent 生成 Action(capability="say", params={"text": "..."})
  -> Watch 调用 driver.execute(action)
  -> Driver 查 tools["say"]
  -> 得到 self.audio.speaker.speak
  -> 发 JSON-RPC tools/call 到小智 MCP endpoint
```

## 为什么不让 agent 直接调 MCP

这个项目刻意把 agent 和真实硬件隔开。

这样做有几个好处：

```text
安全：
  agent 只能提交 action，不能直接无限制操作硬件。

可观察：
  TASK / ACTIONS / FEEDBACK / WORLD 都落在 Markdown 文件里，方便审计和调试。

可替换：
  今天是小智 MCP，明天可以换成机械臂、小车、摄像头、PLC。

可测试：
  mode: mock 时，不需要真实设备也能跑通流程。

可扩展：
  新设备只要实现 PhysicalDriver 接口即可。
```

最关键的一条边界是：

```text
Agent can propose actions.
Watch decides whether and how they touch the physical world.
```

agent 可以提出动作意图，但只有 watch 进程可以决定动作是否以及如何触达真实物理世界。

## 新设备接入时要实现什么

如果你要接一个新的硬件，最小接入形态通常是：

```text
my_device_driver/
  physical_driver.yaml
  driver.py
```

`physical_driver.yaml` 负责声明：

```text
schema
name
version
entrypoint.module
entrypoint.class
robot.kind
robot.supports_simulation
config_schema
```

`driver.py` 负责提供：

```python
class MyDeviceDriver(PhysicalDriver):
    async def connect(self) -> None:
        ...

    async def disconnect(self) -> None:
        ...

    async def health(self) -> HealthStatus:
        ...

    async def observe(self) -> Observation:
        ...

    def capabilities(self) -> list[Capability]:
        ...

    async def execute(self, action: Action) -> ActionResult:
        ...
```

然后在项目的 `physical-agent.yaml` 里声明 robot：

```yaml
robots:
  my_device_1:
    driver: ./my_device_driver
    config:
      mode: mock
```

watch 启动后就会自动加载这个 driver，并把它的能力发布给 agent。

## 一句话总结

一个 `physical_driver.yaml` 加一个 `driver.py` 能让 agent 接入能力，是因为 Physical Agent 已经提供了完整的插件协议和运行时：

```text
physical_driver.yaml 负责声明和校验。
driver.py 负责暴露 PhysicalDriver 子类。
capabilities() 负责告诉 agent 能做什么。
execute() 负责把标准 Action 翻译成真实设备调用。
workspace Markdown 文件负责 agent 和 watch 之间通信。
JSON-RPC 负责 watch 和小智 MCP 之间通信。
```

所以接入新能力的本质不是让大模型直接学会控制硬件，而是把硬件包装成 Physical Agent 能理解的标准 driver。
