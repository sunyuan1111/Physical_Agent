# PLAYBOOK：待办项执行指引

> 配套 `SPEC.zh-CN.md` §4 矩阵使用：矩阵管"做什么/状态"，本册管"怎么做"。每项含：思路、关键文件、坑、验收。
> 写给后续执行者（人或 agent）。动工前先读 SPEC §0 不变量与 REFACTORING §3 决策先例；每项动工时按惯例先出一份轮次 brief。
> 最后更新：2026-07-07

---

## F0 LLM planner 实验

**思路**：三件事互相独立、并行推进。① 启用：项目 `physical-agent.yaml` 改 `agent.planner: llm`（代码默认值 rule_based 不动）；`agent.model` 保持 `fake/local` 即可——它是"此处未配置"的哨兵值，planner 会转而读 `workspace/.llm.json`（GUI 里配好的模型与 key）。② **本地调用留痕**：在 `openai_compatible` 的调用出口（chat/structured/stream 共用点）加薄封装，每次调用追加一行 JSONL 到 `workspace/llm-trace/`（gitignore）：ts / surface（复用 `metadata.physical_agent_surface`）/ model / messages / 响应 / usage / 延迟 / 错误。约 30 行，零新依赖；环境变量 `PA_LLM_TRACE=0` 可关。③ 实验：固定任务集写成脚本（越界坐标/不存在能力/中文/多步/模糊指令各≥3 条），逐条经 `/api/tasks/submit` 提交 + watch step，记录提案 JSON、gate 判定、feedback。
**坑**：trace 含 prompt 明文，留在 workspace 别提交；实验用 mock_arm 即可，别等仿真。Langfuse 已挂起（重启条件见 SPEC 挂起清单）——别在 F0 引入。
**验收**：llm-trace 里能对出三条调用路径的完整记录；产出 `docs/f0-report.zh-CN.md`（失败模式分类 + 对 F1/F3/F4 的排序建议）。

## B6 退役 markdown 后端（已完成，维护约束）

**完成状态**：`MarkdownStateStore` / runtime Markdown backend 已退役；active backend 只支持 SQLite。`workspace.backend: markdown` 和"省略 backend 但存在完整 legacy Markdown workspace"都必须报迁移指引，不能静默打开旧后端。
**保留边界**：`protocol/markdown.py` 与 parsers/renderers 仍服务 SAFETY.md 文件真源、SQLite 的 LOG.md 人类可读镜像、audit export，以及旧 workspace 迁移输入解析。不要把这类协议工具误删成"markdown 全家退役"。
**禁止回流**：`LegacyMarkdownWorkspaceReader` 只服务 `migrate-md-to-sqlite`，不得被 runtime factory、watch、API、GUI、agent、chat、planner 或 MCP 直接使用；不得实现 `StateStore`，不得承接新功能字段。后续删除 `migrate-md-to-sqlite` 时，应一并删除 `LegacyMarkdownWorkspaceReader`。
**维护检查**：新增状态字段时只改 SQLite 与审计导出；全仓 grep `LegacyMarkdownWorkspaceReader`、`MarkdownStateStore`、`workspace.backend: markdown`、`backend_role: legacy`，确认旧后端只出现在迁移/历史说明语境。

## F1 提案卡片 + Approve + 审批流

