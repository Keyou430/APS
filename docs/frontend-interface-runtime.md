# 前端接口与模块运行逻辑

版本：2026-08-14

适用分支：`codex/frontend-replacement`

当前参考 head：`3436467aec73aa945c72d59328bf2bd220278f04`

本文面向后端接入、演示准备和前端后续迁移。它是前端视角的接口索引和运行逻辑说明，不替代权威 OpenAPI。字段必填、枚举、schema、operationId 和后端权限判定，以联调环境 `/openapi.json`、`/docs` 和仓库快照 `backend/docs/openapi.json` 为准。

## 1. 总体边界

- 前端目录：`web-platform/`
- 技术栈目标：React + TypeScript + Vite
- API 默认基址：浏览器同源 `/api`
- 前端 service 内部路径：写 `/auth/login`、`/dashboard`、`/knowledge`，不重复写 `/api`
- 本地代理：Vite 将 `/api` 代理到后端
- 非同源联调：契约目标支持自定义 API baseUrl；当前 `createAuthRuntime()` / `createApiClient()` 已支持 `baseUrl` 注入，但 `main.tsx` 默认安装仍使用 `/api`
- 普通 JSON 请求统一走 `web-platform/src/api/client.ts`
- Chat SSE 走 `web-platform/src/api/services/chatStream.ts`
- token 只进入 `Authorization: Bearer ...` 和 `sessionStorage` 内的 auth session，不进入 URL、`localStorage`、日志或截图

禁止事项：

- 前端不得新增临时后端路由
- 不得伪造真实 `/api/...` 路径
- 不得修改后端、Docker、Nginx、Compose、deploy 或 `.github/**`
- 真实 API 与仓库 OpenAPI 不一致时，应记录 Issue，由后端确认契约

## 2. 运行入口

浏览器启动链路：

```text
index.html
  -> web-platform/src/main.tsx
    -> installAppRuntime(window)
      -> createAuthRuntime()
        -> createApiClient()
        -> createAuthStore(sessionStorage)
        -> createOrganizationCache()
        -> createOrganizationAbortRegistry()
      -> create*Service(auth.client)
      -> window.__agentRuntime
      -> window.__contractAuth
    -> mountReactApp(root)
      -> App
        -> resolveRoute(pathname)
        -> React page 或 LegacyWorkspaceHost
```

当前运行时对象：

```ts
window.__agentRuntime = {
  auth,
  services: {
    chat,
    chatStream,
    audit,
    dashboard,
    enterprise,
    hermes,
    invitations,
    knowledge,
    memory,
    organization,
    reminders,
    skills,
    users,
    workItems,
  },
  security,
  ui,
}
```

普通页面请求链路：

```text
React page
  -> injected service
    -> ApiClient.request(path, options)
      -> normalize baseUrl + path
      -> attach Authorization header
      -> JSON stringify body when needed
      -> fetch()
      -> 401 single-flight refresh when allowed
      -> parse JSON / text / 204
      -> throw ApiError(status, code, details)
```

组织切换链路：

```text
auth.store.switchOrganization()
  -> POST /auth/switch-organization
  -> GET /auth/me with returned access token
  -> commit new session to sessionStorage
  -> invalidate previous organization cache
  -> abort previous organization in-flight work
```

## 3. 路由与页面状态

`web-platform/src/app/routes.tsx` 维护前端路由元数据。`status` 表示迁移状态，`isReactOwnedRoute()` 表示当前是否由 React page 接管首屏。

