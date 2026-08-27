# Phase C 门户、工作台与组织运营实施计划

> 本计划以 TDD 执行。每个 Task 的 Step 1 必须先新增失败测试并实际看到失败，再实现最小修复；每个 Task 完成后运行定向测试和完整回归，更新 checkbox，创建边界清晰的提交并推送当前 draft PR。不得提交 `.superpowers/`、`.secret/`、runtime 报告、上传文件或凭据。

**Goal:** 在当前组织上下文和 Hermes/知识库能力之上，完成内部门户、工作台、组织架构和知识导航的真实业务闭环，并关闭三个 422 契约缺口。

**Do not:** 不打开 `FEATURE_EXTERNAL_GUESTS`，不配置正式 email/identity delivery，不创建匿名分享链接，不执行生产迁移；不复制 `E:\My_Opjects\qm` 源码，不替换 Hermes runtime，不恢复 `User.default_organization_id` 授权推导。

**Shared migration gate:** 本计划允许先写 migration 和在本地/隔离数据库验证，但在任何共享测试数据库应用 schema 前，必须先备份并获得明确确认；生产数据库、正式邮件和真实外部 guest 是独立门禁。

## Task 1：冻结真实 API 契约并修复知识导航 422

**Files:**

- Modify: `backend/app/models/entities.py`, `backend/app/schemas/knowledge.py`, `backend/app/routers/knowledge.py`
- Create: `backend/migrations/versions/20260803_0008_phase_c_knowledge_collections.py`
- Create: `web-platform/src/mock/handlers/memory.ts`, `web-platform/src/mock/handlers/skills.ts`
- Modify: `web-platform/src/mock/handlers/index.ts`, `web-platform/src/mock/index.ts`, `web-platform/src/mock/types.ts`, mock generators/seed
- Modify: `web-platform/src/api/services/knowledge.ts`, `web-platform/src/api/services/memory.ts`, `web-platform/src/api/services/skills.ts`, `web-platform/src/shared/types/memory.ts`, `web-platform/src/shared/types/skill.ts`, `web-platform/src/hooks/useKnowledgeSources.ts`, `web-platform/src/hooks/useKnowledgeSubmodules.ts`, `web-platform/src/components/knowledge/KnowledgeNavigator.tsx`, knowledge view/types as required
- Test: `backend/tests/test_knowledge_collections.py`, `backend/tests/test_memory_scope.py`, `backend/tests/test_skills_scope.py`, `web-platform/src/api/knowledge.contract.test.ts`, create `web-platform/src/api/memory.contract.test.ts` and `web-platform/src/api/skills.contract.test.ts`, `web-platform/src/api/services/services.test.ts`, `web-platform/src/hooks/__tests__/useKnowledgeSubmodules.test.tsx`, mock handler and relevant page tests

