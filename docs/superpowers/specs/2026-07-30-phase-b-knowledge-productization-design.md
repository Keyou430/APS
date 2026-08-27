# 阶段 B：知识产品化、共享治理与外部访客详细设计

日期：2026-07-30
状态：详细设计完成，等待按实施计划执行
前置：平台自有 RAG、真实 query embedding、Hermes knowledge gateway 和测试服务器验收已完成
生产边界：本设计不授权生产迁移、公开互联网入口或真实外部用户上线

## 1. 决策摘要

阶段 B 不重复建设知识 AI，也不新增侧边栏“云枢助手”。现有知识库继续是唯一产品入口，本阶段把已经可运行的个人知识 RAG 扩展为可治理的组织知识产品：

1. 先统一真实前后端契约，让资源状态、知识会话、来源范围和引用在刷新后仍准确。
2. 增加同组织只读共享，默认仍为私有；资源所有者保持唯一内容管理者。
3. 增加组织级知识运营视图，只展示状态、计数、时延和稳定错误码，不展示问题或切片正文。
4. 增加邀请制外部访客。访客是受控 organization membership，只能访问显式授权资源和 tool-less knowledge 会话。
5. 匿名公开链接、跨组织 grant、外部写入、共同编辑和匿名 RAG 延期，不能作为邀请制访客的捷径实现。

阶段 B 采用分段门禁：B0 契约修正，B1 内部共享，B2 运营治理，B3 外部访客。前三段通过后才允许开启 B3 功能开关。

## 2. 当前基线与必须修正的问题

### 2.1 已有能力

- `KnowledgeEntry` 是资源根，RAG job/chunk 均以其为归属来源。
- `OrganizationMembership -> Role -> RolePermission` 是当前授权事实来源。
- API 已支持资源 CRUD、ingestion、授权 hybrid retrieve、knowledge chat、SSE、history、stop 和 delete。
- `hermes-knowledge` 是独立 tool-less 私网 gateway，浏览器不能选择 Hermes URL 或 toolset。
- 前端知识库已有资源区和 `AssistantView mode="knowledge"`，真实聊天生命周期已接入平台 API。
- `AuditEvent`、`KnowledgeRetrievalEvent` 和平台 run 生命周期表已经存在，可作为运营数据基础。

### 2.2 当前缺口

- 前端真实知识资源 service 仍调用 `/knowledge/sources`、`/collections` 等不存在的目标 API；页面的资料能力主要依赖 Mock。
- `source_ids=[]` 在旧设计中表示“不使用知识”，当前实现表示“检索所有 owner-ready 资源”。空数组语义不能继续承载产品状态。
- `AssistantView` 的 assistant/knowledge 两种表面共用同一 session list；创建请求没有公开 `surface`，客户端不能稳定区分 agent 和 knowledge 会话。
- 当前 history 只有纯文本消息，citation 没有结构化持久化，刷新后无法可靠显示、校验或重新授权。
- 知识读取仍强制 `organization_id + owner user_id`，没有内部 grant、组织可见或 guest 授权。
- `KnowledgeRetrievalEvent` 尚未写入，知识创建、更新、摄取、删除也未完整写审计。
- 用户的活动组织依赖可变的 `default_organization_id`；JWT 没有 organization context，多标签页切换组织会产生歧义。`organization_id_for(user)` 仍被 chat、knowledge、memory、skills 和 reminders 使用，不能只修 auth/users。
- `User.role_id` 与 membership role 并存；阶段 B 授权与展示必须统一读取当前 membership role。
- `HermesProfile` 当前按 user 单例，切换组织会原地修改 profile organization；多组织必须改为 `(organization_id, user_id)` 唯一的 profile，不能跨组织复用 home 或 scope。
- 现有知识 AI Mock E2E 仍定位旧 `KnowledgeAIView`，与实际 `AssistantView` 路径脱节。

## 3. 角色与权限

阶段 B 首版继续使用系统角色，不开放任意自定义角色编辑器。

