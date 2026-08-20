# Agent 执行守则（Physical Agent 仓库）

任何 agent（Codex / Claude Code / 其他）在本仓库开工前，必须走完以下流程。人类贡献者同样适用。

## 开工前（必做，缺一不开工）

1. 读 `docs/SPEC.zh-CN.md` §0 安全边界——两条宪法不可破：**执行权唯一**（`driver.execute` 只许出现在 watch 循环调用栈）、**执行前校验不可绕过**（SafetyGate + SAFETY 文件真源）。
2. 在 SPEC §4 待办矩阵中找到本次任务条目，确认状态与依赖。
3. **读 `docs/PLAYBOOK.zh-CN.md` 中同名条目**——实现思路、关键文件、坑、验收都在那里，不要凭空重新设计。
4. 在 `docs/` 写一份轮次 brief（范围、验收、范围外），再动代码。

## 开工中

- 新能力默认关闭或向后兼容；小步可回滚。
- 改动必须带测试；两个状态后端（markdown/sqlite）的行为改动要过 backend 矩阵测试。
- driver 内阻塞调用必须带超时或走 `asyncio.to_thread`（W5 守则）。
- 不确定的设计决策：先查 `docs/REFACTORING.zh-CN.md` §3 有无先例，再做取舍并记录。

## 收工时（缺一不算完成）

1. 全量测试通过（`pytest`；改前端则加 `tsc -b && vite build`）。
2. 更新 SPEC §4 对应行状态；REFACTORING §1 表格追加一行，实现要点并入 §2 小节，新决策/教训补 §3/§4。
3. **不写独立 handoff 文档**（历史上堆出过 33 份）——收工总结的家就是 REFACTORING；本轮 brief 用完即删（升级为 `specs/00X/` 的大条目除外，可在目录内留完整记录）。
4. commit 全部改动并 push。

## 文档纪律（三条约定）

1. **大条目升级门槛**：预计超过 1 轮 session、跨层改动多、或验收需要正反用例枚举的条目（如 F1.3 审批流、F6.0 场景规格），不再只写单份 brief，升级为 `docs/specs/00X-<名字>/` 独立目录（spec/plan/tasks 齐全，编号递增）。小条目维持"PLAYBOOK 条目 + 轮次 brief"，不摆仪式。
2. **决策三落点**：任何二选一级别的技术/产品决策必须留痕，落在三处之一——所在条目内一句话 rationale（选了什么/为什么/放弃了什么）、SPEC 挂起清单（决定不做的，带日期与重启条件）、REFACTORING §3（做完回顾的）。修宪级决策按 SPEC §0.1 单独出决策记录。
3. **粒度旋钮**：任务拆解粒度按条目现调，默认停在"思路+关键文件+坑+验收"（PLAYBOOK 级）；仅高风险顺序敏感操作（删除/迁移）、跨多轮大条目、或派发给弱执行者时才拆原子 checklist。不为有判断力的执行者写原子步骤——过度规定会让执行者照着过时步骤开进沟里。

## 常用命令

```bash
pip install -e .[dev,server,llm]   # 后端依赖
pytest                              # 全量测试（Python ≥3.11）
physical-agent api --watch          # 启动后端（项目根目录）
cd frontend && npm run dev          # 前端开发模式
cd frontend && npm run build        # 重建 dist（FastAPI 托管产物）
```

## 红线速查

- 永不在请求/提案侧代码路径调用 `driver.execute` 或加载 driver。
- 永不绕过 SafetyGate；`SAFETY.md` 保持文件真源，不迁入数据库。
- 授权/自动化改变"是否等人"，不改变"是否校验"。
- 例外（急停直达、会话粒度流控）需按 SPEC §0.1 预注册条款显式设计。