| 路由 | 模块 | 权限 | 路由状态 | 当前接管 |
| --- | --- | --- | --- | --- |
| `/` | 驾驶舱 Dashboard | `portal:read` | `legacy-host` | Legacy |
| `/portal` | 企业门户 Portal | `portal:read` | `react-ready` | React |
| `/organization` | 组织架构 | `org:read` | `react-ready` | React |
| `/users` | 用户管理 | `users:read` | `react-ready` | React |
| `/invitations` | 邀请管理 | `members:invite` | `react-ready` | React |
| `/hermes` | AI 服务 / Hermes Profiles | `agent:admin` | `react-ready` | React |
| `/knowledge` | 知识库 | `knowledge:read` | `legacy-host` | Legacy |
| `/chat` | 会话 / Chat SSE | `chat:use` | `legacy-host` | Legacy |
| `/work-items` | 工作项 | `work_items:read` | `legacy-host` | Legacy |
| `/memory` | 记忆 | `memory:read` | `react-ready` | 未纳入 React-owned set |
| `/skills` | 技能 | `skills:read` | `react-ready` | 未纳入 React-owned set |
| `/reminders` | 提醒 | `reminders:read` | `react-ready` | 未纳入 React-owned set |

React 页面统一覆盖这些 UI 状态：

- `loading`
- `empty`
- `error`
- `forbidden`
- `conflict`
- `success`

页面不得直接调用 `fetch` 或 Axios。SSE、文件上传下载等特殊传输也必须由 service 封装后再给页面使用。

## 4. Auth 与组织运行逻辑

Service：`web-platform/src/api/services/authService.ts`

Store/runtime：

- `web-platform/src/features/auth/authRuntime.ts`
- `web-platform/src/features/auth/authStore.ts`

接口：

| Method | Path | 用途 |
| --- | --- | --- |
| `POST` | `/api/auth/login` | 登录并取得 token |
| `GET` | `/api/auth/me` | 获取当前用户 profile |
| `POST` | `/api/auth/refresh` | refresh token 单次旋转 |
| `POST` | `/api/auth/logout` | best-effort 注销当前 refresh token |
| `GET` | `/api/auth/organizations` | 当前用户可切换组织 |
| `POST` | `/api/auth/switch-organization` | 切换当前组织 |

关键逻辑：

1. 登录先 `POST /auth/login`，再用新 access token 调 `GET /auth/me`。
2. 两步都成功后才写入 auth store。
3. auth session 存 `sessionStorage` key：`agent-platform.auth`。
4. 401 refresh 使用 single-flight，全局同一时间只发起一次 refresh。
5. `/auth/login`、`/auth/token`、`/auth/refresh`、`/auth/logout` 不触发 refresh loop。
6. logout 无论接口成功或失败，最后都清空本地 session。
7. 组织切换成功后，旧组织 cache invalidate，旧组织 in-flight work abort。

## 5. 模块接口总览

### 5.1 驾驶舱 Dashboard

Service：`web-platform/src/api/services/dashboardService.ts`

当前页面：legacy cockpit route；`DashboardPage.tsx` 和 service tests 保留为后续恢复 React 接管的基础。

| Method | Path | 前端用途 |
| --- | --- | --- |
| `GET` | `/api/dashboard` | 读取驾驶舱数据 |
| `GET` | `/api/dashboard/layout` | 读取布局 |
| `PUT` | `/api/dashboard/layout` | 保存布局，提交 `expectedRevision` |
| `POST` | `/api/dashboard/layout/reset` | 重置布局 |

运行逻辑：

- React 页面恢复接管后，从 `appRuntime.services.dashboard` 获取 service。
- cache key 按 organizationId 隔离。
- 布局写操作必须带 revision；409 时不能覆盖服务端布局。
- 当前不再纳入 React-owned production artifact 验收；驾驶舱演示以 legacy cockpit route 为准。

### 5.2 企业门户 Portal

Service：`web-platform/src/api/services/enterpriseService.ts`

React page：`web-platform/src/pages/PortalPage.tsx`

| Method | Path | 前端用途 |
| --- | --- | --- |
| `GET` | `/api/enterprise/portal` | 读取门户聚合数据 |
| `GET` | `/api/enterprise/announcements` | 公告列表 |
| `POST` | `/api/enterprise/announcements` | 创建公告 |
| `PATCH` | `/api/enterprise/announcements/{id}` | 更新公告 |
| `POST` | `/api/enterprise/announcements/{id}/publish` | 发布公告 |
| `POST` | `/api/enterprise/announcements/{id}/pin` | 置顶公告 |
| `POST` | `/api/enterprise/announcements/{id}/withdraw` | 撤回公告 |
| `POST` | `/api/enterprise/announcements/{id}/read` | 标记已读 |
| `PUT` | `/api/enterprise/portal/todos/{id}` | 更新门户待办 |