| 角色 | 范围 | 能力 |
| --- | --- | --- |
| `admin` | 当前组织 | 成员、邀请、角色、全部知识治理、运营与审计 |
| `manager` | 当前组织 | 读取成员；创建自己的知识；共享自己的资源；查看知识运营；按治理权限重试失败任务 |
| `user` | 当前组织 | 创建和管理自己的知识；读取组织可见或显式授权资源；使用知识 AI |
| `guest` | 当前组织 | 只读取显式授权资源、受控下载和使用 knowledge AI；无资源创建、成员列表、agent、工具或运营权限 |

新增规范化 permission：

- `knowledge:share`：管理自己资源的可见性和显式 grant。
- `knowledge:govern`：查看组织资源元数据、重试/取消 ingestion、撤销不合规共享；不修改资源正文。
- `knowledge:ops`：查看组织级知识指标和任务列表。
- `audit:read`：读取脱敏组织审计事件。
- `members:invite`：创建、撤销和重新生成邀请。

`knowledge:write` 只代表创建和管理自己的内容，不能隐式编辑他人的共享资源。owner 权限由 `KnowledgeEntry.user_id` 隐式提供，不建立可被删除的 owner grant。

新增权限矩阵固定如下；`admin` 的 `*` 仍覆盖全部权限：

| permission | manager | user | guest |
| --- | --- | --- | --- |
| `chat:use`, `knowledge:read` | yes | yes | yes |
| `knowledge:write`, `knowledge:share` | yes | yes | no |
| `knowledge:govern`, `knowledge:ops`, `audit:read` | yes | no | no |
| `members:invite`, `org:admin` | no | no | no |
| `agent:admin`（创建 agent surface） | yes | no | no |

`knowledge:govern` 是资源 access/grant 管理的明确例外：`(owner AND knowledge:share) OR knowledge:govern`。govern 查询 grantee 时只返回 user id、display name、member type、grant 状态和到期时间，不返回 email 以外的账号资料或其他组织信息。

## 4. 信息架构与界面

### 4.1 知识库资源区

不增加全局导航项。`KnowledgeNavigator` 在知识库内部增加以下视图：

- `我的知识`：当前用户拥有的资源。
- `共享给我`：显式 grant 的资源。
- `组织知识`：`organization_members` 可见资源；guest 不进入该集合。
- 既有 `文件`、`经验与方法`、`记忆库`、`回收站` 保持。
- `知识运营`：仅 `knowledge:ops` 用户可见，仍在知识库内部。

资源列表使用安静、紧凑的工作区布局。每条资源稳定显示：owner、可见性、ingestion 状态、更新时间和类型。状态变化不能调整卡片/行高度。

资源详情 Drawer 使用四个并列 tab，不嵌套卡片：

- `概览`：标题、摘要、类型、owner、版本和受控内容预览。
- `访问`：私有/组织成员可见 segmented control、显式成员 grant 列表、到期时间和撤销动作。
- `索引`：queued/processing/ready/failed/cancelled、稳定错误码、attempts 和重新摄取动作。
- `活动`：该资源的脱敏审计事件。

非 owner 只显示自己获得的 read 权限、到期时间和 owner，不显示其他 grantee 的完整列表。guest 不显示组织成员浏览器。

### 4.2 知识 AI

保持现有双栏会话布局。资源与 AI 视图改由 URL 驱动：`/knowledge` 与 `/knowledge/ai/:sessionId?`；不再把 `knowledgeView` 或本地 AI session 持久化到 localStorage。知识会话顶部增加固定高度的来源工具条：

- segmented control：`全部可见`、`选择资料`、`不使用知识`。
- `选择资料` 使用可搜索 Drawer 和 checkbox；只能选择当前可见且 ready 的资源。
- 显示已选数量、不可用资源数量和当前 retrieval mode。
- scope 修改只在没有 active run 时允许，保存到 session 后再发送问题。

