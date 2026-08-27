# 门户、工作台与组织架构设计规格

日期：2026-08-03

状态：下一阶段实施基线，待进入 TDD 实施

## 1. 决策摘要

下一阶段命名为 Phase C：门户、工作台与组织运营。目标是把当前“能打开页面”的门户和工作台推进成以当前组织为边界、以可持久化业务对象为中心、可由管理员治理的内部工作系统。

本阶段的主线是：

- 侧边栏新增“组织架构”，内部成员可查看，具备 `org:admin` 的管理员可调整组织单元、职位和成员归属。
- 门户负责组织信息、公告、待办入口和协作导航；工作台负责个人任务负载、智能任务、日历和可持久化布局。
- “知识库集合”不再把集合名称伪装成 `KnowledgeType`；集合使用独立资源 API。记忆使用现有 `/api/memory`，经验与方法使用现有 `/api/skills`，不再请求不存在的 `/api/knowledge/memories` 或 `/api/knowledge/experiences`。
- 所有组织范围 API 继续从 token-bound `CurrentOrganizationContext` 获取组织和 membership role。不得从 `User.default_organization_id` 推导授权组织。
- Phase B 的正式 email/identity delivery、真实外部 guest 和匿名分享不进入本阶段主线。它们被重新分类为“按产品需求触发的外部协作扩展”，不是内部门户、工作台或知识库演示的完成条件。

本阶段不执行生产迁移、不配置正式邮件、不打开真实外部 guest。新增 schema 只在本地和隔离测试数据库完成 upgrade/rollback 验证；共享测试环境迁移也必须在实施时先备份并获得明确确认。

## 2. 当前事实与问题边界

### 2.1 门户和工作台的真实 API 已存在，但业务数据仍是骨架

`/api/enterprise`、`/api/enterprise/portal`、`/api/dashboard` 和 `/api/dashboard/layout` 已经可访问，但后端当前从 membership 和 role 临时拼接部门、职位、人员，公告、活动和待办为空；布局响应由默认值生成，PUT 不持久化。

这意味着下一阶段不能只继续做 CSS。需要把组织结构、公告、工作项和布局保存为服务端持有的当前组织数据，再由前端做交互投影。

### 2.2 三个 422 的确切原因

1. “知识库集合”在 `KnowledgePage` 中把 `knowledge_base` 放入 `filters.types`，请求 `/api/knowledge?type=knowledge_base`。后端 `KnowledgeType` 只有 `link | file | workflow_result`，所以它不是合法知识条目类型。集合是目录资源，不是条目类型。
2. “记忆库”请求 `/api/knowledge/memories`。后端没有该路径，FastAPI 将 `memories` 尝试解析为 `/{entry_id}` 的整数，返回 422。真实记忆 API 是 `/api/memory`，并且返回 `{items, provider}`。
3. “经验与方法”请求 `/api/knowledge/experiences`。后端同样没有该路径，返回 422。当前可用的持久化能力是 `/api/skills`；技能内容就是可执行的方法资产，应该以方法视图展示，而不是再造一套未持久化的 Experience 表。

前端 mock 中的 `knowledge_base`、`memory`、`experience` 可以保留为展示模型兼容值，但不得继续作为 real API 的 `KnowledgeType` 或路径。

当前 mock 模式之所以没有暴露相同错误，是因为 `knowledgeService` 的 mock 分支直接读取 `memoryEntries/experienceEntries`；现有 `memoryService`、`skillsService` 都是纯 Axios，在 `VITE_USE_MOCK=true` 时会被 client interceptor 拒绝。因此不能只把 hook 改为调用这两个 service，必须先补齐它们的 mock 双实现。

## 3. 信息架构与侧边栏

内部成员的主导航顺序固定为：

1. 企业门户网站
2. 工作台
3. 组织架构
4. 知识库
5. 平台

访客继续只看到知识库，不出现组织架构、门户、工作台、成员、平台或管理入口。折叠侧边栏只保留图标，必须有 `aria-label` 和 `title`；展开侧边栏显示中文名称。当前路径 `/organization/structure`、`/organization/members` 均选中“组织架构”这一导航项。