运行逻辑：

- Portal 使用 camelCase DTO。
- internal member 且具备 `portal:read` 才能读取。
- 管理动作依赖后端权限，不以隐藏按钮替代权限判断。

### 5.3 组织架构 Organization

Service：`web-platform/src/api/services/organizationService.ts`

React page：`web-platform/src/pages/OrganizationPage.tsx`

| Method | Path | 前端用途 |
| --- | --- | --- |
| `GET` | `/api/organization/structure` | 获取部门、职位、成员、任职记录和 `revision` |
| `POST` | `/api/organization/units` | 创建部门 |
| `PATCH` | `/api/organization/units/{unit_id}` | 更新部门 |
| `DELETE` | `/api/organization/units/{unit_id}` | 删除部门 |
| `POST` | `/api/organization/positions` | 创建职位 |
| `PATCH` | `/api/organization/positions/{position_id}` | 更新职位 |
| `DELETE` | `/api/organization/positions/{position_id}` | 删除职位 |
| `PUT` | `/api/organization/placements/{membership_id}` | 更新单个成员任职 |
| `POST` | `/api/organization/placements/batch` | 批量更新任职 |

运行逻辑：

- 页面无 organizationId 时 fail-closed，不调用 service。
- cache key：`["organization", "structure"]`，由 `organizationId` 分区。
- mutation 使用 `expected_revision`。
- 409 时保留当前结构并提示刷新。
- 当前 React 页面已覆盖读取、删除职位、403、404、409 和移动端展示边界；完整创建/更新/placement UI 仍待后续纵切。

### 5.4 用户管理 Users

Service：`web-platform/src/api/services/usersService.ts`

React page：`web-platform/src/pages/UsersPage.tsx`

| Method | Path | 前端用途 |
| --- | --- | --- |
| `GET` | `/api/users` | 分页读取用户列表 |
| `POST` | `/api/users` | 创建用户 |
| `GET` | `/api/users/{user_id}` | 用户详情 |
| `PUT` | `/api/users/{user_id}` | 更新用户 |
| `DELETE` | `/api/users/{user_id}` | 删除用户 |
| `PUT` | `/api/users/{user_id}/roles` | 分配角色 |

运行逻辑：

- 页面无 organizationId 时 fail-closed，不调用 service。
- cache key：`["users", "directory"]`，由 `organizationId` 分区。
- 当前列表请求默认 `{ page: 1, page_size: 20 }`。
- 403 后禁用用户管理动作。
- 移动端表格保留 `aria-label`，不渲染可见 caption，避免 390px 竖排文字。

### 5.5 邀请管理 Invitations

Service：`web-platform/src/api/services/invitationsService.ts`

React page：`web-platform/src/pages/InvitationsPage.tsx`

| Method | Path | 前端用途 |
| --- | --- | --- |
| `GET` | `/api/invitations` | 邀请列表 |
| `POST` | `/api/invitations` | 创建邀请 |
| `POST` | `/api/invitations/{id}/revoke` | 撤销邀请 |
| `POST` | `/api/invitations/{id}/regenerate` | 重新生成邀请 |
| `POST` | `/api/invitations/accept` | 接受邀请 |
| `POST` | `/api/invitations/guest-memberships/{id}/revoke` | 撤销 guest membership |

运行逻辑：

- 管理权限依赖 `members:invite`。
- 邀请 token 不能进入 query、日志、analytics 或截图。
- 接受邀请场景应只从 URL fragment 或受控测试响应读取 token。

### 5.6 AI 服务 / Hermes Profiles

Service：`web-platform/src/api/services/hermesService.ts`

React page：`web-platform/src/pages/HermesPage.tsx`

