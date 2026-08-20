# Current Architecture Audit

日期：2026-07-08

范围：本报告以代码为准，文档只作为对照。扫描范围包括 `physical_agent/`、`frontend/`、`tui/`、`tests/`、`docs/`。本轮未修改业务代码。

## 0. 模块地图

```text
physical_agent/
├── api/                 FastAPI 服务、HTTP/SSE 接口、API 进程内可选 watch 服务
├── agent/               任务/聊天 runtime、规则/LLM planner、上下文构造、tool loop、driver 生成辅助
├── watch/               唯一真实执行循环、SafetyGate、world observe/merge、driver 调用封装
├── drivers/             driver 抽象、内置 driver、local driver loader/manifest、transport 层
├── state/               SQLite 状态后端、状态协议、审计导出、旧 markdown 迁移读取
├── protocol/            Pydantic 数据模型、workspace 文档格式、期望检查、记忆/检索协议
├── llm/                 OpenAI-compatible 客户端与设置
├── ingest/              上传文件入库、chunk、memory note
├── gui/                 旧版内置静态 GUI，自己持有 watch runtime
├── mcp/                 proposal-only MCP facade
├── cli.py               Typer CLI：init/api/watch/run/chat/ingest/inspect 等入口
└── config.py            配置模型、默认配置、sqlite-only backend 校验

frontend/
├── src/api.ts           浏览器端 HTTP/SSE client
├── src/App.tsx          React 应用编排、事件订阅、chat/task/action handler
├── src/actionDraft.ts   解析后端聊天回复中的 action-draft fenced JSON
├── src/viewmodels/      GUI 侧 world/capability/robot/overview 展示模型
└── src/components/      Actions、Chat、World、Robots、Events 等面板

tui/
├── src/api/             TUI HTTP/SSE/upload client
├── src/App.tsx          Ink 应用编排、命令分发、chat stream、SSE/poll 合并
├── src/commands/        slash command parser
├── src/formatters/      TUI 侧 schema/robot/action 展示格式化
└── src/components/      Ink panels

tests/
├── test_watch_*.py      watch 执行、安全、超时、重连、world 更新
├── test_api_*.py        FastAPI、API watch events、边界测试
├── test_state_*.py      SQLite state store、backend matrix
├── test_*driver*.py     driver contract、loader、mock/xiaozhi driver
├── test_chat_runtime.py ChatRuntime proposal-only/stream 行为
└── frontend/tui tests   UI/TUI render、command、SSE、safety smoke

docs/
├── SPEC.zh-CN.md        安全宪法、待办矩阵
├── PLAYBOOK.zh-CN.md    待办实现路线、验收、坑
├── REFACTORING.zh-CN.md 已完成重构总结和决策记录
└── 其他专题文档         CI、TUI matrix、硬件 bringup、xiaozhi driver 等
```

## 1. 当前真实工作流程

当前系统是“提案面”和“执行面”分离的架构：

```text
用户入口
  -> API/CLI/旧 GUI/MCP 创建任务或 action proposal
  -> StateStore 写入 pending action
  -> watch loop claim ready action
  -> SafetyGate 重新校验
  -> driver.execute(action)
  -> feedback + world update + expected check
```

主要入口如下。