回答下方显示结构化 citation 行，使用来源图标、标题和 locator。点击后打开同一资源详情 Drawer，并再次调用授权 API。资源被撤销、删除或版本失效时，历史答案保留，但 citation 显示“当前无权访问”或“来源版本已更新”，不暴露旧正文。

`degraded_full_text` 是低噪声状态提示，不是阻断错误；`none` scope 明确显示“本轮未使用知识”。guest 只能创建 knowledge surface，会话中不出现 approval 或 tool event UI。

`KnowledgeAIView`、`useAIQuery` 和 `knowledgeStore.aiSessions` 当前已脱离生产路径；真实契约迁移完成后删除，不保留第二套会话事实来源。`AIPanel` 中仅拼接文件名/链接到 prompt 的伪附件交互必须改为真实 upload + ingestion，或在能力就绪前移除。生产与本地开发默认使用真实 API；Mock 只作为明确的测试/演示 adapter，并实现同一 DTO 和 endpoint 语义，不能继续静默运行“Mock 资料 + 真实聊天”的混合模式。

### 4.3 知识运营

运营视图面向重复操作，不做营销式大卡片。首屏由紧凑指标带、筛选工具栏和任务表组成：

- ready/queued/processing/failed/cancelled 资源数。
- ingestion 最老等待、失败率和稳定错误码分布。
- hybrid/degraded/empty 比例、P50/P95、零结果率。
- 资源数、chunk 数和估算索引空间。
- failed/queued job 表，支持 owner、类型、错误码、时间筛选。

允许操作：重试 failed、取消 queued、打开资源、查看相关审计。禁止展示 query、chunk、回答正文、对象 key、provider 响应或凭据。

### 4.4 邀请制外部访客

组织管理的成员页增加 `邀请访客` 命令。管理员输入 email、邀请 token 到期、guest membership 到期和初始资源，系统返回一次性邀请链接。测试环境允许管理员复制链接；任何真实外部试点必须通过已批准的邮件/身份验证适配器把链接送达 normalized email，手工复制不能作为 email ownership 证据。

访客接受邀请后设置用户名和密码，进入精简知识库：

- 只显示显式授权资源和 knowledge AI。
- 无工作台管理、成员列表、上传、资源编辑、共享、agent、terminal/file 或运营入口。
- 原文件下载经平台鉴权代理流式返回，不提供对象 key 或签名 URL。
- membership 到期、资源 grant 撤销或组织停用后立即失效。邀请被 accepted 后撤销 invitation 不等于撤销 membership；管理员必须执行独立的 guest membership revoke。

匿名公开分享链接不在阶段 B。任何无需登录即可访问资源或 RAG 的设计必须另立威胁模型和审批。

### 4.5 响应式与可访问性

- 验证宽度：390、768、1024、1440 px。
- 移动端会话列表、来源选择和资源详情使用独立 Drawer；不得同时堆叠两个 Drawer。
- `AssistantView` 不能在 `KnowledgePage` 的 header/padding 内再次使用 `100vh`；使用父容器 `minmax(0, 1fr)` 和稳定高度，避免嵌套页面纵向溢出。
- 长文件名、email、locator、错误码和会话标题必须换行或省略并提供 tooltip。
- 所有 icon button 有 `aria-label` 和 tooltip；tab、segmented control、checkbox 和状态提示可键盘操作。
- 流式回答遵循用户滚动位置；用户离开底部后不强制抢回滚动。

## 5. 核心状态机

### 5.1 资源与 ingestion

```text
uploading -> stored -> queued -> processing -> ready
                         |          |          |
                         v          v          v
                      cancelled cancel_requested replacing
                                      |             |
                                      v             +-> ready
                                   cancelled

stored/ready/failed -> archiving -> archived -> restoring -> prior visible state
archived -> purging -> purged
```

