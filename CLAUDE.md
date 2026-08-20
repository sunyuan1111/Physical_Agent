# Physical Agent

安全的物理世界 agent 运行时：认知侧只提案，watch 唯一执行，SafetyGate 执行前校验。

**开工前必读 `AGENTS.md`（本仓库 agent 执行守则）**：先读 `docs/SPEC.zh-CN.md` §0 与 §4，再读 `docs/PLAYBOOK.zh-CN.md` 对应条目，出轮次 brief 后才动代码；收工更新 SPEC 矩阵与 `docs/REFACTORING.zh-CN.md`。

红线：`driver.execute` 只许在 watch 循环调用栈出现；SafetyGate 不可绕过；SAFETY.md 为文件真源。