## 4. 组织架构

### 4.1 用户流程

普通内部成员：

1. 点击“组织架构”进入组织结构页。
2. 默认看到当前组织根节点、部门树、职位分布和人员数量。
3. 选择部门后，右侧显示部门成员、职位和直属上级；可以搜索姓名、邮箱、职位。
4. 点击人员查看只读人员卡片；不展示 guest，不允许从此页发起外部邀请。

管理员：

1. 页面顶部显示“管理组织架构”入口；进入编辑模式前加载最新 `revision`。
2. 可新增、重命名、排序、移动和停用部门；可新增、重命名、停用职位。
3. 可将内部成员分配到部门、职位和直属上级；批量调整通过批量 placement endpoint 在一个事务中提交，任一条失败则整批回滚。
4. 删除有子节点或仍有成员的部门必须返回 409 并提示先迁移；不能级联删除人员。
5. 服务端返回 revision conflict 时，前端保留未提交表单，提示“组织架构已被其他管理员更新”，用户选择刷新后再提交。
6. 所有写操作显示成功/失败反馈，并在审计中记录 actor、组织、目标、旧值和新值；不得记录密码、token 或正文。

移动端使用“部门树 -> 成员列表 -> 成员详情”的单列 drill-down，编辑表单使用 Drawer；桌面端为树、列表、详情三栏但不把页面区块再套成卡片。

### 4.2 数据模型

新增以下组织范围实体，均带 `organization_id` 外键：

- `organization_units`：`id`、`organization_id`、`parent_id`、`name`、`code`、`sort_order`、`is_active`、`created_at`、`updated_at`。
- `organization_positions`：`id`、`organization_id`、`unit_id`、`title`、`level`、`sort_order`、`is_active`、时间字段。
- `organization_placements`：`membership_id` 唯一、`unit_id`、`position_id`、`manager_membership_id` 可空、时间字段。只允许 internal membership，所有引用必须属于同一组织。
- `organization_structure_state`：每组织一行 `revision`，用于事务锁和乐观并发控制。

迁移为现有组织建立一个根 unit；现有 internal membership 建立兼容 placement，无法推断的职位使用 role 名称作为初始显示值。guest 不创建 placement。

### 4.3 API 契约

所有路由使用 `CurrentOrganizationContext`，并在依赖层检查 guest/internal 和权限：

- `GET /api/organization/structure`：返回 `{revision, units, positions, placements, people}`。
- `POST/PATCH/DELETE /api/organization/units[/{id}]`。
- `POST/PATCH/DELETE /api/organization/positions[/{id}]`。
- `PUT /api/organization/placements/{membership_id}`，请求包含 `expected_revision`、`unit_id`、`position_id`、`manager_membership_id`。
- `POST /api/organization/placements/batch`，请求包含一个 `expected_revision` 和 placement items；服务端对整批目标图进行校验并在单一事务中提交。

读取权限使用 `org:read`；写权限复用现有 `org:admin`，其语义从“组织用户和角色管理”扩展为“组织用户、角色和结构管理”。管理员写请求锁定 `organization_structure_state`，检查 expected revision、同组织外键和 unit 树无环。placement 写入还必须在应用整批变更后的有效 manager 图上做 visited-set 环检测，最大跟随深度为当前组织 active internal membership 数量加一；出现自指、重复节点或超过上限均返回 409。全部校验成功后才递增 revision。权限不足返回 403，guest 统一返回 403。

## 5. 企业门户业务闭环

门户是组织入口，不是另一个任务看板：

- 顶部显示当前组织、当前用户职位和组织架构入口。
- 公告区读取可见公告；点击打开详情，标记已读；置顶公告优先，已读状态按用户/组织持久化。
- “我的待办”从统一 WorkItem API 读取，勾选完成后提交服务端状态，而不是只改本地 state。
- 快捷入口打开知识库 AI、工作台、组织架构和日历；统一由服务端返回路径白名单，不能由用户输入任意 URL。
- 协作动态只展示经过脱敏的组织事件（公告发布、任务完成、组织结构更新），不展示知识正文、token、邮箱验证码或 provider/object key。
- 管理员可创建草稿、发布、置顶、撤下公告；发布和撤下都写审计，普通成员只读。