- `uploading` 是前端瞬时状态；`stored` 表示资源已创建但尚无 job。
- 更新资源时旧 ready revision 继续可检索，只有新 revision ready 后原子替换。
- queued 可以立即 cancelled；processing 只能进入 `cancel_requested`。worker 必须在解析/embedding 后、写 chunk 前和 commit 前重新锁行检查，发现取消则回滚新 chunk 并置 cancelled，不能继续写 ready。
- failed 只显示稳定 error code；重试由 owner 或 `knowledge:govern` 发起并写审计。
- phase B 将现有 `DELETE` 语义改为 archive：列表默认隐藏、retrieve/chat/citation/download 立即拒绝，grant 保留但不生效；restore 后按当前 membership/grant 重新授权。永久 purge 是独立 owner/admin 命令，只允许 archived 资源，并删除对象、chunk 和 grant。`archiving/restoring/purging` 是前端瞬时状态，数据库只持久化 `archived_at`。

### 5.2 分享 grant

```text
private -> organization_members -> private
   |               |
   +-> explicit grant(active -> expired/revoked)
```

- 默认 `private`。
- `organization_members` 只包括 active 且 `member_type=internal` 的 membership，不通过角色名猜测 guest。
- 显式 grant 只允许当前组织 active membership，可选到期时间，仅 `read` capability。
- owner、membership、grant、组织或资源任一失效时，访问立即失败。

### 5.3 邀请

```text
pending -> accepted
   |  \-> expired
   \----> revoked
```

- token 至少 256 bit，数据库只存 digest，明文只返回一次；`token_expires_at` 与 `membership_expires_at` 是两个独立字段。
- pending token 一次性使用。若 normalized email 不存在，可创建新用户；若已存在，必须先登录该用户且当前账号 normalized email 完全匹配，accept 只增加 membership，绝不修改已有密码。已有同组织 membership 返回稳定幂等结果，不能创建重复 membership。
- 同组织 active internal membership 永不被降级，只消费邀请并按治理规则处理资源 grant；active guest 可延长至新的 membership expiry；expired/revoked guest 只能通过新邀请重新激活；跨组织 existing user 在认证后增加独立 guest membership。
- 测试环境手工复制 token 只证明 token possession，不证明邮箱所有权；真实 guest flag 开启前必须验证批准的邮件/身份适配器。
- 不能撤销最后一个 admin；guest 不能被提升为 admin，必须由管理员显式转换为内部成员后再分配角色。

### 5.4 知识会话与 run

```text
session(surface=knowledge)
  -> scope(all_visible | selected | none)
  -> idle -> retrieving -> streaming -> completed
                         |       |  \-> stopped
                         |       \----> disconnected/failed
                         \------------> empty-context streaming
```

- `surface` 是公开产品概念，服务端固定映射到 `hermes_backend`；客户端不能提交 backend、URL 或 toolset。
- scope 是 session 状态，不再通过空 `source_ids` 推断。
- selected scope 中失效资源被剔除并返回 rejected count，不把 404 资源身份写入错误正文。
- 每个 session 同时只有一个 active run，沿用现有 admission lock、quota、stop 和 delete 规则。

## 6. 授权模型

### 6.1 活动组织

access/refresh token 增加 `organization_id` claim。登录选择用户默认 active membership；切换组织调用专用 endpoint 返回新的 token pair。`User.default_organization_id` 只作为偏好，不再作为每次请求的授权事实。

前端每个标签页把 active access/refresh token pair 和 organization context 放入 `sessionStorage`，不能继续由一个 localStorage persisted auth store 覆盖所有标签页。refresh token 每个标签页独立轮换；跨标签页只共享非授权偏好。由此两个标签页可以同时停留在不同 organization。

每次请求必须重新校验：user active、organization active、membership active/未过期、token organization 与 membership 一致。角色展示和 permission 判断只读取 membership role。chat、knowledge、memory、skills、reminders 以及之后新增的所有组织路由都注入同一个 `CurrentOrganizationContext`；阶段 B 完成时 `rg 'organization_id_for\(' backend/app` 只能剩兼容 helper 定义和明确注释，不得留业务调用。