| Method | Path | 前端用途 |
| --- | --- | --- |
| `POST` | `/api/hermes/profiles` | 创建或更新 Hermes profile |
| `GET` | `/api/hermes/profiles/{user_id}` | 获取用户 profile |
| `DELETE` | `/api/hermes/profiles/{user_id}` | 删除 profile |
| `GET` | `/api/hermes/profiles/{user_id}/health` | 读取 profile 健康状态 |

运行逻辑：

- 权限边界：`agent:admin`。
- 页面展示 profile、健康状态和错误状态。
- 当前已纳入 production artifact 多断点截图验收。
- 页面不得宣称外部 provider、Agent runtime 或密钥已在前端可控上线；真实能力由后端确认。

### 5.7 Chat 与 SSE

JSON service：`web-platform/src/api/services/chatService.ts`

SSE service：`web-platform/src/api/services/chatStream.ts`

当前页面：legacy host 迁移期

| Method | Path | 前端用途 |
| --- | --- | --- |
| `POST` | `/api/chat/attachments` | 上传会话附件 |
| `POST` | `/api/chat/link-preview` | 获取链接预览 |
| `GET` | `/api/chat/sessions` | 会话列表 |
| `POST` | `/api/chat/sessions` | 创建会话 |
| `DELETE` | `/api/chat/sessions/{session_id}` | 删除会话 |
| `GET` | `/api/chat/sessions/{session_id}/messages` | 历史消息 |
| `POST` | `/api/chat/sessions/{session_id}/messages` | 发送消息并读取 SSE |
| `PUT` | `/api/chat/sessions/{session_id}/knowledge-scope` | 更新知识范围 |
| `POST` | `/api/chat/sessions/{session_id}/runs/{run_id}/stop` | 停止 run |
| `POST` | `/api/chat/sessions/{session_id}/runs/{run_id}/approval` | 处理 approval |

SSE 运行逻辑：

- 请求头：`Accept: text/event-stream`
- 请求头：`Content-Type: application/json`
- token 仅放 `Authorization`
- `AbortSignal` 由调用方传入，用于中断流
- 只有 terminal event 才能结束 loading
- 断流但无 terminal event 时，UI 必须显示 interrupted/retry，不得伪装完成

必须处理的事件包括：

- `run.created`
- `response.output_text.delta`
- `tool.*`
- `approval.request`
- `knowledge.context`
- `response.completed`
- `response.failed`
- `response.cancelled`
- `upstream.disconnected`

### 5.8 知识库 Knowledge

Service：`web-platform/src/api/services/knowledgeService.ts`

当前页面：legacy host 迁移期

| Method | Path | 前端用途 |
| --- | --- | --- |
| `GET` | `/api/knowledge` | 列表 |
| `POST` | `/api/knowledge` | 创建知识条目 |
| `POST` | `/api/knowledge/upload` | 文件上传 |
| `GET` | `/api/knowledge/{entry_id}` | 详情 |
| `PUT` | `/api/knowledge/{entry_id}` | 更新 |
| `DELETE` | `/api/knowledge/{entry_id}` | 归档 |
| `POST` | `/api/knowledge/{entry_id}/ingest` | 触发 ingest |
| `GET` | `/api/knowledge/{entry_id}/ingestion` | ingest 状态 |
| `GET` | `/api/knowledge/{entry_id}/content` | preview |
| `GET` | `/api/knowledge/{entry_id}/download` | 下载 |
| `PUT` | `/api/knowledge/{entry_id}/access` | 更新访问策略 |
| `GET` | `/api/knowledge/{entry_id}/grants` | grant 列表 |
| `POST` | `/api/knowledge/{entry_id}/grants` | 创建 grant |
| `DELETE` | `/api/knowledge/{entry_id}/grants/{grant_id}` | 删除 grant |
| `POST` | `/api/knowledge/search` | 搜索 |
| `POST` | `/api/knowledge/retrieve` | RAG retrieve |
| `GET` | `/api/knowledge/citations/{turn_id}/{ordinal}` | citation resolve |
| `GET` | `/api/knowledge/operations/overview` | operations 总览 |
| `GET` | `/api/knowledge/operations/jobs` | operations jobs |
| `POST` | `/api/knowledge/operations/jobs/{job_id}/retry` | 重试 job |
| `POST` | `/api/knowledge/operations/jobs/{job_id}/cancel` | 取消 job |