**实现口径（2026-07-07 已落地）**：① Draft 结构化（F1.1）：chat 的 Action Draft 固定走 `action-draft` fenced code block；前端用纯函数抽取并按 `ActionItem` 形状校验，坏 JSON/坏形状降级为普通 Markdown。② 卡片（F1.2）：`ChatPanel` 渲染 draft 卡片，对照"任务原文 vs 提案动作"，展示 robot/capability/params/reason；按钮文案用 **Add to Actions**，只调用既有 `proposeAction()` 创建 pending action，Edit 回填 `ProposalPanel`。**LLM/chat 不直接写动作板，只有人的提交会创建 action**。③ 审批流（F1.3）：不新增 runtime backend 状态机状态，approval 放在 action metadata；Actions 板的 **Approve execution / Reject** 才是执行审批。`approval.required` 由后端按 robot/capability 的 `requires_approval` 与 SAFETY 文件真源计算，不能信任 LLM、前端或 API caller；`claim_next_ready_action()` 在 SQLite 事务里跳过 `required && status != approved` 的 pending action，不阻塞后续 ready action。`POST /api/actions/{id}/approve|reject` 做幂等和非法终态保护，reject 写原因并转 cancelled。
**坑**：两个 Approve 语义必须分开：Chat draft 是"提交到动作板"，Actions 板是"放行执行"。审批≠免检，SafetyGate 只把 `requires_approval` 从"等待人"推进到"继续校验"，schema、bounds、capability、robot、SAFETY.md 仍照跑；approved action 后续被 Gate 拒绝时，保留 approval 记录并记录 safety rejected feedback/log。B6 后只维护 SQLite，不恢复 `MarkdownStateStore`、markdown backend 矩阵或 legacy runtime backend。
**F0 实验追加的两个子项**：① **planner 拒绝理由透出**——结构化输出加可选 `refusal_reason`，无提案时 GUI 展示"为什么没方案"，旧调用方缺字段仍兼容。② **Gate 直击组**——绕 planner 直接 propose 越界/幻觉动作，留下 LLM 时代 Gate 拦截审计样本，证明 planner 没产出时 Gate 仍能拦。
**验收**：chat 起草→Add to Actions→Actions 板 Approve execution→watch 执行→feedback 全程 GUI；非 `requires_approval` 不被审批流程阻塞；`requires_approval` 未 approved 不被 claim，approved 后仍经过 SafetyGate；队首未批准动作不阻塞后续 ready action；拒绝动作进 cancelled 并带原因；approval/source/refusal_reason 进入 LOG 镜像与 audit export；全量 pytest 与前端 build 通过。

## F2 结构化信息可读化（全应用原则）

**原则**：只做"读"。已知协议字段（pydantic schema 锁定）写定制组件；未知/raw/driver 私有字段用 JSON 树兜底；全应用 `<pre>` 裸 JSON 逐步清零。**不引表单库**（rjsf/JSON Forms 已挂起，见 SPEC 挂起清单）——产品没有手写 JSON 的需求，数据来源是 SDK 文件和 yaml。
**首批落地**（改 `ContextTabs.tsx` 为主）：① feedback 时间线：antd Timeline/Table，`status` 红绿灯 Tag，**失败原因读 `message` 字段**（不是 detail），`action_id` 点击跳 Actions 页（复用 setActivePage），事件类条目（`event: driver_*`）用不同图标；② world：objects 转表格（id/type/location/pose），environment 用 Descriptions，summary 置顶；③ raw 兜底：使用 AntD 原生折叠/Tree 或 `JsonSummaryLine` 摘要，继续只服务 unknown/raw/private 字段，不把 JSON viewer 当产品组件。
**实现口径（2026-07-07 已落地，2026-07-08 收口）**：`ContextTabs` 拆出 world/feedback/safety/capabilities 四个可读 tab；`FeedbackTimeline` 合并 feedback history、action approval/source metadata 与 chat `refusal_reason`；`WorldObjectsTable` 展示 objects/environment/robots/artifacts，未知 object 字段折叠进 raw。首轮曾用 `react18-json-view` 做懒加载 raw tree；F2.5 后续已改为 AntD 原生 RawDebug，非 RawDebug 展示统一为 `JsonSummaryLine`，`ActionBoard`、`ChatPanel`、`ConfigPanel`、`SettingsPanel`、`RawDebug` 均不再用裸 `<pre>` 或第三方 JSON viewer 展示状态 JSON。
**实现经验**：status 颜色映射、pose/location/schema 摘要应集中在 formatter，避免各面板各写一套；JSON tree 只作为折叠兜底，首屏仍优先放人能直接读的 message、action、robot、capability、approval 与 world summary；Playwright mocked 场景比 live workspace 更适合锁 UI 可读性，live smoke 继续覆盖真实 API 拼接。
**后续批次**：integration 结果与 state-check 可继续补更细的诊断分组；audit 导出内容的 Dashboard 页内预览仍远期；2026-07-08 已先以 `docs/current-architecture-audit.html` 落一版 current architecture audit 静态展示；若 F6 SceneView 落地，world 表格可与图形视图联动但不替代 raw 兜底。
**验收**：mock 跑 demo 全程不点 Raw Debug 能看懂发生了什么；坏任务拒绝原因在时间线直接可读；全应用 `<pre>` 出现次数下降可统计。

