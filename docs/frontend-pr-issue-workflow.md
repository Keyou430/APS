# 前端 Issue、分支与 Pull Request 流程

版本：2026-08-11

仓库：`OneAsmallFish/agent-platform-system`

前端替换分支：`codex/frontend-replacement`

本文用于本次“采用 `Keyou430` 版本并替换现有前端”的大型改造，也作为后续普通前端需求的提交规范。

### 固定职责

- `Keyou430`：前端负责人，只负责 `web-platform/`、前端 API 适配、前端类型以及前端测试和相关说明；
- `OneAsmallFish`：仓库维护者，负责除前端以外的全部工作，包括后端、Agent、知识库/RAG、数据库、Docker、Nginx、部署、CI/CD、仓库设置、API 契约确认和最终合并；
- `qiang880`：项目管理，以只读权限查看进度、里程碑、风险和验证证据，不执行任何仓库写操作。

## 1. 已确定的分支策略

本次改造**不直接合并成员代码到 `main`**，也不新建永久 `frontend-main`。

采用以下方式：

```text
main
  └─ codex/frontend-replacement   # 临时大型功能分支
       └─ Draft PR -> main        # 从第一批代码开始持续展示
```

理由：

- 两套前端差异大，直接覆盖无法逐步审阅和回滚；
- `main` 必须一直保持可构建、可测试；
- 临时分支允许按里程碑提交，同时保留一个完整 Draft PR；
- 最终合并后自动删除分支，不产生长期双主线；
- 旧前端由 Git 历史保留，不复制成 `web-platform-old/`。

普通小需求仍从最新 `main` 创建独立短分支，不继续复用 replacement 分支。

## 2. GitHub 权限与仓库设置

### 2.1 当前权限审计

截至 2026-08-11：

| 账号 | 权限 | 说明 |
| --- | --- | --- |
| `OneAsmallFish` | `admin` | 仓库维护者；负责全部非前端工作、API 契约、保护规则、合并和发布 |
| `Keyou430` | `write` | 前端负责人；在非保护分支提交前端代码并维护前端 PR |
| `qiang880` | `read`（邀请待接受） | 项目管理；可查看代码、Issue、PR 和 Actions，不执行仓库写操作 |

`write` 是 `Keyou430` 的正确权限：可以创建/push 非保护分支、开 Issue/PR 和触发 Actions，但不能修改仓库设置、读取 secret 值、部署或绕过 `main` 保护。不授予 `maintain/admin`。`qiang880` 只授予 `read`，用于查看仓库内容和进度，不授予 `triage/write/maintain/admin`。

`Keyou430` 已是 collaborator。若 `git push` 返回 403，先检查本机 GitHub 账号和 SSH key 是否对应 `Keyou430`，不要共享维护者 token、SSH key 或登录信息。`qiang880` 的 `read` 邀请已发送，须由本人接受后生效；若邀请显示的不是 `read`，不得接受，应由 `OneAsmallFish` 撤销并重发。

### 2.2 `main` 保护规则

`main` 当前要求：

- 分支必须与最新 `main` 同步（strict）；
- 五项 GitHub Actions check-run context 必须通过：
  - `quality`（frontend workflow）；
  - `test`（backend workflow）；
  - `sqlite`（migration workflow）；
  - `postgres`（migration workflow）；
  - `config`（compose workflow）；
- 至少 1 名非作者 reviewer 批准；
- 新 push 后旧审批失效，并要求最后一次 push 由其他人批准；
- 所有 review conversations 必须解决；
- 管理员同样受保护；
- 禁止 force push 和删除 `main`。

`CODEOWNERS` 仍用于自动请求 `OneAsmallFish` 审核 `web-platform/**`，但不再强制“必须 CODEOWNER 批准”。小团队中维护者自己发 PR 时无法批准自己的 PR；保留独立 1 人审批门禁可以避免该死锁。成员提交前端 PR 时，维护者仍应作为主要 reviewer。

仓库合并后自动删除 head branch。Actions 默认 token 为只读，workflow 不允许代替人工批准 PR。仓库仅允许 GitHub 自有 Action 和 Marketplace verified publisher Action；新增未验证第三方 Action 必须先由维护者审阅来源和版本并显式批准。

Dependabot vulnerability alerts 与自动安全更新已启用。当前没有 GitHub Environment，因为仓库尚无自动 CD；未来接入测试/生产部署前由 `OneAsmallFish` 分别建立受保护 Environment、审批人和最小权限 secret，不能把部署 secret 交给 `write` 协作者或写入仓库变量。

## 3. Issue 流程

### 3.1 先建父 Issue

大型前端替换先创建一个 `enhancement` Issue，标题建议：

```text
[Frontend] Replace web-platform implementation against platform API contracts
```

父 Issue 必须包含：

```markdown
## 背景
为什么采用新前端，当前用户问题是什么。

## 范围
- 页面/路由：
- 复用的现有组件：
- 计划删除的旧实现：
- 明确不做：

## API 契约
- OpenAPI operations：
- 请求/响应 schema：
- 认证与 permissions：
- organization/guest 边界：
- SSE/上传/下载/409 等特殊行为：

## UI 状态
- loading
- empty
- error/forbidden
- success
- desktop / 390px

## 验收
- [ ] contract tests
- [ ] component tests
- [ ] lint/build
- [ ] real API E2E
- [ ] accessibility/console

## 风险与回滚
- 风险：
- 回滚 commit/artifact：
```

