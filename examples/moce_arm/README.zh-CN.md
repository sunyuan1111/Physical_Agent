# MomoAgent Partial Hardware 使用说明

这份文档记录当前 `momoagent_driver` 的实际接入方式、配置文件位置、GUI/CLI 操作方法，以及后续扩展到更多舵机时应该怎么改。

当前这套接入是针对：

- 机械臂仓库：`/home/houzhinan/MomoAgent`
- Physical Agent driver：`/home/houzhinan/Physical_Agent/Physical_Agent/examples/moce_arm`
- 当前真机模式：`partial hardware`
- 当前已接入舵机：
  - `ID 5` -> `wrist_roll`
  - `ID 6` -> `gripper`

该项目由硬件接入助手生成： `physical-agent integrate https://github.com/wanhaoniu/MomoAgent --name momoagent_driver`
## 1. 当前关键文件

### Driver 相关

- Driver 实现：
  `~/Physical_Agent/examples/moce_arm/driver.py`
- Driver manifest：
  `~/Physical_Agent/examples/moce_arm/physical_driver.yaml`

### 配置相关

- Partial hardware 配置：
  `~/Physical_Agent/examples/moce_arm/physical-agent.partial-hardware.yaml`
- LLM `.env`：
  `~/Physical_Agent/examples/moce_arm/.env`
- MomoAgent 串口运行配置：
  `/home/houzhinan/MomoAgent/runtime/soarm_moce_serial.local.yaml`

### Workspace 相关

当前 workspace 就是本目录：

```text
workspace-partial-hardware/
```

重要文件：

- `WORLD.md`：当前舵机状态
- `ACTIONS.md`：动作板
- `FEEDBACK.md`：执行反馈
- `LOG.md`：审计日志
- `CHAT.md`：GUI/Chat 对话记录

## 2. 当前控制能力

当前这套 partial hardware 模式只暴露并验证了以下能力：

- `observe`
- `home`
- `stop`
- `move_joint`
- `move_joints`
- `set_gripper`
- `open_gripper`
- `close_gripper`

其中当前最稳定、已经验证有物理响应的是：

- `open gripper`
- `close gripper`

`observe` 只读取状态，不会让舵机动作。

## 3. 当前 partial hardware 配置

当前配置文件：

```text
~/Physical_Agent/examples/moce_arm/physical-agent.partial-hardware.yaml
```

核心配置示例：

```yaml
robots:
  momo_1:
    driver: .
    config:
      mode: hardware
      hardware_profile: partial
      sdk_repo: ~/MomoAgent
      runtime_config: ~/MomoAgent/runtime/soarm_moce_serial.local.yaml
      serial_port: /dev/ttyACM1
      partial_joint_name: wrist_roll
      partial_joint_id: 5
      partial_joint_reduction_ratio: 1.0
      gripper_available: true
      gripper_id: 6
      partial_gripper_open_raw: 2087
      partial_gripper_close_raw: 1967
```

说明：

- `hardware_profile: partial`
  代表当前不是完整 1~6 舵机链路，而是只控一部分舵机。
- `partial_joint_name: wrist_roll`
  当前单关节运动对应 `ID 5`。
- `gripper_id: 6`
  当前夹爪对应 `ID 6`。
- `partial_gripper_open_raw / partial_gripper_close_raw`
  是当前为这颗 6 号舵机人工指定的开合 raw 值窗口。

## 4. `.env` 的作用

当前自然语言 GUI/Chat 能正常工作，是因为在这个目录下放了 `.env`：

```text
~/Physical_Agent/examples/moce_arm/.env
```

常见写法：

```env
GPT_URL=...
GPT_KEY=...
GPT_MODEL=...
```

这份 `.env` 会被 Chat/LLM 路径读取

注意：

- 不要把真实 API Key 提交到 Git 仓库
- 如果以后换模型或 API 服务，只改 `.env` 即可

## 5. 环境要求

项目环境路径：

```text
~/Physical_Agent/Physical_Agent/.venv
```

常用进入方式：

```bash
cd ~/Physical_Agent/Physical_Agent
source .venv/bin/activate
```

如果环境容易混乱，建议直接用绝对路径执行：

```bash
~/Physical_Agent/.venv/bin/physical-agent ...
```

## 6. 串口与权限

当前机械臂串口已经确认：

```text
/dev/serial/by-id/usb-1a86_USB_Single_Serial_5B61036646-if00
```

实际指向：

```text
/dev/ttyACM1
```

推荐优先使用 `by-id` 路径，因为重插设备后更稳定。

Linux 权限注意：

- 当前用户需要在 `dialout` 组里
- 如果没有权限，会出现 `Permission denied: '/dev/ttyACM1'`

常见修复：

