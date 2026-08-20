# SPEC：优化目标与追溯矩阵（活文档）

> 本文合并了原 optimization-spec（安全不变量）、plan-f（当前目标）与 traceability-matrix（账本），原件已删除、git 历史可查。历史过程见 `REFACTORING.zh-CN.md`。
> **维护规则**：每轮 session 收尾更新 §4 矩阵一行 → commit → push；里程碑拆分时拆行记录；状态以验收测试通过为准。
> 最后更新：2026-07-08

## 0. 安全边界（三层：宪法 / 授权策略 / 工程纪律）

### 0.1 宪法（仅两条；修改=修宪，需单独决策记录说明动机与放弃了什么）

1. **执行权唯一**：`driver.execute` 只允许出现在 watch 执行循环的调用栈里。一切提案/请求侧代码路径（HTTP 处理器、LLM 调用链、CLI 命令、MCP 工具）不得加载 driver、不得调用执行。约束对象是**代码路径**而非模块或进程——API 进程里跑 watch 后台服务不违宪，请求处理器直接执行才违宪（`test_safety_boundaries` 强制）。
2. **执行前校验不可绕过**：任何作用于物理世界的动作，执行前必须过执行侧校验（SafetyGate）；SAFETY 规则以文件为真源，提案侧无法修改。

**预注册例外**（用到时显式设计即可，不算破例）：急停/halt 类"去激活"指令可有提案侧直达通道——宪法管"让机器人动"，不管"让它停"；高频流式控制（遥操作/VLA 技能）按**会话粒度**过闸——gate 审"开启会话"，帧流走专用通道，急停与边界包络兜底。

### 0.2 授权策略（用户可配，决定人参与到什么程度）

人类参与度按能力分级：每次询问（ask）/ 一次放行（standing grant）/ 白名单全自动（auto）。**授权改变的是"要不要停下来等人"，永远不改变"要不要校验"**。当前载体：`requires_approval` + F1.3 审批流；档位 3 闭环是 auto 档的延伸，仍在管线内。

### 0.3 工程纪律（会演化，改动记入 REFACTORING 即可）

- 新能力默认关闭或向后兼容；每步小步可回滚。
- 校验清单内容随功能演化（当前 10 项非冻结数字），删减需谨慎评估。
- **每轮开工流程（对人和 agent 同等生效）**：读本节 → §4 找到条目 → 读 `PLAYBOOK.zh-CN.md` 同名条目 → 出轮次 brief → 实现+测试 → 更新 §4 与 REFACTORING。agent 执行者的完整守则见仓库根目录 `AGENTS.md`。

## 1. 系统与产品框架

```
入口(CLI/API/GUI/MCP) → 认知侧(只提案) → 状态黑板(SQLite默认) → watch(执行+看门狗) → driver+transport → 硬件
```

三入口 = 同一提案管线的自主档位：**档位0** 手动表单（jog）· **档位1** Chat 起草→人批 · **档位2** Task 一次规划 · **档位3** 闭环自主（未建）。
分工恒定：LLM 起草、人类批准、Gate 校验、watch 执行、规则判成败。

## 2. 当前目标（Phase F：LLM in the Loop）

