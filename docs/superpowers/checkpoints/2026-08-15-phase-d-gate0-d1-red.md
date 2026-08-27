# Phase D Gate 0 与 D1 RED 复核 checkpoint

Date: 2026-08-15
Branch: `codex/phase-d-memory` @ `aedc6f7eb9963707fa12cd69d28dab15bbf755d2`
Base: `origin/main` @ `25dbd67bc07138e37d11b4ae41ee9ca94021e181`（merge-base = 25dbd67，即当前最新 origin/main）
Worktree: `E:\My_Opjects\agent-platform-system-phase-d-memory`（复用既有隔离 worktree，用户已确认；授权新路径
`E:\My_Opjects\agent-platform-system-worktrees\phase-d-memory` 因分支已归属而未创建）
Review input: 2026-08-15 master/execution 复审 R1-R11（存于主 checkout 的未跟踪文档，未复制进本 worktree）

## 1. 计划修订（主 checkout，仅两个未跟踪 2026-08-15 文档）

- R1：master §7.1 `20260815_0017` scope 补入 `decision_actions`。
- R2：master §7.3 `successful_run_count` 标注“由 `0018` 追加”；§8.3 注明计数递增与 derivation job
  插入副作用随 `0018`（E6）落地，E2 阶段不执行。
- R3：execution Gate 0 通过条件 #6 改为仅记录 PR #7 fallback/mock 现状；移除与证明属 PR #7 merge
  退出条件，不阻断 backend D1-D3。
- R5 冻结：master §7.2 新增“Memory 内容 CAS update 后 `embedding_state` 重置 `pending` 并重新
  enqueue embedding job；该语义在 `0013` schema 写入前冻结”。
- R4-R11 已记录至 execution E0 checkpoint（“E0 复审澄清项记录”小节，含建议默认值）。
- master §18 处置记录表延续编号追加 R1-R11 行。
- 校验：master 546 行 / exec 689 行，代码块闭合（master 2 fences / exec 12 fences 均为偶数），
  无行尾空白；未修改/stage 任何其他 dirty 文件。

## 2. Gate 0 只读核对结果

- 主 checkout：`codex/frontend-replacement` @ `5c29449`，落后远端 51 commits，dirty =
  `M 2026-08-10-phase-d-memory-first-governance.md` + 3 个未跟踪计划文档（含两份 2026-08-15）。
  全程未 stage/commit/reset/clean/checkout/pull，未修改 governance 与其他 dirty 文件。
- `web-platform` 嵌套仓库：`refactor/modern-ui` @ `8072e0b`，大量未提交前端改动，归前端负责人；
  本轮未触碰。
- PR #7：Open、Draft、BLOCKED、REVIEW_REQUIRED，head `ab72cd8`；五项 checks 全 pass
  （config/postgres/quality/sqlite/test，check run id 见 2026-08-15 gh pr checks 输出）。fallback/mock
  现状按 R3 仅记录，未验证移除（属 merge 退出条件）。
- Issue #6 与 #8：均 OPEN。
- Alembic：主 checkout 单 head `20260810_0012`；本 worktree 单 head `20260811_0013`。
  `0013` 在本 worktree 已被既有实现占用（20260811_0013_phase_d_memory.py 已存在并已推送）。
- DATABASE_URL：环境未设置、无 .env 文件；config 默认 `sqlite+aiosqlite:///./agent_platform.db`
  （本地文件，归属清晰）。未连接任何共享/生产数据库；主 checkout 内未执行 `alembic current/check`
  （避免写脏只读工作区），在本 worktree 用一次性 `gate0_char.db` 完成 upgrade/check 后即删除。

## 3. Characterization 真实基线（worktree，2026-08-15 重跑）

- 全量 pytest：`317 passed, 60 warnings in 54.64s`（与 08-12 handoff 一致，不沿用历史数字）。
- Ruff：`All checks passed!`。
- OpenAPI snapshot：`scripts/export_openapi.py --check` → snapshot is current。
- Alembic：单 head `20260811_0013`；一次性 SQLite `upgrade head`（0005→0013 全链）、
  `alembic check` → `No new upgrade operations detected.`（2 条已知 sqlite expression-index
  反射 warning，非本轮失败）、`alembic current` = `20260811_0013 (head)`。

## 4. D1 RED（新增 `backend/tests/test_memory_embedding_contract.py`）

定向结果：`7 failed, 1 passed in 3.84s`；全量加 RED：`318 passed, 7 failed, 60 warnings`。
7 个失败全部因业务能力缺失（未使用 import/fixture/拼写/环境错误制造红灯）：