## F3 context_builder 解耦

**思路**：新建 `agent/context_builder.py`：`build_context(store, message, *, purpose: Literal["reply","proposal","tool_loop"], budget: ContextBudget) -> ContextBundle`（含 system 文案与 payload）。`ContextBudget` dataclass 收拢：recent_messages=12、summary 阈值 24、memory_top_n=20、world_max_chars、每 note 截断长度、max_tokens。替换 `chat_runtime.py` 三处重复（约 500/800/945 行区域）与 `llm_planner.py` 一处。world 超预算时降级：objects 仅留 id/location/status，raw 丢弃；memory 按 `importance DESC, created_at DESC` 取 top-N（B4a 字段终于用上）。
**坑**：三处 system 文案有故意的措辞差异（reply vs proposal）——用 purpose 参数化，别硬统一；先写 golden-file 快照测试锁住现有 payload 再动手，重构后 diff 应只有预期变化。
**验收**：golden 测试通过；chat/planner/tool_loop 行为回归全绿；魔法数字 grep 不再散落。

## F4 期望-比对-回灌

**实现口径（2026-07-07 已落地）**：`Action.metadata.expected` 进入 chat draft、LLM planner、MCP proposal 与 API proposal 的可选 metadata；实际归一化和比对集中在 `physical_agent/protocol/expectations.py`，避免 API/state 顶层 import watch 或 driver。断言形如 `{"path": "world.objects[id=red_block].location", "op": "eq", "value": "tray"}`，op 支持 `eq/ne/in/range`，路径支持点号、数组索引和简单 selector。watch 仅在 SafetyGate 通过、driver 返回 completed、并且 `update_world()` 成功后运行 `evaluate_expected()`；动作失败或 world 刷新失败时，只要原 action 有 expected，就写 `skipped` 的 `expectation_check`。SafetyGate 拒绝仍只写安全失败，不跑 expected。
**状态聚合**：一条 action 可带多条 check；任一 check 为 `violated` 则总事件 `violated`，否则任一 check 为 `skipped` 则总事件 `skipped`，全部 `verified` 才是 `verified`。每条 check 保留自己的 `status/message/expected/actual/path/op`；总事件的 `message` 摘要第一条 violated/skipped，方便 F2 时间线直接读。`expected` 为空或缺失时不产生 `expectation_check`。
**归一化边界**：`expected` 是执行后诊断，不是 SafetyGate，也不是 action schema 本体；坏 expected 不能让原本合法的 action 提交失败。写入 action metadata 时只做轻量规范化：单个对象转 list；非 list/object、条目非 object、字段缺失、未知 op、路径不可解析等都保留为后续 `skipped`；条数限制为 20，序列化大小限制为 8 KiB，超限写入截断说明；actual 用稳定 JSON 排序，避免快照抖动。
**回灌与可见性**：`expectation_check` 进入 feedback history；context_builder 在后续 chat/planner 上下文注入 expectation feedback，让 LLM 看到期望、实测与 message，但不自动重试。前端不大改流程：Chat draft 卡片与 Actions 表格显示 expected 摘要，raw expected 作为折叠兜底，避免模型生成的“自证”完全隐形。
**验收**：pick/place 带正确断言产生 verified；错误断言产生 violated；坏路径/坏格式/动作失败产生 skipped；缺失 expected 不产事件；多 check 聚合规则固定；expected 在提交前或动作详情可见；全量 pytest 与前端 build 通过。

## W2 观察并发化 + 频率解耦

**落地**（2026-07-07，`4e0f732`）：`update_world()` 对不同 robot 的 observe 使用 `asyncio.gather(..., return_exceptions=True)` 并发执行，timeout/异常逐 robot log-only 隔离；成功观测按 `robot_id` 稳定 merge，失败时以前一份 world 为底覆盖成功结果，避免单 robot 故障清空全局 world。
**频率**：`WatchConfig.observe_interval_ms` 为可选正整数；未配置或模板为 `null` 时运行时使用 `tick_ms`。`step()` 维持单步入口的 idle refresh 直觉；`tick()`/`run_forever`/API watch 用 observe interval 控制 idle observe，action claim/execute 仍按 tick，动作后的 `update_world()` 不受分频限制，继续给 F4 expectation_check 提供新鲜 world。
**验收**：并发启动、稳定 merge、单 robot observe exception 隔离、observe interval 默认/校验/分频、F4 post-action expected 回归均有测试；全量 `pytest` 277 passed。

