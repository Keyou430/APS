# 源前端完整替换实施计划

> **供 Agent 执行：** 必须使用 `executing-plans` 或 `subagent-driven-development`，按任务逐项完成并更新复选框。

**目标：** 将星纪云源前端完整迁入 Replica，并在不改变源界面和导航行为的前提下接通当前 FastAPI 后端。

**架构：** 先把源目录作为 UI 真源镜像到 `web-platform`，再仅在 API、认证和 DTO 边界应用当前后端需要的适配。旧版 DOM 工作台和 React 路由页的双栈结构保持不变，驾驶舱/门户子菜单定位卡片、复合页签和高亮行为直接沿用源实现。

**技术栈：** React 19、TypeScript 6、Vite 8、Vitest、Playwright、原生 JavaScript、GridStack、FastAPI。

---

## 文件边界

- 整体替换：`web-platform/index.html`、`web-platform/styles.css`、`web-platform/public/**`、`web-platform/src/**`、前端配置、前端测试。
- 不镜像生成物：`web-platform/node_modules`、`web-platform/dist`、`web-platform/test-results`。
- 后端适配：`src/api/client.ts`、指定 `src/api/services/*.ts` 及对应测试、`src/app.js` 单用户认证块。
- 保持源实现：导航 DOM、菜单文字、子菜单、卡片布局、页签、路由归属、页面和 CSS。
- 不修改：`backend/**`、`deploy/**`、根目录其他源码及用户现有后端改动。

### 任务 1：建立可恢复快照并镜像源前端

**文件：**

- 来源：`D:\星纪云v1.0\agent-platform-system\web-platform\**`
- 替换：`D:\Replica1.0\web-platform\**`
- 备份：`D:\Replica1.0-backups\20260827-web-platform-before-source-replacement\**`

- [ ] **步骤 1：验证绝对路径和替换范围**

运行：

```powershell
$source = (Resolve-Path -LiteralPath 'D:\星纪云v1.0\agent-platform-system\web-platform').Path
$target = (Resolve-Path -LiteralPath 'D:\Replica1.0\web-platform').Path
if ($source -ne 'D:\星纪云v1.0\agent-platform-system\web-platform') { throw "源路径异常：$source" }
if ($target -ne 'D:\Replica1.0\web-platform') { throw "目标路径异常：$target" }
```

预期：无输出且退出码为 0。

- [ ] **步骤 2：备份当前前端源码和未提交文件**

运行：

```powershell
$backup = 'D:\Replica1.0-backups\20260827-web-platform-before-source-replacement'
if (Test-Path -LiteralPath $backup) { throw "备份目录已存在：$backup" }
New-Item -ItemType Directory -Path $backup | Out-Null
robocopy 'D:\Replica1.0\web-platform' $backup /E /XD node_modules dist test-results /R:1 /W:1
if ($LASTEXITCODE -gt 7) { throw "前端备份失败：$LASTEXITCODE" }
```

预期：`robocopy` 退出码为 0 至 7，备份目录包含当前前端源码。

- [ ] **步骤 3：将源前端镜像到目标目录**

运行：

```powershell
robocopy 'D:\星纪云v1.0\agent-platform-system\web-platform' 'D:\Replica1.0\web-platform' /MIR /XD node_modules dist test-results /R:1 /W:1
if ($LASTEXITCODE -gt 7) { throw "源前端镜像失败：$LASTEXITCODE" }
```

预期：当前前端独有源码被移除，源前端源码完整复制，依赖和生成目录不参与镜像。

- [ ] **步骤 4：验证关键 UI 文件与源文件完全一致**

运行：

```powershell
$files = @('index.html', 'styles.css', 'src\legacy-entry.ts', 'src\app.js')
foreach ($file in $files) {
  $sourceHash = (Get-FileHash -LiteralPath (Join-Path 'D:\星纪云v1.0\agent-platform-system\web-platform' $file) -Algorithm SHA256).Hash
  $targetHash = (Get-FileHash -LiteralPath (Join-Path 'D:\Replica1.0\web-platform' $file) -Algorithm SHA256).Hash
  if ($sourceHash -ne $targetHash) { throw "文件不一致：$file" }
}
```

预期：无输出且退出码为 0。

### 任务 2：先恢复后端契约测试