| 入口 | 真实模块 | 是否直接执行 |
| --- | --- | --- |
| React frontend chat | `frontend/src/App.tsx` -> `frontend/src/api.ts` -> `/api/chat/stream` 或 `/api/chat` | 否，只得到 reply / draft；Add to Actions 后才写 pending |
| React frontend task | `/api/tasks/submit` -> `ApiController.submit_task()` -> `SafeProposalPlanner` | 否，只写 pending |
| TUI chat/task | `tui/src/App.tsx` -> `tui/src/api/client.ts` -> FastAPI | 否，只走 API |
| CLI `physical-agent run` | `AgentRuntime.run_task()` | 否，只写 pending，等待外部 watch feedback |
| CLI `physical-agent chat` | `ChatRuntime.respond()` | 默认否；`tool_loop + auto_step` 可实例化 `WatchRuntime` 跑一步 |
| CLI `physical-agent watch` | `WatchRuntime` | 是，watch 内执行 |
| API `--watch` | `ApiWatchService` lazy import `WatchRuntime` | 是，API 进程里的后台 watch loop 执行 |
| 旧 GUI `physical_agent/gui` | `GuiController` 直接持有 `WatchRuntime` | 是，旧 GUI 可 start/step watch |
| MCP facade | `PhysicalAgentMCP.submit_task/propose_action` | 否，只写 pending |

### 典型任务："pick red block"

以当前 React Chat 入口为例：

```text
User: "pick red block"
  -> frontend/src/App.tsx handleChatSubmit()
  -> frontend/src/api.ts sendChatStream()
  -> POST /api/chat/stream
  -> physical_agent/api/server.py ApiController.chat_stream()
  -> _new_chat_runtime()
  -> physical_agent/agent/chat_runtime.py ChatRuntime.respond_stream()
  -> 读取 state: capabilities/world/feedback/chat/memory
  -> 规则或 LLM reply/proposal context
  -> 生成聊天回复；可能包含 action-draft fenced JSON
  -> frontend/src/actionDraft.ts parseActionDraft()
  -> 用户点击 Add to Actions
  -> frontend/src/App.tsx handleAction()
  -> frontend/src/api.ts proposeAction()
  -> POST /api/actions/propose
  -> ApiController.propose_action()
  -> _validate_action()
  -> _with_proposal_metadata(source="manual", proposed_by="api")
  -> SqliteStateStore.append_pending_action()
  -> pending action board
```

对应执行链：

```text
physical-agent watch 或 API --watch
  -> physical_agent/watch/runtime.py WatchRuntime.tick()
  -> WatchRuntime.step()
  -> SqliteStateStore.recover_stale_actions()
  -> SqliteStateStore.claim_next_ready_action(claim_owner="watch")
  -> SafetyGate.validate(action)
  -> _call_with_timeout(loaded.driver.execute(action), timeout_s)
  -> SqliteStateStore.mark_action_completed() 或 mark_action_cancelled()
  -> WatchRuntime._record_action_result()
  -> WatchRuntime.update_world()
  -> driver.observe()
  -> merge_observations()
  -> SqliteStateStore.write_world()
  -> optional expected check
```

如果用户从 React Task 面板或 TUI `/task pick red block` 进入，则链路更短：

```text
POST /api/tasks/submit
  -> ApiController.submit_task()
  -> SafeProposalPlanner.plan(task, capabilities, world)
  -> Action(capability="pick", params={"object_id": "..."} )
  -> _append_planned_actions()
  -> SqliteStateStore.append_pending_action()
```

`SafeProposalPlanner._object_id()` 会优先在 `world.state.objects` 中找 `color == "red"` 且 `type == "block"` 的对象；找不到时回退为 `"red_block"`。

### LLM 是否参与

不是所有路径都用 LLM：

- `/api/tasks/submit` 当前使用 `SafeProposalPlanner`，不走 `LLMPlanner`。
- React/TUI chat 使用 `ChatRuntime`。`planner=auto` 时如果 LLM 设置可用，非 streaming 路径可用 structured JSON；streaming 路径是 reply-only，仍可让模型在文本中生成 `action-draft` fenced JSON，但不会直接写 pending。
- CLI `run` 和 MCP `submit_task` 走 `AgentRuntime`，按配置选择 `RuleBasedPlanner` 或 `LLMPlanner`。
- `LLMPlanner` 的输入来自 `context_builder.build_planner_context()`：task、capabilities、world，并要求只使用已发布 capability。

## 2. Action 数据模型与生命周期

Python 真实模型在 `physical_agent/protocol/schemas.py`：

