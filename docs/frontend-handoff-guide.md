# 前端交接入口

版本：2026-08-11

仓库：`OneAsmallFish/agent-platform-system`

前端目录：`web-platform/`

原交接指南已经按职责拆分为两份正式文档，旧版中的 PR #1、旧 SHA、Draft 状态和旧 API 说明不再有效。

## 职责划分

| 成员 | 职责 | 仓库操作 |
| --- | --- | --- |
| `Keyou430` | 前端负责人；维护 `web-platform/` 的界面、路由、状态、API 适配、前端类型及测试 | 使用现有 `write` 权限，在非保护分支提交并创建/更新 PR |
| `OneAsmallFish` | 仓库维护者；负责后端、Agent、知识库/RAG、数据库、Docker、Nginx、部署、CI/CD、仓库设置和最终合并 | `admin`；确认 API 契约与非前端变更 |
| `qiang880` | 项目管理；只跟进里程碑、风险和进度 | `read`；可查看代码、Issue、PR 和 Actions，不执行 push、Issue/PR 变更、review、merge 或设置操作 |

`qiang880` 可在 GitHub 只读查看技术记录和验证证据；代码提交、Issue/PR 更新、代码审查和合并操作只由 `Keyou430` 与 `OneAsmallFish` 完成。

`Keyou430` 开始工作前必须依次阅读：

1. [前端 API 接口与契约](frontend-api-contract.md)
   - API 基址、认证、refresh/logout、组织隔离、权限、错误格式、SSE、上传下载；
   - 89 个路径、117 个 operations 的领域入口和请求/响应 schema；
   - Mock/Real 边界、service/type/contract test 要求。
2. [前端 Issue、分支与 Pull Request 流程](frontend-pr-issue-workflow.md)
   - GitHub 权限、Issue 内容、分支策略、提交规范、Draft PR、CI、review、合并和回滚；
   - 本次替换式前端改造的里程碑和验收门禁。

## 当前交接基线

- PR #1 已合并到 `main`，merge commit：`25dbd67bc07138e37d11b4ae41ee9ca94021e181`。
- 前端替换分支：`codex/frontend-replacement`。
- 新前端应在该临时分支内替换 `web-platform/`，不得直接 push `main`。
- 不在仓库中长期保留第二套前端目录；现有实现由 Git 历史和 tag/commit 保留。
- API 权威快照：[backend/docs/openapi.json](../backend/docs/openapi.json)。

## 开始前最短检查

```powershell
git fetch origin --prune
git switch codex/frontend-replacement
git pull --ff-only origin codex/frontend-replacement
cd web-platform
npm ci
npm run lint
npm run test:ci
npm run build
```

`Keyou430` 已有 `write` 权限，不需要 `maintain` 或 `admin`。若 push 返回 403，应先确认本机 GitHub 账号和 SSH key 对应 `Keyou430`，不得共享 `OneAsmallFish` 的 token、SSH key 或登录信息。`qiang880` 应接受权限为 `read` 的 collaborator 邀请；该权限只用于查看，不应升级为 `triage/write/maintain/admin`。