## W3 transport 断线重连

**落地口径（2026-07-07）**：`drivers/transport/base.py` 增加 `ReconnectPolicy` 与 `connected/disconnected/reconnecting` 状态语义，policy 默认关闭；`WebSocketTransport` / `SerialTransport` 在初始 connect 失败时按 `delay = min(cap, base * 2 ** attempt)` 退避重试，运行中读写发现断连时丢弃旧资源并启动后台重连。Loopback 扩展了连接失败次数、运行中断连和后台重连模拟，供单测使用。
**执行语义**：reconnecting/disconnected 期间 `write/read/request` 立即抛 `TransportReconnecting` / `TransportDisconnected` / `TransportReconnectFailed`，watch 把 action 标 failed 并写人可读 feedback；不排队命令、不自动 retry action、不重放旧 execute。执行中 peer close/OSError 视为 execution state unknown，以现有 failed/cancelled 语义收口。
**driver hook**：`PhysicalDriver.on_transport_reconnected()` 默认 no-op；transport 可通过 `on_reconnected` 回调通知 owner driver。`xiaozhi_mcp` 在 WebSocket 重连成功后标记待刷新，下一次 health/observe/execute 前重新 initialize 与 tools/list（fire-and-forget 模式刷新工具映射）。
**边界**：W3 不改 SafetyGate、F1 approval、F4 expected 语义；不做 W4 多机器人并行 execute，也不扩 `observed_at` schema。reconnect success 只说明通信恢复，不代表机器人状态安全，后续仍以 observe/health 的世界事实为准。
**验收**：Loopback 覆盖 connect retry、max retries exhausted、reconnecting fail-fast、hook；WebSocket 本地 fake server 覆盖 server 主动断开后重连并再次 read/write；Serial fake 覆盖 open retry 与 OSError 断连；watch 覆盖 fail-fast feedback、执行中断连 unknown failed、reconnect exhausted feedback。全量 `pytest` 294 passed。

## W4 多机器人并行执行 + observed_at

**思路**：step() 领取后按 robot 分组，不同 robot 的动作 `asyncio.gather` 并行执行（同 robot 内保持串行）；`Observation` schema 加 `observed_at: datetime`（driver 基类默认填 now，driver 可覆盖）。
**坑**：并行后 feedback 写入是共享 store——SQLite 的写锁已由 B3.5 事务保证，但写入顺序不再确定，测试断言别依赖顺序。
**验收**：双机器人各一动作时一次 step 双执行；world 里能看到各机器人观察时间。

## W5 driver 编写守则

**思路**：三处落笔：`drivers/templates.py` 生成的 driver 模板注释里加"阻塞调用须带超时或 `asyncio.to_thread`"；`agent/driver_coder.py` 的 LLM 生成 prompt 加同样规则；`hardware-bringup-checklist.zh-CN.md` 加检查项。
**验收**：`integrate` 生成的新 scaffold 里能看到该注释；driver_coder 生成的代码不出现裸阻塞 I/O（抽查）。

## F5.1 LeRobot motors（触发：舵机臂到手）

**思路**：`feetech-servo-sdk` 进 `[servo]` extra；新 driver `feetech_arm`——初始化 FeetechMotorsBus（端口/波特率/舵机 id 表进 config_schema），observe 轮询 Present_Position/Load/Temperature/Voltage，execute 的 move_to 走 sync write 目标位置，halt 写 Torque_Enable=0。参考 LeRobot `src/lerobot/motors/feetech/`。
**坑**：所有总线读写是阻塞串口——全部 `to_thread`（W5）；先做标定流程（限位/零位存 config）再谈动作。

## F5.2 ros_mcp driver（触发：有 ROS 设备）

**思路**：仿 `xiaozhi_mcp.py` 结构；经 rosbridge websocket 订阅指定 topic 集合→observe 组装，execute 映射到 service/action 调用；topic/service 白名单写进 config_schema。**不采用让 LLM 直连 ros-mcp-server 的用法**——一切过 gate。

## F5.3 感知补语义（触发：小车+摄像头）

**思路**：做成 observe-only driver（无 execute 能力）：抓帧→检测模型（ultralytics 或小 VLM）→物体列表进 `Observation.objects`，原始帧路径进 artifacts。模型推理进程外跑或 to_thread。