- [x] **Step 1: 先写失败契约测试。** 断言 real mode 下“知识库集合”不发送 `type=knowledge_base`、`knowledgeService.list` 会传 `collection_id`；记忆搜索统一调用 `list({query})` 并使用 `GET /memory?query=`，不请求不存在的 `/memory/search`；skills detail 使用整数 `/skills/{skill_id}`、update 使用 PUT、delete 接受 204。再增加 mock mode 红灯：`memoryService`/`skillsService` 必须被选为 `mockServices.memory/skills`，记忆/方法子模块能返回 mock 数据且不抛 `MockModeRequestError`，Axios adapter 不被调用。后端 collections 路由在当前 organization 返回 200，跨组织 token 不可读；运行后端定向 pytest 和前端定向 Vitest，记录红灯。
- [x] **Step 2: 按方案 A 建立独立 mock-aware canonical services。** 新增 memory/skills mock handlers 和 canonical DTO seed，注册 `mockServices.memory/skills`；`memory.ts`、`skills.ts` 分别用 `selectServiceImplementation` 包装完整 mock/real interface，`services.test.ts` 的 mode selection 矩阵同步扩展。memory interface 收束为 list(query)/get/create/update/delete，删除无 consumer 的虚假 search；skills interface 收束为 list/getById/create/update/generate/hub/delete，delete 返回 void。`useKnowledgeSubmodules` 改调这两个 service，停止调用 `knowledgeService.listMemories/listExperiences`；确认无 consumer 后删除旧方法并修正 deprecated 注释。real/mock 共用同一 DTO-to-view mapper，方法卡片只渲染真实 Skill 字段，不伪造 rating/steps。
- [x] **Step 3: 实现集合最小持久化契约。** 增加 collection 表、`knowledge_entries.collection_id`、`GET /knowledge?collection_id=` 和当前组织授权过滤；集合不是 access grant，移动仍复用 owner/govern 权限；新增非空删除 409、跨组织 404/403、空集合 200、集合不能扩大条目权限测试。
- [x] **Step 4: 在隔离 PostgreSQL 16 + pgvector 对 `20260803_0008` 执行 upgrade -> schema/data invariants -> downgrade -> upgrade。** 未通过不得进入 Task 2；共享测试环境仍不执行 migration。
- [x] **Step 5: 运行定向测试，确认三个入口不再 422，mock mode 不产生 `MockModeRequestError` 且 service registry 没有漏项；再运行 backend pytest、web Vitest、lint、build。** 只有 real service 和 mock service 都通过后才更新本 Task checkbox。

## Task 2：组织架构后端模型、权限与并发契约

**Files:**

- Create/Modify: `backend/app/models/entities.py`, `backend/app/schemas/organization.py`, `backend/app/routers/organization.py`, `backend/app/seed.py`, `backend/app/main.py`
- Create: `backend/migrations/versions/20260803_0009_phase_c_organization_structure.py`
- Test: `backend/tests/test_organization_structure.py`, `backend/tests/test_organization_scope_context.py`, migration roundtrip/permission tests

- [x] **Step 1: 先写失败测试。** 覆盖 root unit、同组织 unit/position/placement、guest 无 placement、跨组织引用拒绝、普通 user 只读、管理员增删改、unit 树环和 manager 链环拒绝、批量 placement 任一失败整批回滚、非空 unit 删除 409、旧 revision 409，以及 token 组织切换后读到不同结构；测试必须证明请求不会读取 `default_organization_id`。
- [x] **Step 2: 增加 additive schema、权限和 seed backfill。** 建立 units、positions、placements、structure state；现有组织创建 root，internal membership 建立兼容 placement，guest 不回填。复用并扩展现有 `org:admin` 描述；新增 `org:read`、`portal:read`、`portal:manage`、`work_items:read`、`work_items:write`，同时更新 `seed.py` 和 `20260803_0009` migration 中的 permission/role links，沿用 `0006` 的模式。
- [x] **Step 3: 实现结构 API。** 所有读写依赖 `CurrentOrganizationContext`；管理员写请求锁定 structure state、检查 revision 和同组织外键，校验 unit 树以及应用整批变更后的 manager 图无环；增加单条 PUT 和单事务 `POST /organization/placements/batch`，成功后统一递增 revision、写审计；响应只返回当前组织安全元数据。
- [x] **Step 4: 在隔离 PostgreSQL 16 + pgvector 执行 upgrade -> invariants -> downgrade -> upgrade。** 共享测试环境 migration 前暂停，先创建备份并请求用户确认；未确认前不得连接共享数据库执行迁移。
- [x] **Step 5: 运行 backend 全量回归和 Ruff/OpenAPI snapshot，更新 checkbox。**

## Task 3：组织架构页面、导航和管理员交互

**Files:**