运行逻辑：

- 上传由 `FormData` 承载，浏览器生成 multipart boundary。
- 下载必须按二进制响应处理，不展示 `file_path`。
- `content` 为 `null` 不代表无权限通过；preview/download/citation 仍需后端鉴权。
- search/retrieve 的降级模式不是失败，但 UI 不得展示 provider secret 或内部错误。

### 5.9 Work Items

Service：`web-platform/src/api/services/workItemsService.ts`

当前页面：legacy host 迁移期

| Method | Path | 前端用途 |
| --- | --- | --- |
| `GET` | `/api/work-items` | 列表 |
| `POST` | `/api/work-items` | 创建 |
| `GET` | `/api/work-items/{id}` | 详情 |
| `PATCH` | `/api/work-items/{id}` | 更新 |
| `DELETE` | `/api/work-items/{id}` | 删除 |
| `PATCH` | `/api/work-items/{id}/status` | 状态流转 |
| `GET` | `/api/work-items/{id}/events` | item events |
| `GET` | `/api/work-items/events/{event_id}` | event detail |

运行逻辑：

- 状态只能由后端状态机接受：`pending`、`in_progress`、`completed`、`cancelled`。
- 前端不能直接改列表对象假装成功。
- events 是审计来源。

### 5.10 Memory / Skills / Reminders

Services：

- `web-platform/src/api/services/memoryService.ts`
- `web-platform/src/api/services/skillsService.ts`
- `web-platform/src/api/services/remindersService.ts`

当前状态：service 和 contract tests 已存在；页面级 React 接管仍需按后续纵切确认。

| 模块 | Method / Path | 前端用途 |
| --- | --- | --- |
| Memory | `GET /api/memory` | 列表 |
| Memory | `POST /api/memory` | 创建 |
| Memory | `GET /api/memory/{memory_id}` | 详情 |
| Memory | `PUT /api/memory/{memory_id}` | 更新 |
| Memory | `DELETE /api/memory/{memory_id}` | 删除 |
| Skills | `GET /api/skills` | 列表 |
| Skills | `POST /api/skills` | 创建 |
| Skills | `GET /api/skills/{skill_id}` | 详情 |
| Skills | `PUT /api/skills/{skill_id}` | 更新 |
| Skills | `DELETE /api/skills/{skill_id}` | 删除 |
| Skills | `GET /api/skills/hub` | hub 列表，当前有 mock/兼容边界 |
| Skills | `POST /api/skills/generate` | deterministic mock generation |
| Reminders | `GET /api/reminders` | 列表 |
| Reminders | `POST /api/reminders` | 创建 |
| Reminders | `GET /api/reminders/upcoming` | upcoming |
| Reminders | `PUT /api/reminders/{id}` | 更新 |
| Reminders | `DELETE /api/reminders/{id}` | 删除 |
| Reminders | `POST /api/reminders/{id}/complete` | 完成 |

运行逻辑：

- Skills Hub/generate 不得被前端描述为真实外部 provider 已上线。
- Reminder 目前只有元数据，不承诺 cron 或外部通知交付。

### 5.11 Audit

Service：`web-platform/src/api/services/auditService.ts`

| Method | Path | 前端用途 |
| --- | --- | --- |
| `GET` | `/api/audit-events` | 审计事件列表 |

运行逻辑：

- 读取权限：`audit:read`
- 前端无写操作

## 6. 错误与权限约定

后端普通错误格式：

```json
{
  "error": {
    "code": "http_404",
    "message": "Resource not found"
  }
}
```

后端校验错误格式：

```json
{
  "error": {
    "code": "validation_error",
    "message": "Request validation failed",
    "details": []
  }
}
```

前端统一行为：

