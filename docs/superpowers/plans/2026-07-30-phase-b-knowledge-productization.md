# 阶段 B：知识产品化、共享治理与外部访客 Implementation Plan

> 设计依据：`docs/superpowers/specs/2026-07-30-phase-b-knowledge-productization-design.md`

**Goal:** 在现有知识库入口内完成真实前后端契约、内部只读共享、知识运营和邀请制 guest 试点，同时保持平台自有 RAG、组织隔离和 tool-less knowledge gateway 边界。

**Architecture:** 以 token organization context 和 membership role 作为请求身份；以统一授权资源 repository 解析 owner、组织成员可见和显式 grant；以 session surface/scope 驱动服务端知识检索；以平台 turn/citation 表补充 Hermes history；以脱敏 event/audit 聚合支撑运营。B0--B2 先行，B3 默认功能开关关闭。

**Tech Stack:** FastAPI、SQLAlchemy async、Alembic、PostgreSQL 16/pgvector、React 19、Arco Design、Zustand、Vite/Vitest、Playwright、Docker Compose。

**Do not:** 不新增侧边栏助手，不恢复 `chatStore.ts`，不创建匿名分享链接，不把 provider key/对象 key/正文写入 API、SSE、审计或日志，不执行生产迁移。

---

## Task 1：冻结契约并建立 B0 失败测试

**Files:**
- Modify: `backend/tests/test_organization_authz.py`
- Modify: `backend/tests/test_chat_knowledge_context.py`
- Modify: `backend/tests/test_knowledge_retrieval.py`
- Modify: `web-platform/src/api/chat.contract.test.ts`
- Create: `web-platform/src/api/knowledge.contract.test.ts`
- Modify: `web-platform/src/stores/__tests__/assistantStore.test.ts`

- [x] **Step 1:** 写后端失败测试：token organization 与 membership 不一致拒绝；inactive organization 拒绝；角色只读 membership；最后 admin 不能被停用或降级。
- [x] **Step 2:** 写 session 失败测试：`surface=agent|knowledge` 列表隔离；guest 禁止 agent；`none|all_visible|selected` 三态；active run 修改 scope 返回 409。
- [x] **Step 3:** 写 citation 失败测试：SSE `knowledge.context`、history 结构化 citations、刷新保持、资源撤销后 resolve 404。
- [x] **Step 4:** 写前端真实 contract 测试，固定现有 `/api/knowledge`、ingestion、chat surface/scope 请求；明确旧 `/knowledge/sources` 不属于真实 API。
- [x] **Step 5:** 运行定向 pytest/Vitest，记录预期失败，不修改生产代码绕过测试。

## Task 2：组织上下文与角色安全修正

**Files:**
- Modify: `backend/app/auth/security.py`, `backend/app/auth/dependencies.py`
- Modify: `backend/app/routers/auth.py`, `backend/app/routers/users.py`
- Modify: `backend/app/routers/chat.py`, `knowledge.py`, `memory.py`, `skills.py`, `reminders.py`
- Modify: `backend/app/schemas/auth.py`, `backend/app/schemas/users.py`
- Modify: `backend/app/models/entities.py`, `backend/app/seed.py`, `backend/app/services/hermes_manager.py`
- Create: `backend/alembic/versions/*_phase_b_identity_context.py`
- Modify: `web-platform/src/stores/authStore.ts`, `web-platform/src/api/services/auth.ts`