- Modify: `web-platform/src/router/index.tsx`, `web-platform/src/components/AppLayout.tsx`, `web-platform/src/components/AppLayout.module.css`
- Create: `web-platform/src/pages/OrganizationStructurePage.tsx`, `OrganizationStructurePage.module.css`, `web-platform/src/api/services/organizationStructure.ts`
- Modify: `web-platform/src/pages/OrganizationMembersPage.tsx` 仅复用导航和权限入口，不重复实现 placement
- Test: sidebar/router/page/permission/responsive Vitest

- [x] **Step 1: 先写失败 UI 测试。** 覆盖展开/折叠侧边栏、`/organization/structure` 路由、guest 不显示、普通 user 只读、admin 显示编辑入口、树/成员/详情布局、409 冲突提示和移动端 Drawer。
- [x] **Step 2: 增加“组织架构”导航项和页面。** 桌面三栏、移动 drill-down；新增/编辑/移动/停用操作均使用图标按钮 + tooltip，破坏性操作要求确认，文本不溢出。
- [x] **Step 3: 接入 revision-aware service。** 编辑态加载最新结构，提交携带 expected_revision；409 保留草稿并提供刷新；成功后刷新树、成员计数和当前用户侧边栏职位。
- [x] **Step 4: 运行定向 Vitest、build/lint，并用 Browser 在 1440/1024/768/390 检查无水平溢出和无重叠。** 保留一个 Browser deliverable/handoff tab，不关闭最后 tab，不调用 `finalize({ keep: [] })`。

## Task 4：门户公告、待办和协作入口

**Files:**

- Create/Modify: `backend/app/models/entities.py`, `backend/app/schemas/portal.py`, `backend/app/routers/portal.py`
- Create: `backend/migrations/versions/20260803_0010_phase_c_portal_content.py`
- Modify: `web-platform/src/api/services/enterprise.ts`, `web-platform/src/hooks/usePortalData.ts`, `web-platform/src/pages/PortalPage.tsx` and CSS
- Test: portal backend contracts, announcement read/publish tests, PortalPage interaction tests

- [x] **Step 1: 先写失败测试。** 覆盖公告草稿/发布/置顶/撤下、普通成员只读、已读状态刷新保留、待办完成写回服务端、快捷链接白名单和组织动态脱敏；验证不同组织 token 互不可见。
- [x] **Step 2: 增加公告与 read-state 持久化。** 管理操作限 `portal:manage`，读取限 internal `portal:read`；所有变更审计，分页排序稳定。
- [x] **Step 3: 将 PortalPage 从 local-only toggle 改成 server-backed mutation。** 加载、空态、错误、权限态分离；公告详情使用 Drawer，移动端不产生页面滚动；组织架构入口跳转 `/organization/structure`。
- [x] **Step 4: 在隔离 PostgreSQL 16 + pgvector 对 `20260803_0010` 执行 upgrade -> schema/data invariants -> downgrade -> upgrade。**
- [x] **Step 5: 运行门户定向/全量回归、lint/build，再进行 Browser 业务流程验收。**

## Task 5：工作台任务负载、智能任务和布局持久化

**Files:**

- Create/Modify: `backend/app/models/entities.py`, `backend/app/schemas/work_items.py`, `backend/app/routers/work_items.py`, `backend/app/schemas/portal.py`, `backend/app/routers/portal.py`
- Create: `backend/migrations/versions/20260803_0011_phase_c_work_items_dashboard_layouts.py`
- Modify: `web-platform/src/api/services/dashboard.ts`, add `workItems.ts`, `web-platform/src/shared/types/dashboard.ts`, `useDashboardData.ts`, `WorkspacePage.tsx`, dashboard widgets/types/stores
- Test: `backend/tests/test_work_items.py`, `backend/tests/test_dashboard_layout_scope.py`, dashboard/workspace Vitest

