# 前端 API 接口与契约

版本：2026-08-11

后端基线：`main@25dbd67bc07138e37d11b4ae41ee9ca94021e181`

适用分支：`codex/frontend-replacement`

本文面向负责替换和维护 `web-platform/` 的前端负责人 `Keyou430`。目标不是照搬旧页面，而是在保留后端安全、组织和状态机边界的前提下，将新界面完整接入现有 API。

### 职责与变更权限

- `Keyou430` 负责前端界面、组件、路由、状态、前端 API service/adapter、TypeScript 类型与映射、contract/component/E2E 测试；
- `OneAsmallFish` 负责并最终确认后端 API、Agent、知识库/RAG、数据库、Docker、Nginx、部署与运行环境；
- `qiang880` 以 `read` 权限查看仓库中的项目进度和验证证据，不参与接口设计、代码提交、Issue/PR 变更或 review 操作；
- `Keyou430` 发现接口缺失或不一致时，在 Issue 中提交 operationId、页面场景、期望 request/response/error 和权限要求，由 `OneAsmallFish` 判断是否修改后端及 OpenAPI；
- 未经确认，不得由前端提交临时后端路由、Docker/Nginx/部署变更，也不得在前端伪造一个看似真实的 `/api/...` 接口。

## 1. 权威来源和变更规则

契约按以下顺序判断：

1. 指定联调环境的 `/openapi.json`；
2. 同一环境的 `/docs`；
3. 仓库快照 [`backend/docs/openapi.json`](../backend/docs/openapi.json)；
4. `backend/app/routers/**` 和 `backend/app/schemas/**`；
5. `web-platform/src/api/services/**`、`shared/types/**` 和 `*.contract.test.ts`。

当前快照包含 **89 paths、117 operations、132 schemas**。本文只解释前端必须遵守的跨接口规则；字段是否必填、长度、枚举、query 参数和 operationId 以 OpenAPI 为准。

发现运行环境与仓库快照不一致时，应停止联调并提交 Issue，不得在组件中临时兼容两个未经确认的契约。

后端接口变更必须在同一后端提交中重新生成快照：

```powershell
cd backend
.\.venv\Scripts\python.exe scripts/export_openapi.py
.\.venv\Scripts\python.exe scripts/export_openapi.py --check
```

禁止手工编辑 `backend/docs/openapi.json`。

## 2. 地址、传输和字段规则

### 2.1 API 基址

- 浏览器默认同源基址：`/api`。
- 前端 service 内写 `/auth/login`、`/knowledge` 等相对路径，不再重复写 `/api`。
- 本地 Vite 将 `/api` 代理到 `http://localhost:8000`。
- 非同源联调可设置 `VITE_API_BASE_URL=http://127.0.0.1:8000/api`。
- `/health`、`/ready`、`/docs`、`/openapi.json` 不在 `/api` 前缀下。

组件不得直接创建第二个 Axios 实例。普通 JSON 请求统一经过 `src/api/client.ts`；SSE 使用 `src/api/services/chatStream.ts` 的 `fetch + ReadableStream` 实现。

### 2.2 内容类型

| 场景 | Content-Type / Accept | 规则 |
| --- | --- | --- |
| 普通 API | `application/json` | 请求和响应均为 JSON |
| OAuth2 Swagger token | `application/x-www-form-urlencoded` | 只给 Swagger UI；页面登录不用它 |
| 文件上传 | `multipart/form-data` | 交给浏览器生成 boundary，不手写 boundary |
| Chat 消息 | `Accept: text/event-stream` | 响应必须按 SSE frame 增量读取 |
| 文件下载 | 二进制响应 | 使用 `Blob`，从响应头处理文件名 |
| `204` | 空 body | 不执行 `response.json()` |

### 2.3 响应和错误

成功响应是**直接 DTO**，没有统一 `{ data: ... }` 包装。旧的 `unwrapApiData` 仅用于兼容，不应成为新前端的协议假设。

普通错误：

```json
{
  "error": {
    "code": "http_404",
    "message": "Resource not found"
  }
}
```

校验错误：

```json
{
  "error": {
    "code": "validation_error",
    "message": "Request validation failed",
    "details": []
  }
}
```

稳定上传错误码：

- `payload_too_large`：文件超过后端上限；
- `content_type_not_allowed`：扩展名、MIME 或文件魔数不匹配。