门户数据接口保留 `/api/enterprise/portal`，增加分页游标或稳定 page/page_size，不以空数组作为“加载成功但没有实现”的长期状态。错误、空态和权限态分开呈现。

## 6. 工作台业务闭环

工作台第一位固定为“任务负载”，现有“智能任务”作为更容易理解的 AI pipeline 名称继续使用，不恢复“岗位推荐任务”和“岗位推荐日程”。

### 6.1 任务负载

新增组织范围 `work_items` 和 `work_item_events`：

- work item：`id`、`organization_id`、`assignee_membership_id`、`created_by`、`title`、`description`、`status`、`priority`、`due_at`、`origin`、`source_ref`、时间字段。
- status：`pending | in_progress | completed | cancelled`；状态迁移由服务端校验并写 event。
- origin：`manual | reminder | chat | agent`；agent/chat 只能带不敏感的 source ref，不把完整 prompt 或 provider 请求复制到任务表。

个人视图默认只返回当前 membership 的任务；管理员可按组织、部门、负责人筛选，但仍使用 token-bound organization context。

### 6.2 智能任务、日历与布局

- “智能任务”显示当前用户有权看到的 agent/chat 运行摘要，使用 run/turn 状态和标题，不复制回答正文；点击可回到知识 AI 或对应会话。
- 日历摘要复用 reminders/calendar 的组织范围接口，未配置日历时显示明确空态，不伪造同步成功。
- Dashboard layout 通过 `GET/PUT /api/dashboard/layout` 持久化到 organization + user，保存带 revision，旧 `hermes-dashboard` localStorage 只作为一次性迁移来源。保存失败必须保留当前编辑布局并提示重试。
- 所有 widget 的尺寸、拖拽、移动端单列和亮暗主题行为保持现有契约；只替换数据源和文案层级。

## 7. 知识库契约修复

### 7.1 集合

新增 `knowledge_collections`：`id`、`organization_id`、`parent_id`、`name`、`description`、`sort_order`、时间字段。`knowledge_entries.collection_id` 可空，v1 每条资料至多属于一个集合；集合不是 access grant，也不改变条目授权。删除非空集合必须 409 或先显式移出资料。

新增：

- `GET /api/knowledge/collections`：返回当前组织可见集合树和每个集合中当前用户可见的 source_count。
- `POST/PATCH/DELETE /api/knowledge/collections[/{id}]`：写权限为 `knowledge:write`，治理权限控制跨所有者移动。
- `PUT /api/knowledge/{entry_id}/collection`：服务端重新验证条目可见性和移动权限。
- `GET /api/knowledge?collection_id={id}`：先确认集合属于 token-bound 当前组织，再返回该集合中当前用户已授权可见的条目；集合不存在或跨组织时返回 404，绝不因集合成员关系扩大条目权限。

`GET /api/knowledge` 的 `type` 只接受后端 `KnowledgeType`；选择“知识库集合”时先调用 collection API，再用 `collection_id` 筛选条目，不再发送 `type=knowledge_base`。前端 `knowledgeService.list` 和 `useKnowledgeSources` 必须显式传递该参数。

### 7.2 记忆

现有 `memoryService` 的 list/get/create/update/delete real 路径与后端一致，但 `search()` 错误指向不存在的 `/api/memory/search`，且当前没有调用方。本阶段选择“独立双实现 service”方案，为它增加与现有 service registry 一致的 mock implementation，并通过 `selectServiceImplementation(mockServices.memory, realMemoryService)` 导出 canonical service。canonical interface 固定为 list（`query` 即搜索）/get/create/update/delete；删除未使用的独立 search 方法，不新增虚假后端路由。mock 实现必须覆盖完整 canonical interface，使用独立 canonical mock records，不发 Axios 请求。`useKnowledgeSubmodules` 直接复用该 service，解析 `{items, provider}` 并把 `memory_id/created_at/updated_at/metadata` 映射为前端视图，同时移除“应改用 knowledgeService”的误导性 deprecated 注释。记忆是当前用户、当前组织范围的 Mem0 资产；metadata 中的 tags 只作展示，不扩大权限。保留现有 CRUD 入口，统一错误和空态。