`HermesProfile` 改为 `(organization_id, user_id)` 唯一，profile key/name/home 均包含 organization scope；内部用户切换组织时选择对应 profile，不修改另一组织的 profile 行或目录。guest knowledge session 不创建 profile 行或 home，只使用服务端计算的 organization/user request scope，仍无工具或 runner metadata。

### 6.2 可见资源谓词

资源可见必须满足同一 organization、资源未归档、当前 membership active/未过期，并满足下列任一条件：

```text
owner_user_id == current_user_id
OR (visibility == organization_members AND member_type == internal)
OR active explicit user grant exists
```

读取、retrieve、citation resolve 和 download 复用同一 `AuthorizedKnowledgeEntryRepository`。跨组织、无 grant、grant 过期、membership 撤销、组织停用统一返回 404。

共享资源的 chunk 仍携带 owner user id。候选 SQL 必须使用已授权 revision 的 `(organization_id, entry_id, owner_user_id, content_sha256)` tuple 约束，不能把 caller user id 直接代入 chunk owner 条件。

### 6.3 写入与治理

- owner + `knowledge:write`：更新、归档、恢复、purge 和摄取自己的资源。
- owner + `knowledge:share`：修改 visibility 和显式 grant。
- `knowledge:govern`：查看组织资源状态、重试/取消 job、撤销共享；不编辑正文、不转移 owner。
- `admin`：具有上述权限，但所有治理动作仍写 actor、resource 和 outcome 审计。

## 7. 持久化设计

### 7.1 既有表 additive 变更

| 表 | 新增/修正 | 说明 |
| --- | --- | --- |
| `knowledge_entries` | `visibility`, `updated_at`, `archived_at` | 默认 private；`user_id` 继续是 owner |
| `chat_sessions` | `surface`, `knowledge_scope` | surface=`agent|knowledge`；scope=`all_visible|selected|none` |
| `audit_events` | `actor_kind`, `outcome`, `request_id` | 不记录正文、token 或路径 |
| `organization_memberships` | `member_type`, `expires_at` | internal/guest 是身份边界；guest 可到期 |
| `refresh_tokens` | `organization_id` | token pair 固定组织上下文 |
| `hermes_profiles` | organization+user unique | profile name/home/key 按组织隔离，不再 user 单例 |
| `users` | `normalized_email` unique | casefold 后唯一；邀请与账号匹配只用该字段 |
| `knowledge_retrieval_events` | `chat_session_id` nullable, `request_kind`, `retrieval_mode`, `outcome`, `query_hmac_version` | REST retrieve 使用 null；mode 与执行 outcome 分离 |

`hermes_backend` 保持内部兼容字段。既有行根据 backend 回填 surface；客户端响应只返回 surface，不返回 backend。

### 7.2 新表

| 表 | 关键列与约束 | 数据边界 |
| --- | --- | --- |
| `knowledge_access_grants` | organization、entry、grantee_membership、capability=`read`、expires/revoked、granted_by | composite FK 保证同组织；仅 active grant 局部唯一 |
| `organization_invitations` | organization、normalized_email、role=`guest`、token_digest unique、invited_by、token_expires、membership_expires、accepted/revoked | 不存明文 token；accept 后创建 guest membership |
| `organization_invitation_resources` | invitation、entry；联合主键 | 只允许同组织资源；accept 时转换为 guest read grants |
| `chat_session_knowledge_sources` | session、entry；联合主键 | 只在 selected scope 使用，每次 run 重新授权 |
| `chat_turns` | session、run_id unique、status、retrieval_mode、assistant_message_id、question_hmac/version、created_at | 不存 question 正文或裸 hash |
| `chat_turn_citations` | turn、ordinal、entry、content_sha256、source_locator、title snapshot | 不存 chunk text、对象 key 或 URL |