| 编号 | 内容 | 要点 |
| --- | --- | --- |
| F0 | LLM planner 实验（立即） | yaml 切 `planner: llm`（代码默认不动）；**本地 JSONL 调用留痕**（llm-trace，零新服务，surface 标签区分三条调用路径）；坏任务实验集（越界/幻觉能力/中文/多步）→ 实验报告驱动后续排序 |
| **B6（已完成历史收口项）** | 状态层收口 | 已删 `MarkdownStateStore`/factory 分支/config legacy 自动探测/矩阵测试 md 侧与 `test_e2e_markdown_loop`；**保留** markdown renderer/parser（SAFETY 真源、LOG 镜像、audit export 依赖）；`migrate-md-to-sqlite` 留一个版本周期仅为读取旧 Markdown workspace 迁移输入，**不代表 Markdown runtime backend 仍被支持**。已在 F1.3 前完成，避免审批元数据继续为退役后端重复实现 |
| F1 | 提案卡片 + Add to Actions + 审批流（已完成） | chat draft 固定为 `action-draft` fence，前端解析校验后渲染卡片；Chat 卡片按钮叫 Add to Actions，只创建 pending action，不等同执行审批。`requires_approval` 由后端按 robot/capability 计算，写入 action metadata；Actions 板的 Approve execution / Reject 才改变执行放行状态。watch claim 会原子跳过未批准动作但不阻塞后续 ready action；SafetyGate 仍照常校验 schema、bounds、capability、robot、SAFETY.md。 |
| F2 | 结构化信息可读化（全应用原则） | **通用原则：已知协议字段一律定制组件呈现，未知/raw 字段 JSON 树兜底（懒加载），`<pre>` 裸 JSON 逐步清零**。首批落地：feedback 时间线（status 灯/action 跳转/失败原因用 `message` 字段）、world objects 表格、capabilities/config/integration 结果的卡片化；协议 schema 由 pydantic 锁定，定制组件不会白写 |
| F3 | context_builder 解耦（已完成） | `context_builder` 统一 reply/proposal/planner/tool_loop 上下文；ContextBudget 收拢魔法数字；world/capabilities 超限摘要化；memory 按 importance 排序注入；golden-file 测试 |
| F4 | 闭环地基（已完成） | 提案带 expected 断言 → 执行后**确定性比对**（不用 LLM 当裁判）→ 写入 `expectation_check` feedback；violated/skipped 回灌 LLM 上下文，自动重试默认关 |
| F5 | 硬件生态（条件触发） | F5.1 舵机臂到手→LeRobot motors 包 driver（D2b 销账）；F5.2 有 ROS 设备→ros_mcp driver（不绕 gate）；F5.3 小车+摄像头→YOLO/VLM 物体列表进 world |
| **T（独立线：Ink 终端 UI）** | 第五入口 | Node/TS/Ink 5 交互式终端工作台（`tui/` 目录，纯 API 客户端零核心改动）；T1 只读（状态+流式 chat+actions 实时）→ T2 交互（提交/审批/重置，审批依赖 F1.3）→ T3 补齐。typer CLI 保留管脚本化，Ink 管交互；选 Ink 而非 Textual 是为复用 dashboard 的 React 技能。与 F 主线无依赖（除 T2 审批），可随时穿插 |
| F6 | Demo Twin + BYO Simulator（**不做通用仿真**） | **统一技术路线：N 个 sim driver + 一个通用 SceneView 面板**（canvas 顶视图读 world.objects，按对象 type 绘制；新增 demo = driver+图标+场景 yaml，渲染零改动）。F6.0 场景规格先行：每个 demo 一份规格（能力 schema/初始对象/SAFETY 边界/演示任务集）；F6.1 **Hero：机械臂孪生（公司产品）**——能力词汇表继承 mock_arm，加运动插值与对象状态；F6.1b 智能小车第二示例（使用指南性质，能力词汇表从零设计：move_to/stop/dock/patrol）；F6.2 **remote_sim driver + BYO 协议**——WebSocket+JSON 镜像 driver 契约，**必须含 capabilities 发现**（无 params_schema 则 Gate 无从校验，拒连），CoppeliaSim 作参考适配器（高保真 3D 需求者自接）；F6.3 conformance 套件（`sim-verify` CLI）；F6.4 远期：真臂 URDF 数字孪生 + 预演 Gate |

**挂起（明确不做）**：Langfuse 观测平台（2026-07-05 评估：F0 量级几十次调用，本地 JSONL 留痕足够；重启条件=F4 闭环自动调用量增大或 F6.2 批量评测需要打分 UI，届时优先 Cloud 免费档）、instructor / LiteLLM（等 F0 数据）、自动重规划无人值守档、chat markdown **深度**渲染扩展（基础渲染已由用户以 react-markdown 落地于 ChatPanel；代码高亮/一键复制等扩展不排期）、通用 yaml 编辑器（lite 版已够）、schema 驱动表单库 rjsf/JSON Forms（2026-07-05 评估：产品无手写 JSON 需求——若将来出现高频结构化输入场景再评估，届时选 rjsf + @rjsf/antd）、**通用仿真平台**（2026-07-05 产品决定：只做 demo twin 与 BYO 接口，见 F6）。

## 3. 已完成里程碑（速查）

P0/P1/D0/P1.5 安全边界+工具循环 · A3 上下文压缩 · B1-B3.8 状态存储全套（SQLite 默认/原子动作/lease/审计）· B4a-c 记忆摄入检索地基 · C1-C3.2 FastAPI+SSE+React 仪表盘 · D1-D3.1 传输层+心跳看门狗 · D4 实机文档 · A1.0-A1.6a 官方 SDK/流式/abort/设置/深思考 · B5 后端口径收口 · E0.1-E0.3 GUI 对齐（重置/硬件面板/配置注册）· W1 驱动调用超时保护 · B6 退役 MarkdownStateStore 后端 · F1 提案卡片与 action 级审批流 · F2 结构化信息可读化 · F3 context_builder 解耦 · F4 expected 确定性比对 · W2 观察并发化与 observe 分频 · W3 transport 断线重连。
逐项提交号与决策见 `REFACTORING.zh-CN.md` §1-§2。测试基线 294 用例。

## 4. 待办矩阵（backlog，活账本）