- [x] **Step 1:** access/refresh token 写入 `organization_id`；`CurrentOrganizationContext` 每次校验 user、organization、membership active/expiry，授权 role 只取 membership。
- [x] **Step 2:** 增加 memberships 列表和 switch-organization token pair endpoint；`default_organization_id` 只作为登录偏好。
- [x] **Step 3:** 修复 `/users` role 响应、更新自停用绕过和最后 admin 并发门禁；使用行锁事务。
- [x] **Step 4:** membership 增加 `member_type=internal|guest` 和可选 expiry；seed 固定 permission matrix 与 guest role。guest 不进入通用 UserCreate/RoleAssignment DTO，只能由关闭默认的 invitation service 创建。
- [x] **Step 5:** 将 chat/knowledge/memory/skills/reminders 的 `organization_id_for(user)` 全部替换为 request organization context；`rg 'organization_id_for\(' backend/app` 不得保留业务调用。
- [x] **Step 6:** `HermesProfile` 改为 organization+user 唯一，name/home/scope 含 organization；切换组织选择另一 profile，guest knowledge 不创建 profile 或 runner metadata。
- [x] **Step 7:** 前端每标签页把 active token pair/context 放 sessionStorage；refresh rotation tab-local，仅多 membership 用户显示切换器。
- [x] **Step 8:** identity migration 先检测 normalized email 冲突并 fail closed，不自动合并账号；revoke 全部旧 refresh token 并要求重登。运行 Task 1 identity、双 tab 不同 organization、完整 authz 与 migration 往返测试。

## Task 3：阶段 B schema 与统一授权资源 repository

**Files:**
- Modify: `backend/app/models/entities.py`, `backend/app/models/__init__.py`
- Create: `backend/alembic/versions/*_phase_b_knowledge_productization.py`
- Create: `backend/app/services/knowledge_authorization.py`
- Modify: `backend/app/services/knowledge_retrieval.py`
- Modify: `backend/app/routers/knowledge.py`

- [x] **Step 1:** 在 identity migration 之后增加 knowledge visibility/archive、access grant、invitation/resources、session source、turn/citation、audit 和 retrieval event additive 字段；所有默认值 fail closed。
- [x] **Step 2:** 迁移既有资源为 private；按 `hermes_backend` 回填 session surface；现有 knowledge session scope 显式回填 all_visible，agent scope 回填 none。
- [x] **Step 3:** 实现 `AuthorizedKnowledgeEntryRepository`，统一 list/detail/retrieve/citation/download 可见谓词。
- [x] **Step 4:** 修改 chunk 检索为授权 revision tuple `(organization, entry, owner, content_hash)`，不能以 caller user id 过滤共享 chunk。
- [x] **Step 5:** grant 通过 composite FK 引用同组织 entry/membership，active partial unique 且 revoke 后可 regrant；retrieval event 支持 nullable session、request_kind、mode/outcome 和 query HMAC version。
- [x] **Step 6:** 添加 owner、org member、explicit grant、guest、expired/revoked、跨组织、archive/restore/purge 和删除矩阵测试。
- [x] **Step 7:** 在隔离 PostgreSQL 16 + pgvector 执行 upgrade -> schema/index -> downgrade -> invariants -> upgrade；生产迁移仍需另行确认。

## Task 4：knowledge session surface、scope 与结构化 citation

**Files:**
- Modify: `backend/app/routers/chat.py`, `backend/app/schemas/chat.py`
- Modify: `backend/app/services/chat_context.py`, `backend/app/services/hermes_client.py`
- Modify: `backend/app/models/entities.py`
- Modify: `backend/tests/test_chat_knowledge_context.py`, `backend/tests/test_api.py`

- [x] **Step 1:** session create/list 增加 surface；服务端映射内部 backend，响应不暴露 backend，省略 surface 保持当前 knowledge 默认；agent surface 受额外权限约束。
- [x] **Step 2:** 实现 session scope endpoint 和 selected source relation；active run 时拒绝修改；每次 send 重新解析授权来源。
- [x] **Step 3:** 对固定 Hermes 做 live contract probe：重复 history 的 message id 必须稳定，terminal run 必须能关联唯一 assistant message；不通过则停止并修订设计，禁止“最新消息”或随机 UUID 猜测。
- [x] **Step 4:** 建立 chat turn/citation 行；run 创建后发 `knowledge.context`，只包含 citation metadata、mode 和 rejected count；仅持久化探针证明稳定的 upstream message id。
- [x] **Step 5:** history 返回 citations 和 retrieval mode；citation resolve 同时校验 turn -> owned knowledge session 和当前资源权限。
- [x] **Step 6:** `source_ids: list[int] | None`：省略/null 使用 session scope，显式空映射 legacy all_visible，显式非空映射单次 selected；新客户端不发送并记录弃用指标。
- [x] **Step 7:** 验证 agent/knowledge/guest、SSE、history、stop、delete、刷新、撤权 citation 和 runner cleanup。