Issue 中不得粘贴 `.env`、JWT、access/refresh token、邀请 token、真实账号密码、生产响应或真实用户数据。

父 Issue 和前端子 Issue 默认指派给 `Keyou430`。`Keyou430` 在 Issue/PR 中记录技术进度、阻塞和验证证据；`OneAsmallFish` 负责确认 API、非前端依赖和验收结论。`qiang880` 可在 GitHub 只读查看这些内容，也可在仓库外接收摘要，但不在 GitHub 中建 Issue、评论、分派、review 或变更状态。

### 3.2 按里程碑拆子 Issue

建议拆分：

1. `M0`：导入新前端骨架、依赖和构建；
2. `M1`：路由、布局、主题、响应式和可访问性；
3. `M2`：登录、refresh、logout、组织切换和权限导航；
4. `M3`：Portal、Dashboard、Organization、Users；
5. `M4`：Knowledge、上传下载、授权、Chat SSE；
6. `M5`：Work Items、Memory、Skills、Reminders、Invitation；
7. `M6`：真实 API 联调、跨组织/guest、桌面/移动验收和旧实现清理。

每个子 Issue 只描述一个可验收结果。纯缺陷使用 `bug`，功能使用 `enhancement`，只改文档使用 `documentation`。不使用 `good first issue` 标记高风险认证、组织或知识授权工作。

### 3.3 Issue 状态

- `Open`：尚未验收；
- PR 中写 `Refs #123`：关联但不自动关闭；
- 只有最终验收完成时使用 `Closes #123`；
- 外部环境、账号或后端接口未就绪时保持 Open，并写清 owner 和解除条件；
- 不用“代码已写”代替“已验证”。

## 4. 开始开发

维护者已经从合并后的 `main@25dbd67` 创建 replacement 分支。`Keyou430` 执行：

```powershell
git clone https://github.com/OneAsmallFish/agent-platform-system.git
cd agent-platform-system
git fetch origin --prune
git switch --track origin/codex/frontend-replacement
git status --short
```

若本地已存在仓库：

```powershell
git fetch origin --prune
git switch codex/frontend-replacement
git pull --ff-only origin codex/frontend-replacement
```

开始前必须确认 `git status --short` 为空。不得在维护者的 dirty 工作区开发，也不得从合并前的 `codex/hermes-platform-integration` 继续。

## 5. 导入成员前端的规则

成员代码应替换同一个 `web-platform/`，不要新增第二个永久应用目录。

导入时禁止提交：

- 原项目的 `.git/`；
- `node_modules/`、`dist/`、coverage、缓存；
- `.env*` 中的真实地址或 secret；
- IDE 用户配置；
- Playwright storage/auth state；
- 本地数据库、日志、截图临时文件；
- 不明来源的二进制或未确认许可证的素材。

建议按提交分层：

```text
chore(web): import selected frontend baseline
build(web): align dependencies and vite contract
feat(web): connect auth and organization context
feat(web): connect portal and dashboard APIs
feat(web): connect knowledge and chat streaming
test(web): close replacement acceptance matrix
```

第一笔 import commit 只完成源码、依赖和 build，不同时重写 API。依赖变化单独提交并保留 `package-lock.json`。不要删除现有 contract tests；若技术栈变化，先移植等价测试再删除旧测试。

## 6. API 和职责边界

`Keyou430` 可直接修改：

- `web-platform/**`；
- 前端 contract/component/Playwright tests；
- 与本次前端实现直接相关的说明文档；API 契约结论仍须 `OneAsmallFish` 确认。

以下内容由 `OneAsmallFish` 负责。`Keyou430` 发现需求时先开 Issue，不直接修改：

- FastAPI router/schema；
- 数据库模型或 migration；
- Agent/Hermes 运行时；
- 知识库/RAG 后端、worker、索引和存储；
- organization/membership/guest/grant 权限；
- refresh/logout、Chat SSE、run stop/approval；
- 上传下载限制、外部 URL allowlist；
- `deploy/**`，包括 frontend Dockerfile、Nginx、Compose、secret 和生产部署；
- `.github/**`、分支保护、Actions、Environment 和仓库设置。

缺少 API 时不得在前端伪造 `/api/...` 路径。Issue 中附 operationId、期望 request/response/error、权限和页面状态，由 `OneAsmallFish` 确认并在需要时先更新后端与 OpenAPI，再由 `Keyou430` 接入。

## 7. Pull Request 流程

### 7.1 立即建立 Draft PR

第一批文档/骨架推送后，从 `codex/frontend-replacement` 向 `main` 创建 Draft PR。Draft PR 用于持续 review，不代表允许提前合并。

标题建议：

```text
[frontend] replace web platform implementation
```

PR 描述必须使用仓库模板并补充：

