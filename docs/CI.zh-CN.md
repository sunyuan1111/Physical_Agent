# CI 说明

CI（Continuous Integration，持续集成）是在每次 push 或 pull request 时，让 GitHub 自动在干净机器上跑一组检查。它的目标不是限制重构，而是在代码合入前提醒维护者：安全底线、构建产物或主要交互流程可能被改坏了。

本仓库的 CI 配置在 `.github/workflows/ci.yml`。

## 当前策略：宽松但守底线

Physical Agent 连接真实物理执行链路，CI 必须守住安全宪法；同时项目仍在快速重构，CI 不能把每一次内部拆分都卡成重活。因此当前采用三层策略：

| 层级 | 默认阻塞 | 作用 |
| --- | --- | --- |
| 必跑 smoke | 是 | 快速守住安全边界和前端可构建性 |
| 建议性检查 | 否 | 跑 TUI 与浏览器 e2e，失败会提示但不直接阻塞 |
| 手动 full run | 手动触发 | 需要收口、发版或大重构后再跑完整 pytest 矩阵 |

## 自动检查

push 和 pull request 默认会跑：

1. `Python safety smoke`
   - Python 3.12
   - 安装 `.[dev,server,llm]`
   - 只跑关键安全/执行边界测试：
     - `tests/test_safety_boundaries.py`
     - `tests/test_safety.py`
     - API 请求侧不得实例化 watch 或执行 driver
     - HTTP auto-step 字段不得启动 watch
     - SQLite 默认状态后端 smoke
     - watch 单步执行 smoke

2. `Frontend build`
   - Node 20
   - `cd frontend && npm ci`
   - `npm run build`，实际包含 `tsc -b && vite build`

这两项失败时，一般应该先修。它们代表“安全底线”和“主 GUI 至少能构建”。

注意：GitHub Actions 的 workflow `env:` map 会把变量名按大小写不敏感处理。因此不能同时写 `HTTP_PROXY` 和 `http_proxy`、`NO_PROXY` 和 `no_proxy`。CI 里只保留一套大写代理变量；如果需要在测试进程内处理更多宿主环境差异，应放到测试 fixture 或命令步骤里，而不是在同一个 `env:` map 中重复声明。

## 建议性检查

这些检查默认会显示结果，但 workflow 标记为 `continue-on-error`，失败时不直接阻塞：

1. `Ink TUI advisory`
   - `cd tui && npm ci`
   - `npm run build`
   - `npm test`

2. `Playwright dashboard advisory`
   - PR 和手动运行时触发
   - 启动临时 API 与 Vite dev server
   - 跑 `cd frontend && npm run test:e2e`

建议性检查失败不等于可以无视。合并前至少要判断它是已知环境波动、测试本身过时，还是确实把用户流程改坏了。

## 手动 full run

在 GitHub Actions 页面选择 `CI` → `Run workflow`，把 `full` 选为 `true`，会额外跑：

- Python 3.11 / 3.12 矩阵
- `python -m pytest -q`

适合这些场景：

- 大重构收口
- 准备发布或打 tag
- 修改状态层、watch、安全边界、API 合同时
- 自动 smoke 通过，但你想确认没有更远处的回归

## 本地复现

后端 smoke：

```bash
python -m pip install -e ".[dev,server,llm]"
python -m pytest -q \
  tests/test_safety_boundaries.py \
  tests/test_safety.py \
  tests/test_api_server.py::test_api_requests_do_not_instantiate_watch_or_execute_driver \
  tests/test_api_watch_events.py::test_http_auto_step_like_fields_do_not_start_watch \
  tests/test_backend_matrix.py::test_default_init_setup_and_state_check_use_sqlite_with_safety_file \
  tests/test_state_store.py::test_open_state_store_defaults_to_sqlite \
  tests/test_watch_runtime.py::test_watch_runtime_step_executes_action
```

前端构建：

```bash
cd frontend
npm ci
npm run build
```

TUI：

```bash
cd tui
npm ci
npm run build
npm test
```

浏览器 e2e：

```bash
cd frontend
npx playwright install chromium
npm run test:e2e
```

全量后端：

```bash
python -m pytest -q
```

## 写新测试时的边界

优先测试行为和契约，不要锁死内部实现。适合放进 smoke 的测试应满足至少一个条件：

- 它保护 `driver.execute` 的唯一执行权。
- 它保护 SafetyGate 和 `SAFETY.md` 文件真源。
- 它证明请求/API/LLM/GUI 侧只能提案，不能执行。
- 它能快速发现主 GUI 无法构建。

不建议轻易放进默认阻塞 CI：

- 大量 snapshot。
- 依赖精确 DOM 结构的测试。
- 耗时或易受浏览器环境影响的 e2e。
- 只验证私有函数调用顺序的测试。

## 失败时怎么判断

如果阻塞检查失败，默认按真实回归处理，除非能证明测试已经过时。

如果建议性检查失败，先看失败类型：

- 构建或类型错误：通常要修。
- 浏览器超时、截图、trace 失败：判断是环境波动还是用户流程坏了。
- 测试断言旧实现细节：重构时可以同步改测试，让它继续表达外部行为。

CI 的原则是：内部重构可以自由，但安全边界、状态契约和用户主要路径不能悄悄坏掉。