```text
Action
├── id: str
├── robot: str
├── capability: str
├── params: dict
├── reason: str
├── depends_on: list[str]
└── metadata: dict
```

当前没有 Python 顶层 `Action.approval` 或 `Action.expected` 字段。它们都在 `metadata` 里：

- `metadata.approval`: 后端根据 capability、robot、SAFETY 计算/刷新。
- `metadata.expected`: planner/chat 可提供，state store 会 normalize，watch 完成后做 post-execution check。
- `metadata.source/proposed_by/original_task/user_message/planner_reason/draft_reason`: proposal 来源追踪。

前端存在 TypeScript `ActionItem`，但它是 UI 类型，不是后端契约源。TUI 也有独立 `ActionItem` 类型。

真实 lifecycle：

```text
created by planner/chat draft/manual/MCP
  -> pending
     owner: SqliteStateStore.append_pending_action()
     side effect: recompute approval metadata

pending + approval.required=true
  -> pending, metadata.approval.status="approved"
     owner: SqliteStateStore.approve_action()

pending + rejected
  -> cancelled
     owner: SqliteStateStore.reject_action()

pending + ready
  -> in_progress
     owner: SqliteStateStore.claim_next_ready_action()
     note: public read_actions() 不把 in_progress 展成单独列表

in_progress + driver result completed
  -> completed
     owner: WatchRuntime.step() -> mark_action_completed()

in_progress + safety reject / driver fail / timeout / exception
  -> cancelled
     owner: WatchRuntime.step() -> mark_action_cancelled()

stale in_progress
  -> pending
     owner: recover_stale_actions()
```

状态转换主要由 SQLite store 执行，watch 决定何时 claim/complete/cancel，API 只 approve/reject/propose。

## 3. Capability 来源与数据流

真实 capability 源头是运行时 driver，不是 LLM：

```text
physical-agent.yaml
  -> robot_id + driver name + driver config
  -> drivers.loader.load_driver()
  -> built-in registry 或 local physical_driver.yaml
  -> driver.capabilities()
  -> RobotRuntimeProfile(capabilities=[Capability...])
  -> SqliteStateStore.write_capabilities()
  -> API / planners / ChatRuntime / frontend / TUI
```

来源分类：

| 来源假设 | 当前真实情况 |
| --- | --- |
| A. driver 自带 | 是。`MockArmDriver.capabilities()`、`MockRoverDriver.capabilities()`、`XiaozhiMcpDriver.capabilities()` 直接返回 schema。 |
| B. config yaml | 部分。YAML 选择 robot/driver/config，但不直接声明 capability 列表。 |
| C. robot registry | 部分。registry 只解析内置 driver 类，不是 capability registry。 |
| D. LLM 生成 | 否。LLM 只能选择已发布 capability 名称。 |
| E. local manifest | 部分。manifest 提供 driver 元数据和 config schema；真实 capability 仍来自 driver runtime。 |

## 4. Driver 分析

Driver 接口在 `physical_agent/drivers/base.py`：

```text
connect()
disconnect()
health()
observe()
capabilities()
execute(action)
heartbeat()   optional no-op
halt()        optional no-op
```

当前内置 driver：

| driver | 用途 | capabilities |
| --- | --- | --- |
| `mock_arm` | 模拟机械臂、对象拾取/放置 | `observe`, `move_to`, `pick`, `place` |
| `mock_rover` | 模拟移动底盘 | `observe`, `move_to` |
| `xiaozhi_mcp` | 连接/模拟小智 MCP 设备 | `observe`, `set_volume`, `otto_action`, `home`, `stop` |
| local driver | `physical_driver.yaml` + entrypoint class | 由 driver runtime 返回 |

Driver 当前知道业务语义。`mock_arm.execute()` 理解 `pick`、`place`、`object_id`、`target`；`xiaozhi_mcp.execute()` 理解 `set_volume`、`otto_action`、`home`、`stop` 并映射到 MCP tool。它不是纯低层运动指令层，而是“capability 执行层 + 设备/模拟状态适配层”。