**文件：**

- 恢复：`web-platform/tests/single_user_auth_mode.test.js`
- 修改：`web-platform/src/api/services/dashboardService.test.ts`
- 修改：`web-platform/src/api/services/pipelineService.test.ts`
- 修改：`web-platform/src/api/services/usersService.test.ts`
- 修改：`web-platform/src/api/services/chatService.test.ts`
- 修改：`web-platform/src/api/services/knowledgeService.test.ts`

- [ ] **步骤 1：从备份恢复已验证的后端契约测试**

仅复制下列测试文件，不复制页面、样式或应用外壳：

```powershell
$backup = 'D:\Replica1.0-backups\20260827-web-platform-before-source-replacement'
$target = 'D:\Replica1.0\web-platform'
$tests = @(
  'tests\single_user_auth_mode.test.js',
  'src\api\services\dashboardService.test.ts',
  'src\api\services\pipelineService.test.ts',
  'src\api\services\usersService.test.ts',
  'src\api\services\chatService.test.ts',
  'src\api\services\knowledgeService.test.ts'
)
foreach ($file in $tests) {
  Copy-Item -LiteralPath (Join-Path $backup $file) -Destination (Join-Path $target $file) -Force
}
```

- [ ] **步骤 2：运行测试并确认后端契约适配尚未实现**

运行：

```powershell
npm test
npx vitest run src/api/services/dashboardService.test.ts src/api/services/pipelineService.test.ts src/api/services/usersService.test.ts src/api/services/chatService.test.ts src/api/services/knowledgeService.test.ts
```

预期：单用户模式测试或 TypeScript 契约测试失败，证明镜像后的源实现尚未包含当前后端适配。

### 任务 3：实现最小后端契约适配

**文件：**

- 修改：`web-platform/src/api/client.ts`
- 修改：`web-platform/src/api/services/dashboardService.ts`
- 修改：`web-platform/src/api/services/pipelineService.ts`
- 修改：`web-platform/src/api/services/usersService.ts`
- 修改：`web-platform/src/api/services/chatService.ts`
- 修改：`web-platform/src/api/services/knowledgeService.ts`
- 修改：`web-platform/src/api/services/enterpriseService.ts`
- 修改：`web-platform/src/app.js`

- [ ] **步骤 1：恢复纯 API/DTO 适配文件**

这些文件与源项目的差异只包含后端契约，不包含界面结构。运行：

```powershell
$backup = 'D:\Replica1.0-backups\20260827-web-platform-before-source-replacement'
$target = 'D:\Replica1.0\web-platform'
$adapters = @(
  'src\api\client.ts',
  'src\api\services\dashboardService.ts',
  'src\api\services\pipelineService.ts',
  'src\api\services\usersService.ts',
  'src\api\services\chatService.ts',
  'src\api\services\knowledgeService.ts',
  'src\api\services\enterpriseService.ts'
)
foreach ($file in $adapters) {
  Copy-Item -LiteralPath (Join-Path $backup $file) -Destination (Join-Path $target $file) -Force
}
```

必须保留的契约内容：

```ts
// client.ts：匿名单用户请求出现 401 时不得无 Token 刷新。
options.refresh && token

// chatService.ts
export type KnowledgeScopeUpdate =
  | { mode: "selected"; source_ids: number[] }
  | { mode: "all_visible" | "none"; source_ids: [] };

// usersService.ts
export type UserRole = "admin" | "manager" | "user";
export type UserCreate = { username: string; password: string; email: string; role?: UserRole };
export type UserUpdate = { username?: string; email?: string | null; is_active?: boolean };
export type RoleAssignment = { role: UserRole };

// dashboardService.ts / pipelineService.ts
export type DashboardDecisionApprovePayload = { comment?: string };
export type PipelineApprovePayload = { comment?: string };

// knowledgeService.ts
type NumericString = `${number}`;
resolveCitation(turnId: number | NumericString, ordinal: number): Promise<KnowledgeCitationResolveResponse>;
```

- [ ] **步骤 2：在源 `app.js` 中应用单用户认证适配**

保留源文件全部导航与 UI 代码，只加入以下认证行为：