| 测试 | 契约依据 | 失败原因 |
|---|---|---|
| test_memory_record_declares_embedding_state_column | master §7.2 / D1.1 | `memory_records` 无 `embedding_state` 列 |
| test_embedding_job_table_is_declared_and_claimable | master §7.2 | 无 `memory_embedding_jobs` 表（可 claim job 缺失） |
| test_create_writes_embedding_state_without_provider | D1.1 | create 未写入 `embedding_state`（`getattr=... None`） |
| test_content_update_resets_embedding_state_and_reenqueues_job | §7.2 R5 冻结 | 无 state 列，ready→pending 重置与重排队无法表达 |
| test_delete_physically_clears_embedding_and_job_rows | D1.1 | embedding job 表缺失，删除契约无法覆盖 job 行 |
| test_non_ready_embeddings_are_excluded_from_vector_ranking | §7.2 | 无 state 列，vector 分支只能按 `embedding IS NOT NULL` 过滤 |
| test_rollback_contract_includes_embedding_job_table | §7.2 | job 表缺失，回滚契约无法覆盖 embedding job |

1 passed（文档性）：`test_rollback_of_existing_writes_leaves_no_memory_version_or_audit_rows`
证明现有 Memory+version+audit 写路径共享同一 unit of work、回滚无残留。
持久化/owner-only/CAS/删除正文契约由既有绿色测试继续覆盖（test_memory_persistence.py、
test_memory_authorization.py 等，含在全量 318 passed 内）。

## 5. 强制停止点与下一步 GREEN 前置门禁

- 本批次未写任何 migration/schema、未执行数据库变更、未 stage/commit/push、未触碰 PR #7 与
  `web-platform`、未读取 secret/.env/客户数据、未调用真实模型/飞书/钉钉。
- worktree 新增仅 `tests/test_memory_embedding_contract.py`（未跟踪、未 stage）；
  既有 dirty `.github/workflows/frontend-ci.yml` 保持原样未触碰。
- GREEN 前置：① 用户批准 0013 增量设计（embedding_state CHECK 枚举 + 可 claim 的
  `memory_embedding_jobs` 表 + 索引/CAS 写回语义），并复核 R9（Memory `user_id` FK 默认
  `RESTRICT`）；② R5 重置/重排队语义与删除/回滚契约按本 RED 文件逐条转绿；③ 一次性
  PostgreSQL 16 + pgvector 的 0013 增量 roundtrip；④ 全量 pytest/Ruff/OpenAPI 回归。

## 6. D1 GREEN 记录（2026-08-15，用户已批准）

用户确认（三项）：放行 GREEN 按 RED 契约实现；Memory user FK 改为 RESTRICT + 受控清理（R9）；
0013 就地扩展本分支已推送的 `20260811_0013`（新 commit 追加，不重写历史）。

实现（全部未 stage/未 commit）：

- `entities.py`：`memory_records` 新增 `embedding_state`
  （`not_configured|pending|ready|failed` CHECK）；`fk_memory_records_org_user` CASCADE→RESTRICT；
  新增 `MemoryEmbeddingJob`（status CHECK、claim partial index、record FK CASCADE、revision CAS 列）。
- `20260811_0013` migration 同步上述增量；downgrade 顺序更新。
- `memory_repository.py`：create/confirm 在 `memory_embedding_enabled` 时写 pending + job，
  否则 not_configured；内容 CAS update 触发 R5 重置（pending + 取消未终态 job + 重排队）；
  delete/reject 显式物理清除 version/source link/embedding job 行（SQLite/PG 双确定性）；
  update 后 `db.refresh` 修复 RETURNING 实例属性过期。
- `memory_retrieval.py`：vector 分支三处增加 `embedding_state == 'ready'` 谓词，FTS 分支不变。
- 新增 `app/services/memory_embedding.py`：claim（PG SKIP LOCKED / sqlite 顺序领取）、
  prepare（record_deleted/stale_revision/state_conflict 终态）、revision/CAS 写回、
  `run_embedding_cycle`（claim 短事务 → 事务外 provider 调用 → CAS 写回短事务）；
  worker 循环按 `memory_embedding_enabled` 接入。
- `config.py`：新增 `memory_embedding_*` 设置（默认关闭）。

GREEN 证据：

- 定向契约+worker+migration 测试：`14 passed`。
- 全量 pytest：`329 passed, 60 warnings in 54.07s`（RED 时为 318 passed + 7 failed）。
- Ruff：`All checks passed!`；OpenAPI snapshot：current。
- Alembic：单 head `20260811_0013`；一次性 SQLite upgrade/check/`No new upgrade operations detected.`
- 一次性 PostgreSQL 16.14 + pgvector（E:\Temp\phase-d-pg16，port 55432，本地 trust，DB
  `phase_d_memory_delta` 用完即删）：0012→marker→0013→downgrade 0012（marker 保留、memory 表移除）→
  再 upgrade head 单 head；schema_check 全过：embedding_state 列+CHECK（bogus 值被拒）、
  jobs 表+claim 索引、`fk_memory_records_org_user` confdeltype=r（RESTRICT，membership 删除被
  Memory 行阻止）、job FK confdeltype=c（record 删除级联清 job）。服务器已停止。
