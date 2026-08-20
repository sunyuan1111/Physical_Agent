# State Backend

## 结论

Physical Agent 现在只有一个 active state backend：

```text
StateStore Protocol -> SqliteStateStore
```

`workspace/state.db` 是运行态状态真源。项目没有 `JsonStateStore`，也没有可选的 Markdown backend；JSON 是 SQLite payload、API 传输和 GUI 渲染的数据格式。

Markdown 协议代码仍保留，但角色已经收窄：

- `SAFETY.md` 仍是安全规则文件真源，watch 执行前读取并强制校验。
- `LOG.md` 仍作为人类可读镜像保留，SQLite 的 log_entries 是状态真源。
- `protocol/markdown.py`、parsers、renderers 仍服务于 SAFETY、LOG、audit export 和旧 workspace 迁移。
- 旧 Markdown workspace 只能作为 `migrate-md-to-sqlite` 的输入格式读取，不能作为 active backend 打开。

## SQLite Backend

默认配置：

```yaml
workspace:
  path: ./workspace
  backend: sqlite
```

SQLite backend 把 task、capabilities、world、actions、feedback、chat、plan、memory、uploads、log 等动态状态写入 `workspace/state.db`。action board 使用 SQLite 行来支持原子 append、claim、terminal mark、lease recovery 和并发 proposal。

`SAFETY.md` 不迁入 SQLite。即使状态真源是 `state.db`，watch 执行动作前仍读取 `workspace/SAFETY.md` 并运行 SafetyGate。

## Retired Markdown Backend

以下两种配置都会被拒绝，不会打开旧 MarkdownStateStore：

```yaml
workspace:
  path: ./workspace
  backend: markdown
```

以及：配置省略 `workspace.backend`，但 `workspace/` 里已经存在完整 legacy Markdown 协议文件。

错误信息会提示：

```text
physical-agent migrate-md-to-sqlite --config physical-agent.yaml
workspace.backend: sqlite
```

## Migration And Audit

`migrate-md-to-sqlite` 只做旧 Markdown workspace -> SQLite 迁移：

```powershell
.\.venv\Scripts\python.exe -m physical_agent.cli migrate-md-to-sqlite --config physical-agent.yaml
```

如果 `workspace/state.db` 已存在，命令默认拒绝覆盖。只有确认不会丢失用户状态时，才显式使用 `--overwrite`。

迁移命令会使用迁移专用 legacy reader 读取旧 Markdown 文件；它不会通过 active backend loader 打开 MarkdownStateStore。迁移成功后，命令会提示用户把 `physical-agent.yaml` 改成：

```yaml
workspace:
  backend: sqlite
```

当前版本不提供 `--switch-config`，不会自动修改配置。

`export-audit` 从当前 SQLite backend 导出人类可读审计视图：

```powershell
.\.venv\Scripts\python.exe -m physical_agent.cli export-audit --config physical-agent.yaml
```

导出的 `workspace/audit/` 是视图，不是新的真源。它不修改 backend，不修改 action board，也不做 SQLite -> Markdown 反向迁移。

## Operational Checks

`state-check` 和 `GET /api/state-check` 是只读诊断：

- backend 必须是 `sqlite`。
- workspace 必须已初始化。
- SQLite schema 必须完整。
- audit export 目标必须可写。
- SAFETY source 会显示为 `workspace/SAFETY.md`。

GUI 只显示当前 backend、workspace、state-check 摘要和 audit export 能力，不提供 backend select、切换按钮、运行时 active backend 切换，或“迁移并自动切换”API。