## 5. World Model 分析

`Observation` 当前字段：

```text
summary: str
robots: dict
objects: dict
environment: dict
artifacts: list[str]
raw: dict
```

SQLite `write_world()` 会存两层：

```text
world.summary
world.state.robots
world.state.objects
world.state.environment
world.state.artifacts
world.state.raw
world.observation
```

真实数据流：

```text
driver.observe()
  -> WatchRuntime._observe_robot()
  -> WatchRuntime._observe_all_robots_concurrently()
  -> merge_observations(previous_world)
  -> SqliteStateStore.write_world()
  -> planners/context_builder/API state/frontend/TUI
```

谁写 world：watch。API reset/migration 初始化也会写默认空 world。

谁读 world：`SafeProposalPlanner`、`RuleBasedPlanner`、`LLMPlanner/context_builder`、ChatRuntime、API state、frontend viewmodels、TUI formatters、expected checker。

偏差：文档里 W4 提到 `observed_at`，但当前 `Observation` 与 world store 里没有 `observed_at` 字段。

## 6. GUI/TUI/API 数据流

### React frontend

```text
FastAPI endpoints
  -> frontend/src/api.ts fetch/send/SSE
  -> frontend/src/App.tsx state orchestration
  -> frontend/src/viewmodels/* + components
```

关键路径：

- chat：`App.handleChatSubmit()` -> `sendChatStream()` 或 `sendChat()`。
- task：`submitTask()` -> `/api/tasks/submit`。
- action：`proposeAction()` / `approveAction()` / `rejectAction()`。
- events：browser `EventSource("/api/events")`。
- draft：`actionDraft.ts` 从聊天 reply 里解析 fenced JSON。

### TUI

```text
slash command / free text
  -> tui/src/commands/parser.ts 或 chat input
  -> tui/src/api/client.ts
  -> FastAPI
  -> tui/src/App.tsx applyEvent()/state merge
  -> tui/src/formatters/* + Ink components
```

关键路径：

- chat：`sendChatStream()` -> `/api/chat/stream`。
- task：`submitTask()` -> `/api/tasks/submit`。
- action：`approveAction()` / `rejectAction()`。
- state/events：`state()` + `connectEvents()`，并有 summary-state 不覆盖 full-state 的判断。

### 重复解析

存在重复逻辑：

- React 和 TUI 各自定义 `AgentState`、`ActionItem`、`RobotCapability`。
- React `viewmodels/*` 与 TUI `formatters/*` 都解析 capability/world/config。
- React `api.ts` 与 TUI `api/sse.ts` 都处理 SSE。
- React `actionDraft.ts` 解析 `action-draft`，TUI 目前主要展示后端 chat 文本和 action board，没有共享 draft parser。

这些重复目前没有绕过安全边界，但会造成字段漂移风险。

## 7. Safety Report

安全宪法的主线基本成立：

```text
真实硬件/driver 执行调用点：
physical_agent/watch/runtime.py WatchRuntime.step()
  -> _call_with_timeout(loaded.driver.execute(action), timeout_s)
```

request/proposal 侧未发现 frontend 或 TUI 直接执行入口。FastAPI request handler 不直接调用 `driver.execute()`；`/api/actions/propose`、`/api/tasks/submit`、`/api/chat` 均返回 proposal/draft/pending。

需要注意的边界点：

