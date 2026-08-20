# TUI Command Acceptance Matrix

| 命令 | 用途 | API endpoint | 测试文件 | 覆盖状态 |
| --- | --- | --- | --- | --- |
| `<text>` | 发送 chat 流式消息 | `POST /api/chat/stream` | `tui/tests/scenarios/chat.scenario` | 已覆盖 |
| `/help` | 展示本地命令帮助 | Local only | `tui/tests/scenarios/basic.scenario` | 已覆盖 |
| `/view status` | 展示 API/backend/watch/workspace 摘要 | `GET /api/health`, `GET /api/state`, `GET /api/config` | `tui/tests/scenarios/basic.scenario`, `tui/tests/scenarios/error.scenario` | 已覆盖 |
| `/view chat` | 返回 chat transcript 视图 | Local view switch | `tui/tests/scenarios/basic.scenario`, `tui/tests/scenarios/error.scenario` | 已覆盖 |
| `/view actions` | 展示 action board | `GET /api/health`, `GET /api/state`, `GET /api/config` | `tui/tests/scenarios/chat.scenario`, `tui/tests/scenarios/actions.scenario` | 已覆盖 |
| `/view config` | 展示 effective config | `GET /api/health`, `GET /api/state`, `GET /api/config` | `tui/tests/scenarios/config.scenario` | 已覆盖 |
| `/view robots` | 展示 robot 列表 | `GET /api/health`, `GET /api/state`, `GET /api/config` | `tui/tests/scenarios/robots.scenario` | 已覆盖 |
| `/view uploads` | 展示 upload 元数据 | `GET /api/health`, `GET /api/state`, `GET /api/config` | `tui/tests/scenarios/upload.scenario` | 已覆盖 |
| `/task <text>` | 提交 task proposal | `POST /api/tasks/submit` | `tui/tests/scenarios/actions.scenario` | 已覆盖 |
| `/approve <action_id>` | 批准 action 交给 watch 执行 | `POST /api/actions/{id}/approve` | `tui/tests/scenarios/actions.scenario` | 已覆盖 |
| `/reject <action_id> <why>` | 拒绝 pending action | `POST /api/actions/{id}/reject` | `tui/tests/scenarios/actions.scenario` | 已覆盖 |
| `/reset true` | 通过后端确认重置 workspace | `POST /api/workspace/reset` | `tui/tests/scenarios/config.scenario` | 已覆盖 |
| `/config` | config 视图别名 | `GET /api/health`, `GET /api/state`, `GET /api/config` | `tui/tests/scenarios/config.scenario` | 已覆盖 |
| `/robots` | robots 视图别名 | `GET /api/health`, `GET /api/state`, `GET /api/config` | `tui/tests/scenarios/robots.scenario` | 已覆盖 |
| `/robot <robot_id>` | 展示单个 robot 详情 | `GET /api/health`, `GET /api/state`, `GET /api/config` | `tui/tests/scenarios/robots.scenario` | 已覆盖 |
| `/capabilities <robot_id>` | 展示单个 robot 的 capabilities | `GET /api/health`, `GET /api/state`, `GET /api/config` | `tui/tests/scenarios/robots.scenario` | 已覆盖 |
| `/upload <path>` | 通过 API 上传并摄入本地文本文件 | `POST /api/upload` | `tui/tests/scenarios/upload.scenario` | 已覆盖 |
| `/ingest <path>` | upload 别名 | `POST /api/upload` | `tui/tests/scenarios/upload.scenario` | 已覆盖 |
| `/register-robot <json>` | 通过既有 config API 注册 robot | `POST /api/config/robots` | `tui/tests/scenarios/config.scenario` | 已覆盖 |
| `/refresh` | 刷新 health/state/config 和 LLM 状态 | `GET /api/health`, `GET /api/state`, `GET /api/config`, `GET /api/settings/llm`, `POST /api/settings/llm/test` | `tui/tests/scenarios/basic.scenario` | 已覆盖 |
| `/quit` | 退出 TUI | Local only | `tui/tests/scenarios/basic.scenario` | 已覆盖 |
| Missing arguments | 缺参命令本地拒绝并展示可读提示 | Local only | `tui/tests/scenarios/error.scenario` | 已覆盖 |
| Invalid command / unavailable direct execution | 拒绝 unsupported command，不触发 API 执行 | Local only | `tui/tests/scenarios/error.scenario` | 已覆盖 |
| API offline | API 调用失败时仍保持状态可读 | All initial read endpoints mocked offline | `tui/tests/scenarios/error.scenario` | 已覆盖 |
| SSE error | SSE 异常后降级 polling fallback 并展示错误 | `GET /api/events` mocked error | `tui/tests/scenarios/error.scenario` | 已覆盖 |
| SSE clean EOF | SSE 正常 EOF 后降级 polling fallback 并展示 EOF 提示 | `GET /api/events` mocked clean EOF | `tui/tests/scenarios/error.scenario` | 已覆盖 |
| Polling fallback | 不启用 SSE 时仍可用 polling 路径操作 | Polling `GET /api/health`, `GET /api/state` | `tui/tests/scenarios/basic.scenario` | 已覆盖 |
| Upload failure | 上传失败可读提示，且不污染 upload state | `POST /api/upload` mocked failure | `tui/tests/scenarios/upload.scenario` | 已覆盖 |
| Reset confirmation failure | reset 确认失败可读提示，且不重置状态 | `POST /api/workspace/reset` mocked failure | `tui/tests/scenarios/config.scenario` | 已覆盖 |