`knowledge_entries` 和 `organization_memberships` 增加可供 composite FK 使用的 organization+id unique constraint。grant 采用 append-only 周期：revoked/expired 行保留，新一轮授权创建新行；PostgreSQL partial unique index 以 `revoked_at IS NULL` 限制同 entry+membership 同时存在一行。regrant 事务必须先锁定并把已到期旧行写入 revoked_at，再插入新行；审计保留每轮 actor/outcome。

`KnowledgeRetrievalEvent` 继续作为指标表，必须在真实 retrieve/chat 路径写入。query 标识使用服务端密钥 HMAC-SHA-256 和可轮换 key version，不使用可字典反查的裸 SHA-256，也不能作为跨保留期用户画像键。REST retrieve 的 `chat_session_id` 为 null 且 `request_kind=rest`，knowledge chat 写 owned session id 和 `request_kind=chat`；`retrieval_mode=hybrid|degraded_full_text|empty`，`outcome=success|failed|cancelled`。邀请接受事务同时创建 guest membership 和 invitation resource 对应 grants；任一资源已删除、跨组织或不可分享时整体失败。

### 7.3 删除与保留

- 删除资源级联 grant 和 chunks；turn citation 保留最小 snapshot 但 entry FK 使用 `SET NULL`。
- citation snapshot 只能证明历史回答当时的来源标签，不能授予资源访问。
- 邀请、grant 和审计采用 revoke/expire，不硬删除安全历史。迁移新增 token organization 后，所有既有 refresh token 统一 revoke 并要求重新登录，不根据可变 default organization 猜测回填。
- 运营指标按 organization 和时间聚合；原始 event 设置可配置保留期。

## 8. API 契约

### 8.1 组织上下文与成员

| API | 权限 | 说明 |
| --- | --- | --- |
| `GET /api/auth/organizations` | authenticated | 返回 active memberships 和当前 organization |
| `POST /api/auth/switch-organization` | authenticated + target membership | 返回绑定目标组织的新 token pair |
| `GET /api/organization/members` | `users:read` | 当前组织成员，role 来自 membership |
| `POST /api/organization/invitations` | `members:invite` | 创建 guest 邀请，token 只返回一次 |
| `GET /api/organization/invitations` | `members:invite` | 不返回 token digest 或明文 |
| `DELETE /api/organization/invitations/{id}` | `members:invite` | 撤销 pending 邀请 |
| `POST /api/auth/invitations/accept` | anonymous token endpoint | token 放 request body，一次性激活账号和 membership |

邀请 URL 使用 `/invite#token=...`，浏览器读取 fragment 后通过 request body 提交。token 不出现在 HTTP path、query、Referer 或常规 access log；服务端禁止记录该 endpoint body。创建邀请和通用 `/users` API 均不能直接创建/分配 `guest`；guest 只能由开启功能开关的 invitation service 创建。existing-user accept 必须携带该用户有效 token 且 email 匹配，不能重设密码。

### 8.2 知识资源

`GET /api/knowledge` 扩展 `view=mine|shared|organization`、`status`、`owner_id`、`updated_after` 和游标/页码兼容分页。响应使用不含正文的 `KnowledgeEntryMetadata`，增加 owner summary、visibility、access source 和最新 ingestion status。前端不再调用未实现的 `/knowledge/sources` 族 endpoint。

| API | 权限 | 说明 |
| --- | --- | --- |
| `GET /api/knowledge/{id}` | visible predicate | 返回 metadata 与访问摘要；兼容 `content` 仅 owner 暂时可见，shared/guest 固定 null |
| `PUT /api/knowledge/{id}/access` | `(owner AND share) OR govern` | 设置 private/organization_members |
| `GET /api/knowledge/{id}/grants` | `(owner AND share) OR govern` | owner/govern 看最小 member summary，其他人不开放 |
| `POST /api/knowledge/{id}/grants` | `(owner AND share) OR govern` | 创建同组织 membership read grant |
| `DELETE /api/knowledge/{id}/grants/{grant_id}` | `(owner AND share) OR govern` | 即时撤销 |
| `GET /api/knowledge/{id}/content` | visible predicate | 独立 preview DTO，按权限限制长度；不返回对象路径 |
| `GET /api/knowledge/{id}/download` | visible predicate | 平台代理附件下载，写审计 |