状态处理：

| 状态 | 前端行为 |
| --- | --- |
| `400` | 展示输入或业务错误，不自动重试 |
| `401` | 统一 refresh 一次；失败则清空 session 并回登录页 |
| `403` | 显示无权限；不得通过隐藏按钮绕过后端权限 |
| `404` | 资源不存在，或跨组织资源被安全隐藏 |
| `409` | revision/状态冲突；保留本地草稿，拉取服务端新版本 |
| `413` | 文件过大，提示允许的大小 |
| `422` | 显示字段校验或受支持格式，不提交原始 provider 错误 |
| `429/5xx` | 仅 GET/HEAD/OPTIONS 可有限重试；写操作不自动重放 |

### 2.4 命名、ID 和时间

- Auth、Knowledge、Organization 等 DTO 主要使用 `snake_case`。
- Portal、Dashboard、Work Items 使用 Pydantic alias，网络 DTO 为 `camelCase`。
- 禁止全局自动转换字段名；在每个 service 的 DTO mapper 中显式转换。
- 后端整数 ID 不得用 `parseInt` 猜测来自任意 UI 字符串；在 service 边界明确转换。
- 时间为 ISO 8601；展示时转换到用户时区，提交时发送带时区值。
- `null`、字段缺失和空数组含义不同，按 schema 保留。

## 3. 认证、刷新、退出和组织切换

### 3.1 核心 DTO

```ts
type TokenResponse = {
  access_token: string
  refresh_token: string
  token_type: 'bearer'
  expires_in: number
  organization_id: number
}

type UserResponse = {
  id: number
  username: string
  email: string
  role: string
  member_type: 'internal' | 'guest'
  permissions: string[]
  membership_id: number | null
  membership_expires_at: string | null
  organization_id: number
  is_active: boolean
  created_at: string
}
```

### 3.2 接口

| Method | Path | Request | Success |
| --- | --- | --- | --- |
| `POST` | `/api/auth/login` | `LoginRequest` | `200 TokenResponse` |
| `POST` | `/api/auth/token` | form body | `200 TokenResponse`，仅 Swagger |
| `POST` | `/api/auth/refresh` | `RefreshRequest` | `200 TokenResponse` |
| `POST` | `/api/auth/logout` | `RefreshRequest` | `204` |
| `GET` | `/api/auth/me` | Bearer | `200 UserResponse` |
| `GET` | `/api/auth/organizations` | Bearer | `200 OrganizationMembershipListResponse` |
| `POST` | `/api/auth/switch-organization` | `SwitchOrganizationRequest` | `200 TokenResponse` |
| `GET` | `/api/auth/oauth/{provider}` | `feishu`/`dingtalk` | discovery stub |

### 3.3 必须实现的流程

登录：

1. `POST /auth/login`；
2. 使用返回的**新 access token**调用 `/auth/me`；
3. 两步均成功后一次性写入 auth store；
4. token 存在 `sessionStorage`，不存 `localStorage`、cookie、URL 或日志。

Refresh：

- refresh token 单次旋转；成功后 access/refresh 必须同时替换。
- 多个并发 401 只能发起一次 refresh，其余请求等待同一个 Promise。
- 原请求最多重放一次，`/login`、`/token`、`/refresh`、`/logout` 不触发 refresh loop。

退出：

- `/auth/logout` 只撤销提交的当前 refresh token，不是 revoke-all。
- 前端 best-effort 调用，建议 3 秒独立超时；无论网络结果如何都在 `finally` 清空本地 session。
- 不显示或记录 refresh token，也不根据 `204` 推断其他会话状态。

组织切换：

1. 用旧组织 access token 调用 `/auth/switch-organization`；
2. 用返回的**目标组织 access token**调用 `/auth/me`；
3. profile 成功后再原子替换 token、用户和 organizationId；
4. 任一步失败都保留旧组织 session；
5. 切换后清空或按 organizationId 隔离所有页面缓存、query cache 和草稿。

## 4. 授权和组织边界

当前组织由 access token 中的 `organization_id` 与有效 membership 共同确定。前端不得使用 `User.default_organization_id`、URL 参数或缓存角色替代后端判定。

导航、按钮和页面可依据 `/auth/me.permissions` 改善体验，但后端始终是最终权限源。