- 既有测试适配：`test_memory_retrieval.py` 向量 fixture 补 `embedding_state="ready"`；
  `test_phase_d_memory_migration.py` 预期表/列/FK/索引/降级顺序同步增量并新增 RESTRICT/CHECK 断言。

已知解释与待办：

- R5 语义解释：无既有向量且 `not_configured` 的记录内容变更不产生空转 job；有向量或非
  not_configured 状态才重置 pending 并重排队（已写入 checkpoint，无 provider 时 worker 收敛
  not_configured）。
- `memory_embedding_enabled` 默认 False；真实 provider 接入与 IM/部署配置不在本批次。
- 未做：PR #7 相关、真实 provider。

## 7. D2 RED/GREEN（worker crash 恢复，commit `1beae0f`）

- RED：`test_phase_d_d2_worker_crash_contract.py` `1 failed, 1 passed`——崩溃遗留的 processing
  extraction job 无法重新领取（claim 只扫 queued，无 lease 恢复）；lease 未过期不抢占（pass）。
- GREEN：`recover_stale_extraction_jobs`（lease 过期重置 queued，不消耗 attempt，恢复在 claim 前
  执行）；`recover_stale_embedding_jobs` 对称实现；`memory_worker_lease_seconds`（默认 300s）。
- 证据：D2+embedding 定向 `8 passed`；全量 `333 passed`；Ruff clean。RED 断言修正说明：恢复不
  消耗 attempt，重新领取算一次新尝试（重领后 attempts==2 为正确契约）。

## 8. D3 RED/GREEN（memory-mode CAS，commit `53064e7`）

- RED：`test_phase_d_d3_review_contract.py` `2 failed`——PUT memory-mode 无 expected_revision，
  陈旧切换返回 200 静默覆盖（exec D3.2 要求权限校验和 CAS）。
- GREEN：`chat_sessions.revision`（0013 内追加列，server_default 1）+ 端点 CAS（陈旧 409，
  revision 递增，audit 记录 revision）+ `MemoryModeUpdate.expected_revision` /
  `MemoryModeResponse.revision`。既有 `test_memory_mode_api.py` 调用点同步适配。
- 证据：定向 `4 passed`；全量 `335 passed, 60 warnings`；Ruff clean；OpenAPI 重新生成并 check；
  一次性 SQLite upgrade/check 干净。

## 9. Backend API Handoff（D1-D3）

- 冻结 API commit SHA：`53064e7`（branch `codex/phase-d-memory`，ahead origin 4 commits：
  `51ab2ad`、`c5e9efa`、`1beae0f`、`53064e7`）。
- OpenAPI 增量（aedc6f7..53064e7）：仅 memory-mode 契约变化——`MemoryModeUpdate` 增
  `expected_revision`，`MemoryModeResponse` 增 `revision`（+14/-2 行，无新路径；D1-D3 其余
  API 路径与 aedc6f7 一致）。
- D1-D3 RED/GREEN、migration（SQLite + 一次性 PG16 roundtrip）、OpenAPI、Ruff、全量回归均已通过。
- 推送 Draft PR 与前端（Keyou430）交接仍需用户批准；`web-platform/**` 与 PR #7 未触碰。

## 10. D6 RED/GREEN（Skill 生命周期 + `0014`，commit `c2c00f0`）

- RED：`test_phase_d_d6_skill_lifecycle_contract.py` `4 failed, 1 passed`——create 无
  status/revision/version、update 无 CAS（stale 200 静默覆盖）、no-op 无幂等、review/publish/archive
  端点缺失；文件系统 `hr-weekly-report` 不自动 published/installed（pass，既有正确行为）。
- GREEN：`skills` 增加 status/revision/current_version/content_hash/updated_at + CHECK；
  新 `skill_versions` 不可变表（unique skill_id+version，FK CASCADE）；`0014` 把现有 rows
  backfill 为 v1 draft 并生成 v1 版本行；update CAS（stale 409、no-op 不追加版本）；review 需
  `skills:review`、publish 需 `skills:publish` 且仅 reviewed 可发布（draft 直接 publish 409）；
  archive 后默认 catalog 不可见；`/versions` 只读历史；删除显式清理版本行；seed 新增两个权限
  （admin `['*']` 自动生效，user/manager 默认无）。
- 证据：契约文件 `7 passed`；全量 `342 passed, 60 warnings`；Ruff clean；OpenAPI 97 paths；
  一次性 SQLite `upgrade→check(无新操作)→downgrade 0013→upgrade head` 干净（单 head
  `20260811_0014`）；一次性 PG16：0013 插入 legacy skill → 0014 backfill 校验（draft/v1/hash/
  版本行/CHECK/CASCADE）→ downgrade 回 legacy → 再 upgrade 单 head；服务器已停止、库已删。

