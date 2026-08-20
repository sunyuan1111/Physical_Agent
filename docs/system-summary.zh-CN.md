# 系统现状快照（按子系统：职责 · 现状）

> 快照时间：2026-07-05 · 对照 HEAD `9bf3510` + 未提交的 W1/docs 改动
> **防腐设计**：本文只写"是什么、现在怎样"；一切欠账/待办**不在此复制**，统一见 `SPEC.zh-CN.md` §4（上一版就是因为复制了欠账表而三天过期）。过时后可随时让 agent 按本结构重扫生成。
> 状态图例：✅ 稳定 · 🟢 近期新增 · 🟡 部分/降级

## 0. 一句话地图

```
入口(CLI/API/GUI/MCP) → 认知侧(只提案) → SQLite 黑板 → watch(执行+看门狗+超时保护) → driver+transport → 硬件/仿真
```

三入口 = 同一提案管线的自主档位（详见 SPEC §1）；安全边界三层结构见 SPEC §0。

## 1. 入口层

| 模块 | 职责 | 状态 |
| --- | --- | --- |
| `cli.py`（typer，16 命令 + driver 子命令） | init/setup/doctor/state-check/gui/api/watch/run/chat/inspect/llm-test/integrate/export-audit/migrate/ingest-file/search-memory | ✅ |
| `api/server.py`（FastAPI，22 端点） | proposal-only REST + chat(stream/reset/abort) + settings/llm + upload + events(SSE) + **workspace/reset + integrate + config + config/robots**(E0) | ✅ 🟢 |
| `api/watch_service.py` | `--watch` opt-in 常驻 watch + SSE broker | ✅ |
| `frontend/`（React+AntD，14 组件 9 页面） | Overview/Actions/World/Robots/**Hardware**/Memory/Safety/Events/Settings；懒加载+chunk 拆分；chat 基础 markdown 渲染（react-markdown）；ConfigPanel 只读 + 注册 robot | ✅ 🟢 |
| `gui/server.py`（旧内联 GUI） | ThreadingHTTPServer 单文件版，经同一 SQLite-only state factory 读写 | 🟡 legacy UI |
| `mcp/server.py` | MCP facade：submit_task/get_state/list_robots/propose_action（提案专用） | ✅ |
| Ink 终端 UI | 第五入口（计划中，SPEC T 系列） | ⚪ 未建 |

## 2. 认知侧（只提案）

`agent/runtime.py`（run_task→planner→写提案）、`chat_runtime.py`（chat 主入口，流式 respond_stream）、`context_builder.py`（reply/proposal/planner/tool_loop 上下文组装）、`planner.py`+`rule_based.py`+`llm_planner.py`（规则/LLM 双 planner，yaml 可切）、`tool_loop.py`（proposal-only 工具白名单）、code 技能族、`onboarding.py`+`driver_coder.py`（接入助手，已接 GUI）。全部 ✅。

## 3. LLM 接入

官方 openai SDK（`[llm]` extra）✅ · strict json_schema+降级 ✅ · 流式+abort ✅ · 默认深度思考 ✅ · `workspace/.llm.json` 本地设置（CLI/GUI/watch 共用）✅ · 错误归一+key 脱敏 ✅。观测（Langfuse）未接（SPEC F0）。

## 4. 状态 · 协议层

SQLite 唯一 active 后端（原子动作/lease/恢复/WAL）✅ · retired Markdown workspace 仅可经 `migrate-md-to-sqlite` 读取迁移 ✅ · `SAFETY.md` 文件真源 ✅ · audit export 人类可读导出 ✅ · state-check 诊断 ✅ · rolling summary 上下文压缩 ✅ · pydantic 协议模型 ✅。

## 5. 摄入 · 记忆 · 检索

文本摄入+浏览器上传（≤5MB，标记不可信）✅ · PDF 仍拒绝 🟡 · 结构化记忆（kind/tags/importance）✅（F3 起上下文注入按 importance/created_at 排序）· 确定性关键词检索（默认关）🟡 · 向量 RAG 未做（延后）。

## 6. 执行侧 watch

tick 监督循环 + SafetyGate（10 项检查）+ 原子领取/lease 恢复 ✅ · heartbeat/watchdog/halt ✅ · **全链路驱动调用超时保护 + 超时即 halt**（W1）🟢 · 无动作时每 tick 仍刷新 world ✅。观察串行/无重连/无 observed_at（SPEC W2-W4）。

## 7. 驱动 + 传输

`PhysicalDriver` 契约（connect/observe/execute/capabilities/health/heartbeat/halt）✅ · loader/registry/manifest/templates ✅ · mock_arm/mock_rover ✅ · xiaozhi_mcp（mock/http/ws）✅ · transport：websocket/serial（pyserial 自带读写超时）/loopback ✅。舵机协议层未做（F5.1 计划用 LeRobot motors）；仿真 driver 未建（F6）。

## 8. 配置

`physical-agent.yaml`（robots/watch/agent；watch 含 4 个 W1 超时预算）✅ · `physical_driver.yaml` manifest+config_schema ✅ · GUI：只读配置视图 + 一键注册 robot 写回 yaml（E0.3）🟢 · `.llm.json` 独立于 git/审计 ✅。

## 9. 测试 · 文档 · 基建

**246 用例**（含安全边界 monkeypatch 断言、backend 矩阵、传输、W1 挂死回归、API、e2e 闭环；Python≥3.11 全绿）✅ · Playwright e2e 1 spec 13 用例 🟡（E0 新面板未覆盖）· docs 三件套（SPEC/PLAYBOOK/REFACTORING）+ 3 份操作手册 ✅ · 根目录 AGENTS.md/CLAUDE.md agent 守则 🟢 · **无 CI** 🟡（SPEC 基建项）。

---

*欠账与排期一律见 `SPEC.zh-CN.md` §4；历史过程见 `REFACTORING.zh-CN.md`；实现指引见 `PLAYBOOK.zh-CN.md`。本文过时后按此结构重扫即可。*