## F6.0 场景规格设计（F6.1 前置，纯设计轮）

**思路**：每个 demo 一份场景规格文档（建议 `docs/scenarios/<name>.zh-CN.md` + 对应 yaml）：①能力词汇表（capability 名/params_schema/constraints/requires_approval）；②初始对象表（id/type/pose/状态字段）；③SAFETY 边界（bounds 与场地对齐）；④演示任务集（正例 + 必须被拦的反例，即 F0 坏任务的场景版）。**arm**：直接继承 mock_arm 的四能力和 schema，只需补对象状态字段（末端位置/持有物）；**car**：从零设计——`move_to(x,y)`/`stop`/`dock`/`patrol(zone)`，场地 bounds、障碍与充电桩对象、电量字段。
**验收**：两份规格评审通过后 F6.1 才动代码——规格即 driver 的验收标准。

## F6.1 Hero Demo Twin：机械臂（公司产品）+ 通用 SceneView

**产品定位**（2026-07-05 修订）：机械臂是公司产品，hero 归它；小车降为第二示例（F6.1b，使用指南性质）。**统一技术路线：渲染只做一个通用 SceneView 面板**——canvas 顶视图读 `world.objects`，按对象 `type` 映射图标（末端/方块/托盘/车/障碍/dock），新增 demo = 新 driver + 新图标 + 场景 yaml，面板零改动。任务级演示 2D 顶视图足够（demo 讲的是命令→审批→执行→断言闭环，不是运动学）。观众零安装、浏览器五分钟闭环、可随 demo 站部署。
**思路**：① `sim_arm` driver（纯 Python）：继承 mock_arm 能力 schema，加运动插值（末端 pose 随自身时钟连续变化而非瞬移，SceneView 上看得到"在动"）与持有物状态；② 通用 `SceneViewPanel`：懒加载 canvas，SSE 驱动，图标注册表按 type 扩展；③ F6.1b `sim_car` driver 随后复用面板：pose(x,y,θ)/速度/电量，运动学积分在 driver 自身时钟内做，halt=速度清零，碰撞判定在 driver（撞上→failed+人话 message，喂 F2 时间线与 F4 断言）。
**坑**：对象 pose 的坐标系约定要写进 F6.0 规格并与 SAFETY bounds 对齐，让"越界被 Gate 拦"在画面上可解释；插值状态是 driver 内部的，observe 只报快照——别把渲染帧率需求压到 watch tick 上。
**验收**：arm——`pick the red block and place it on the tray` 在 SceneView 上连续可见，断言 verified；car——"go to charging dock" 车开过去、"drive to x 999" 被拦画面不动；新增第三个 demo 不改面板代码。

## F6.2 remote_sim driver + BYO Simulator 协议

**定位**：Physical Agent 不内置仿真引擎，提供"把你自己的仿真器接成一台虚拟硬件"的协议。行业先例：VDA5050（AGV 主控↔车辆的 JSON 标准，MQTT 承载）证明这类"命令/状态协议"是成熟模式；我们不用 MQTT（省 broker），用**已有的 WebSocketTransport + JSON**。
**思路**：新 driver `remote_sim`（config：endpoint/token/capability 超时）。协议消息**镜像现有 driver 契约**：连接握手时对端必须先发 `capabilities` 声明（含 params_schema/constraints）——**没有它 Gate 无从校验，直接拒连**（这是对外部方案最重要的修正：只给 observe/execute/health/halt 四件套不够）。随后 `{op: observe|execute|health|halt, ...}` 请求-响应，负载对齐 Observation/ActionResult 的 pydantic schema。W1 超时全覆盖。**参考适配器**：一个独立 Python 脚本把 CoppeliaSim 的 ZMQ API 包成本协议 ws 服务——一石二鸟：验证协议可用性 + 提供机械臂 3D 体验（本地开发用）。
**明确不做**：通用建模器、拍照生成场景、统一物理语义、"仿真通过=真实安全"的等价承诺。
**验收**：用参考适配器接 CoppeliaSim 跑通 pick/place；断掉适配器时 watch 按 W1 超时降级不挂死。

## F6.3 conformance 测试套件

