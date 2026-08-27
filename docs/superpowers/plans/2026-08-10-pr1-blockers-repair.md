# PR #1 阻塞项与隐性风险修复实施计划

> 版本：2026-08-10（agent review 修订版）
> 计划状态：执行中；Phase 1-4 本地修复已完成，Phase 5 远端 required checks 待验证
> 适用仓库：`OneAsmallFish/agent-platform-system`
> 当前分支：`codex/hermes-platform-integration`
> 计划创建时 HEAD：`82aaea1`（初版计划提交）；代码修复基线固定为 `290f233a5059911f218f8653ac7ccb8cfebaf51a`；当前远端 head 以执行前 Git/PR Checks 复核为准
> PR：[#1](https://github.com/OneAsmallFish/agent-platform-system/pull/1)

本计划是 PR #1 当前阻塞项和隐性风险的唯一实施入口。除非维护者明确更新本文件，否则执行 agent 不得自行扩大文件范围、改变数据库迁移策略或将未验证的外部 provider 接入生产。

## 1. 当前基线

### 1.1 Git 与 PR 状态

- 远端 PR 已包含门禁 workflow、CODEOWNERS 和审阅证据；执行 agent 开始前必须运行 `git rev-parse HEAD`、`git status --short` 和 `git rev-list --left-right --count origin/codex/hermes-platform-integration...HEAD` 重新记录实际基线。
- 在创建本计划前，工作区已清理，`git status --short` 无输出；此前 135 个 dirty 项已按职责提交，`.omo/` 和 `.superpowers/` 仍为本地忽略目录，不进入 Git。计划文件本身尚未提交时，不能再次声称当前工作区为 clean。
- `main` 仍是发布基线，维护者没有授权直接修改或强推 `main`。
- PR #1 仍是 Draft，`mergeStateStatus=BLOCKED`，`reviewDecision=REVIEW_REQUIRED`，需要至少一名其他 reviewer 批准并解决全部 conversation。
- 当前通过的 required check 只有 `frontend / quality`，包括 npm 安装、audit、lint、229 个 Vitest 测试和生产 build；后端测试、迁移 smoke 和 Compose 配置检查尚未成为 PR gate。

### 1.2 已确认的提交边界

当前 PR 的阶段提交如下，修复计划必须以 `290f233` 为基线，不重写这些提交：

| 提交 | 范围 |
| --- | --- |
| `de12b5f` | 前端页面、service、类型、mock、测试 |
| `34f3146` | 后端 portal/chat/context/work-item/附件/link parser |
| `af67cfd` | Compose、Hermes DingTalk plugin/Skill、脚本、文档 |
| `44ebcb7` | 忽略本地 `.omo/`、`.superpowers/` 生成物 |
| `8d326b6` | 清理后的前端移交基线文档 |
| `290f233` | PR 审阅阻塞项记录 |

现有 [前端移交指南](../../frontend-handoff-guide.md) 的基线 SHA 仍有旧值，必须在本计划最后一阶段同步更新，不能让执行 agent 直接引用旧 SHA。

## 2. 目标与非目标

### 2.1 目标

1. 消除五项 P1 阻塞项，使认证、权限、迁移、RAG worker 和密钥启动契约可证明正确。
2. 修复审阅中发现的高风险隐性 bug，尤其是跨组织授权、并发终态、外部 URL 和前端状态不一致。
3. 建立后端、迁移、Compose 和前端的统一 PR CI 门禁。
4. 形成可复现的 staging 验收、发布和回滚记录，再将稳定 API 基线交给前端成员。

### 2.2 非目标

- 不在本计划中引入新的 agent runtime、Mem0/TencentDB runtime、第二个数据库权威源或新的组织权限模型。
- 不把 mock provider 伪装成真实 provider，不在未获授权的情况下调用 TikHub、付费 AI、Feishu、SMTP、Hermes 生产服务或真实用户数据。
- 不修改 `main`，不删除尚未确认归属的文件，不使用 `git reset --hard`、`git clean` 或强制 checkout 覆盖工作区。
- 不把数据库 downgrade 当作生产回滚的唯一方案；生产迁移必须有备份和恢复演练。
- 不把前端页面视觉调整、无关依赖升级和历史分支清理混入本修复计划。

## 3. 问题清单与完成定义

### 3.1 P1 阻塞项

| ID | 位置 | 根因 | 必须完成的验收 |
| --- | --- | --- | --- |
| B1 | [backend/app/routers/auth.py:165](../../../backend/app/routers/auth.py:165)、:183 | refresh token 先读后撤销，没有行锁或原子条件更新 | SQLite 基础测试和 PostgreSQL+asyncpg 并发测试均通过；两个并发 refresh 只有一个成功；失败请求不能产生可用 token；旧 refresh token 单次使用 |
| B2 | [backend/migrations/versions/20260729_0005_platform_rag.py:7](../../../backend/migrations/versions/20260729_0005_platform_rag.py:7)、:17、:71、:95-106 | 模块级 `pgvector` import 以及 extension、Vector 类型、GIN/HNSW 索引均无 dialect guard；SQLite 可能在 `alembic check` 阶段就失败；完整 PostgreSQL 链还在 `20260731_0006` seed 阶段缺少 `manager` role | 全新 SQLite 可 `upgrade head` 和 `alembic check`；PostgreSQL+pgvector 可建立 Vector/FTS/HNSW 并完成 revision `20260803_0011`；两种 dialect 的 schema 断言通过 |
| B3 | [deploy/compose.yaml:87](../../../deploy/compose.yaml:87)、[rag_ingestion.py:20](../../../backend/app/workers/rag_ingestion.py:20) | Compose 将缺失 `RAG_EMBEDDING_API_KEY` 注入为空字符串，绕过只检查 `None` 的 client guard，worker 启动后首次 embedding 才失败 | `/health` 只证明 API liveness；`/ready` 聚合 DB、RAG worker 和配置状态；enabled worker 不 ready 时 `/ready` 返回 503，不能把 crashloop 报成全栈 healthy |
| B4 | [backend/app/routers/invitations.py:224](../../../backend/app/routers/invitations.py:224)（revoke）、[backend/app/services/invitations.py:238](../../../backend/app/services/invitations.py:238)（accept/reactivate） | guest membership 撤销没有清理旧 KnowledgeAccessGrant；accept/reactivate 路径会按新邀请资源补 grant，但不会自动收敛旧 grant | 撤销立即失效；重新邀请更小资源集不恢复旧 grant；旧 grant 有审计记录 |
| B5 | [deploy/.env.example:22](../../../deploy/.env.example:22)、[knowledge_retrieval.py:51](../../../backend/app/services/knowledge_retrieval.py:51) | RAG HMAC 允许空值或已知占位值，启动脚本不阻断 | 空值、短值、默认值和占位字符串全部拒绝；真实随机 key 才能启动查询审计 |
| B6 | [.github/workflows/frontend-ci.yml](../../../.github/workflows/frontend-ci.yml) | PR 只有前端 quality，没有 backend/Ruff/Alembic/Compose gate | 新 workflow/job 有固定 check 名称；仓库管理员实际配置 required checks、CODEOWNERS 和 latest-push approval；PR 必须同时通过后端、迁移、配置和前端检查 |

### 3.2 隐性风险

| 优先级 | 风险 | 位置 | 处理结果 |
| --- | --- | --- | --- |
| P1 | `APP_ENV=container` 未被识别为生产-like，可能允许 test delivery adapter 返回明文邀请 token | [backend/app/config.py:84](../../../backend/app/config.py:84)、[invitations.py:63](../../../backend/app/routers/invitations.py:63) | 将 `container` 视为生产环境或在生产 Compose 设置 `APP_ENV=production`；增加 fail-closed 测试 |
| P2 | 自定义 `VITE_API_BASE_URL` 时 refresh 请求写死 `/api/auth/refresh` | [web-platform/src/api/client.ts:111](../../../web-platform/src/api/client.ts:111) | 所有认证请求使用同一 base URL；增加自定义绝对 URL 和 401 retry 测试 |
| P2 | 组织切换先持久化 token，profile 失败后留下新 token+旧用户的部分状态 | [web-platform/src/components/AppLayout.tsx:242](../../../web-platform/src/components/AppLayout.tsx:242) | 使用旧快照和两阶段提交；失败恢复旧 session 并显示可重试错误 |
| P2 | Chat finalizer 在 completed 后的 history 重试失败时可能把已写入的 `completed`/`cancelled` 覆盖为 `failed` | [backend/app/routers/chat.py:266](../../../backend/app/routers/chat.py:266)、:273-287 | finalizer 使用终态保护或 CAS；补 history retry failure、重复 completion 和断流测试 |
| P2 | Chat 在 `_run_admission_lock`、数据库行锁和事务内执行 Playwright/link fetch、检索、embedding、provider 请求 | [backend/app/routers/chat.py:566](../../../backend/app/routers/chat.py:566)、:589 | 网络 I/O 移出 admission lock/长事务；并发 stop/scope/long-link 测试确认不会长期阻塞其他 chat |
| P2 | Knowledge 上传 `file.read()` 无应用级大小限制，且缺少 filename allowlist/content-type 校验；chat attachment 已有 10 MB 检查 | [backend/app/routers/knowledge.py:292](../../../backend/app/routers/knowledge.py:292)、[backend/app/routers/chat.py:80](../../../backend/app/routers/chat.py:80) | knowledge 流式计数、filename allowlist、content-type/魔数校验、413 响应；不重复修改已有 chat attachment 上限 |
| P2 | 公共链接抓取已有 host allowlist、解析后 global-IP 检查、手动 redirect 校验和 2 MB body 限制；剩余风险是解析与实际连接之间的 DNS rebinding TOCTOU，以及浏览器子资源 socket 绑定 | [backend/app/services/public_link_fetcher.py:161](../../../backend/app/services/public_link_fetcher.py:161)、:185-217、[public_link_fetcher.py:95](../../../backend/app/services/public_link_fetcher.py:95) | 以 resolver/transport/browser fixture 验证现有防护；对残余 TOCTOU 使用 egress proxy 或解析后按 IP 连接，不能把该模块描述为无 SSRF 防护 |
| P2 | DingTalk plugin 接受任意 API 返回 URL 且无 body 上限；权限探测可能有写副作用 | [deploy/hermes/plugins/dingtalk_documents/client.py](../../../deploy/hermes/plugins/dingtalk_documents/client.py) | 仅允许 HTTPS 和 approved DingTalk host，限制字节数；权限检查改为只读或明确单独授权 |
| P2 | Hermes `SOUL.md` 禁止 knowledge mode 工具，但配置和后端提示允许三个 DingTalk 只读工具 | [deploy/hermes/SOUL.md](../../../deploy/hermes/SOUL.md) | 建立单一策略源，明确只读工具、untrusted content 和禁止写操作 |
| P2 | 组织结构首次初始化无并发锁，可能重复创建 root/state | [backend/app/services/organization_structure.py:24](../../../backend/app/services/organization_structure.py:24) | DB upsert/唯一冲突重试或组织行锁；补并发初始化测试 |
| P2 | 用户/管理员列表未统一检查 membership expiry 和 user.is_active | [backend/app/routers/users.py:49](../../../backend/app/routers/users.py:49) | 列表和写操作统一状态规则；补过期、停用成员测试 |
| P2 | “记住我”字段没有影响 storage，实际始终使用 sessionStorage | [web-platform/src/stores/authStore.ts:63](../../../web-platform/src/stores/authStore.ts:63) | 删除无效选项或实现明确的 persistent storage；补刷新/退出测试 |
| P2 | 部分 E2E fixture 使用 localStorage，而真实 auth 使用 sessionStorage | `web-platform/tests/frontend-refactor-*.spec.ts` | 统一 fixture；禁止测试用错误 storage 伪造登录成功 |
| P2 | Mock 模式仍允许真实 chat API，不能被描述为完全离线 | [web-platform/src/api/client.ts:71](../../../web-platform/src/api/client.ts:71) | 明确 mock/real test profile；文档和 CI 不得混用结论 |

## 4. 执行原则

1. 每个改变业务行为的任务遵循 `RED -> GREEN -> focused regression -> full regression`。
2. 外部 HTTP、embedding、Hermes、SMTP、DingTalk 和 provider 调用必须使用 fixture/mock；真实调用只能在单独授权的 staging gate 发生。
3. 所有组织作用域从 `CurrentOrganizationContext + membership role` 派生；不能从请求体、用户名、`User.default_organization_id` 或 provider 返回值派生权限。
4. 外部 I/O 不得在数据库 row lock 或长事务内运行；写回使用短事务、CAS 和固定锁顺序。
5. 迁移前先备份；禁止在共享测试库或生产库直接实验。所有 migration roundtrip 使用一次性隔离数据库。
6. 每个阶段使用独立、可回滚的提交；不得使用 `git add -A`，只 stage 本任务声明的路径。
7. Refresh rotation 固定采用 persisted JTI 单次消费 + PostgreSQL row lock/conditional update；本计划不引入 token family 树。后续若要做 reuse detection/family revoke，必须另立安全 issue，不得在本修复中临时改变 token contract。

## 5. 分支与 PR 策略

### 5.1 基线分支

从执行前重新核对的 HEAD 创建隔离 worktree 或基线分支，不直接在维护者移交分支上堆积未审阅代码。当前执行基线是已推送的 `be19631`；若未来另有未推送计划提交，执行 agent 才需要显式以代码修复基线 `290f233` 创建分支，并把计划文件作为本地审阅资料：

```powershell
git fetch origin --prune
git switch codex/hermes-platform-integration
git pull --ff-only origin codex/hermes-platform-integration
git switch -c codex/pr1-blockers-base
```

`main` 保持不动。若 PR #1 在修复前已被合并，改从合并后的 `main` 创建同名新分支并记录新的 base SHA，不强推旧分支。

### 5.2 推荐拆分

| 顺序 | 建议提交/PR | 内容 | 依赖 |
| --- | --- | --- | --- |
| 1 | `fix(authz): atomic refresh rotation and guest grant reconciliation` | B1、B4、production-like guest guard、跨组织授权矩阵；**不修改 migration** | 基线分支 |
| 2 | `fix(db-deploy): dialect-safe RAG migration and worker contract` | B2、B3、B5、默认 secret/placeholder 校验、health/readiness | 1 |
| 3 | `fix(runtime): preserve chat terminal state and bound external work` | history retry finalizer、admission lock、knowledge upload、SSRF/DingTalk/policy | 2 |
| 4 | `fix(web): stabilize auth refresh and organization switching` | 前端 base URL、切换原子性、remember-me、LoginPage 临时 user、E2E fixture | 1、2 的 API 契约 |
| 5 | `ci: add backend migration and compose gates` | B6 workflow、OpenAPI check、migration jobs、placeholder scan | 1-4 的稳定测试 |
| 6 | `docs: refresh handoff and deployment evidence` | 更新移交指南 SHA、API、环境、验收记录 | 5 |

每个表格行对应一个 stacked PR，不是同一分支上的“并行提交”：

- PR-1 branch：`codex/pr1/security`，base 为 `codex/pr1-blockers-base`。
- PR-2 branch：`codex/pr1/db-deploy`，base 为 PR-1 合并后的 SHA；PR-2 才能修改 migration/Compose。
- PR-3 branch：`codex/pr1/runtime`，base 为 PR-2 合并后的 SHA。
- PR-4 branch：`codex/frontend/auth-contract`，base 为 PR-2 稳定 SHA；前端成员不必等待 runtime PR-3，除非使用其 API。
- PR-5/6 由维护者从全部前置 PR 的集成 SHA 创建。

若仓库不接受 stacked PR，退化为单个 `codex/pr1-blockers-repair` PR，但必须保留上述提交顺序和文件边界；不允许让 PR-1 与 PR-2 同时修改同一 migration 文件。

## 6. 分阶段实施任务

### Phase 0：冻结基线与问题复现

**目标：** 保证 agent 审阅和后续修复都使用同一个可复现状态。

- 记录 branch、HEAD、upstream、worktree、PR checks 和当前 OpenAPI SHA。
- 将当前移交指南的旧 SHA 更新计划列入收尾，但本阶段不改业务代码。
- 运行认证、邀请、RAG、chat、knowledge、frontend auth/org switch 的定向测试，保存 RED 证据。
- 确认 `backend/migrations/versions` 单一 head，确认没有未授权数据库连接。
- 输出 `docs/superpowers/checkpoints/2026-08-10-pr1-blockers-baseline.md`，包含命令、测试数量、已知失败和环境变量名，不包含 secret 值。

**通过条件：** 所有待修复问题至少有一个可重复失败测试或静态代码证据；未确认的 dirty 文件和外部环境均列为暂停项。

### Phase 1：认证、访客权限和部署密钥

**任务 1A：Refresh rotation。**

- 为 refresh token 查询加 row lock 或使用 `UPDATE ... WHERE revoked=false RETURNING`。
- 在同一事务内检查 expiry、user active、membership context，再写 revoked。
- 重复 refresh 返回明确认证错误，不泄露 token 是否存在。
- 增加 SQLite 单线程、过期、撤销、跨用户 token 测试；另建 PostgreSQL+asyncpg integration fixture/job，使用真实临时 PostgreSQL、两个独立连接和同一 refresh token 并发请求，明确断言一个 `200`、一个 `401`，且失败响应不含可用 access/refresh token。SQLite 通过不能替代 PostgreSQL 并发 gate。

**任务 1B：Guest grant 生命周期。**

- revoke membership 时失效该 guest 的所有 active grants，并记录非内容审计。
- re-invite 时按新资源集合重建 grants，禁止复用未审查的旧 grants。
- 验证 revoke -> old token -> re-invite narrower scope -> old resource 全部 403/404。

**任务 1B-Org：跨组织授权矩阵。**

- 为 organization members/roles、guest invitations/memberships、knowledge entries/grants、portal announcements/read state、dashboard layouts、work items/events、chat sessions/turns 和 skills/memory 各增加至少一条跨组织集成测试。
- 每个资源至少验证 owner organization 可读写、其他 organization 返回 403/404、过期/inactive membership 被拒绝、请求体伪造 `organization_id` 不改变授权结果。
- 该任务是 P1 安全门禁，不得只列在测试矩阵而没有实现 owner；它与任务 1A/1B 同属 PR-1。

**任务 1C：生产-like guest delivery。**

- 将 `container` 纳入 production-like 校验，或把 Compose 中的正式服务固定为 `APP_ENV=production`。
- production-like + external guests 时强制 SMTP adapter、allowlist、public base URL 和 sender 配置。
- test adapter 只能在明确 local/test profile 中返回 token。

**任务 1D：密钥契约。**

- 删除或在 production-like 环境拒绝 [config.py:18](../../../backend/app/config.py:18) 的 `development-only-change-me` 和 [config.py:66](../../../backend/app/config.py:66) 的 `admin123` 默认值；拒绝 `change-this`、`replace-with-*`、空值、过短值和固定默认值。
- `RAG_EMBEDDING_API_KEY`、embedding URL、`RAG_QUERY_AUDIT_HMAC_KEY` 的配置错误在启动前失败。
- `up.ps1`/`up.sh` 必须检查 `replace-with-*`，不能只检查 `change-this*`；启动脚本输出变量名和修复动作，不输出值。增加 config unit test 和 `.env.example` static scan。

**任务 1E：服务端 logout 决策（本 PR 明确延期）。**

- 本修复 PR 不新增 logout endpoint；当前 logout 语义固定为清理浏览器 session，refresh token 仍依赖单次 rotation、撤销和 expiry。
- 已创建安全 issue [#3](https://github.com/OneAsmallFish/agent-platform-system/issues/3)，owner 为 `OneAsmallFish`；必须在该 issue 中登记风险接受人、截止 release、stolen refresh token 的最大剩余有效期和“token 不可在服务端 logout 后继续刷新”的后续验收条件。Issue 未关闭或未获得明确风险接受前，不得把 PR 从 Draft 改为 Ready。
- 生产发布前若安全负责人不接受该残留风险，则必须另行实现 revoke-current/revoke-all，并将前端 logout 改为 best-effort server revoke 后再清理本地状态。

### Phase 2：RAG migration 与 worker 启动契约

**任务 2A：Dialect-safe migration。**

- 移除 migration 模块级无条件 `pgvector` import；SQLite 执行 `alembic check`/`upgrade` 时不能因 import 阶段加载 PostgreSQL 类型而失败。PostgreSQL 分支才注册 Vector 类型。
- `CREATE EXTENSION vector` 只在 PostgreSQL 执行。
- `embedding` 使用 `Vector(1024)` with SQLite JSON variant。
- FTS、HNSW、PostgreSQL operator class 只在 PostgreSQL 创建。
- downgrade 必须显式删除索引/表，不能留下部分 schema。

**任务 2B：Migration matrix。**

- fresh SQLite：`alembic upgrade head`、创建/写入/查询 KnowledgeChunk。
- fresh PostgreSQL+pgvector：upgrade、检查 extension、column type、GIN/HNSW、查询计划。
- existing Phase C fixture：upgrade 不破坏已有 organization、membership、knowledge grant。
- `alembic check` 和 export OpenAPI 均必须通过。
- 新增只读的 `backend/scripts/assert_migration_schema.py`，按 dialect 检查 extension、column type、index/predicate 和关键表；脚本只能读取一次性数据库，不执行 seed 或业务写入。
- 远端 `migration / postgres` 首次运行（run `31369518221`）已确认 `20260731_0006` 的 `KeyError: manager`；对应 [Issue #5](https://github.com/OneAsmallFish/agent-platform-system/issues/5)，在 Issue #5 关闭前不得把 PostgreSQL migration gate 标记为通过。

隔离命令必须显式设置 `DATABASE_URL`，不得依赖当前 `.env` 或 `alembic.ini` 默认值：

```powershell
# SQLite migration smoke；只使用一次性文件，命令结束后删除 .runtime/migration.sqlite
New-Item -ItemType Directory -Force .runtime | Out-Null
$sqlitePath = Join-Path (Resolve-Path .runtime) "migration.sqlite"
$env:DATABASE_URL = "sqlite+aiosqlite:///$($sqlitePath.Replace('\','/'))"
Remove-Item .runtime/migration.sqlite -Force -ErrorAction SilentlyContinue
Push-Location backend
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\python.exe scripts\assert_migration_schema.py --dialect sqlite
Pop-Location

# PostgreSQL+pgvector migration smoke；仅允许使用临时 Compose project/db
$env:DATABASE_URL = "postgresql+asyncpg://migration_user:migration_password@127.0.0.1:55432/migration_db"
docker run -d --name pr1-pgvector -e POSTGRES_USER=migration_user `
  -e POSTGRES_PASSWORD=migration_password -e POSTGRES_DB=migration_db `
  -p 55432:5432 pgvector/pgvector:pg16
docker exec pr1-pgvector sh -c 'until pg_isready -U migration_user -d migration_db; do sleep 1; done'
Push-Location backend
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\python.exe scripts\assert_migration_schema.py --dialect postgresql
.\.venv\Scripts\alembic.exe downgrade 20260727_0004
.\.venv\Scripts\alembic.exe upgrade head
Pop-Location
docker rm -f pr1-pgvector
```

上面的 PostgreSQL 命令只作为一次性隔离环境示例；实际 CI 使用 service container 和随机数据库名，不能连接部署目录的数据库、共享测试库或生产库。任何 migration roundtrip 失败都必须保留日志并停止后续任务。

**任务 2C：Worker lifecycle。**

- 固定配置名为 `RAG_EMBEDDING_ENABLED`，默认值为 `false`（local/CI FTS-only）；staging/production-like 环境必须显式设置为 `true`，除非有带 owner 和期限的风险接受记录。
- `false` 的语义是 Compose 不启动 `rag-worker` profile，API 将查询 embedding 标记为 `disabled` 并使用授权后的 FTS-only fallback；不得伪造 vector 结果，也不得访问外部 embedding provider。
- `true` 的语义是启动 `rag-worker`；缺 `RAG_EMBEDDING_API_KEY`、URL 或 query token 时 worker 在启动阶段退出，API readiness 返回 503。
- `/health` 保持 liveness，仅返回进程可响应；新增 `/ready` 返回 `200` 和 `{"status":"ready","database":"ready","rag_worker":"ready|disabled"}`，数据库不可用或 enabled worker 不可达时返回 503，并包含非 secret 的 `components` 状态。
- Compose API healthcheck 改为 `/ready`；enabled profile 使用 `depends_on.rag-worker.condition=service_healthy`，disabled profile 不声明 worker 依赖；web 继续依赖 API `/ready`。staging 验收必须分别打 `/health`、`/ready`、`rag-worker:8091/health`，并验证 worker crashloop 时 API `/health=200`、`/ready=503`、web 不报告 ready。
- `.env.example`、`up.ps1`、`up.sh`、compose profiles、settings validator、API fallback 和 tests 必须同时使用该唯一配置名；不能保留“或等价开关”的实现分歧。
- 实施前执行 `rg -n "RAG_EMBEDDING_ENABLED|RAG_EMBEDDING_API_KEY|rag-worker|/ready" backend deploy .github`，将所有旧拓扑引用列入变更清单；命中仍依赖旧无开关语义的文件必须在同一 PR 修正或明确列入延期 issue。

### Phase 3：Chat、Knowledge 和网络边界

**任务 3A：终态保护。**

- finalizer 只能把仍处于运行态的 turn 更新为 `completed/failed/interrupted`；已写入的 `completed`、`cancelled` 或其他终态不可被后续 history retry failure 覆盖为 `failed`。
- 使用终态保护或 CAS，并保留 `assistant_message_id` 的一致性；不要引入代码中不存在的 `stopped`/`denied` turn status。
- 增加 history retry failure-after-completed、cancelled-after-stream、重复 completion 和断流测试。

**任务 3B：事务与外部 I/O。**

- `_run_admission_lock` 和数据库 row lock 只覆盖读取必要状态、配额检查和 run ownership；在锁外执行 Playwright/link fetch、retrieval、embedding/provider 调用。
- 外部调用结束后重新打开短事务，以 CAS 方式写回。
- 为每个外部阶段配置独立 timeout、总预算和取消信号。
- 增加最长 12+ 秒 collaboration URL 渲染期间的 stop、scope 变更、并发 session 测试，证明一个长请求不会阻塞其他 session 的 admission。

**任务 3C：输入和响应上限。**

- 固定并写入配置/文档的上限：knowledge multipart `50 MiB`（与 Nginx `client_max_body_size 50m` 对齐）、chat attachment `10 MiB`、knowledge content `200,000` UTF-8 字符、work item description `20,000` 字符、announcement content `100,000` 字符、skill content `50,000` 字符、DingTalk response body `10 MiB`，DingTalk 返回文本最多 `40,000` 字符。
- upload 和 attachment 采用流式读取并累计 UTF-8 bytes；超限返回 HTTP `413`、error code `payload_too_large`。JSON schema 字段超限返回 HTTP `422`、error code `content_too_large`；多字节字符必须有边界测试。
- Nginx 作为外层 50 MiB 限制，API 对具体业务类型使用更小上限；不得让代理或 provider 接受大于 API 的 body。已有超限记录允许读取和导出，但更新必须重新满足上限；本计划不做未经批准的数据截断迁移。
- Knowledge filename 只允许安全 basename 和当前 parser 支持的 `.pdf`、`.docx`、`.xlsx`、`.pptx`、`.txt`、`.md`、`.html`、`.csv` 扩展名；content-type 必须与文件魔数/解析器一致，未知或冲突类型返回 `content_type_not_allowed`，不得仅信任浏览器上传的 `Content-Type`。
- 每个上限都要有配置名、默认值和测试 fixture，避免执行 agent 自行选择数值。

**任务 3D：SSRF 与 DingTalk。**

- 解析 URL 后拒绝 loopback、link-local、private、特殊 scheme 和未允许域名；每次 redirect 重新解析和校验，优先使用 egress proxy 或固定 IP 连接。
- 先用 provider fixture 盘点 DingTalk `resourceUrls` 的 API host、签名 CDN host、region host、过期时间和签名字段，再将 inventory 固化为 `DINGTALK_ALLOWED_RESOURCE_HOSTS` 配置；默认空 allowlist 即拒绝，不能简单硬编码为 `api.dingtalk.com`，也不能接受任意 API 返回 host。
- signed URL 必须满足 HTTPS、host 在 inventory、签名/expiry 验证通过、解析 IP 为 global、redirect 每跳重新校验和 body 不超过 `10 MiB`。provider fixture 覆盖批准 CDN、未批准域名、私网 IP、过期签名、超大 body。
- SSRF 使用 deterministic resolver/HTTP transport fixture 覆盖 loopback/link-local/private/global、DNS rebinding 和 redirect；浏览器 route fixture 单独验证私网子资源，不将普通 `httpx.MockTransport` 结果误称为真实浏览器 DNS 证明。
- DNS rebinding 修复必须在 socket 层绑定已验证 IP，或通过 egress proxy 让代理执行同一 allowlist；仅在连接前调用一次 `getaddrinfo` 不算通过。HTTPS 连接必须保留正确 Host/SNI，测试需证明实际连接地址属于已验证集合。
- 权限探测必须无写副作用，或从 read-only tool 列表中移除并单独审批。

### Phase 4：前端状态与 API 交接

**任务 4A：统一认证 client。**

- `refreshAccessToken()` 必须复用 axios client 的 base URL、headers 和 single-flight 逻辑。
- 自定义绝对 URL、路径前缀、401 重试一次、refresh 失败清理状态均有测试；同步更新 `auth.contract.test.ts:226`，不能继续固化错误的 `/api/auth/refresh` bare-axios 请求。

**任务 4B：组织切换两阶段提交。**

- 保存旧 auth snapshot。
- 请求 switch token 后先 fetch profile 和组织权限。
- profile 成功才一次性写入 store；失败恢复旧 snapshot 并显示错误。
- 增加网络失败、403、旧 token 保持可用和刷新页面测试。
- LoginPage 不得在 profile 返回前用 `String(username)` 写入临时 user；先保留 pending auth，profile 成功后一次性提交真实 user，401/refresh 竞态失败时 store 不得出现假 user id。

**任务 4C：Storage 与 E2E。**

- 明确 remember-me 设计：实现 persistent storage，或删除无效 checkbox。
- 所有 E2E fixture 与真实 auth storage 统一，禁止 local/session 混用。
- Mock 模式和 real mode 使用不同 CI profile，文档中明确真实 chat 不属于完全离线 mock。

**任务 4D：策略文档。**

- 统一 `SOUL.md`、knowledge config 和 `chat_context` 的 DingTalk 只读工具范围。
- 明确 retrieved content 是 untrusted data，不得覆盖系统指令或触发写操作。

### Phase 5：CI/CD 与部署验收

**任务 5A：Backend CI。**

- 安装 `backend/requirements-dev.txt`。
- 执行 Ruff、pytest、OpenAPI snapshot check、Alembic heads/check。
- 认证、邀请、RAG、chat、SSRF 测试必须是 required subset。
- 修改 `backend/scripts/export_openapi.py` 支持 `--output` 和 `--check`；`--check` 在临时文件中生成规范化 JSON，与 tracked `backend/docs/openapi.json` 比较，漂移返回非零且不修改工作区。CI 不得只运行会覆盖 snapshot 的无参数 export。snapshot 更新只能由后端 API PR 明确提交，并在 PR 描述中附 operation diff。

**任务 5B：Migration CI。**

- SQLite job：为每次 job 创建随机 `.runtime/migration-<run_id>.sqlite`，设置 `DATABASE_URL` 后执行 fresh DB upgrade、schema smoke、selected CRUD，结束后删除文件。
- PostgreSQL+pgvector job：使用 `pgvector/pgvector:pg16` service container 和随机数据库/用户名，显式写入 `DATABASE_URL`，执行 fresh DB upgrade、extension/index/type assertions 和 upgrade/downgrade/upgrade；job 结束销毁 service 和数据库。
- 两个 job 都禁止读取 deploy `.env`、共享测试库或生产库；CI 日志不得打印完整连接串、密码或 secret。

**任务 5C：Compose/config CI。**

- static job 使用无 secret fixture 只运行 `docker compose --env-file .env.ci -f deploy/compose.yaml config --quiet`、placeholder scan 和 workflow path scan；不能因缺少 provider secret 启动真实容器。
- integration/staging-only job 在明确 Environment secret 和 Docker runner 上运行 `docker compose ... up -d --build --wait`，只在 `RAG_EMBEDDING_ENABLED=true` 且 embedding/HMAC/JWT 等值已注入时启动 worker；清理使用独立 Compose project，不接入生产卷。
- 静态扫描使用仓库脚本 `backend/scripts/validate_deploy_config.py --env-file deploy/.env.ci --mode ci`，拒绝 `.env`、JWT、SMTP、HMAC、embedding 的占位值，并由 `backend/tests/test_deploy_startup_scripts.py` 覆盖 `change-this*`、`replace-with-*`、空值和代码默认 secret。
- Compose health 必须覆盖 db、api `/health`、api `/ready`、enabled rag-worker `:8091/health`、web；启动失败时采集 logs，并验证 worker crashloop 时 `/health=200`、`/ready=503` 的分层语义。

**任务 5D：Frontend CI。**

- 保留 `npm ci`、audit、lint、串行 Vitest、real-mode build。
- 增加 API client/org switch contract tests。
- Playwright 只在 staging 或明确 mock fixture 中运行，不上传 auth state、token 或真实数据。

**任务 5E：GitHub branch protection 实际启用。**

- 新增 workflow 后先运行一次，固定 check 名称：`frontend / quality`、`backend / test`、`migration / sqlite`、`migration / postgres`、`compose / config`。
- workflow paths 必须覆盖 `backend/**`、`web-platform/**`、`deploy/**`、`.github/workflows/**`、OpenAPI/迁移/CI 脚本；backend-only、migration-only、workflow-only PR 各做一次触发验证。
- 仓库管理员由 GitHub Settings/Ruleset owner 负责把上述 checks 加入 `main` required status checks，并启用至少一名 reviewer、CODEOWNERS review、latest-push approval 和 resolved conversations；workflow YAML 本身不会自动完成这些设置。
- 用 GitHub PR API 或 `gh api repos/OneAsmallFish/agent-platform-system/branches/main/protection` 保存不含 secret 的配置证据；证据必须包含 check 名、branch、更新时间和管理员确认人。
- 该外部动作的 owner 固定为仓库管理员/维护者 `OneAsmallFish`，时间窗为“新 workflow 首次运行后、PR 从 Draft 改为 Ready 之前”。已创建 [Issue #4](https://github.com/OneAsmallFish/agent-platform-system/issues/4)；没有该 issue 的 check 运行记录、管理员确认人和 API evidence 时，B6 只能标记为“技术部分完成”，不能标记为合并通过。

### Phase 6：发布、交接与文档收尾

- 更新 [frontend-handoff-guide.md](../../frontend-handoff-guide.md) 的 branch/SHA、required checks、API 快照和已修复阻塞项。
- 输出一份不含 secret 的 staging 验收记录：commit SHA、image digest、容器 ID、health、迁移记录、测试数量、失败重试。
- 前端成员从后端修复已合并的稳定 SHA 创建 `codex/frontend/<issue>-<slug>`，不从旧 PR head 开始。
- PR 模板必须包含 API operationId、组织权限、错误契约、桌面/390px 截图、命令和回滚方式。
- 合并前由维护者确认 CODEOWNERS、latest push approval、conversation resolution 和 required checks。

## 7. 测试与验收矩阵

| 范围 | 必测内容 | 最低通过条件 |
| --- | --- | --- |
| Auth | refresh rotation、expiry、revoked、并发双请求、logout policy | SQLite 基础测试通过；PostgreSQL integration job 中并发只允许一个成功，旧 token 不可再次刷新 |
| Authorization | guest revoke/reinvite、跨组织、expiry、inactive user | 不恢复旧 grant；跨组织只返回 403/404 |
| Migration | SQLite、PostgreSQL+pgvector、upgrade/downgrade/upgrade | 无 extension/type/index 方言错误，单 head |
| RAG | worker config、embedding proxy、HMAC、`/health`、`/ready`、worker health | 无 placeholder；enabled 配置错误明确 fail-fast；disabled 明确 FTS-only；worker crashloop 时 `/health=200`、`/ready=503` |
| Chat | history retry finalizer、completed/cancelled 终态、断流、长 I/O、取消 | 终态不可覆盖，admission lock/DB lock 不跨越外部请求 |
| Network | SSRF、redirect、DNS rebinding、DingTalk URL/body | 私网和未批准域名拒绝，超限返回明确错误 |
| Frontend | custom base URL、401 retry、org switch rollback、storage | 无 partial auth state；E2E storage 与运行时一致 |
| CI/CD | backend/frontend/config/migration/health、branch protection evidence | required checks 全绿且可复现；管理员配置证据完整 |

本地建议命令：

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check app tests
.\.venv\Scripts\alembic.exe check
.\.venv\Scripts\python.exe scripts\export_openapi.py

cd ..\web-platform
npm ci
npm audit --omit=dev --audit-level=high
npm run lint
$env:VITE_USE_MOCK='true'; npm run test:ci
$env:VITE_USE_MOCK='false'; npm run build

cd ..\deploy
docker compose --env-file .env -f compose.yaml config
docker compose --env-file .env -f compose.yaml up -d --build --wait
docker compose --env-file .env -f compose.yaml ps
docker compose --env-file .env -f compose.yaml logs --no-color api rag-worker web
```

真实 staging 验收必须额外记录 `/health`、`/docs`、登录、组织切换、chat SSE、knowledge upload/preview/download 和 guest revoke/reinvite；没有授权不得把 staging 结果描述为生产结果。

## 8. 暂停、回滚和升级条件

### 8.1 必须暂停

- 任一 P1 测试失败或出现 flaky 且无法定位。
- migration 在任一目标 dialect 失败，或没有完成数据库备份。
- guest 缩权、跨组织隔离、refresh 单次旋转出现回归。
- RAG worker crashloop、HMAC/embedding 仍接受占位值。
- 外部 URL allowlist 无法证明阻断私网、重定向或 DNS rebinding。
- CI required check 尚未启用，或测试依赖未提交文件/本地 secret 才能通过。

### 8.2 回滚方式

- 应用代码：恢复到最后一个已验收的 commit/image digest，使用 PR revert，不强推公共分支。
- 数据库：使用迁移前的 `pg_dump --format=custom` 和恢复演练；禁止只执行 downgrade 后宣称恢复完成。
- 配置：恢复上一份经审阅的环境变量版本，立即轮换已暴露或疑似暴露的 HMAC/JWT/SMTP/embedding secret。
- 前端：回滚到前一 artifact；确认浏览器缓存不会继续引用不兼容的 API base URL。

### 8.3 允许继续

只有在所有 P1、相关 P2、定向测试、全量测试、迁移矩阵、Compose health 和 reviewer checklist 全部通过后，才能把 PR 从 Draft 改为 Ready for review。

## 9. Agent 审阅清单

请审阅 agent 重点回答以下问题，并把结论写入 PR review 或本计划的附录：

- 是否遗漏了任何会导致跨组织读取、guest grant 恢复或 token 重放的路径？
- B1-B6 的验收是否都有可自动化的 RED/GREEN 测试，而不是仅靠人工检查？
- SQLite 与 PostgreSQL 的 migration 是否能在同一个 clean checkout 中复现？
- worker、API、web 的 health 是否会正确反映依赖服务失败，而不是只报告容器进程存在？
- Chat finalizer、completed/cancelled、disconnect 的状态机是否存在其他覆盖顺序？
- 外部 URL、DingTalk signed URL、redirect、响应体和权限探测是否存在绕过点？
- 前端 refresh、组织切换、remember-me、E2E fixture 是否会留下不一致 session？
- CI 是否真正阻止 backend、migration、secret placeholder 和 Compose 配置回归？
- 是否有不必要扩大范围的任务，应延期到单独 PR？

Agent 审阅完成后，维护者只根据已确认的 findings 修改本计划；未被证据支持的“顺手重构”不得进入执行范围。

## 10. Definition of Done

- [ ] B1-B6 全部关闭，并有对应测试或部署证据。
- [ ] P1 隐性风险全部关闭；跨组织授权、guest grant、token replay、SSRF、DingTalk 任意 URL 等安全项不得仅以“后续处理”通过。
- [ ] 每个延期的 P2 都有 issue URL/ID、owner、截止日期或 release、影响范围、复验条件和维护者/安全负责人明确风险接受；当前 logout 延期对应 Issue #3，没有这些字段的延期项视为未完成。
- [ ] backend、frontend、migration、Compose required checks 全部通过。
- [ ] B6 的技术 gate 与治理 gate 分开记录：workflow/job 全绿，以及 [Issue #4](https://github.com/OneAsmallFish/agent-platform-system/issues/4)、管理员确认人和 API evidence 全部存在。
- [ ] OpenAPI 快照、前端 service/types、handoff guide 与实际代码一致。
- [ ] 跨组织授权矩阵和 guest grant 缩权测试覆盖所有声明资源类型。
- [ ] staging 验收记录完整且不含 secret、token、真实数据。
- [ ] PR review、latest push approval、conversation resolution 和 CODEOWNERS 均完成。
- [ ] 计划文档及其审阅修订已先以独立提交提交，再重新执行 `git status --short` 并确认为空；提交闭包只包含声明路径。
- [ ] 前端成员收到稳定 SHA、API 文档、测试账号/非生产地址、分支规则和回滚方式。

## 11. 本轮四 agent 审阅修订记录

- 已修正 guest revoke/accept 的代码位置、chat finalizer 实际终态、chat attachment 已有 10 MB guard、RAG empty-string credential bypass，以及 public-link fetch 的实际防护与 DNS TOCTOU 缺口。
- 已将 PostgreSQL 并发 refresh、SQLite 模块级 pgvector import、默认 secret、`replace-with-*` 启动脚本绕过、OpenAPI contract test、LoginPage 临时 user、knowledge filename/content-type 校验和 admission lock 内 Playwright 纳入任务。
- 已将跨组织授权矩阵升为 Phase 1 P1 任务；logout 改为明确延期并要求安全 issue/owner/期限；PR 拆分改为 stacked branch，禁止 migration 文件并行冲突。
- B6 的 required checks 仍依赖仓库管理员外部动作，计划已固定 owner、时间窗、issue 记录和 API evidence；在这些证据出现前，不得宣称 B6 完成。
- B6 治理 gate 已完成：`main` protection API 已回读确认五个 required checks、strict、1 approval、CODEOWNERS、latest-push approval、conversation resolution 和 admin enforcement；[Issue #4](https://github.com/OneAsmallFish/agent-platform-system/issues/4) 已于 2026-08-10 关闭。
- 已验证的远端 gate evidence（workflow commit `be19631`；后续 docs-only commits 会重新触发同一 workflow family）：run `31370057001` 的 `frontend / quality` 与 run `31370057254` 的 `compose / config` 通过；run `31370056999` 的 backend 仅因 OpenAPI snapshot drift 失败；run `31370057079` 的 SQLite 因 `CREATE EXTENSION vector`、PostgreSQL 因 `KeyError: manager` 失败。上述失败均保留为阻塞证据，不得通过修改 workflow 将其软化；执行时以当前 PR Checks 为准。

## 12. 本轮执行记录（2026-08-10）

- 已完成认证与访客授权修复：PostgreSQL refresh 查询使用 persisted JTI 行锁；guest revoke 会撤销该 membership 的未撤销 `KnowledgeAccessGrant`；container/production-like 默认 JWT、管理员密码和查询审计 HMAC 占位值 fail closed。
- 已完成 migration/RAG 修复：RAG migration 按 dialect 创建 Vector、extension、FTS/HNSW；identity migration 对角色和权限 seed 幂等；新增 `20260810_0012` 对齐历史可空时间列、refresh token organization 外键和幂等索引；SQLite fresh upgrade、downgrade/upgrade、schema assertion、`alembic check` 已通过。
- 已完成 worker contract：`RAG_EMBEDDING_ENABLED=false` 为 FTS-only 且默认不启动 `rag` profile；enabled worker 缺 provider/proxy secret 时启动失败；API `/health` 保持 liveness，`/ready` 聚合数据库和 worker；Compose/API/Web healthcheck 使用 `/ready`。
- 已完成 Chat/输入/外部 URL 修复：终态 turn 不可被 history retry 覆盖；admission marker 将 retrieval/provider 调用移出全局锁；stop/approval/delete 使用两段短事务；knowledge upload 流式限制 50 MiB、扩展名和魔数；DingTalk signed resource 仅允许配置的 HTTPS host 且响应不超过 10 MiB。
- 已完成前端 auth/org 修复：refresh URL 使用配置的 API base；显式新 token 不再被旧 store token 覆盖；组织切换在新 token 下 profile 成功后才提交；移除无效 remember-me；Playwright auth fixture 统一使用 `sessionStorage`。
- 本地证据：backend `261 passed`、Ruff 通过；frontend Vitest `231 passed`、lint 通过、生产 build 通过；OpenAPI snapshot 88 paths 且 `--check` 通过；DingTalk plugin tests `10 passed`。
- 远端 required checks 已在提交 `0405518` 上重新验证：`config` run `31383559920`、`postgres/sqlite` run `31383559931`、`quality` run `31383560000`、`test` run `31383559932` 全部通过；本机仍没有 Docker，因此 Compose 容器级运行和 staging health 仍需在具备环境后单独验收。PR review、latest-push approval 和 conversation resolution 仍是合并前人工门禁。

## 13. Issue #3/#5 执行记录（2026-08-10）

- Issue #3 已实现“撤销当前 refresh token”契约：`POST /api/auth/logout` 接收当前 refresh token，使用 persisted JTI 行锁校验 user/organization 绑定，幂等返回 `204`，不泄露 token 是否存在；不提供 revoke-all 语义。
- 前端退出登录会在清理 sessionStorage 前 best-effort 调用 `/auth/logout`；网络或服务失败时仍在 `finally` 清理本地 access/refresh token，不记录 token 或错误详情。
- logout revoke 请求使用独立 3 秒超时，避免服务不可达时被通用 API 30 秒超时拖住本地退出。
- Issue #3 定向证据：后端覆盖当前 token 撤销、重复撤销、跨用户保留和跨组织保留；前端覆盖成功撤销及服务不可用时的本地清理；新增 OpenAPI 路径并完成 snapshot check。
- Issue #5 已验证：Phase B identity migration 在缺少任何角色的 fresh legacy schema 上先创建 `admin/manager/user/guest`，再按权限码建立 role links；重复执行 seed 不产生重复链接。迁移测试、fresh SQLite upgrade/check 和远端 PostgreSQL migration job 均已在 `0405518` 上通过。