```js
const SINGLE_USER_MODE = true
const singleUserFallback = {
  id: 0,
  username: "admin",
  display_name: "admin",
  email: null,
  default_org_id: "0",
  default_dept_id: null,
  roles: ["admin", "super_admin"],
  permissions: ["*"],
  must_change_password: false,
}

function applySingleUserFallback() {
  if (!SINGLE_USER_MODE) return false
  _authToken = null
  _authUser = { ...singleUserFallback }
  window.App = window.App || {}
  window.App._authToken = null
  window.App._authUserId = _authUser.id
  _syncAuthModule(null, _authUser)
  updateAuthUI()
  return true
}

async function restoreSingleUserIdentity() {
  _authToken = null
  window.App = window.App || {}
  window.App._authToken = null
  _syncAuthModule(null, _authUser)
  await loadCurrentUser()
  return _authUser !== null || applySingleUserFallback()
}
```

同时完成这些窄范围调整：`loadCurrentUser()` 无 Token 也请求 `/auth/me`；请求头仅在
Token 存在时附加；`isLoggedIn()` 以 `_authUser` 判断；无 Token 时不刷新；退出登录
恢复本地单用户；管理员入口不再被登录门禁重定向；聊天 401 仅在非单用户模式显示
登录过期；用户按钮直接打开资料菜单。

- [ ] **步骤 3：运行聚焦测试**

运行：

```powershell
npm test
npx vitest run src/api/services/dashboardService.test.ts src/api/services/pipelineService.test.ts src/api/services/usersService.test.ts src/api/services/chatService.test.ts src/api/services/knowledgeService.test.ts
```

预期：全部通过。

### 任务 4：验证源导航行为没有被适配破坏

**文件：**

- 验证：`web-platform/index.html`
- 验证：`web-platform/src/app.js`
- 验证：`web-platform/tests/portal_workbench.test.js`

- [ ] **步骤 1：运行源导航契约测试**

运行：

```powershell
node --test tests/portal_workbench.test.js tests/platform_contracts.test.js tests/production_artifact.test.js
```

预期：子菜单 `data-scroll-target`、复合页签、AI 服务菜单和生产入口契约全部通过。

- [ ] **步骤 2：静态核对卡片导航实现仍来自源项目**

运行：

```powershell
rg -n "function openSubTab|compoundView|scrollIntoView|cockpit-flash|data-scroll-target" src/app.js index.html
```

预期：`openSubTab` 包含复合页签、滚动、高亮及侧栏同步逻辑，`index.html` 包含驾驶舱和门户卡片目标。

### 任务 5：执行全量构建和前后端契约验证

**文件：**

- 验证：`web-platform/**`
- 只读验证：`backend/tests/**`

- [ ] **步骤 1：安装锁定依赖并运行前端验证**

运行：

```powershell
npm ci
npm test
npx vitest run
npm run build
npm run lint
```

预期：Node 测试、Vitest、TypeScript、Vite 构建和 ESLint 全部通过。

- [ ] **步骤 2：运行关键后端契约测试**

运行：

```powershell
..\backend\.venv\Scripts\python.exe -m pytest -q ..\backend\tests\test_single_user_mode.py ..\backend\tests\test_pipeline_approval_contract.py ..\backend\tests\test_chat_platform_actions.py
```

预期：全部通过；若仓库虚拟环境不存在，则使用当前可用 Python 环境运行相同测试并记录环境差异。

### 任务 6：浏览器验证与交付

**文件：**

- 验证：运行中的前端和后端
- 生成：`web-platform/test-results/**`（不提交）

- [ ] **步骤 1：启动前后端开发服务器**

后端使用 8000 端口，前端使用首个可用 Vite 端口。确认 `/api/auth/me`、门户数据和驾驶舱数据返回成功。

- [ ] **步骤 2：在桌面和移动视口验证关键交互**

浏览器检查：主导航切换、驾驶舱子菜单定位 KPI/决策/任务/文档/快捷入口、门户子菜单定位对应卡片、复合页签创建和关闭、目标卡片高亮、AI 服务菜单保持会话窗口、移动端无重叠和空白页面。

- [ ] **步骤 3：检查最终差异**

运行：

```powershell
git diff --check
git status --short
git diff --stat -- web-platform
```

预期：差异仅包含源前端替换、明确列出的后端适配和测试；后端原有未提交修改未被本任务改写。