### 7.3 经验与方法

现有 `skillsService.list/create/generate/hub/delete` 方向正确，但 `getByName(name)` 与后端整数 `/{skill_id}` 不一致，frontend interface 也漏了后端已有的 update；当前错误方法没有调用方。本阶段将 canonical interface 固定为 list/getById/create/update/generate/hub/delete，再增加完整 mock implementation，并通过 `selectServiceImplementation(mockServices.skills, realSkillsService)` 导出 canonical service。delete 与后端 204 一致返回 void。mock 实现必须覆盖完整 canonical interface，使用独立 canonical mock records，不发 Axios 请求。`useKnowledgeSubmodules` 直接复用该 service，并移除“应改用 knowledgeService”的误导性 deprecated 注释。Skill 作为方法资产展示：名称、分类、SKILL.md 摘要、创建时间和 AI 生成标记。删除当前“评分/步骤”这类 mock-only 字段，避免向真实 API 伪造数据。后续若需要组织共享方法，再沿用 knowledge grant 或专门 skill grant，不在本阶段偷偷放宽当前 owner-only 语义。

`mockServices` 必须新增 `memory` 和 `skills`，`services.test.ts` 将二者加入 service mode selection 矩阵。mock seed 使用与 API DTO 对齐的 memory/skill records；旧 `memoryEntries/experienceEntries` 在完成 consumer 搜索前保留，只有无调用方时才删除。real 和 mock 使用同一 hook 映射逻辑，防止两套展示语义漂移。

### 7.4 检索范围

`KnowledgeScopeControl` 只列出当前授权且 ingestion status 为 ready 的 knowledge entries。集合、记忆、方法是导航视图，不自动变成可检索 source type。空集合、无记忆、无方法和服务错误分别显示，422 不再被包装成“暂无数据”。

## 8. 权限、审计与迁移边界

- 复用现有 `org:admin` 并扩展其描述为组织用户、角色和结构管理；新增 `org:read`、`portal:read`、`portal:manage`、`work_items:read`、`work_items:write` 等最小权限。admin 通过 `*` 拥有全部；manager/user 获得 `org:read`、`portal:read` 和自己的任务读写，只有 admin 获得 `portal:manage`/`org:admin`；guest 无此组权限。
- 新权限必须同时写入 `seed.py` 的 `DEFAULT_PERMISSIONS`/`DEFAULT_ROLE_PERMISSIONS` 和增量 migration 的 permission/role link backfill；seed 只保证全新部署，不能代替既有数据库 migration。
- 每一个 endpoint 都必须从 `CurrentOrganizationContext` 取 organization_id 和 membership_id；服务层接收明确 scope，禁止 fallback 到 `organization_id_for(user)`。
- schema migration 只允许 additive changes 和可回滚 backfill；生产数据库不在本阶段操作。迁移顺序固定为 `backend/migrations/versions/20260803_0008_phase_c_knowledge_collections.py`、`20260803_0009_phase_c_organization_structure.py`、`20260803_0010_phase_c_portal_content.py`、`20260803_0011_phase_c_work_items_dashboard_layouts.py`，不得并行占用同一 revision。每一个迁移 Task 都必须先在隔离数据库完成 upgrade -> invariants -> downgrade -> upgrade；共享测试部署前先创建备份并取得确认。
- 审计事件覆盖组织结构、公告、任务状态、集合移动和布局管理操作；查询只返回当前组织、当前权限允许的数据。

## 9. 从 QM 提取的能力与明确取舍