> **每项的实现思路、关键文件、坑与验收见 `PLAYBOOK.zh-CN.md` 同名条目**；动工前按惯例出轮次 brief。
> 归属列图例：`§2` = 本文件第 2 节"当前目标"的对应行（不是外部文档）；其余为来源备注（W1 遗留 = REFACTORING §2 W1 小节；PLAYBOOK 同名条目 = 只在 PLAYBOOK 有详情）。

| 编号 | 内容 | 归属 | 状态 |
| --- | --- | --- | --- |
| F0 | LLM planner + 本地调用留痕 + 坏任务实验报告 | §2 | 🟡 第一轮完成；15 条：10 完成、5 无提案、0 Gate 拦截。**Review 复核（2026-07-06）**：trace 证实 bounds 在 prompt 内、拒绝为知情拒绝——报告"F3 优先"论据不成立，顺序维持 F1→F3；Gate 直击组已并入 F1 补齐 |
| B6 | 退役 markdown 后端（保留 renderer 与迁移命令） | §2 | ✅ 2026-07-06 完成 `9072b4e`：active backend 只剩 SQLite；旧 Markdown 仅迁移 reader 可读 |
| F1 | 提案卡片 + Add to Actions + 审批流 | §2 | ✅ 2026-07-07 完成：Chat draft 卡片只提交动作板；Actions 板审批才放行 `requires_approval`；approval required 后端计算，SQLite 原子 claim 跳过未批准动作；拒绝/审批元数据进 LOG/audit |
| F2 | feedback 时间线 + world 视图 + JSON 树 | §2 | ✅ 2026-07-07 完成：feedback/action approval/refusal_reason 时间线可读，world objects 表格化，capabilities/config/integration 轻量可读；raw JSON 改懒加载树兜底。提交 `58a75b0`。2026-07-08 补 `docs/current-architecture-audit.html` 静态审计阅读页，展示 `docs/current-architecture-audit.md` 内容 |
| F2.5 | State Overview 产品化收口 | §2/F2 后续收口 | ✅ 2026-07-08 完成：新增 `frontend/src/viewmodels/` formatter 层；Overview 首屏用 AntD Card/Statistic/Table/Descriptions/Tag/List 展示 system/robots/capabilities/environment/world objects；`RawDebug` 仅折叠展示 unknown/raw/backend private 字段。follow-up：非 RawDebug 的 params/schema/raw 展示统一为 Overview capability 风格的轻量摘要；RawDebug 也改为 AntD Collapse/Tree，移除 `react18-json-view` 依赖与 `json-view` chunk |
| F3 | context_builder 解耦 | §2 | ✅ 2026-07-07 完成 `9cbb540`：新增只读 `context_builder`，统一 chat reply/proposal/tool_loop 与 LLM planner payload；planner 使用独立 purpose；golden snapshot 覆盖四路；memory 改按 importance/created_at 注入 |
| F4 | 期望-比对-回灌 | §2 | ✅ 2026-07-07 完成：action metadata 接收 `expected`；watch 在动作完成并刷新 world 后写 `expectation_check`；多 check 状态按 violated > skipped > verified 聚合；坏 expected 不影响 action 合法性；Chat/Actions 可见 expected 摘要 |
| W2 | 观察并发化（gather）+ 频率与 tick 解耦 | W1 欠账 | ✅ 2026-07-07 完成 `4e0f732`：`update_world()` 按 robot 并发 observe、按 `robot_id` 稳定 merge；`observe_interval_ms` 未配置时等价 `tick_ms`；长跑 watch/API watch 中 claim 仍按 tick，idle observe 分频，动作后 world refresh 仍立即服务 F4 expectation_check |
| W3 | transport 断线重连（backoff） | W1 欠账 | ✅ 2026-07-07 完成 `1d9a812`, `7762c0f`：`ReconnectPolicy` 默认关闭；Loopback/WebSocket/Serial 支持 connect retry 与运行中断连后台 backoff；reconnecting/disconnected execute fail-fast、不排队、不重放旧动作；driver 预留 reconnect hook，xiaozhi_mcp 重连后刷新 handshake/tool cache；关闭/取消中的迟到 open 会清理资源且不触发 hook；未做 W4 并行 execute/observed_at |
| W4 | 多机器人并行执行 + world 带 observed_at | W1 欠账 | ⚪ 接实机/多机前；F4 当前使用执行后 `update_world()` 的新鲜观测，未扩 `observed_at` |
| W5 | driver 编写守则：阻塞调用须带超时或走 to_thread（写进 driver 模板与生成规则） | 讨论产出 | ⚪ 轻 |
| F5.1-F5.3 | LeRobot motors / ros_mcp / 感知语义层 | §2 | ⏸ 条件触发 |
| F6.0 | 场景规格设计（arm 继承 mock_arm；car 能力词汇表从零定） | §2 | ⚪ F6.1 前置 |
| F6.1 | Hero Demo Twin：机械臂（公司产品）+ 通用 SceneView 面板 | §2 | ⚪ F0 之后 |
| F6.1b | 智能小车第二示例（使用指南） | §2 | ⏸ 随 F6.1 面板复用 |
| F6.2 | remote_sim driver + BYO Simulator 协议（含 capabilities 发现；CoppeliaSim 参考适配器） | §2 | ⚪ 排 F6.1 后 |
| F6.3 | BYO conformance 测试套件（`sim-verify`） | §2 | ⏸ 随 F6.2 |
| F6.4 | 真臂 URDF 数字孪生 + 预演 Gate | §2 | ⏸ 远期 |
| MuJoCo-harness | 无头批量评测（原 F6.2，降级为远期候选） | git 历史可查设计 | ⏸ |
| T1 | Ink 终端 UI 只读三面板（状态/chat/actions） | T 独立线 | ✅ 2026-07-07 完成：`tui/` 独立 Node/TS/Ink 包，状态/chat/actions 三面板，SSE 优先 + polling/degraded fallback，纯 HTTP API/SSE 客户端；2026-07-08 review fix：SSE clean EOF 降级轮询、真实 watch enabled/disabled/unknown 状态；2026-07-08 chat/actions 持久化修复：`/api/events` summary 不再覆盖完整 state，而是触发完整 `/api/state` 刷新；2026-07-08 LLM 状态显示：启动/`/refresh` 检查 LLM settings/test，显示模型、key 是否配置与短失败原因；2026-07-08 Windows/npm 启动参数兼容裸 API URL（`npm start -- http://127.0.0.1:8766`） |
| T2/T3 | Ink 交互（审批依赖 F1.3）与补齐 | T 独立线 | ✅ 2026-07-07 T2-lite 完成：chat、`/task`、`/approve`、`/reject`、`/reset true`、`/refresh`、`/help`、`/quit`；2026-07-08 review fix：chat stream 异常/AbortError 均清理 streaming/busy 状态；2026-07-08 交互改为更接近 Claude Code 的纵向 transcript；2026-07-08 取消单条 chat 220 字符硬截断并保留换行；2026-07-08 chat 历史改为 Ink `Static` append-only 输出，空闲 `watch_step` 不再触发 live 刷新；2026-07-08 T3 完成 config/robots/uploads 视图、`/view`/`/config`/`/robots`/`/robot`/`/capabilities`/`/upload`/`/ingest`/`/register-robot` 命令、API-only multipart 上传与 TUI 安全 grep；2026-07-08 command acceptance 收口：新增 `tui/tests/scenarios/*.scenario` 与 runner，覆盖全部用户命令、API offline、SSE error/EOF、polling fallback、缺参、非法命令、上传失败、reset confirmation failure，并生成 `docs/tui-command-matrix.md`；`cd tui && npm test` 场景纳入默认测试，`npm run build` 通过 |
| C4 | 前端 zh/EN i18n | PLAYBOOK 同名条目 | ✅ 2026-07-07 完成：轻量字典 + AntD locale + Settings 切换 + localStorage；高频导航/状态/Actions/Chat/Settings/Hardware/Config 文案已抽取 |
| E3 | 暗色模式 + 首次引导 | PLAYBOOK 同名条目 | ✅ 2026-07-07 完成：AntD `darkAlgorithm` + CSS 变量暗色适配 + localStorage；首次 3 步 Tour 与 Settings 重开入口 |
| E0-e2e | Hardware/注册/DangerZone/ConfigPanel 的 Playwright 用例 | PLAYBOOK 同名条目 | ✅ 2026-07-07 完成：补 Danger Zone reset、Hardware scaffold→register→ConfigPanel、i18n、dark mode、Tour；dashboard e2e 18 passed |
| B4-vec | 真实向量 RAG（sqlite-vec + embedding） | 延后项；原设计见 git 历史 optimization-spec §4 | ⏸ |
| 基建 | CI（pytest 3.11/3.12 + 前端 build）；push 纪律；测试 env-scrub fixture | 流程欠账 | ✅ 2026-07-08 调整为宽松 CI：默认阻塞 Python safety smoke + frontend build；TUI/e2e 为 advisory；Python 3.11/3.12 全量 pytest 改为手动 full run；新增 `docs/CI.zh-CN.md` |

## 5. 验证环境备注

沙盒验证需：Python≥3.11（或 datetime.UTC shim）、清除代理环境变量、Linux 版 esbuild/rollup 原生二进制（与 lock 版本一致）。用户本机（Win + Py3.12）无需处理。唯一预期失败：doctor 在 Py3.10 沙盒正确拒绝版本。
