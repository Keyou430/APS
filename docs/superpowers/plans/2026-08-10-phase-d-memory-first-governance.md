# Phase D 持久记忆优先与资产治理实施计划

> **重新基线日期：2026-08-11。** 本计划是当前唯一可执行的 Phase D 计划，承接先前会话中的草案；旧草案未纳入仓库，不作为实施依据。计划已复审通过。前端初始导入已形成远端 commit，但 replacement 仍处于阻塞修复期：Task 0 Steps 1-6 通过后允许 backend-only Task 1-3 在隔离 worktree 并行推进，Task 4 和 Task 5 必须等待 Task 0 Step 7 的前端合并门禁。Task 0 与 Task 5 不制造假红灯；其余每个修改业务行为的 Task 必须先新增失败测试并实际确认 RED，再实施最小 GREEN。不得为了继续开发而 reset、checkout、clean 或覆盖当前前端工作。

## 当前已核对基线

- Repository baseline: PR #1 已合并，`main` / `origin/main` 为 `25dbd67bc07138e37d11b4ae41ee9ca94021e181`。远端 replacement head 已推进到 `7f6cbc76e47aea7ccef13676620064f666526448`；当前本地外层 `codex/frontend-replacement@5c29449` 因本计划未提交修改而未 pull，落后远端 1 commit，禁止在当前工作树强行更新。
- Worktree boundary: `7f6cbc7` 已把前端初始导入提交到外层仓库（相对 `main` 共 281 files、16224 additions、30071 deletions），因此“无外层前端 diff”的旧阻塞已解除。但 `web-platform/` 内仍有独立 Git 工作树 `refactor/modern-ui@8072e0bfc93c40ed476710f958cdd4cc6671685c` 和大量本地改动；外层 Git 状态不能替代 `git -C web-platform status` 核验，Phase D 也不得触碰该工作树。
- Ownership: `codex/frontend-replacement` 和嵌套 `web-platform` 工作树属于前端负责人当前任务，Phase D 不得在其中修改、stage、commit 或清理文件。原前端仓库的 `.git/` 不得进入外层仓库提交。
- Plan state: 本文件的 2026-08-11 同步修改当前仅存在于本地工作树，不能夹带进 PR #7。进入 Task 0 写操作前，应在独立 docs-only worktree/branch 只提交本计划并经用户批准合并，或把等价 plan commit 作为 `codex/phase-d-memory` 的首个边界提交；禁止使用 `git add .`。
- Frontend gate: Draft PR [#7](https://github.com/OneAsmallFish/agent-platform-system/pull/7) 当前为 `BLOCKED/REVIEW_REQUIRED`；`test/sqlite/postgres/config` 通过，`quality` 因 `package.json` 缺少 `lint` script 失败。父 Issue [#6](https://github.com/OneAsmallFish/agent-platform-system/issues/6) 与 blocker Issue [#8](https://github.com/OneAsmallFish/agent-platform-system/issues/8) 均 open；当前导入删除了原 memory/skills contract 与 mock 测试，只保留 2 个 Node tests 且其中 1 个失败。该状态不允许冻结 Task 4 文件路径或宣称 M0 完成。
- Alembic: 使用 `backend/.venv` 核对为单一 head `20260810_0012`；`20260810_0012_schema_alignment.py` 已占用 `0012`。Phase D 当前预留 `0013-0016`，若 Task 0 后再出现 revision，必须再次顺延文件名和 `down_revision`，禁止制造多 head。
- Memory: `/api/memory` 仍由 `backend/app/services/mem0_client.py` 的进程内字典提供，重启丢失；`mem0_api_url` 尚未被真实客户端使用。
- Skill: `/api/skills` 仍是数据库 owner-only catalog；同时 `deploy/hermes/skills/hr-weekly-report` 已作为演示用文件系统 Skill 全局挂载到 Hermes。这两套 Skill 不是同一个授权域。
- Conversation: 平台持久化 `ChatSession`、`ChatTurn`、citations 和 HMAC 元数据，但完整消息正文仍由 Hermes 管理；不能把现有 `ChatTurn` 误称为平台已持久化的 L0 对话。
- Context: 普通知识默认 `knowledge_scope=none`；演示账号还会获得代码固定企业/岗位上下文。临时附件、公开链接和钉钉 tool output 有各自生命周期，不能自动沉淀为长期记忆。
- Characterization evidence: 2026-08-11 `main` backend memory/skills/chat-context 定向测试 `24 passed`，完整 pytest `263 passed`，Ruff 与 OpenAPI snapshot check 通过；现有 60 条 Pydantic alias warnings 作为既有警告记录，不是本轮失败。旧前端 memory/skills service/hook 定向 Vitest `11 passed` 只能作为待迁移行为清单，不能作为 `7f6cbc7` 的通过证据；replacement 的真实证据以 PR #7 checks、Issue #8 和后续 merge SHA 为准。

## 目标与交付切片

**Goal:** 先交付平台自有、owner-only、可删除、可追溯的持久记忆，再在独立门禁下增加异步提取、授权优先召回（无 embedding provider 时以 FTS-only 为 D1 基线，启用测试 provider 时才验证 vector/RRF）和显式会话注入；记忆稳定后，继续吸收 QM 的 Project scope、no-transitive re-share 和 Skill 生命周期经验。

**Phase D1（Task 0-5）:** durable memory、capture-source、candidate review、混合召回、会话开关和隔离验收。D1 不依赖 Project、Skill grant 或 TencentDB adapter 即可独立交付。

**Phase D2（Task 6-9）:** Skill catalog 版本/审核、Project scope、Skill grant，以及经过授权的运行时投影。D2 不得阻塞 D1。

**Architecture:** PostgreSQL/pgvector 是 memory、skill、project、grant 和 audit 的唯一权威源。所有组织范围来自 `CurrentOrganizationContext + membership role`。Hermes 继续是 conversation/runtime；平台仅为符合 capture policy 的用户文本创建最小、限时 source snapshot，不复制完整会话。检索必须在 SQL 中先限定 organization/user/status，再执行 FTS/vector ranking。外部 provider 只返回候选结构，不能决定 scope、授权、状态或直接写库。

## 前后端职责与分支边界

- `OneAsmallFish` 负责 Phase D backend、migration、OpenAPI、authorization、Hermes/deploy 和最终集成；backend 分支从当前最新 `origin/main` 在隔离 worktree 创建为 `codex/phase-d-memory`，并在 replacement 合并后同步最新 `main` 再进入最终集成。
- `Keyou430` 负责 `web-platform/**` 的 Phase D service adapter、DTO/ViewModel mapper、mock、UI 和前端测试；Task 4 使用独立 `codex/frontend/phase-d-memory-ui` 分支，不在 backend 分支直接改前端。
- Task 1-3 先冻结并提交 backend API/OpenAPI contract；Task 4 前端分支可以临时以该 API commit/branch 为 stacked base，backend 合并后再 retarget `main`。frontend PR 不得修改 backend/migration/deploy，backend PR 不得夹带前端替换文件。
- `docs/frontend-api-contract.md` 是交接契约，但权威 schema 仍是 `backend/docs/openapi.json`。任何 Phase D API 变更必须先由后端更新 router/schema、OpenAPI snapshot 和权限测试，再由前端适配；禁止在 UI 中伪造临时 `/api/...` 路径。

## QM 参考决策（固定范围）

- 参考版本固定为 QM `v0.1.4` / `7f2c916360f1797a8ff2a77ce2ce40c5fabab087`；本计划只吸收设计原则，不拉入 QM runtime、不复制源码、不改变现有 Hermes 运行时。
- 纳入本 Phase D 的原则：Project 作为独立组织内协作边界；roster 用 revision/CAS 管理；resource link 只表达归属/排序而不产生权限；Skill 采用 immutable version、review/publish/archive 生命周期；grant 由显式 capability 控制且禁止受让人传递授权。
- 保留为后续评估而不在本计划实现的 QM 能力：runtime/Panel/Proxy、SQLite/COS/VDB/Redis 存储栈、自有 team/auth、cron/watch、artifact、sandbox、多 harness 和应用发布。它们只有在平台边界、运维成本和隔离验收另立计划后才可进入候选。
- 评估标准：优先选择能复用当前 `CurrentOrganizationContext`、PostgreSQL/pgvector、现有审计和 server-authoritative pattern 的小范围机制；任何功能若需要绕过平台授权、全局挂载或引入第二个持久化权威源，直接判定为不纳入。

## 明确非目标

- 不引入 QM runtime、TencentDB MemoryPanel/MemoryProxy、自有 team/auth、SQLite/COS/VDB/Redis 存储栈、多 harness 或替换 Hermes。
- 不把代码固定企业/岗位资料、临时附件、公开链接、assistant 回复、tool output、钉钉文档或全局挂载 Skill 自动写入个人长期记忆。
- 不把 collection、Project link、organization placement、外部 team id 或 Skill runtime mount 作为 access grant。
- 不在 D1 实现组织共享 memory、匿名/长期 capability link、cron/watch、keychain、通用 sandbox routing、app publishing 或正式 external guest/email。
- 不执行共享测试数据库或生产数据库迁移；不把当前演示服务器当作 migration sandbox。
- 不读取、打印或提交 `.secret/`、deploy `.env`、runtime 报告、上传文件、演示源文档、凭据或 `.superpowers/`。

## 固定安全与数据生命周期不变量

1. `organization_id`、`user_id`、`membership_id` 和 role/permission 只能由 `CurrentOrganizationContext` 派生；请求 DTO、username 特判、provider 返回值和 `User.default_organization_id` 都不是授权来源。
2. 缺少必需 scope 必须拒绝，不得回填 `default` bucket。跨组织/跨用户 detail、update、delete、confirm、reject 统一 fail closed，并尽量 404 隐藏存在性。
3. D1 memory 仅当前 organization + 当前 user 可读写；manager/admin 不因角色默认读取他人个人记忆。未来共享必须另立 migration、grant 和审计计划。
4. 自动 capture 首期只处理用户本人输入的普通文本；固定上下文、附件、链接、assistant/tool 消息、钉钉结果、Hermes filesystem Skill、credential-like 内容和高风险员工 PII（证件、健康、薪酬、处分等）全部默认排除。任何未来 promotion 必须有显式用户动作和单独测试。
5. 原始 capture snapshot 只为异步提取短期保存，不出现在普通 API、audit 或日志；job 终态后按配置 TTL 清理。候选未确认前不能注入会话。
6. 手工创建 memory 直接为 active；自动提取只能生成 candidate。确认后才 active；reject 必须删除候选内容。L3 偏好不得由单次低置信输入自动激活。
7. 用户 `DELETE /api/memory/{id}` 保持 204，但语义固定为物理清除 record/version/source links/embedding；audit 只保留 id、actor、action、时间和非内容元数据，不保留正文。
8. 来源 session 删除时，未确认 candidate、未完成 job 和短期 snapshot 一并删除；用户已显式确认的 active memory 可保留，但 source 正文必须清除并显示 source unavailable/tombstoned。
9. 外部 extraction/embedding HTTP 调用必须发生在数据库事务和 row lock 之外；写入阶段使用短事务、CAS 和固定锁顺序。
10. FTS/vector 候选查询本身必须含 organization/user/status predicate；禁止先做全局 top-k 再仅在 Python 中过滤。
11. Memory 内容始终作为 untrusted data 注入，不能覆盖 system/platform instructions。D1 只允许在 knowledge/AI 办事 surface 且 session `memory_mode=auto` 时注入；agent/terminal surface 保持关闭。`AUTHORIZED_MEMORY` 每请求硬上限为 2,000 个 UTF-8 字符，并计入现有 chat context 总预算。
12. 数据库 Skill catalog、部署目录中的全局 Skill 和 Hermes runtime capability 是三个不同边界。catalog publish/grant 不自动安装或执行 Skill。

## 数据库设计约束

- 当前预留 revisions：`20260811_0013` memory、`20260811_0014` Skill lifecycle、`20260811_0015` Project scope、`20260811_0016` Skill grants。Task 0 必须再次确认。
- 每个复合组织外键都包含 `organization_id`；PostgreSQL 不自动为 FK 建索引，因此每个 FK/复合 FK 的引用列必须有匹配索引。
- owner list/search 使用 equality columns 在前、排序列在后；memory active list 使用 `(organization_id, user_id, updated_at DESC, memory_id DESC)` partial index。
- memory FTS 使用与现有 RAG 一致的 PostgreSQL `to_tsvector('simple', content)` partial GIN，predicate 为 active；1024 维 HNSW 只索引 `embedding IS NOT NULL AND status='active'`。不得为不查询的 metadata JSON 预建 GIN。
- extraction queue 使用可领取状态的 partial/composite index，并在 PostgreSQL 通过 `FOR UPDATE SKIP LOCKED` claim；SQLite 测试保留进程锁替身。
- 列表使用 `(updated_at, memory_id)` keyset cursor；不得新增深分页 OFFSET。旧 `page/page_size` 只是前端/mock 残留，不作为后端兼容层，Task 1/4 直接删除并统一到 `cursor/limit`。
- migration roundtrip 后执行 missing-FK-index 检查，并在合成规模数据上对 list、FTS、vector 和 job claim 运行 `EXPLAIN (ANALYZE, BUFFERS)`；不在共享/生产数据上运行分析。

## Task 0：冻结并行 backend 基线与前端集成门禁

**Files:**

- Read-only inspect: outer repository, nested `web-platform` Git boundary, replacement PR/Issue/check evidence, `backend/migrations/versions/`, deploy configs and tests
- Create after backend Steps 1-6 pass: `docs/superpowers/checkpoints/2026-08-11-phase-d-baseline.md`; append frontend merge SHA/evidence when Step 7 passes
- Do not edit business code, stage frontend work or switch/clean the nested frontend worktree in this Task

- [x] **Step 1: 记录 replacement 初始导入而不误判完成。** 固定远端 head `7f6cbc7`、PR #7、Issue #6/#8 和五项 checks；确认初始外层 diff 可复现，但 `quality` 失败、PR 仍 Draft/Blocked、测试迁移和 API/security gates 未完成。此 Step 允许 backend lane 继续评估，不允许 Task 4、Task 5 或 replacement merge。
- [x] **Step 2: 重新记录双层 Git boundary。** 分别运行外层和 `git -C web-platform` 的 branch/HEAD/status/remote 检查；确认嵌套 `.git/`、`.env`、node_modules、dist、test-results、`.sisyphus/` 均不会进入外层提交。不得 reset/clean/switch 嵌套前端工作树，也不得把前端负责人未提交文件归入 Phase D。
- [x] **Step 3: 创建隔离 Phase D backend branch。** 从最新 `origin/main` 创建独立 worktree 和 `codex/phase-d-memory`；不得在当前 `codex/frontend-replacement` 或嵌套前端仓库开发。backend Draft PR base 为 `main`，变更范围只包含 Task 1-3 backend/migration/OpenAPI/checkpoint；在 replacement 合并后、backend PR 合并前必须 merge/rebase 最新 `main` 并重跑回归。
- [x] **Step 4: 重跑 backend characterization。** 至少覆盖 memory、skills、chat context、attachments/link、sandbox toolsets，并运行完整 pytest、Ruff、OpenAPI check、Alembic heads/check；记录真实通过数和既有失败。Steps 1-6 全绿后允许进入 backend-only Task 1，不以 replacement 的前端失败阻断后端 TDD。
- [x] **Step 5: 固定 demo-only exclusions。** 明确 `fixed_knowledge.py` username mapping、`hr-weekly-report` filesystem Skill、`dingtalk_documents` global operator、临时附件/链接均不是 memory source 或 organization authorization；相应负向测试必须进入 Task 2/3。
- [x] **Step 6: 核对 Alembic 与部署门禁。** 使用 `backend/.venv` 运行 `alembic heads`，确认单 head；确认 `0013` 未被占用且 `down_revision='20260810_0012'`。任何共享数据库迁移、生产迁移或现有 demo DB mutation 均在此停止并另行请求授权。
- [ ] **Step 7: 前端合并与 Task 4 解锁门禁。** 只有 Issue #8 A-H、Issue #6 M0-M6、`quality/test/sqlite/postgres/config`、真实 API 正负向验收、独立 reviewer、resolved conversations 和 PR #7 merge 全部完成后，才记录 replacement merge SHA、冻结新的 memory service/query/UI 路径并启动 Task 4。Task 5 必须等待 backend Task 1-3 与 frontend Task 4 在最新 `main` 上共同通过。

## Task 1：平台自有手工记忆、严格 API 契约与 `0013`

**Files:**

- Modify: `backend/app/models/entities.py`, `backend/app/models/__init__.py`, `backend/app/schemas/memory.py`, `backend/app/routers/memory.py`, `backend/app/config.py`
- Create: `backend/app/services/memory_repository.py`, `backend/app/services/memory_authorization.py`, `backend/app/services/memory_provenance.py`
- Create: `backend/migrations/versions/20260811_0013_phase_d_memory.py`
- Modify: `backend/docs/openapi.json`, `docs/frontend-api-contract.md`
- Test: `backend/tests/test_memory_persistence.py`, `backend/tests/test_memory_authorization.py`, `backend/tests/test_phase_d_memory_migration.py`, OpenAPI snapshot/permission tests

- [x] **Step 1: 先写并运行真实 RED。** 覆盖重启/新 DB session 后仍可读、owner-only、跨组织/跨用户 404、provider 为 `platform-postgres`、稳定 string `memory_id`、revision/CAS 409、manual create 为 active、candidate 默认不可见、物理 delete 204、keyset list、audit 不含正文。保留 URL/method：list/get/create/update/delete 和 `GET /memory?query=`。
- [x] **Step 2: 固定受控 backend contract change。** `MemoryResponse` additive 增加 `revision/layer/status/origin/source_summary`；`MemoryUpdate` 必须携带 `expected_revision`，DELETE 必须带 `expected_revision` query 并在 stale 时返回 409。后端当前从未消费 `page/page_size`；真实服务端过滤/分页参数固定为 `query/type/cursor/limit`，list response additive 增加 `next_cursor`。`provider` 的线上 canonical 值为 `platform-postgres`。本 Step 更新 backend schema/router、OpenAPI snapshot 和 `docs/frontend-api-contract.md`，并输出 Task 4 handoff；不直接修改正在替换的 `web-platform/**`。
- [x] **Step 3: 创建 additive schema 与 provider DTO。** 建立 `memory_capture_sources`、`memory_records`、`memory_versions`、`memory_source_links`、`memory_extraction_jobs`、`memory_retrieval_events`，并给 `chat_sessions` 增加 `memory_mode IN ('off','auto')`，existing/new session server default 均为 `off`。同时冻结 provider-neutral 的 Pydantic `MemoryCandidateDTO`（含 type/layer/content/confidence/source_ref/provider/version，不含 scope/status/id），Task 2/3 只能消费该 DTO，字段扩展必须新增 RED。建立 composite FK、CHECK、unique/idempotency、FK indexes、active partial list、FTS GIN、partial HNSW 和 queue claim indexes。
- [x] **Step 4: 实现 manual repository/API。** 每个 statement 显式限定 organization/user；create 写 active v1；update 用单事务 CAS 追加 immutable version 并更新 head；delete 物理清除内容。metadata/source/provider 不参与权限。此 Step 不启动 extraction、不调用 LLM/TencentDB，也不自动修改 chat 路径。
- [x] **Step 5: 清理虚假 Mem0 边界。** consumer 全量搜索后移除运行时对进程内 `_items` 的依赖；测试 fake 移至 fixture。删除或重命名未使用的 `mem0_api_url`，避免把 `platform-postgres` 误报为真实 Mem0。不得保留两个可写权威源。
- [x] **Step 6: 写现有 audit。** create/update/delete/confirm/reject 使用 `record_audit`；details 仅含 revision、layer、origin、status/source kind 等非正文信息。验证 audit list 跨组织隔离。
- [x] **Step 7: 在一次性 PostgreSQL 16 + pgvector 执行 `0013` 的 `upgrade -> invariants -> downgrade -> upgrade`。** 同时验证 SQLite ORM 测试兼容、missing FK indexes、partial index predicate、HNSW/GIN 存在、已有 `0012` schema-alignment 数据不变。未通过不得进入 Task 2。

## Task 2：最小 capture-source、异步 extraction job 与 candidate 生命周期

**Files:**

- Create: `backend/app/services/memory_capture.py`, `backend/app/services/memory_extraction.py`, `backend/app/workers/memory_worker.py`
- Modify: `backend/app/routers/chat.py`, stream lifecycle hook, `backend/app/routers/memory.py`, `backend/app/schemas/memory.py`, `backend/app/config.py`, deploy compose/template only as required
- Test: `backend/tests/test_memory_capture.py`, `backend/tests/test_memory_extraction.py`, `backend/tests/test_memory_worker.py`, affected chat lifecycle tests

- [x] **Step 1: 先写 source-policy RED。** 普通 user text 可生成 capture source；固定企业/岗位 context、attachment content、link content、assistant/tool output、钉钉 document、filesystem Skill 文本、credential-like input 和高风险员工 PII 均不能自动 capture。跨组织 provider scope、失败/中断 turn、重复 stream completion 不能入队。
- [x] **Step 2: 从已校验请求输入创建最小 snapshot。** 文本来源是平台在调用 Hermes 前已校验的 user request payload，不从 Hermes 流或已组装 instructions 反向提取；每 turn 最多 4 KiB UTF-8，超限 turn 不自动 capture。成功终态（`response.completed`）只决定是否入队，失败/中断 turn 丢弃 snapshot；只保存 bounded user-authored text、content SHA、organization/user/session/turn ids 和时间。session/turn FK 必须带 organization scope；同一 turn/hash 唯一，重放幂等。
- [x] **Step 3: 实现 queue claim/retry。** PostgreSQL 使用 `FOR UPDATE SKIP LOCKED`，SQLite 测试使用进程锁；claim transaction 立即提交。provider HTTP 调用在事务外；结果落库前重新锁定 job/source 并复查状态、membership/resource lifecycle。固定最大 attempts、稳定 error code、取消和 shutdown drain。
- [x] **Step 4: 实现严格 provider protocol。** provider 只接收服务器选择的 source text 和最小 opaque scope correlation，返回 Task 1 已冻结、经 Pydantic 校验的 candidate DTO；禁止 provider 提交 organization/user/status/id。默认 extraction disabled 时 manual memory 全部可用，worker 不崩溃也不伪造结果。
- [x] **Step 5: 落 candidate、冲突关系和审核 API。** candidate 记录 type `fact/preference/decision/context`、layer `L1/L2/L3`、confidence、source link 和 provider/version；同一 source/provider/version 幂等。事实更正使用 `supersedes_memory_id`，不静默覆盖 active 历史。新增 `GET /api/memory/candidates`、`POST /api/memory/{id}/confirm`、`POST /api/memory/{id}/reject`；静态 candidates route 必须在 dynamic id route 前注册，confirm/reject 必须 owner-scoped 且携带 `expected_revision`。
- [x] **Step 6: 实现 retention/delete。** memory worker 在独立 purge sweep 中清理达到 TTL 的终态 source raw text；session 删除级联取消 job、删除 candidate 和 snapshot。确认后的 active memory 只保留 source tombstone/hash，不保留已删除源正文。
- [x] **Step 7: 运行定向 GREEN 和并发测试。** 至少证明两个 worker 不会 claim 同一 job、外部 timeout 时锁不被长期持有、固定锁顺序无死锁、重启后 queued job 可恢复。

## Task 3：授权优先混合召回与显式会话注入

**Files:**

- Create: `backend/app/services/memory_retrieval.py`, `backend/app/services/memory_context.py`
- Modify: `backend/app/services/chat_context.py`, `backend/app/routers/chat.py`, `backend/app/routers/memory.py`, chat schemas
- Reuse: existing query embedding boundary/RRF utilities only where contracts match
- Test: `backend/tests/test_memory_retrieval.py`, `backend/tests/test_chat_memory_context.py`, query-plan assertions/helpers
- Create: `backend/tests/fixtures/memory_eval/` with synthetic, non-customer data

- [x] **Step 1: 先写 retrieval/injection RED。** 跨组织或他人相似向量永不返回；candidate/superseded/deleted 不返回；缺少 query embedding fail closed 或降级到 authorized FTS；memory 文本不能覆盖 instructions；`memory_mode=off`、agent surface、guest 和无 permission 时不注入。
- [x] **Step 2: 实现 SQL-first retrieval。** authorization predicate 与 active status 进入 FTS/vector statement；执行 bounded overfetch + RRF、确定性 tie-break、type/layer filter、最大结果数和 token budget。D1 在没有 embedding provider 时必须以 authorized FTS-only 作为可部署基线；仅允许 test-only 的本地 deterministic fake embedding adapter 运行 vector/RRF/query-plan 覆盖，不能把 fake 质量当作生产效果。Python post-check 只能作为 defense-in-depth，不能补救未 scoped SQL。若 ANN 在 scope filter 下欠召回，只能退回该 organization/user 的 bounded exact vector scan，禁止扩大到全局候选。
- [x] **Step 3: 实现 list/search 与 keyset。** 无 query 使用 active partial list index；有 query 使用 hybrid retrieval；cursor 包含完整 `(updated_at,memory_id)` 排序键并严格解析，非法 cursor 返回 422；每次请求仍重新应用 scope，cursor 不承载授权。response 不暴露 embedding、raw source、provider credentials 或内部 job id。
- [x] **Step 4: 实现 `AUTHORIZED_MEMORY` data block。** 仅 knowledge/AI 办事 surface 且 session memory mode 为 auto 时注入短摘要、type/layer、memory id 和安全 source label；每请求最多 2,000 个 UTF-8 字符且不突破现有 `_MAX_CONTEXT_CHARS=12_000` 总预算。固定 context、ordinary knowledge、transient context 和 memory 分区组装，分别预算，均不能互相取得授权。
- [x] **Step 5: 增加 session API/审计。** memory mode update 由 session owner + `memory:read` 控制；existing sessions 保持 off。retrieval event 只存 query HMAC/版本、mode、result count、latency/outcome，不存 query 或 memory 正文。
- [x] **Step 6: 建立评测基线和 query-plan gate。** 最小合成集为 3 个组织、每组织至少 100 条 active memory，另加每组织 30 条 candidate/superseded/deleted 排除样本；每组织至少 20 条 query。覆盖事实、偏好、决策、更正、冲突、过期、无答案、跨组织近似文本和 prompt injection；无 embedding provider 时只报告 FTS baseline，启用 test-only deterministic adapter 时另报告 vector/RRF，不互相冒充。记录 Precision@5、Recall@5、p95、token 数。授权泄漏必须为 0；`EXPLAIN (ANALYZE, BUFFERS)` 必须证明 scope/list/FTS/queue 使用预期索引。
- [ ] **Step 7: 冻结 backend API handoff。** Task 1-3 的 RED/GREEN、迁移 roundtrip、OpenAPI check 和定向回归全部通过后，生成 operation/schema/permission/error diff；经用户批准 staged 白名单后创建并推送 backend API commit/Draft PR，供 `Keyou430` 创建 Task 4 stacked frontend branch。此 handoff 不是 D1 最终验收，Task 5 仍须验证两条分支的集成结果。

## Task 4：记忆候选审核、CRUD 与会话开关 UI

**Files:**

- Resolve exact paths in the Task 0 checkpoint after the replacement frontend is merged; do not assume legacy `useKnowledgeSubmodules.ts` or `KnowledgeSubmoduleViews.tsx` survives
- Modify under `web-platform/**`: canonical memory service interface, real/mock adapters, DTO/ViewModel mapper, query/store boundary, existing knowledge/AI surface and focused components only where the replacement architecture requires
- Test: replacement frontend memory contract/service/query/component tests, real/mock selection matrix and responsive Browser specs; preserve or port the behavioral coverage currently carried by `knowledgeExtended.test.ts`

- [ ] **Step 1: 在独立前端分支先写 UI RED。** `Keyou430` 从已冻结的 backend API commit 创建 `codex/frontend/phase-d-memory-ui`（可先 stacked，backend 合并后 retarget `main`）；覆盖 manual create/edit/delete、expected revision 409 草稿保留、candidate confirm/reject、source unavailable、empty/loading/error、memory mode off/auto、mock mode 不调用 Axios、跨 session/organization 切换状态不串线。frontend branch 不修改 backend/migration/deploy。
- [ ] **Step 2: 在现有 AI 办事/知识导航中增强“记忆库”。** Active memory 与待确认候选分区展示；type/layer/status/source/revision 使用紧凑标签和 timeline/detail drawer，不展示 raw source、embedding、confidence 内部调参或 demo 固定资料正文。
- [ ] **Step 3: 实现 canonical real/mock workflow。** frontend Zod、mock records、real/mock adapters 和 mapper 只有一套；server cursor 为权威分页。删除前端/mock 的 `page/page_size` 残留，不新增后端兼容字段。旧 `mock-mem0-self-hosted` 只允许在迁移期 fixture 输入中解析并立即归一化为 `platform-postgres`，所有新 real/mock 输出和 Zod 默认值均为 canonical；其余 mock-only 字段也必须在 consumer 核对后清除。
- [ ] **Step 4: 增加显式记忆开关。** 开关仅修改当前 session `memory_mode`，不得改变 knowledge scope、固定 context 或附件行为；首次开启明确显示个人 owner-only 和记忆可管理状态，但不在页面写功能说明长文。
- [ ] **Step 5: 运行定向 `npx vitest run`、完整 `npm run test:ci`、lint/build，并使用 in-app Browser 在 320/390/414/768/1280/1440 验收。** 检查无重叠/溢出、刷新恢复、双组织隔离、409、删除后不可见、键盘/焦点/reduced-motion 和 console；保留一个 deliverable tab。

## Task 5：Phase D1 隔离验收与可选 TencentDB adapter go/no-go

**Files:**

- Modify deploy templates only after local D1 tests pass and only for a fresh isolated environment
- Create: `docs/superpowers/checkpoints/2026-08-11-phase-d1-memory-acceptance.md`
- Do not commit runtime logs, benchmarks containing content, credentials or customer/demo source documents

- [ ] **Step 1: 重跑 `0013` roundtrip 和全量回归。** backend pytest/Ruff/OpenAPI，frontend 定向 Vitest/`test:ci`/lint/build，受影响 Browser specs 全部通过；验证 migration from `0012 -> 0013 -> 0012 -> 0013` 和 schema/data invariants。
- [ ] **Step 2: 在 fresh PostgreSQL 16 + pgvector 和 fresh app volume 部署 D1。** 不连接现有演示 DB、共享测试 DB 或生产 DB；验证 restart persistence、worker restart、mode off、candidate review、hard delete 和跨组织 404。
- [ ] **Step 3: 先以 platform/manual + fake extraction provider 验收。** durable memory、candidate lifecycle 和 retrieval 不依赖 TencentDB。若核心不绿，禁止通过外部 adapter 掩盖问题。
- [ ] **Step 4: 可选自托管 TencentDB adapter 仅在隔离试点启用。** 默认关闭、无公共网络依赖；adapter 不能写数据库、不能接受未授权 fixed/transient/tool content、不能回传 scope。测试 timeout、malformed DTO、恶意 scope、shutdown 和完整 fallback。
- [ ] **Step 5: Go/no-go。** 在看到任何真实 provider 结果前冻结 FTS baseline 的 candidate precision、p95 和 token 预算；若启用 test-only deterministic embedding，再单独冻结 vector/RRF 指标，之后不得为通过验收下调。只有授权泄漏为 0、跨重启持久化通过、candidate precision 达标、对应检索指标不低于同模式 platform baseline、p95/token 在冻结预算内、关闭 adapter 可完整回退时才保留 adapter；否则交付 FTS-only 平台 D1。
- [ ] **Step 6: 在用户批准提交范围后分别创建 backend 与 frontend D1 边界提交/PR。** backend PR 仅允许 Task 1-3、5 的 backend/migration/OpenAPI/checkpoint 白名单；frontend PR 仅允许 Task 4 的 `web-platform/**` 与明确交接文档。分别将 `git diff --cached --name-only` 与白名单逐项比较；嵌套 `.git/`、`.superpowers/`、`.secret/`、runtime、uploads、演示源文档和凭据 staged count 必须为 0。backend PR 可先以当前 `main` 为 base 并行推进，但 replacement 合并后必须同步最新 `main`、解决契约文档冲突并重跑完整回归；Task 4 frontend PR 只能在 replacement 合并后创建，可先 stacked 到 backend API branch，backend 合并后必须 retarget `main`。若无法保持此边界，停止推送。

## Task 6：Skill catalog 版本、审核、发布与归档（Phase D2）

**Files:**

- Modify: `backend/app/models/entities.py`, models exports, Skill schemas/router, `backend/app/seed.py`
- Create: `backend/app/services/skill_repository.py`, `backend/app/services/skill_versioning.py`
- Create: `backend/migrations/versions/20260811_0014_phase_d_skill_lifecycle.py`
- Modify: `backend/docs/openapi.json`, `docs/frontend-api-contract.md`
- Test: backend lifecycle, migration, authorization and OpenAPI contract tests

- [ ] **Step 1: 先写 catalog RED。** owner create v1；update 带 expected revision 并追加 immutable version；stale 409；no-op 幂等；跨组织/非 owner 404/403；archive 后 catalog 默认不可见。测试必须证明 `deploy/hermes/skills/hr-weekly-report` 的存在不会让数据库 Skill 自动 published/installed。
- [ ] **Step 2: 建立 `skill_versions` 和 head 字段。** status `draft/reviewed/published/archived`、revision、current_version、content hash；现有 rows backfill v1 draft。所有 FK 和 `(organization_id,user_id,status,updated_at,id)` list path 建索引。
- [ ] **Step 3: 实现短事务版本追加和 audit。** review 需 `skills:review`、publish 需 `skills:publish`，同时更新 seed 和 `0014` role links；AI-generated 只是 provenance。不得在 DB transaction 中复制 filesystem、调用 Git/COS 或重启 Hermes。
- [ ] **Step 4: 固定 catalog-only 语义。** published 表示可进入授权/发现流程，不表示已挂载 Hermes。`/api/skills/hub` 的 mock provider 不得冒充 runtime inventory。
- [ ] **Step 5: 隔离执行 `0014` roundtrip、backend 定向/全量回归和 OpenAPI snapshot check。** frontend real/mock parity 延至 Task 9 的前端负责人分支。

## Task 7：QM Project scope、roster revision 与资源分组（Phase D2）

**Files:**

- Modify models/exports/seed/main
- Create: Project schemas/router/authorization service
- Create: `backend/migrations/versions/20260811_0015_phase_d_project_scope.py`
- Test: project CRUD/scope/migration/concurrency tests

- [ ] **Step 1: 先写 Project RED。** 当前组织可列；跨组织不可见；private Project 非 roster 不可读；owner/admin 管理 roster；stale revision 409；批量成员变更全事务；guest 默认不能加入。
- [ ] **Step 2: 建立 `projects`、`project_members`、`project_resource_links`。** membership 使用 organization composite FK；resource link 只存 type/id/order，不是 grant。新增 `projects:read/write/manage` 时同步 seed 和 `0015` role links。
- [ ] **Step 3: 使用 keyset、复合索引和固定锁顺序。** Project/roster 批量更新先按 id 排序锁定；事务内不做外部调用。删除/归档 Project 不级联删除 knowledge/memory/skill/work item。
- [ ] **Step 4: 验证 directory/placement/project/grant 分离。** placement 变化不隐式加入 Project；Project member 不自动读取链接资源；撤权后只返回 unavailable reference，不缓存旧正文。
- [ ] **Step 5: 隔离执行 `0015` roundtrip、missing-FK-index 检查和全量回归。**

## Task 8：Skill grant、管理员推广与 no-transitive re-share（Phase D2）

**Files:**

- Modify Skill model/schemas/router/seed, OpenAPI snapshot and frontend API contract document
- Create: `backend/app/services/skill_authorization.py`
- Create: `backend/migrations/versions/20260811_0016_phase_d_skill_grants.py`
- Test: sharing/promotion/revocation/runtime-negative/migration tests

- [ ] **Step 1: 先写 grant RED。** owner grant B read 后 B 可读不可写；B 再 grant C 为 403；撤销/过期立即不可读；跨组织 membership 拒绝；Project link/collection/department/global filesystem mount 均不能代替 grant。
- [ ] **Step 2: 建立 `skill_access_grants`。** capability 初期只 read；新增 `skills:share/govern` 同步 seed 和 `0016` role links；保留 actor membership、expires/revoked 和 audit。active unique 使用 partial index，所有 FK indexed。
- [ ] **Step 3: 实现 promotion。** 只有 reviewed catalog Skill 可推广为组织可发现；管理员不能夺取 owner 写权限。普通受让人不能 edit/review/publish/promote/re-share。
- [ ] **Step 4: 固定 catalog authorization。** grant/promotion 只决定平台 catalog 可见性，不自动改变 Hermes `platform_toolsets`、filesystem mounts 或 profile files。
- [ ] **Step 5: 隔离执行 `0016` roundtrip、撤权即时性和完整回归。**

## Task 9：受控 Skill runtime 投影、Project UI 与 Phase D2 验收

**Files:**

- Create only if runtime gate is feasible: `backend/app/services/skill_context.py` and explicit selection/binding APIs
- Modify replacement Skill/Project views, routes, query/store boundary and mock handlers under `web-platform/src/` on a frontend-owner branch
- Modify Hermes/deploy configuration only after platform authorization tests pass and only through a separate reviewed deployment change

- [ ] **Step 1: 先写 runtime projection RED。** draft/unreviewed/ungranted/revoked/archived Skill 永不进入 Hermes instructions/tools；跨组织相同 id 不串线；existing global `hr-weekly-report` mount 不能作为 scoped authorization 测试替身。
- [ ] **Step 2: 首选 per-request trusted projection。** 只有服务器选定的 published version 可作为 platform instruction 注入；用户 Skill content 在审核前始终是 untrusted data。不得把授权 Skill 复制到长期 Hermes profile；下一请求必须重新授权，确保撤权即时生效。
- [ ] **Step 3: 若 Hermes 无法提供可验证的 per-request boundary，停止 runtime projection。** D2 只交付 catalog/version/grant/Project，不以全局 mount 冒充组织隔离。任何 filesystem install、签名 bundle 或热加载另立计划。UI 与 runtime 解耦：即使 runtime projection 停止，Skill/Project UI 仍按平台 catalog authorization 展示；运行时不可用只显示 projection/install unavailable，不把它误报为未授权。
- [ ] **Step 4: 由前端负责人在独立分支实现 Project/Skill UI。** Project 展示 roster、任务、knowledge、memory 和 Skill 分组；底层 catalog 无权限只显示 unavailable。Skill 展示版本、status、grant/promotion；409 保留草稿。real/mock 共用 DTO/mapper，frontend branch 不修改 backend/migration/deploy。
- [ ] **Step 5: 运行 `0013-0016` 连续 upgrade/roundtrip、backend/frontend 全量、Browser 双组织和撤权验收。** existing Phase C/D1 data 不变；部署仍限 fresh isolated environment。
- [ ] **Step 6: 经用户批准后按 Task 边界提交并推送 Draft PR。** 任何 QM/TencentDB 实质源码复用前增加 MIT notice、版权归属和第三方许可证清单；本计划不授权复制源码。

## 后续独立门禁

以下能力只记录候选，不因本计划获得实现、凭据使用或部署授权：

1. 从附件、公开链接、固定企业/岗位资料、钉钉文档或 assistant/tool output 显式 promotion 到 memory。
2. Organization-shared memory 和 memory grant。
3. Cron/watch/background run 的 durable claim、lease、dedup、配额和副作用隔离。
4. Unified file artifact/object storage、内容检查、保留期和短期下载授权。
5. Credential broker/keychain 的主密钥、轮换、一次性 materialization、审计和泄漏响应。
6. Sandbox routing、多 runner/GPU/多区域、app publishing、多 harness 和框架迁移。
7. External guest、正式 email、匿名或 capability link 的身份、滥用防护和支持责任。

## 最终验收命令与停止条件

从 `backend` 目录，使用项目虚拟环境：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m alembic heads
```

从 `web-platform` 目录：

```powershell
npx vitest run <task-specific-test-files>
npm run test:ci
npm run lint
npm run build
```

每个 implementation Task 仍需先运行定向 RED，再实现 GREEN；完整回归不能替代红灯证据。嵌套前端工作树归属不清、Alembic 出现多 head、`0013` 被占用、共享/生产数据库是唯一可用迁移目标、capture source 无法排除 fixed/transient/tool content、SQL 无法先完成 scope filter、runtime Skill 只能全局挂载、或测试需要读取真实凭据/客户资料时，backend lane 必须停止并修订计划。前端替换尚未 merge、replacement merge SHA 无法重建、Issue #8 未关闭或 PR #7 checks/review 未通过时，只阻断 Task 4、Task 5 和任何 frontend/integration 写操作，不反向软化或取消 backend Task 1-3 的测试门禁。