`knowledge:govern` 读取 grant 是 owner 隐私规则的唯一管理例外，只返回最小 member summary。新前端不依赖旧 `KnowledgeResponse.content`；owner 编辑正文通过 owner-only content/edit 契约，shared/guest 只得到有上限 preview 或受控 attachment download。

旧 owner-only CRUD 路径保持，但统一调用授权 repository。非 owner 不能 update/delete/ingest。

### 8.3 会话与引用

`POST /api/chat/sessions` 增加 `surface=agent|knowledge`，省略时默认 `knowledge` 以保持当前部署行为。服务端映射固定 backend；agent surface 只允许具备既有 agent 路由权限的内部用户，guest 提交 agent 返回 403。`GET /api/chat/sessions?surface=knowledge` 只返回对应会话。

| API | 说明 |
| --- | --- |
| `PUT /api/chat/sessions/{id}/knowledge-scope` | 设置 mode 和 selected ids；active run 时 409 |
| `POST /api/chat/sessions/{id}/messages` | 新客户端只发 content；服务端读取 session scope |
| `GET /api/chat/sessions/{id}/messages` | 每条 assistant message 可带 citations、turn status、retrieval mode |
| `GET /api/knowledge/citations/{turn_id}/{ordinal}` | 先校验 turn 对应 session 属于当前 user+organization+knowledge surface，再校验当前资源权限；任一失败 404 |

旧 `source_ids` 改为 nullable 并保留一个兼容周期：字段省略/null 时使用 session scope；显式非空数组仅覆盖该次 legacy run 为 selected；显式空数组仅覆盖该次 legacy run 为 all_visible，以保持当前部署行为，即使 session scope 为 none。新 UI 永不发送该字段。服务端记录 legacy use，下一主版本删除该字段；测试必须覆盖省略、null、空、非空和 scope 优先级。

SSE 在 `run.created` 后增加 `knowledge.context`：只包含 turn id、mode、citation metadata 和 rejected source count，不含 chunk text。实现前必须对固定 Hermes 版本做 live contract probe，证明 history message id 在重复读取时稳定，且 terminal run 能关联唯一 assistant message。若任一条件不成立，Task 4 必须停止并修订设计，不能使用“最新消息”或 adapter 随机 UUID 猜测关联。通过门禁后才把稳定 upstream message id 写入 turn；history 由 Hermes 文本加平台 citation metadata 共同组成。

### 8.4 运营与审计

| API | 权限 | 说明 |
| --- | --- | --- |
| `GET /api/knowledge/operations/overview` | `knowledge:ops` | 状态、容量和 retrieval 聚合 |
| `GET /api/knowledge/operations/jobs` | `knowledge:ops` | 脱敏 job 列表与筛选 |
| `POST /api/knowledge/operations/jobs/{id}/retry` | `knowledge:govern` | failed -> queued，写审计 |
| `POST /api/knowledge/operations/jobs/{id}/cancel` | `knowledge:govern` | queued -> cancelled；processing -> cancel_requested，由 worker 确认终态 |
| `GET /api/audit-events` | `audit:read` | organization scoped cursor pagination |

## 9. 审计、隐私与安全门禁

必须审计：知识 create/update/delete/ingest、visibility、grant、download、邀请、接受、撤销、member role/status、job retry/cancel、citation denied 和 organization switch。

审计 details 只允许稳定枚举、计数和资源 id。禁止 query、prompt、answer、chunk、文档正文、对象路径、邀请 token、Authorization、provider key 和异常堆栈。

其他门禁：