## 11. D7 RED/GREEN（Project scope + `0015`，commit 见 log）

- RED：`test_phase_d_d7_project_scope_contract.py` `8 failed`——无任何 projects 端点（列表/创建/
  跨组织 404/private 不可见/roster CAS/批量原子性/guest 403/placement-only 链接全部缺失）。
- GREEN：`projects`（visibility public/private CHECK、roster_revision CHECK、org composite
  unique、owner FK RESTRICT）；`project_members` 复合 FK（org,project_id→projects CASCADE；
  org,user_id→organization_memberships CASCADE；role CHECK；project_id+user_id unique）；
  `project_resource_links`（type CHECK 四类、ref unique、ord；placement-only，不授予底层访问）；
  可见性=public 或 owner/roster 成员；roster 更新 CAS 409 + 批量全事务（无效成员整体 404 且无
  部分生效）+ owner/projects:manage；权限 projects:read/write/manage 入 seed（user rw、manager
  rwm、admin '*'）。
- 证据：契约文件 `8 passed`；全量 `350 passed, 60 warnings`；Ruff clean；OpenAPI 101 paths；
  一次性 SQLite `upgrade→check(无新操作)→downgrade 0014→upgrade head` 干净（单 head
  `20260811_0015`）；一次性 PG16：复合 FK 建行成功、owner RESTRICT 阻止 user 删除、project
  删除级联清 members/links、CHECK 集合与全部 FK 索引断言通过、downgrade 移除三表、再 upgrade
  单 head；服务器已停止、库已删。

## 12. D8 RED/GREEN（Skill grant + `0016`，commit 见 log）

- RED：`test_phase_d_d8_skill_grant_contract.py` `7 failed`——grant/revoke/promote/
  discoverable/shared-with-me 端点与 grant 表全部缺失（跨组织/Hermes 非影响两个测试先经收紧
  消除假通过）。
- GREEN：`skill_access_grants`（capability CHECK('read')、active partial unique
  `revoked_at IS NULL`、grantee 复合 FK→organization_memberships CASCADE、grantor RESTRICT、
  skill CASCADE）；owner+skills:share grant/revoke，撤销与过期立即不可读；no-transitive
  re-share（受让人 grant 404）；跨组织 grantee 404；Project resource link 与 filesystem mount
  不能代替 grant（负向测试）；promote 仅 reviewed/published（draft 409）且 skills:govern 门禁，
  推广不转移写权限（PUT 404）；detail 可读 = owner 或 active grant 或 promoted 组织成员；
  `/shared-with-me`、`/discoverable` 目录；grant/promote 不改 Hermes profile（全列比对）与
  filesystem 目录条目；skills:share/govern 入 seed（user share、manager share+govern、admin '*'）。
- 证据：契约文件 `7 passed`（连同 D6/scope 共 `15 passed`）；全量 `357 passed, 60 warnings`；
  Ruff clean；OpenAPI 106 paths；一次性 SQLite `upgrade→check(无新操作)→downgrade 0015→
  upgrade head` 干净（单 head `20260811_0016`）；一次性 PG16：重复 active grant 被 partial
  unique 拒绝、revoke 后允许再授、grantor RESTRICT 阻止删除、skill 删除级联清 grants、
  downgrade 移除表与 promoted 列、再 upgrade 单 head；服务器已停止、库已删。

至此 0013-0016 迁移链完整（单 head `20260811_0016`），Phase D2 backend（D6/D7/D8）完成。

## 13. D9 RED/GREEN（runtime projection 可行性门禁，commit 见 log）

- RED：`test_phase_d_d9_runtime_projection_contract.py` `5 failed`——无 `app.services.skill_context`
  投影服务（能力断言 + 四条行为契约全部因能力缺失失败）。
- GREEN（执行计划 D9 Step 1-3 结论：per-request trusted projection **可行**，采用之）：
  `select_authorized_skills` 在 SQL 层按组织/用户现算 published-only（owner 或 active grant 或
  promoted 组织成员）；draft/unreviewed/ungranted/revoked/archived 永不进入投影；撤权下一请求
  立即生效；`build_authorized_skills_block` untrusted 前缀 + 4 KiB 预算 + 仅 knowledge surface；
  注入 chat instructions（每请求现算，不写 Hermes profile、不写 filesystem——全列比对与目录
  条目断言）；全局 `hr-weekly-report` mount 仍是 demo 文件系统挂载，平台投影从不依赖它（负向
  测试保留）。
- 证据：契约文件 `5 passed`；全量 `362 passed, 60 warnings`；Ruff clean；OpenAPI current；
  单 head `20260811_0016`。D9 Step 4（前端 Skill/Project UI）仍受 PR #7 merge 门禁。