| 领域 | 读取权限 | 写入/管理权限 |
| --- | --- | --- |
| Chat | `chat:use` | `chat:use`；agent surface 的工具仍受服务端限制 |
| Knowledge | `knowledge:read` | `knowledge:write`、`knowledge:share`、`knowledge:govern` |
| Knowledge operations | `knowledge:ops` | retry/cancel 需要 `knowledge:govern` |
| Audit | `audit:read` | 无前端写入 |
| Organization | `org:read` | `org:admin` |
| Users | `users:read` | `org:admin` |
| Invitations | - | `members:invite`，功能开关关闭时 fail closed |
| Portal | `portal:read` 且 internal member | `portal:manage` |
| Work items | `work_items:read` | `work_items:write` |
| Hermes profiles | - | `agent:admin` |
| Memory | `memory:read` | `memory:write` |
| Skills | `skills:read` | `skills:write` |
| Reminders | `reminders:read` | `reminders:write` |

Guest 只允许服务端授予的最小权限。不得因为页面上隐藏了按钮就认为 guest 已被隔离；所有 detail、preview、download、citation resolve 都必须实际调用后端并接受 `403/404`。

## 5. 领域接口目录

表中的 Request/Response 是 `backend/docs/openapi.json#/components/schemas` 名称。

### 5.1 System、Enterprise 和 Dashboard

| Method | Path | Request -> Response |
| --- | --- | --- |
| `GET` | `/health` | `200 {status,service}`，仅 liveness |
| `GET` | `/ready` | `200/503`，数据库和可选 RAG worker readiness |
| `GET` | `/api/enterprise` | `EnterpriseInfoResponse` |
| `GET` | `/api/enterprise/portal` | `EnterprisePortalResponse` |
| `GET/POST` | `/api/enterprise/announcements` | `AnnouncementCreate -> AnnouncementResponse/List` |
| `PATCH` | `/api/enterprise/announcements/{id}` | `AnnouncementUpdate -> AnnouncementResponse` |
| `POST` | `/api/enterprise/announcements/{id}/publish` | `AnnouncementResponse` |
| `POST` | `/api/enterprise/announcements/{id}/pin` | `AnnouncementPinUpdate -> AnnouncementResponse` |
| `POST` | `/api/enterprise/announcements/{id}/withdraw` | `AnnouncementResponse` |
| `POST` | `/api/enterprise/announcements/{id}/read` | `204` |
| `PUT` | `/api/enterprise/portal/todos/{id}` | `PortalTodoUpdate -> PortalTodoResponse` |
| `GET` | `/api/dashboard` | `DashboardDataResponse` |
| `GET/PUT` | `/api/dashboard/layout` | `DashboardLayoutUpdate -> DashboardLayoutResponse` |
| `POST` | `/api/dashboard/layout/reset` | `DashboardLayoutResponse` |

Portal/Dashboard 网络字段使用 camelCase。保存 layout 必须提交 `expectedRevision`；`409` 时不得覆盖服务端布局。

### 5.2 Organization、Users、Invitations 和 Hermes profiles

| Method | Path | Request -> Response |
| --- | --- | --- |
| `GET` | `/api/organization/structure` | `OrganizationStructureResponse`，含 `revision` |
| `POST` | `/api/organization/units` | `OrganizationUnitCreate -> OrganizationStructureResponse` |
| `PATCH/DELETE` | `/api/organization/units/{unit_id}` | update/revision request -> structure/`204` |
| `POST` | `/api/organization/positions` | `OrganizationPositionCreate -> OrganizationStructureResponse` |
| `PATCH/DELETE` | `/api/organization/positions/{position_id}` | update/revision request -> structure/`204` |
| `PUT` | `/api/organization/placements/{membership_id}` | `OrganizationPlacementUpdate -> structure` |
| `POST` | `/api/organization/placements/batch` | `OrganizationPlacementBatch -> structure` |
| `GET/POST` | `/api/users` | query / `UserCreate -> UserListResponse/UserResponse` |
| `GET/PUT/DELETE` | `/api/users/{user_id}` | `UserUpdate -> UserResponse/204` |
| `PUT` | `/api/users/{user_id}/roles` | `RoleAssignment -> UserResponse` |
| `GET/POST` | `/api/invitations` | `InvitationCreate -> InvitationList/CreatedResponse` |
| `POST` | `/api/invitations/{id}/revoke` | `InvitationResponse` |
| `POST` | `/api/invitations/{id}/regenerate` | `InvitationRegenerate -> InvitationCreatedResponse` |
| `POST` | `/api/invitations/accept` | `InvitationAccept -> InvitationAcceptResponse` |
| `POST` | `/api/invitations/guest-memberships/{id}/revoke` | `GuestMembershipResponse` |
| `POST` | `/api/hermes/profiles` | `ProfileCreate -> ProfileResponse` |
| `GET/DELETE` | `/api/hermes/profiles/{user_id}` | `ProfileResponse/204` |
| `GET` | `/api/hermes/profiles/{user_id}/health` | `ProfileHealthResponse` |