- 邀请 accept 和登录限流；响应统一，避免 email/account 枚举。
- `guest` 不出现在通用 UserCreate/RoleAssignment 可选值中，只能由 invitation service 创建；guest -> internal 使用独立、受审计且受 feature flag 控制的转换命令。
- guest knowledge session 不创建 `HermesProfile` 行、home 或 runner metadata；knowledge gateway 使用服务端计算的 organization/user request scope，仍不挂载任何工具。
- 下载设置安全文件名、`Content-Disposition: attachment`、`X-Content-Type-Options: nosniff` 和 `Cache-Control: private, no-store`。
- 上传在开放 guest 前必须实施大小、MIME、文件签名和格式白名单；guest 无上传权限。
- 撤销 grant/membership/organization 后，资源列表、retrieve、chat scope、citation 和 download 同时失效。
- 最后一个 admin 不能被停用、降级或移出；使用行锁事务校验。
- `PUT /users/{id}` 不能绕过自停用和最后管理员门禁。
- 既有 refresh token 在 identity migration 中全部 revoke；用户重新登录后才获得 organization-bound token family。
- query 指标使用可轮换 HMAC key；key 只注入写 retrieval event 的 API 受控运行时，不进入 worker、数据库、日志或前端。
- 任何跨组织 id、过期 grant 或失效 token 统一 404，权限不足但身份明确的管理命令使用 403。

## 10. 发布分段与功能开关

### B0：契约修正

- organization token context、membership role 单一事实来源。
- session surface、显式 knowledge scope、结构化 citation history。
- 真实知识资源 API adapter 和失效 E2E 修复。

### B1：内部共享

- private 默认、organization_members、显式 user read grant。
- 统一授权 repository、共享资源 RAG 和撤销传播。
- 访问与索引详情 UI。

### B2：运营治理

- retrieval event 写入、知识写审计、overview/jobs/audit API。
- 知识运营页面和治理动作。

### B3：外部访客试点

- `FEATURE_EXTERNAL_GUESTS=false` 默认关闭。
- 邀请、激活、guest role、显式 grant、受控 download 和精简 UI。
- 只有 B0--B2 在隔离环境完成授权矩阵、备份恢复和真实浏览器验收后才开启。

## 11. 验收标准

- owner、组织成员、显式 grantee、guest、撤销用户和跨组织用户的 list/detail/retrieve/chat/citation/download 结果与权限矩阵一致。
- 默认创建资源为 private；组织可见不包含 guest；guest 只能访问显式 grant。
- `none|all_visible|selected` 三种 scope 行为可解释且刷新保持，空数组不再产生歧义。
- agent 和 knowledge session 列表隔离；guest 永远不能创建 agent session 或获得工具事件。
- 结构化 citation 在 SSE、history 和刷新恢复后保持；权限撤销后 citation resolve 404。
- ingestion 状态机、失败重试、删除传播和旧 revision 原子替换通过。
- 运营页面不出现正文、query、chunk、对象路径、token 或 provider 错误体。
- organization token context 支持多标签页，不依赖修改用户全局 default organization 才能切换。
- 最后管理员、邀请一次性、token 过期、并发撤销和跨组织 grant 测试通过。
- Chromium 桌面与 390/768/1024/1440 视口完成资源共享、AI scope、citation、运营和 guest 邀请闭环，无横向溢出和控制台 error。
- 本地 build/lint/Vitest/Playwright、后端 pytest/Ruff 通过；测试服务器迁移前后备份、恢复和清理证据完整。

## 12. 明确延期

- 匿名公开链接、匿名 RAG、搜索引擎可索引页面。
- 跨组织共享、组织联盟和跨租户联合检索。
- 共同编辑、评论、审批流和内容发布工作流。
- 外部用户上传、编辑、分享或 agent/terminal/file 工具。
- 自定义角色设计器、字段级 ACL 和 ABAC 策略语言。
- 图片/音视频/OCR、多模态向量、外部 reranker。
- 生产 RDS/OSS 迁移、正式邮件服务和外部互联网发布。