**思路**：CLI `physical-agent sim-verify <endpoint>`——按序验证：握手带 capabilities → observe 返回合法 Observation → execute（observe 能力）语义正确 → 故意超时场景 → halt 立即生效。复用 `test_driver_contract` 的断言逻辑。通过才算合格 BYO endpoint。

## F6.4 远期路标

真臂 URDF 数字孪生（浏览器 urdf-loader/Three.js 生态成熟，可网页端渲染，与 F5.1 会师）；预演 Gate（难点仍是"用当前 world 快照初始化仿真场景"的状态同步）。MuJoCo 无头评测 harness 降级为远期候选（设计见 git 历史）。

## T 系列：Ink 终端 UI（独立线，与 F 主线无依赖）

**定位**：第五个入口——交互式终端工作台（SSH/无 GUI 场景 + 开发者日常），与 typer CLI 分工：typer 管脚本化/自动化命令，Ink 管交互。**纯 API 客户端，零核心改动**，复用 FastAPI 全部端点与 SSE。
**思路**：新目录 `tui/`（Node 20+ / TypeScript / Ink 5 + React 18）。依赖：`ink`、`ink-text-input`、`ink-spinner`、SSE 用原生 fetch 流式解析（复用 dashboard `api.ts` 的 parseSseBlock 逻辑翻译成 Node 版）。三档递进：**T1** 只读——StatusBar（health/backend/watch）+ chat 流式对话 + actions 列表实时刷（SSE）；**T2** 交互——提交 task、approve/reject（依赖 F1.3 端点）、workspace reset；**T3** 补齐——config/robots 视图、上传。入口 `npm start -- --api http://127.0.0.1:8766`。
**坑**：Ink 是 Node 生态——引入了第二运行时依赖，若在意可改用 Python 的 Textual（同语言零新增依赖），**决策记录：选 Ink 是因为技能与 dashboard 的 React 复用 + Claude Code 同款生态**；SSE 断线要做和 dashboard 一样的降级轮询；终端宽度自适应用 Ink 的 flexbox，别写死列宽。
**验收**：T1 三面板可用、chat 流式不卡顿；`ink-testing-library` 覆盖核心组件渲染。
**实现口径（2026-07-07）**：已落 `tui/` 独立包，包含 API client、SSE parser、command parser 与 StatusBar/ChatPanel/ActionsPanel/CommandInput。TUI 只调用 HTTP API/SSE，不读 SQLite/workspace，不 import Python/watch/driver。T2-lite 已含 chat、`/task`、`/approve`、`/reject`、`/reset true`、`/refresh`、`/help`、`/quit`；`/execute`、`/driver`、`/hardware-control` 明确拒绝。T3 的 config/upload 仍未完成。
**实现口径（2026-07-08 T3）**：补 view/page 概念，默认仍是 chat transcript + actions 的纵向终端体验；`/view status|chat|actions|robots|config|uploads` 可切单主视图，StatusBar 与 CommandInput 常驻。`/config` 复用 `GET /api/config` 展示 workspace/watch/agent/robots 摘要并过滤 `api_key`/secret/token；`/robots`、`/robot <id>`、`/capabilities <id>` 合并 config、world、capabilities 展示 driver/mode/endpoint/health、requires_approval、params_schema 与 constraints 摘要。`/upload <path>` 与 `/ingest <path>` 只用本地文件构造 multipart `POST /api/upload` 请求，沿用 dashboard 的文本后缀与 5MB 限制，前置拒绝目录、过大、明显二进制或非 UTF-8 文件；上传内容不直接注入 LLM，视图只显示 filename/size/sha/id/untrusted/chunks 元数据。`/register-robot <json>` 仅调用既有 `POST /api/config/robots`，不做 YAML 编辑器、不直接写 `physical-agent.yaml`。Windows Terminal / PowerShell 下推荐用 `cd tui; npm start -- --api http://127.0.0.1:8766` 启动；带空格路径用引号传给 `/upload`。
**验证**：2026-07-07：`cd tui && npm run build` 通过；`cd tui && npm test` 13 passed。2026-07-08 T3：`cd tui && npm test` 44 passed；`cd tui && npm run build` 通过；TUI 安全 grep 覆盖无 `driver.execute`、无 `physical_agent.watch`/`physical_agent.drivers` import、无 SQLite 直接访问。2026-07-08 command acceptance：新增 `tui/tests/scenarios/{basic,chat,actions,config,robots,upload,error}.scenario` 与 `tests/scenario-runner.test.tsx`，按真实 Ink 输入驱动 `App`，mock API/SSE 响应并断言终端输出、API 调用次数和 state/config 变化；覆盖 `/help`、`/view *`、`/task`、`/approve`、`/reject`、`/reset`、`/config`、`/robots`、`/robot`、`/capabilities`、`/upload`、`/refresh`、`/quit` 及 API offline、SSE error/EOF、polling fallback、缺参、非法命令、上传失败、reset confirmation failure；矩阵见 `docs/tui-command-matrix.md`。