1. `physical_agent/agent/driver_coder.py` 有 `loaded.driver.execute(...)`，用于 driver onboarding 的 mock validation。测试中已把它作为 allowlist，但它不是 watch 调用栈。
2. `physical_agent/agent/chat_runtime.py` 顶层 import `WatchRuntime`，且 tool-loop `auto_step` 分支会实例化 watch。API chat 传 `auto_step=False`，streaming chat 测试也防止实例化 watch；但从架构边界看，agent 层持有 watch 依赖是一个偏差。
3. 旧 GUI `physical_agent/gui/controller.py` 直接持有 `WatchRuntime` 并能 step watch。这仍通过 watch 执行，但它不是当前 React frontend 的纯 API 架构。
4. watch 中大多数 driver 调用都包了 `_call_with_timeout()`；但 `_maybe_halt_for_heartbeat_failure()` 里存在直接 `await loaded.driver.halt()` 的分支，应按 W5 收敛到 timeout wrapper。

SafetyGate 当前校验：

- action id 是否重复。
- dependency 是否完成。
- robot/capability 是否存在于当前 capability doc。
- `allow_autonomous_execution`。
- capability/robot approval 与 `metadata.approval.status`。
- `params_schema` JSON Schema。
- capability constraints bounds。
- `max_action_timeout_s`。

## 8. 文档一致性检查

### A. 文档正确

- `driver.execute` 主执行路径在 watch loop 内，API/frontend/TUI 不直接执行。
- `SAFETY.md` 仍是 safety 文件真源；state store 读取并镜像，不迁入纯 DB truth。
- Runtime markdown backend 已退休，当前 active backend 是 SQLite。
- F1 的“chat draft -> Add to Actions -> pending -> approval/watch”主链路与代码一致。
- F3 `context_builder` 是 proposal/reply/planner 上下文中心，且是只读上下文。
- F4 `metadata.expected` 是执行后期望检查，不是 SafetyGate。
- TUI 基本遵守 API-only，不直接读 SQLite/driver。
- W2 observe 并发/失败保留上次 world 的方向已经实现。
- W3 transport reconnect/watchdog 方向在 driver transport 与 watch 中已有实现。

### B. 代码领先文档

- API 内有独立 `SafeProposalPlanner`，`/api/tasks/submit` 不走配置里的 `LLMPlanner`；文档更多描述 proposal 模式，未突出这条 API 特有 planner。
- React/TUI 已各自形成较完整的 viewmodel/formatter 层，但没有统一契约文档。
- API 支持 `/api/config/robots` 写配置并要求 restart watch，能力发布仍由下次 watch 完成。
- ChatRuntime streaming 路径是 reply-only，action draft 是文本协议；非 streaming LLM 路径和 CLI/MCP planner 路径行为更丰富，文档没有把这些分支讲得很清楚。

### C. 文档领先代码

- W4 `observed_at` 尚未进入 `Observation`/world store/API schema。
- W5 “driver 内阻塞调用必须带超时或 to_thread”未完全闭环：watch 的 heartbeat-failure halt 仍有直接 await；部分 driver 内部同步 I/O 依赖库 timeout，而非统一 `to_thread`。
- F6 场景规格/remote_sim 仍是后续方向，不是当前能力来源。
- “ActionItem”更多是前端/TUI UI 类型；后端真实契约是 `Action` + metadata。
- API/viewmodel 统一层仍未完成，frontend/TUI 仍各自解析后端 JSON。

## 9. 架构偏差

1. `ChatRuntime` 属于 agent/request 侧，却 import 并可在 `auto_step` 分支实例化 `WatchRuntime`。即使执行仍落在 watch 内，这会模糊“提案面不加载执行面”的边界。
2. `driver_coder.py` 的 validation 例外实际调用 `driver.execute()`，与宪法字面冲突，需要继续作为显式例外或搬到 watch-side validation harness。
3. Action contract 真实字段很薄，大量语义塞在 `metadata`；approval/expected/source 没有统一强类型后端模型，前端/TUI 各自猜。
4. Capability 来源是 driver runtime，但 config/manifest/registry/planner 都参与链路，缺少一份“capability contract truth table”。
5. World model 形状偏自由，缺少 `observed_at` 和 freshness contract，planner/context/UI 很难判断世界状态是否新鲜。
6. frontend/TUI/API 的展示模型重复，字段漂移风险高。
7. 旧 GUI 与当前 React frontend 架构不同：旧 GUI 直接持有 watch，容易让“GUI”一词在文档中歧义。
8. watch timeout 包装接近完成，但 halt/watchdog 路径仍有一处未包 timeout。