## Task 5：内部只读共享与知识写审计

**Files:**
- Modify: `backend/app/routers/knowledge.py`
- Modify: `backend/app/schemas/knowledge.py`
- Modify: `backend/app/services/audit.py`
- Create: `backend/tests/test_knowledge_sharing.py`
- Modify: `backend/docs/api-integration-guide.md`

- [x] **Step 1:** 扩展资源 list/detail metadata：owner summary、visibility、access source、updated_at 和最新 ingestion status；增加 `view=mine|shared|organization`，shared/guest 的兼容 content 固定 null。
- [x] **Step 2:** 实现 access/grant CRUD；grant 引用同组织 membership，active partial unique，首版 capability 固定 read；权限表达固定为 `(owner AND knowledge:share) OR knowledge:govern`。
- [x] **Step 3:** owner-only update/ingest 保持；`knowledge:govern` 只允许治理动作，不允许正文修改或 owner 转移，grantee summary 最小化。
- [x] **Step 4:** `DELETE` 归档，增加 restore 和 archived-only purge；归档立即从所有读取/检索路径失效，purge 删除对象/chunk/grant。
- [x] **Step 5:** create/upload/update/archive/restore/purge/ingest/access/grant/download 写事务内审计，details 只包含 id、枚举和计数。
- [x] **Step 6:** 增加独立 preview/download DTO 和 endpoint，验证长度上限、文件名、nosniff、no-store、每次访问重新授权且不返回对象 key。
- [x] **Step 7:** 运行共享权限矩阵、历史 owner-only 回归、Ruff 和 OpenAPI snapshot。

## Task 6：retrieval event、运营与审计 API

**Files:**
- Modify: `backend/app/services/knowledge_retrieval.py`
- Modify: `backend/app/services/knowledge_ingestion.py`, `backend/app/workers/rag_ingestion.py`
- Modify: `backend/app/config.py`, `deploy/.env.example`, `deploy/compose.yaml`
- Create: `backend/app/routers/knowledge_operations.py`, `backend/app/routers/audit.py`
- Create: `backend/app/schemas/knowledge_operations.py`, `backend/app/schemas/audit.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_knowledge_operations.py`, `backend/tests/test_audit_api.py`

- [x] **Step 1:** 增加仅 API 注入的 `RAG_QUERY_AUDIT_HMAC_KEY`/version；每次 REST retrieve 和 knowledge chat 写 HMAC query id、request_kind、nullable session、mode、outcome、count、latency，不存 query/chunk/answer。
- [x] **Step 2:** 实现 overview、jobs、retry、cancel；queued 可立即 cancel，processing 进入 cancel_requested。worker 在发布 chunk/commit 前重新锁 job，取消时丢弃结果并置 cancelled。
- [x] **Step 3:** 实现 organization-scoped、cursor pagination 审计读取；过滤 action/resource/time/outcome。
- [x] **Step 4:** 测试没有 raw query、裸 SHA-256、正文、路径、token、provider error body；跨组织管理 id 统一 404，cancel 与 worker publish 竞态不能产生 ready/chunk。
- [x] **Step 5:** 对 100k/1M 容量数据验证聚合查询计划，不在请求路径执行全表正文扫描。

## Task 7：前端真实知识资源与 ingestion 状态机