```bash
sudo usermod -aG dialout $USER
newgrp dialout
```

如果设备刚插拔，建议重新确认串口：

```bash
ls -l /dev/serial/by-id/
ls -l /dev/ttyACM* /dev/ttyUSB* 2>/dev/null
```

## 7. CLI 运行方式

### 7.1 启动 watch

```bash
physical-agent watch --config examples/moce_arm/physical-agent.partial-hardware.yaml
```

### 7.2 查看当前状态

```bash
physical-agent inspect --config examples/moce_arm/physical-agent.partial-hardware.yaml
```

### 7.3 常用测试命令

读取状态：

```bash
physical-agent run --config examples/moce_arm/physical-agent.partial-hardware.yaml --task "observe"
```

打开夹爪：

```bash
physical-agent run --config examples/moce_arm/physical-agent.partial-hardware.yaml --task "open gripper"
```

关闭夹爪：

```bash
physical-agent run --config examples/moce_arm/physical-agent.partial-hardware.yaml --task "close gripper"
```

让 `wrist_roll` 转到某个角度：

```bash
physical-agent run --config examples/moce_arm/physical-agent.partial-hardware.yaml --task "set wrist roll to 10 degrees"
```

让 `wrist_roll` 增量转动：

```bash
physical-agent run --config examples/moce_arm/physical-agent.partial-hardware.yaml --task "move wrist roll -5 degrees"
```

## 8. GUI 运行方式

### 8.1 启动 GUI

```bash
physical-agent gui --config examples/moce_arm/physical-agent.partial-hardware.yaml
```

默认地址通常是：

```text
http://127.0.0.1:8765
```

### 8.2 GUI 中推荐操作顺序

1. 点击 `初始化`
2. 点击 `Start watch`
3. 在左侧 `Chat` 输入自然语言
4. 勾选 `Run one watch step`
5. 点击 `Send`

### 8.3 GUI 中当前建议输入的自然语言

夹爪：

- `open gripper`
- `close gripper`
- `打开夹爪`
- `关闭夹爪`

单关节：

- `set wrist roll to 10 degrees`
- `move wrist roll -5 degrees`
- `move wrist roll 5 degrees`

观察：

- `observe`
- `查看当前状态`


## 9. 当前 driver 的接入思路

这套 `momoagent_driver` 当前实际上支持两种真机路径：

### `hardware_profile: full`

适合未来接回完整 1~6 舵机时使用。

### `hardware_profile: partial`

适合当前这种只接：

- `ID 5`
- `ID 6`

的场景。

当前 partial 模式不是完整机械臂模型，而是：

- 单关节 `wrist_roll`
- 单夹爪 `gripper`

这种模式的好处是：

- 先把 Physical Agent 到真实硬件的链路跑通
- 后续接回更多舵机时，不需要推翻整个 driver

## 10. 常见问题


### 10.1 `open gripper` / `close gripper` completed 但没动作

常见原因：

- 串口权限不够
- `watch` 没在运行
- `partial_gripper_open_raw / partial_gripper_close_raw` 不适配当前硬件
- 夹爪电源、连线、总线状态有问题

### 10.2 `watch` 报 `Permission denied`

说明当前用户对串口没有权限。

先确认：

```bash
groups
```

看是否包含 `dialout`。


## 11. 后续扩展到完整机械臂时怎么做

如果后续把更多舵机接回去，建议按这个顺序扩展：

1. 先确认 1~6 舵机都能在总线上被 ping 到
2. 切换到 `hardware_profile: full`
3. 让 `runtime_config` 与 MomoAgent 的完整配置一致
4. 逐步验证：
   - `observe`
   - `home`
   - `stop`
   - `move_joint`
   - `move_joints`
   - `gripper`
5. 最后再补更复杂的笛卡尔运动或更自然的语言控制



## 12. 当前建议的最小工作流

```bash
cd /home/houzhinan/Physical_Agent/Physical_Agent
source .venv/bin/activate
sudo chmod 777 /dev/ttyACM1
physical-agent watch --config examples/moce_arm/physical-agent.partial-hardware.yaml
```

新开一个终端：

```bash
cd /home/houzhinan/Physical_Agent/Physical_Agent
source .venv/bin/activate
physical-agent run --config examples/moce_arm/physical-agent.partial-hardware.yaml --task "open gripper"
physical-agent run --config examples/moce_arm/physical-agent.partial-hardware.yaml --task "close gripper"
physical-agent run --config examples/moce_arm/physical-agent.partial-hardware.yaml --task "observe"
```

如果用 GUI：

```bash
physical-agent gui --config examples/moce_arm/physical-agent.partial-hardware.yaml
```

然后在 Chat 中输入：

- `open gripper`
- `close gripper`
- `observe`
