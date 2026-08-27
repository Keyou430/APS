# Phase E E0 产品与 API 决策冻结 checkpoint（已确认）

Date: 2026-08-15
状态：**2026-08-15 用户逐项确认完成（全部接受建议值，无覆盖项）**。已冻结，可作为 E1 契约测试
草稿的输入；但按用户指令，`0017`/worker/智能任务代码必须在 Phase D 合并验收之后才开始。
权威来源：master 2026-08-15 §7.4（E0 单一权威冻结清单）；R4-R11 已记录于 execution E0 小节。

## 逐项确认表（建议接受值；覆盖需用户明示并说明对 0017 的影响）

| # | 决策项 | 确认值 | 状态 |
|---|---|---|---|
| 1 | missed-run 行语义（R4） | `misfire_grace=15m` 窗口内最晚 occurrence 落 `queued` 行，其余 occurrence 落 `missed` 行；重复扫描幂等；scheduled partial unique 只约束 queued occurrence | ✅ 已确认（接受建议值） |
| 2 | Memory 内容更新后 embedding 重置（R5） | 已在 master §7.2 冻结并在 0013 增量实现：内容 CAS update → `embedding_state=pending` + 取消未终态 job + 重排队；无既有向量且 not_configured 不空转 | ✅ 已冻结（0013 已实现，非 E0 决策项） |
| 3 | 成员退出触发点（R6） | membership 变更服务 hook 主动 disable/cancel + scheduler claim 时运行时重新校验 membership 双保险 | ✅ 已确认（接受建议值） |
| 4 | 配额 enforcement 点与粒度（R7） | 创建时校验 per-user 20 active task；手动触发入队时校验 per-user 每小时 10 次；claim 时校验 per-org 同时 running 4 | ✅ 已确认（接受建议值） |
| 5 | soft-delete 与保留期交互（R8） | 软删 task 的 run/output/decision 随 30 天任务物理清理执行；180 天仅适用于未删 task；§7.4 保留期行加注 | ✅ 已确认（接受建议值） |
| 6 | Memory user FK（R9） | 已实现 RESTRICT（0013 增量，PG 门禁实证 membership 删除被 Memory 行阻止）；账号删除服务先受控清理 | ✅ 已落地（非 E0 决策项） |
| 7 | 枚举显式化（R10） | `trigger_kind`（scheduled/manual）与 `decision_actions.action`（approve/reject/regenerate）在 E1 schema/OpenAPI 显式列出，E1.1 测试以此为准 | ✅ 已确认（接受建议值） |
| 8 | admin observe 是否显示任务名（R11） | 隐藏/脱敏（§10.1 归 user-authored content）；不放开 | ✅ 已确认（默认隐藏，无覆盖） |

## 对 0017 的影响（已确认后的执行口径）

- 第 1/3/4/5/7 项为 `0017` 表结构与 E1/E2 RED 清单的冻结输入：missed 行语义、配额索引、
  `trigger_kind`/`decision_actions.action` 枚举 CHECK 均按上表确认值实现。
- 第 8 项：observe 投影与 §10.1 字段矩阵测试均不返回任务名。
- 本表为唯一确认口径；如后续需要覆盖，必须回到本 checkpoint 更新并同步 master §7.4 与
  execution E0，不维护第二份清单。

## E0 完成标准

- ✅ 2026-08-15 用户逐项确认（全部接受建议值，无覆盖项）。
- 冻结条件：`0017` 的 RED/migration 必须在 **Phase D 合并验收之后** 才开始（用户明确指令）。