**Files:**
- Modify: `web-platform/src/api/services/knowledge.ts`
- Modify: `web-platform/src/shared/types/knowledge.ts`, `knowledge-ext.ts`
- Modify: `web-platform/src/hooks/useKnowledgeSources.ts`, `useKnowledgeUpload.ts`
- Modify: `web-platform/src/pages/KnowledgePage.tsx`
- Modify: `web-platform/src/components/knowledge/KnowledgeSourceView.tsx`, `KnowledgeUpload.tsx`
- Create: `web-platform/src/components/knowledge/KnowledgeDetailDrawer.tsx`
- Modify/Create: related Vitest and contract tests

- [x] **Step 1:** 删除 real service 对不存在 `/knowledge/sources` 族 endpoint 的依赖；Mock adapter 与真实 canonical type 在 service 边界归一化。开发默认真实 API，Mock 只能显式启用且不能形成 Mock 资料/真实聊天的隐式混合态。
- [x] **Step 2:** 实现上传 -> create -> ingest -> poll 状态机，卸载/切页取消 poll，避免 stale response 覆盖新请求。
- [x] **Step 3:** 资源列表增加 mine/shared/organization、visibility、owner、ingestion status 和稳定操作尺寸。
- [x] **Step 4:** 实现 detail Drawer 四 tab；访问 tab 只在权限允许时请求完整 grants。移除 AIPanel 仅把文件名/链接拼进 prompt 的伪附件行为。
- [x] **Step 5:** 资源/AI 切换改为 `/knowledge` 与 `/knowledge/ai/:sessionId?`，修复嵌套 `100vh`；更新失效的 Knowledge AI Mock E2E，使测试定位实际 `AssistantView`；补 390/768/1024/1440 资源视图。

## Task 8：前端 knowledge AI scope 与 citation

**Files:**
- Modify: `web-platform/src/features/assistant/AssistantView.tsx`, `.module.css`
- Modify: `web-platform/src/stores/assistantStore.ts`
- Modify: `web-platform/src/api/services/chat.ts`, `chatStream.ts`
- Modify: `web-platform/src/shared/types/chat.ts`
- Create: `web-platform/src/components/knowledge/KnowledgeScopeControl.tsx`
- Create: `web-platform/src/components/knowledge/CitationList.tsx`
- Modify/Create: assistant store/component/Playwright tests

- [x] **Step 1:** store 按 surface 加载/创建 sessions；knowledge page 只显示 knowledge sessions，兼容 assistant route 只显示 agent sessions。
- [x] **Step 2:** 实现 scope segmented control、可搜索来源 Drawer、selected 持久化和 active run 锁定。
- [x] **Step 3:** 解析 `knowledge.context` SSE 并显示 retrieval mode/rejected count；history hydration 恢复结构化 citations。
- [x] **Step 4:** citation 点击重新授权；404 显示撤销/版本更新状态，不回显旧 chunk。
- [x] **Step 5:** guest 隐藏 approval/tool UI；测试 agent/knowledge session 不混合、停止/断连/刷新/长消息/用户手动滚动。
- [x] **Step 6:** 完成迁移后删除未接入的 `KnowledgeAIView`、`useAIQuery` 和 `knowledgeStore.aiSessions`，确保 `assistantStore` 是唯一会话/run 事实来源。

## Task 9：内部共享与运营 UI

**Files:**
- Modify: `web-platform/src/components/knowledge/KnowledgeNavigator.tsx`
- Create: `web-platform/src/components/knowledge/KnowledgeOperationsView.tsx`
- Create: `web-platform/src/api/services/knowledgeOperations.ts`, `audit.ts`
- Modify: resource detail access/activity tabs and organization management routes
- Modify/Create: related tests and responsive styles

- [x] **Step 1:** 增加 knowledge:ops 权限可见的运营视图，使用指标带、筛选表和 retry/cancel command；无正文展示。
- [x] **Step 2:** 完成 owner access/grant、govern 最小 member summary、资源 activity 和 audit filter UI；不向非 owner/govern 请求完整 grants。
- [x] **Step 3:** 390/768/1024/1440 验证长成员名/文件名、指标表、Drawer 单层、键盘和无水平溢出。
- [x] **Step 4:** 完成 B0--B2 全量后端/前端回归；只有本 Task 通过才进入 guest 实现。