## C4 i18n / E3 视觉打磨

**思路**：C4：antd `ConfigProvider locale` + 文案抽到 `locales/{zh,en}.ts` 键值表（不上 i18next，工程量不值），默认跟浏览器语言，切换存 localStorage。E3：暗色模式用 antd `theme.darkAlgorithm` token 切换 + localStorage；首次引导用 antd Tour 组件串 setup→watch→demo 三步。
**实现口径（2026-07-07）**：新增 `frontend/src/locales/`，`App.tsx` 统一接 `ConfigProvider locale`、`MessagesProvider`、theme mode 与 Tour 状态。高频导航、StatusBar、Actions、Chat、Settings、Hardware、Config、RawDebug、Robots 等文案已抽取；Settings 提供语言、主题与重新显示 Tour。暗色模式使用 AntD `darkAlgorithm` + `body[data-theme]` CSS 变量，覆盖页面背景、侧栏、卡片、JSON fallback、chat draft、drawer 等明显浅色区域。
**验证（2026-07-07）**：`cd frontend && npm run build` 通过；Playwright 覆盖语言切换写 localStorage、dark mode 写 localStorage/body 状态、首次 Tour 关闭与 Settings 重开。

## E0-e2e 补课

**思路**：`frontend/e2e/dashboard.spec.ts` 追加：hardware 页生成 scaffold（用临时 SDK 目录 fixture）→注册表单提交→ConfigPanel 出现新 robot；Settings danger zone 确认流；每个新 testid 都已埋好（`register-robot-*`、`reset-workspace-*`、`config-panel`）。
**实现口径（2026-07-07）**：在现有 dashboard e2e 中补 mocked API 场景，固定默认测试态为 English/light/Tour dismissed，避免新 Tour 遮挡旧流程。新增覆盖：reset confirm 错误请求不执行 + GUI Popconfirm 成功 reset、Hardware scaffold→Register to config→ConfigPanel 出现新 robot、i18n、dark mode、Tour 首次打开/关闭/重开。
**验证（2026-07-07）**：`frontend/playwright.config.ts` 默认使用 `.tmp/e2e/physical-agent.yaml` 临时 workspace，避免覆盖根目录本地配置；`cd frontend && npx playwright test` 18 passed。

## 基建：CI

**思路**：`.github/workflows/ci.yml` 三 job：① pytest（matrix 3.11/3.12，`pip install -e .[dev,server,llm]`，**env 里清空代理变量**）；② 前端 `npm ci && tsc -b && vite build`；③ e2e smoke（Playwright chromium，只跑 overview 用例）。触发 push+PR。
**坑**：测试内建 env-scrub fixture（`tests/conftest.py` 里 monkeypatch 删代理变量）比在 CI yaml 里清更治本——两处都做。
**实现口径（2026-07-07）**：新增 `.github/workflows/ci.yml`，包含 Python 3.11/3.12 pytest、frontend `npm ci` + build、TUI `npm ci` + build/test、Playwright Chromium e2e。`frontend/playwright.config.ts` 的 webServer 命令改为 Windows/Linux 分支，先初始化 `.tmp/e2e` 临时 workspace，再启动 API，并允许 `PA_E2E_API_COMMAND` / `PA_E2E_DEV_COMMAND` 覆盖。
**实现口径（2026-07-08）**：按“宽松但守底线”调整 CI：默认阻塞项只保留 Python safety smoke 与 frontend build；TUI 和 dashboard e2e 改为 `continue-on-error` advisory；Python 3.11/3.12 全量 pytest 矩阵改为 `workflow_dispatch` + `full=true` 手动触发；CI 策略、失败处理与本地复现写入 `docs/CI.zh-CN.md`。