Organization mutation 使用 optimistic revision；批量 placement 必须一次提交，不能逐项发送造成半成功。邀请 token 只允许从 URL fragment 或受控测试响应进入接受页，不进入 query、日志、analytics 或截图。

### 5.3 Chat 和 SSE

| Method | Path | Request -> Response |
| --- | --- | --- |
| `POST` | `/api/chat/attachments` | multipart file -> `ChatAttachmentResponse` |
| `POST` | `/api/chat/link-preview` | `LinkPreviewRequest -> LinkPreviewResponse` |
| `GET/POST` | `/api/chat/sessions` | query / `ChatSessionCreate -> list/session` |
| `DELETE` | `/api/chat/sessions/{session_id}` | `204` |
| `PUT` | `/api/chat/sessions/{session_id}/knowledge-scope` | `KnowledgeScopeUpdate -> KnowledgeScopeResponse` |
| `GET` | `/api/chat/sessions/{session_id}/messages` | `ChatMessageListResponse` |
| `POST` | `/api/chat/sessions/{session_id}/messages` | `MessageCreate -> text/event-stream` |
| `POST` | `/api/chat/sessions/{session_id}/runs/{run_id}/stop` | `RunStopResponse` |
| `POST` | `/api/chat/sessions/{session_id}/runs/{run_id}/approval` | `RunApprovalRequest -> RunApprovalResponse` |

`MessageCreate`：`content` 1..20000 字符、最多 5 个 attachments、最多 5 个 links、最多 50 个 source IDs。不要把完整历史发回后端。

附件上限 10 MiB；常用支持格式为 `.txt/.md/.csv/.html/.pdf/.docx/.xlsx/.pptx`，正文最多进入消息 12000 字符。链接预览只接受服务端批准的公开飞书/Lark/钉钉链接。

SSE frame：

```text
event: response.output_text.delta
data: {"delta":"..."}

```

必须处理：

- `run.created`；
- `response.output_text.delta`；
- `tool.*`；
- `approval.request`；
- `knowledge.context`；
- `response.completed`；
- `response.failed`；
- `response.cancelled`；
- `upstream.disconnected`。

只有 terminal event 才能结束 loading。断流且无 terminal event 必须显示可重试的 interrupted 状态，不能伪装成完成。Abort 后调用 stop；approval 仅允许 `once` 或 `deny`。

### 5.4 Knowledge 和 Knowledge Operations