- [x] **Step 1: 先写失败测试。** 覆盖任务状态迁移、事件不可篡改、当前 membership 过滤、管理员部门筛选、来源引用不泄露正文、布局 GET/PUT 响应 schema 含 `revision`、布局持久化和 revision 冲突；同步断言后端 Pydantic schema、前端 Zod/type 和 service contract；验证“任务负载”是首 widget，“智能任务”文案存在且无“AI 流水线”。
- [x] **Step 2: 增加 work_items/work_item_events 和 dashboard_layouts。** 任务状态由服务端校验并写事件；布局按 organization + user 隔离，旧 localStorage 仅一次性迁移。
- [x] **Step 3: 接入 WorkspacePage。** 任务负载优先，智能任务读取安全 run/turn 摘要，日历复用现有 reminders/calendar API；刷新和失败重试不丢本地编辑布局。
- [x] **Step 4: 验证“岗位推荐任务”和“岗位推荐日程”仍不存在，并保留现有负向断言；不得为完成本 Step 搜索或删除不存在的实现。** 保留其他已验收 widget 和响应式网格。
- [x] **Step 5: 在隔离 PostgreSQL 16 + pgvector 对 `20260803_0011` 执行 upgrade -> schema/data invariants -> downgrade -> upgrade。**
- [x] **Step 6: 运行定向测试、backend/frontend 全量、Ruff/lint/build。**

## Task 6：QM 经验的最小本地化落地

**Files:**

- Modify only current project modules from Tasks 2/4/5; do not modify `E:\My_Opjects\qm` or copy source files.
- Test: scope/audit/work-item/permission regression tests

- [x] **Step 1: 先写失败边界测试。** 一个组织内的部门/任务/方法资源不能跨组织读取；管理员变更必须带 actor 和审计；任务的状态事件可追溯；资源授权不能经由集合或部门隐式扩大。
- [x] **Step 2:** 将 QM 的 scope-first、durable task/event、directory/placement 分离、server-authoritative 和 no-transitive-re-share 规则写入当前 service boundaries，不引入 QM runtime。
- [x] **Step 3:** 对“经验与方法”保留当前 skills owner-only 语义；把 skill grant、project scope、cron/watch、files/keychain/sandbox 记录为后续候选，不在本 Task 扩大权限。
- [x] **Step 4:** 运行全量回归并检查第三方许可边界；若未来复制 QM 实质代码，必须先加入 MIT notice 和第三方清单。

## Task 7：Phase C 隔离部署与内部演示验收

- [x] **Step 1:** 在 clean release 中构建 API/Web，确认新增 schema 只在隔离测试数据库完成 roundtrip；生产数据库保持不变。
- [x] **Step 2:** 运行 backend pytest、Ruff、frontend Vitest、lint、build 和受影响 Browser specs；记录既有 Arco React 19 `ReactDOM.render` 兼容噪音，不放宽其他错误。
- [x] **Step 3:** Browser 逐项验证：门户公告/待办 -> 组织架构查看/管理员调整 -> 工作台任务负载/智能任务 -> 知识集合/记忆/方法；检查四档 viewport、刷新恢复、双组织隔离、页面/console 无新增错误。
- [x] **Step 4:** 测试用户、组织结构演示数据、公告、任务、集合、临时文件和 tokens 清理；保留一个 `deliverable` tab，不执行空会话清理。
- [x] **Step 5:** 每个 Task 单独提交并推送当前 draft PR；最后检查 `git diff -- .superpowers`、`.secret`、runtime 和凭据均未进入提交。

## 外部 guest/email/生产门禁决策记录

- [x] **受限真实投递已获单次明确授权。** 在严格收件人 allowlist 和临时配置下完成 SMTP 投递与真实 guest 验收；验收后删除临时配置并恢复 `FEATURE_EXTERNAL_GUESTS=false`。
- [x] **受限外部协作验收已独立完成。** 已覆盖批准的 adapter、指定测试邮箱、一次性 token、权限收敛、停止/撤权、隐私脱敏和临时数据清理；正式外部协作仍需新的发布与支持责任审批。
- [ ] **生产迁移不等于功能需求。** 任何生产发布仍需单独备份、迁移审批和回滚窗口；本计划只做隔离数据库验证。