## 10. 重构建议评分

| 方向 | 收益 | 风险 | 必要性 | 结论 |
| --- | --- | --- | --- | --- |
| A. Capability/Action contract | 高 | 中 | 高 | 最优先。先把 `Action.metadata` 的 approval/expected/source 强约束下来，并明确 capability 来源。 |
| B. World model | 中高 | 中 | 中高 | 第二梯队。补 freshness/`observed_at`，但要小心影响 planner/UI/tests。 |
| C. API/ViewModel | 高 | 中 | 高 | 很值得做。可先增加后端派生 view 或共享 schema，减少客户端猜字段。 |
| D. Frontend/TUI 重复逻辑 | 中高 | 低中 | 中 | 适合跟 C 绑定，小步迁移 parser/formatter。 |
| E. Driver abstraction | 中 | 中高 | 中 | 不建议马上大改。先修 timeout 与 capability contract，再考虑低层/高层语义拆分。 |
| F. 旧 GUI 收敛 | 中 | 中 | 中 | 需要先决定旧 GUI 是否保留；若保留，文档必须明确它是 legacy/watch-owning。 |

## 11. 未来 3 轮最小路线

**第 1 轮：锁定 Capability/Action contract**

- 给 `metadata.approval`、`metadata.expected`、`metadata.source` 建立后端强类型/校验辅助。
- 从 Pydantic 导出 JSON Schema 或 golden examples，供 frontend/TUI 对齐。
- 明确 `driver.capabilities()` 是 runtime truth，config/manifest 只是选择与校验 driver。
- 不改执行行为。

**第 2 轮：收敛 API/ViewModel**

- 增加一个后端聚合 view 或共享 schema 包，覆盖 actions、robots、capabilities、world freshness。
- 先迁移 React/TUI 最重复的 robots/capabilities formatter 和 SSE event shape。
- 保留原 `/api/state` 作为 raw state，避免一次性破坏客户端。

**第 3 轮：World freshness + Safety 边界补洞**

- 为 observation/world 增加 `observed_at`，定义 per-robot 与 merged world 的更新时间规则。
- 将 watch heartbeat-failure halt 改为统一 timeout wrapper。
- 把 `ChatRuntime` 的 `auto_step` 或 watch import 移出 agent 层，或者登记为显式 legacy/CLI-only 例外。
- 重新跑 safety boundary tests，并补一条覆盖 `ChatRuntime` 不在 API request 路径实例化 watch 的测试。

## 12. 总图

### 用户任务完整流程

```text
React/TUI/CLI/MCP/旧 GUI
  -> ChatRuntime / AgentRuntime / SafeProposalPlanner / MCP facade
  -> Action proposal
  -> SqliteStateStore.append_pending_action()
  -> pending action board
  -> human approve if required
  -> WatchRuntime.step()
  -> StateStore.claim_next_ready_action()
  -> SafetyGate.validate()
  -> PhysicalDriver.execute()
  -> ActionResult
  -> StateStore completed/cancelled + feedback
  -> driver.observe()
  -> world update
  -> API/SSE -> frontend/TUI
```

### Capability / Action / World / Driver 关系

```text
physical-agent.yaml
  -> driver loader
  -> PhysicalDriver.capabilities()
  -> capabilities doc
  -> planner/context/chat/API clients
  -> Action(robot, capability, params, metadata)
  -> StateStore pending
  -> WatchRuntime + SafetyGate
  -> PhysicalDriver.execute(action)
  -> PhysicalDriver.observe()
  -> Observation/world
  -> planner/context/UI
```