| Method | Path | Request -> Response |
| --- | --- | --- |
| `GET/POST` | `/api/knowledge` | query / `KnowledgeCreate -> list/KnowledgeResponse` |
| `POST` | `/api/knowledge/upload` | multipart `file,title` -> `201 KnowledgeResponse` |
| `GET/PUT/DELETE` | `/api/knowledge/{entry_id}` | `KnowledgeUpdate -> KnowledgeResponse/204 archive` |
| `POST` | `/api/knowledge/{entry_id}/ingest` | `202 KnowledgeIngestionResponse` |
| `GET` | `/api/knowledge/{entry_id}/ingestion` | `200 KnowledgeIngestionResponse` |
| `GET` | `/api/knowledge/{entry_id}/content` | `KnowledgeContentPreview` |
| `GET` | `/api/knowledge/{entry_id}/download` | private binary response |
| `PUT` | `/api/knowledge/{entry_id}/access` | `KnowledgeAccessUpdate -> KnowledgeResponse` |
| `GET/POST` | `/api/knowledge/{entry_id}/grants` | `KnowledgeGrantCreate -> list/grant` |
| `DELETE` | `/api/knowledge/{entry_id}/grants/{grant_id}` | `204` |
| `POST` | `/api/knowledge/{entry_id}/restore` | `KnowledgeResponse` |
| `DELETE` | `/api/knowledge/{entry_id}/purge` | `204` |
| `GET/POST` | `/api/knowledge/collections` | `KnowledgeCollectionCreate -> list/collection` |
| `PATCH/DELETE` | `/api/knowledge/collections/{id}` | update/`204` |
| `PUT` | `/api/knowledge/{entry_id}/collection` | assignment -> `KnowledgeResponse` |
| `POST` | `/api/knowledge/search` | `KnowledgeSearchRequest -> KnowledgeSearchResponse` |
| `POST` | `/api/knowledge/retrieve` | `KnowledgeRetrieveRequest -> KnowledgeRetrieveResponse` |
| `GET` | `/api/knowledge/citations/{turn_id}/{ordinal}` | authorized citation resolve |
| `GET` | `/api/knowledge/members` | `KnowledgeMemberListResponse` |
| `GET` | `/api/knowledge/fixed-contexts` | immutable fixed context list |
| `GET` | `/api/knowledge/fixed-contexts/{context_id}` | immutable fixed context detail |
| `GET` | `/api/knowledge/operations/overview` | `KnowledgeOperationsOverview` |
| `GET` | `/api/knowledge/operations/jobs` | `KnowledgeOperationJobList` |
| `POST` | `/api/knowledge/operations/jobs/{job_id}/retry` | `KnowledgeOperationJob` |
| `POST` | `/api/knowledge/operations/jobs/{job_id}/cancel` | `KnowledgeOperationJob` |
| `GET` | `/api/audit-events` | `AuditEventListResponse` |

知识库上传上限 50 MiB，只接受 `.pdf/.docx/.xlsx/.pptx/.txt/.md/.html/.csv`，扩展名、MIME 和文件签名必须同时通过。前端的 accept 属性只是体验提示，不能替代后端校验。

`DELETE /knowledge/{id}` 是 archive；永久删除是 `/purge`，且只接受已归档 owner 资源。共享资源的 `content` 可能为 `null`，必须通过 preview/download 再鉴权。`file_path` 永远不应展示。

检索 mode：`hybrid`、`degraded_full_text`、`empty`。降级不是失败；UI 应明确当前结果模式，但不能显示 provider secret 或内部错误。

### 5.5 Work Items、Memory、Skills 和 Reminders

| Method | Path | Request -> Response |
| --- | --- | --- |
| `GET/POST` | `/api/work-items` | query / `WorkItemCreate -> list/item` |
| `GET/PATCH/DELETE` | `/api/work-items/{id}` | `WorkItemUpdate -> item/204` |
| `PATCH` | `/api/work-items/{id}/status` | `WorkItemStatusUpdate -> WorkItemResponse` |
| `GET` | `/api/work-items/{id}/events` | `WorkItemEventListResponse` |
| `GET` | `/api/work-items/events/{event_id}` | `WorkItemEventResponse` |
| `GET/POST` | `/api/memory` | query / `MemoryCreate -> list/item` |
| `GET/PUT/DELETE` | `/api/memory/{memory_id}` | `MemoryUpdate -> item/204` |
| `GET/POST` | `/api/skills` | query / `SkillCreate -> list/item` |
| `GET/PUT/DELETE` | `/api/skills/{skill_id}` | `SkillUpdate -> item/204` |
| `GET` | `/api/skills/hub` | mock hub list |
| `POST` | `/api/skills/generate` | deterministic mock generation |
| `GET/POST` | `/api/reminders` | query / `ReminderCreate -> list/item` |
| `GET` | `/api/reminders/upcoming` | upcoming list |
| `PUT/DELETE` | `/api/reminders/{id}` | `ReminderUpdate -> item/204` |
| `POST` | `/api/reminders/{id}/complete` | `ReminderResponse` |

#### Memory