- 父 Issue 和本次完成的子 Issue；
- 页面、路由、组件和删除范围；
- 使用的 OpenAPI operations；
- DTO/ViewModel 映射；
- permissions、organization、guest 行为；
- loading/empty/error/409/offline 状态；
- 桌面和 390px 截图；
- 测试命令与文件/测试数量；
- 未覆盖项、风险和回滚 commit。

### 7.2 提交前检查

```powershell
git status --short
git diff --check
git diff -- web-platform docs .github

cd web-platform
npm ci
npm audit --omit=dev --audit-level=high
npm run lint
npm run test:ci
npm run build
```

只暂存声明文件：

```powershell
git add web-platform/src/pages/ExamplePage.tsx
git add web-platform/src/pages/ExamplePage.test.tsx
git diff --cached --check
git commit -m "feat(web): connect example page"
git push origin codex/frontend-replacement
```

不要使用 `git add -A`，不要 force push。需要修正历史时新增 commit；是否 squash 由合并阶段决定。

### 7.3 Required checks

每个针对 `main` 的 PR 都会运行五项 required checks，即使只修改前端或文档：

| Context | 内容 |
| --- | --- |
| `quality` | npm ci、audit、lint、串行 Vitest、real build、dist artifact |
| `test` | backend Ruff、pytest、OpenAPI snapshot check |
| `sqlite` | fresh migration、schema assertion、Alembic check |
| `postgres` | PostgreSQL+pgvector upgrade、assert、downgrade/upgrade |
| `config` | Compose config 和 secret placeholder 验证 |

不得通过手工 commit status、修改 check 名或跳过 workflow 让 PR 变绿。只接受 GitHub Actions App 产生的 check run。

### 7.4 Review 和会话

- 作者不能批准自己的 PR；
- `Keyou430` 创建或维护前端 PR，并请求 `OneAsmallFish` review；
- `qiang880` 不作为 assignee、reviewer、approver 或合并人；
- reviewer 必须查看最新 head；
- push 新 commit 后确认审批是否失效；
- 对每条 inline comment 回复 commit、文件和验证；
- 问题真正处理后再 resolve conversation；
- Copilot/自动审阅因为文件数过大而跳过，不等于人工 review 失败或通过。

### 7.5 从 Draft 转 Ready

同时满足后才能 Ready：

- 功能范围完成，不再有占位页面或伪 API；
- 五项 required checks 通过；
- contract/component/E2E 证据完整；
- 桌面和 390px 验收完成；
- API/权限/组织边界经维护者确认；
- 无 secret、真实数据或无关文件；
- 回滚方式明确。

## 8. 大型替换验收门禁

最终替换 PR 必须额外证明：

- 旧前端所有保留路由都有迁移表：保留、替换、合并或删除原因；
- login -> profile -> organization switch -> logout 完整；
- Chat session -> SSE -> history -> stop/approval/delete 完整；
- Knowledge list/upload/ingest/preview/download/grant/citation 完整；
- Portal/Dashboard revision、Organization revision、Work Item 状态冲突完整；
- guest 不显示也不能调用未授权功能；
- 跨组织缓存和数据不会串用；
- 320/390/414/768/1280/1440px 无遮挡或水平溢出；
- 键盘、焦点、语义、对比度、错误反馈和 reduced motion 已检查；
- 浏览器 console 无本次变更引入的 error/warn；
- real-mode build 不含 mock-only 数据承诺；
- `dist` artifact 可从指定 commit 重建。

## 9. 合并策略

普通小 PR 默认 squash merge。

本次 replacement PR 是大型替换：

- 如果里程碑 commits 清晰、均可独立复核，使用 merge commit 保留历史；
- 如果成员开发过程包含大量临时/fixup commits，维护者在最终 review 后 squash；
- 不使用 rebase merge 重写已经共同审阅的长历史；
- 合并前记录 head SHA、checks、批准人和回滚点；
- 合并后删除 `codex/frontend-replacement`。

不得直接 merge 未完成的 Draft，也不得由作者自行批准。

## 10. 回滚

大型替换合并前记录旧前端基线 `25dbd67` 和最终 PR merge commit。

回滚原则：

- 使用 GitHub `Revert` 或 `git revert` 创建反向 PR；
- 不 force push `main`，不 reset 公共分支；
- 前端 artifact 回滚到已记录的 commit；
- 前端回滚不代表数据库 migration 已回滚；
- 若 API 未变化，只回滚 `web-platform`/frontend image；
- 回滚后重新执行五项 required checks 和关键浏览器流程。

## 11. 交付回复格式

`Keyou430` 每个里程碑完成后在 Issue 或 PR 回复以下内容。`OneAsmallFish` 可将其中的完成情况、风险和下一步压缩成进度消息同步给 `qiang880`：

```markdown
## 完成内容
- Issue：
- Commit SHA：
- 页面/路由：
- API operations：

## 验证
- lint：
- tests：
- build：
- desktop/390px：
- real API：

## 风险
- 未覆盖：
- 后端依赖：
- 回滚点：
```

“已写代码”不是完成状态。只有代码、自动测试、真实边界验证、review 和 required checks 同时满足，才能合并。