| 状态 | 前端处理 |
| --- | --- |
| `400` | 展示输入或业务错误，不自动重试 |
| `401` | 非 auth endpoint 触发 refresh，一次失败后清空 session |
| `403` | 显示无权限，不靠隐藏按钮替代后端权限 |
| `404` | 显示不存在或被跨组织隐藏 |
| `409` | 保留当前 UI/草稿，提示刷新或拉取最新 revision |
| `413` | 显示文件过大 |
| `422` | 显示字段校验或格式错误 |
| `429/5xx` | GET/HEAD/OPTIONS 可有限重试；写操作不自动重放 |

## 7. 数据命名与映射

- Auth、Knowledge、Organization 等 DTO 主要使用 `snake_case`。
- Portal、Dashboard、Work Items 使用后端 Pydantic alias，网络 DTO 为 `camelCase`。
- 不做全局字段名自动转换。
- 每个 service 或 page mapper 显式完成 DTO -> ViewModel 映射。
- `null`、字段缺失和空数组含义不同，前端不得随意合并。

## 8. 缓存、Abort 与组织隔离

前端缓存由 `createOrganizationCache()` 提供，页面使用方式是：

```text
cache.get(organizationId, parts)
cache.set(organizationId, parts, value)
cache.invalidateOrganization(organizationId)
```

约束：

- 所有业务缓存必须包含 organizationId。
- 组织切换后必须 invalidate 旧组织缓存。
- 组织切换后必须 abort 旧组织 in-flight work。
- 页面无 organizationId 时 fail-closed，不调用真实 service。
- 不允许用 URL 参数、缓存角色或默认组织替代后端 access token 中的 organizationId。

当前已落地示例：

| 页面 | cache parts |
| --- | --- |
| Dashboard | Dashboard 页面内部组织隔离缓存 |
| Portal | Portal 页面内部组织隔离缓存 |
| Organization | `["organization", "structure"]` |
| Users | `["users", "directory"]` |
| Hermes | Hermes 页面内部组织隔离缓存 |

## 9. Mock / Real 模式

| 模式 | 用途 | 网络边界 |
| --- | --- | --- |
| `VITE_USE_MOCK=true` | 组件开发、确定性单测 | 只允许 `/auth/*` 与 `/chat/*` 真实网络；其他领域必须走 mock service |
| `VITE_USE_MOCK=false` | 生产 build、真实 API 联调 | 已实现 service 使用真实 API |

Production artifact 测试会 fail-closed：非允许的意外真实请求会使测试失败。

## 10. 演示与后端联调建议

当前可优先演示并让后端对齐的模块：

1. 企业门户 Portal
2. 组织架构 Organization
3. 用户管理 Users
4. 邀请管理 Invitations
5. AI 服务 / Hermes Profiles
6. 驾驶舱 Dashboard legacy cockpit route

真实 API 联调建议顺序：

1. `/health`、`/ready`
2. login -> `/auth/me` -> `/auth/organizations`
3. refresh single-flight 与 logout
4. organization switch + cache isolation
5. Dashboard / Portal / Organization / Users / Invitations / Hermes
6. Knowledge list/upload/preview/download/grants/citation
7. Chat session -> SSE -> history -> stop/approval/delete
8. Work Items / Memory / Skills / Reminders
9. guest、跨组织、403、404、409、断网
10. 320/390/414/768/1280/1440 截图、键盘、焦点、console、a11y/security

## 11. 当前未完成风险

- PR #7 仍应保持 Draft，直到真实 API 验收、截图、a11y/security、review 全部完成。
- Knowledge、Chat、Work Items 仍处于页面级迁移未完成状态。
- Memory、Skills、Reminders 虽有 service/contract tests，但 React-owned 页面接管仍需继续核对。
- Dashboard、Portal、Organization、Users、Invitations、Hermes 的 mock/contract artifact 通过，不等于真实 API 权限、组织隔离、SSE、上传下载已经验收。
- 后端若发现契约缺口，应在 Issue 中记录 operationId、页面场景、request/response/error、权限要求，再决定是否更新后端和 OpenAPI。