- PostgreSQL/pgvector 是唯一持久化 memory 权威；所有读写都必须从 `CurrentOrganizationContext` 派生 `organization_id`、`user_id`、成员角色和权限。
- `memory:read` 只允许读取，`memory:write` 才能创建、修改、确认或拒绝候选项。
- 活跃 memory 列表、单条读取、更新、删除、确认和拒绝都必须把跨组织、跨用户、候选、已替换与物理删除记录当成不存在，返回 `404`。
- `GET /api/memory` 是唯一列表/搜索入口，没有 `/api/memory/search`。
- 空 `query` 走活跃 owner 列表；非空 `query` 走授权的 PostgreSQL FTS，vector/RRF 只作为可选补充。
- `MemoryResponse` 只返回 `memory_id`、`content`、`type`、`metadata`、`revision`、`layer`、`status`、`origin`、`source_summary`、`created_at` 和 `updated_at`，不返回 embedding、抓取原文、provider 凭据或内部作业 id。
- 候选项响应可包含 `confidence`、`provider`、`provider_version` 和安全的 `source_ref`；确认接口可带 `supersedes_memory_id`，但只能指向同组织同用户的活跃记录。
- chat session 的 `memory_mode` 默认是 `off`，只有 owner knowledge session 且显式开启 `auto` 才能收到 `AUTHORIZED_MEMORY` 数据块；agent、guest、无权限和候选记录都不能收到 memory 上下文。
- memory 子预算是 2,000 UTF-8 bytes，knowledge + transient + memory 的固定总预算是 12,000 UTF-8 bytes。

Work Item 状态只允许服务端状态机接受的变化：`pending/in_progress/completed/cancelled`。前端不得直接改列表对象后假装成功；事件记录是审计来源。

Skills Hub/generate 以及当前 Mem0 边界可能使用 mock/兼容实现，界面不得宣称外部 provider 已上线。Reminder 目前只有元数据，没有 cron 或外部通知交付承诺。

## 6. Mock 与 Real 模式

| 模式 | 用途 | 网络边界 |
| --- | --- | --- |
| `VITE_USE_MOCK=true` | 组件开发、确定性单测 | 只允许 `/auth/*` 和 `/chat/*` 网络请求；其他领域必须走 mock service |
| `VITE_USE_MOCK=false` | 生产 build、真实 API 联调 | 所有已实现 service 使用真实 API；平台 OAuth/activity 页面仍可能是 presentation-only |

禁止在组件中判断环境后拼两套 URL。Mock/Real 选择必须在 service 层完成，并保持相同 TypeScript 接口。

## 7. 新前端的 service 实现要求

每个领域按以下层次组织：

```text
page/component
  -> hook/query/store
    -> canonical service interface
      -> real adapter / mock adapter
        -> shared API client
```

必须满足：

- 页面不直接调用 Axios/fetch，SSE 和二进制下载除外且仍封装到 service；
- DTO 与 ViewModel 分离，snake_case/camelCase 显式映射；
- 每个新增/变更 operation 有 contract test，断言 method、URL、body/query、header 和响应映射；
- 401 refresh、并发 refresh、custom base URL、logout、组织切换 rollback 保留测试；
- loading、empty、error、forbidden、conflict 和 success 状态都有 UI；
- cache key 必须包含 organizationId；
- AbortController 用于页面卸载、搜索覆盖和 SSE 停止；
- 不在浏览器保存 provider key、SMTP secret、邀请 token 或真实测试数据。

## 8. 联调和验收顺序

1. `/health` 与 `/ready`；
2. login -> `/auth/me` -> organizations；
3. refresh single-flight 与 logout；
4. organization switch + cache isolation；
5. portal/dashboard/organization；
6. knowledge list/upload/ingest/preview/download/grants；
7. chat session -> SSE -> history -> stop/approval/delete；
8. work items、memory、skills、reminders；
9. guest 和跨组织负向测试；
10. 桌面及 390px 移动端、键盘、焦点、console、断网和 409 场景。

本地构建通过不能替代真实 API 联调；Mock 数据通过也不能证明组织权限、SSE、上传下载或 refresh 安全。

## 9. 契约变更提交清单

任何 API 变更必须同时包含：

- FastAPI router/schema；
- OpenAPI snapshot；
- 前端 service interface 和 real adapter；
- TypeScript DTO/ViewModel mapper；
- contract test；
- 页面 loading/error/conflict 行为；
- 权限与组织隔离测试；
- 本文对应章节更新。

`Keyou430` 不得在替换 PR 中自行创建“临时后端路径”。缺失接口应先开 Issue，由 `OneAsmallFish` 确认是新增 API、复用现有 operation，还是保持 presentation/mock。