## Task 10：邀请制 guest 后端与精简 UI（默认关闭）

**Files:**
- Modify: `backend/app/config.py`, `deploy/.env.example`, `deploy/compose.yaml`
- Create: `backend/app/routers/invitations.py`, `backend/app/schemas/invitations.py`
- Create: `backend/app/services/invitations.py`
- Create: `backend/tests/test_guest_invitations.py`, `backend/tests/test_guest_authorization.py`
- Create: `web-platform/src/api/services/invitations.ts`
- Modify: user/organization management page and routes
- Create: invitation acceptance page and guarded guest layout
- Modify/Create: related tests and responsive styles

- [x] **Step 1:** 确认 Task 1--9 已通过；增加 `FEATURE_EXTERNAL_GUESTS=false`，关闭时 guest 创建、邀请和接受 endpoint 全部 404，通用 user/role API 仍拒绝 guest。
- [x] **Step 2:** token 至少 256 bit 且只存 digest；token/membership expiry 分离；创建只返回一次明文，列表不返回 digest/token。
- [x] **Step 3:** URL fragment + body accept 且禁止 body logging；new email 可创建账号，existing email 必须认证同一账号，绝不重设密码。
- [x] **Step 4:** 单事务验证 invitation/resources，创建或重新激活 guest membership、转换 read grants、标记 accepted，并发只允许一个成功。
- [x] **Step 5:** guest 只允许显式 grant、knowledge surface 和受控 download；禁止 organization visibility、agent、上传、编辑、成员、运营、工具、HermesProfile 和 runner metadata。
- [x] **Step 6:** 成员管理增加邀请与状态；accept 页处理 invalid/expired/accepted；guest layout 只显示授权资源和 knowledge AI。
- [x] **Step 7:** 测试环境可复制 token；真实 guest 试点必须配置批准的 email/identity delivery adapter。测试账号接管、internal 不降级、active/expired/revoked guest、跨组织 existing user、限流和组织停用。
- [x] **Step 8:** 390/768/1024/1440 验证长 email、邀请状态、guest revoke fail closed、Drawer 单层和无水平溢出。

## Task 11：隔离部署与阶段门禁

**Files:**
- Modify: `backend/README.md`, `backend/docs/api-integration-guide.md`, `deploy/README.md`
- Create: `docs/superpowers/checkpoints/*_phase_b_test_deployment.md`
- Modify: this plan checkboxes only as evidence is completed

- [x] **Step 1:** 后端完整 pytest/Ruff、Alembic upgrade/downgrade；前端 build/lint/Vitest/Playwright 全通过。
- [x] **Step 2:** 测试服务器迁移前备份并隔离恢复；验证 B migration 往返和既有数据/权限 invariants。
- [x] **Step 3:** 双组织、多内部成员、guest、expired/revoked grant 矩阵验证 list/detail/retrieve/chat/citation/download。
- [x] **Step 4:** 同一浏览器两个独立 tab 使用不同 organization token family，并发 refresh/switch 不互相覆盖；旧 refresh token 全部失效。
- [x] **Step 5:** 真实浏览器执行 owner 上传 -> ready -> share -> grantee AI -> citation -> revoke -> 404；运营 retry/cancel；邀请 -> guest -> expiry。
- [x] **Step 6:** 验证 SSE/history/stop/delete、tool-less guest、无 provider/object key、审计脱敏、queued job/active run/temp user 清理。
- [x] **Step 7:** B0--B2 通过后才允许在测试环境打开 guest flag；真实 guest 还必须通过批准的 email/identity delivery 验证。生产迁移、正式邮件和外部互联网仍需再次明确授权。

## 实施提交建议

按 Task 1--2、Task 3--4、Task 5--6、Task 7--9、Task 10、Task 11 分成至少六个边界清晰的提交。每个提交只在对应测试通过后推送到当前 draft PR；不得把 `.superpowers/`、`.secret/`、runtime report、测试凭据或生产配置加入 Git。