已拉取并阅读官方 [yc-software/qm](https://github.com/yc-software/qm)，当前本地参考快照位于 `E:\My_Opjects\qm`，版本为 `v0.1.4` / `7f2c916`，仅用于研究，不编辑、不复制源码。

### 采用的经验

1. **scope-first**：每个 session、project、memory、file、skill、cron 都有明确 owner scope；本项目对应为 token-bound organization + membership，再向部门、任务和个人资源细分。
2. **目录与成员是独立边界**：QM 的 directory/principal/grant 设计提醒我们把组织树、membership placement 和资源授权分开，组织架构不能直接变成知识读取权限。
3. **持久化工作对象**：QM 的 project/task/event store 把项目、成员和状态迁移存为 durable object；本项目采用 work item + event，而不是继续用 dashboard mock 数组。
4. **上下文资源面板**：QM 在 project/context 中并列展示 files、memory、skills、crons；本项目先采用同样的信息分组原则，暂不引入其 sandbox/keychain。
5. **服务端权威、前端薄**：运行状态、权限、SSE 和审计由服务端持有，浏览器只做呈现和交互，符合当前 Hermes/RAG 设计。
6. **管理变更可审计且不可越权转授**：QM 的 grant 管理明确 owner/manager 和 no transitive re-share；本项目集合移动、组织调整和未来 skill sharing 均采用相同的服务端校验思路。

### 仅记录为后续候选

- project/group scope 和项目成员管理；
- skill grant、管理员推广和 git 导入；
- cron/watch/background run；
- 统一文件、记忆、技能和部署资源页；
- 组织级 model allowlist、security posture 和更完整的 egress policy。

### 本阶段明确不吸收

- Slack、多 harness（Pi/OpenCode/Codex/Claude Code）和 QM 自有运行时；Hermes 是本项目唯一 agent runtime。
- sandbox、keychain、deploy/app publishing、匿名 playground 和 bearer capability link；这些扩大信任边界，且用户未要求。
- QM 的 Fastify/Lit/Postgres 代码结构；当前项目继续 FastAPI、React、Arco、SQLAlchemy 和现有部署方式。
- 真实外部 guest 和邮件投递；QM 的安全文档也把 guest/external user 排除在默认交互边界外。

QM 采用 MIT License。若未来确实复制其实质代码，必须保留版权和许可文本；本阶段只提取行为和架构经验，不形成第三方代码拷贝。

## 10. Phase B Step 7 重新评估

### 当前结论

正式 email/identity delivery、真实外部 guest 和匿名分享不是当前内部 AI/知识库演示或门户/工作台主流程的必要能力。Step 7 以“产品需求未成立，工程门禁转为延期决策”关闭，不以一个未配置的 503 `approved` adapter 冒充完成。

保留 `FEATURE_EXTERNAL_GUESTS=false`、test adapter、邀请契约和已有 token-based Browser 覆盖；不删除代码，以便未来按正式需求开启。生产迁移仍然是任何生产上线的环境门禁，不能被解释为“永远不需要”。

### 重新开启条件

只有出现以下任一明确需求，才创建单独 Phase C+ 外部协作任务：

- 客户或合作伙伴必须在组织外查看被授权知识；
- 需要可证明的邮箱所有权或企业 IdP 登录；
- 需要可追踪的邀请、撤权、过期、重发和支持流程；
- 业务、隐私、保留期、滥用防护和邮件退信责任已有负责人。

届时必须先确定收件人/身份测试窗口、批准的 SMTP/Resend/IdP adapter、限流和审计方案，再做真实 guest 验收。匿名分享仍不纳入默认方案。

## 11. 验收标准

- 内部管理员可通过侧边栏进入组织架构，查看组织树并完成一次新增/移动/成员分配；另一管理员的旧 revision 提交返回 409，普通 user 只读，guest 403。
- 门户公告读取、已读、待办完成、快捷入口和组织架构跳转均走真实 API，刷新后状态保留。
- 工作台任务负载位于首位，“智能任务”取代 AI Pipeline；任务状态、布局和刷新可恢复，不再依赖只存在于浏览器的成功假象。
- “知识库集合”“记忆库”“经验与方法”在真实 API 模式下分别请求 collections、memory、skills，均不返回 422；无数据和错误可区分。
- 组织、知识、记忆、技能、任务和门户请求均在不同组织 token 下隔离；没有从 `User.default_organization_id` 推导授权。
- 本阶段不执行生产迁移、正式邮件、真实外部 guest、匿名分享或关闭最后 Browser tab 的清理操作。
