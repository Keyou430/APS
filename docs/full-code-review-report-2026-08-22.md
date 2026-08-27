# Agent Platform System 全量代码审查与验收报告

日期：2026-08-22
分支：`codex/tuesday-single-user-acceptance`

## 一、审查范围

- 后端 FastAPI 路由、Schema、权限、OpenAPI、Pipeline 时区依赖与测试。
- React Chat/Knowledge 页面、legacy `app.js` 迁移边界、前端服务契约和行为测试。
- 前端 Node 合约测试、Vitest、lint、生产构建，以及后端全量 pytest。

## 二、本轮已修复

### 1. Chat 会话标题持久化

新增 `PATCH /api/chat/sessions/{session_id}`，使用当前用户、组织归属校验和行锁更新标题；标题执行去首尾空白、长度限制和空值校验。同步更新 `ChatSessionUpdate`、OpenAPI 快照及 API 测试。

### 2. React Chat 会话 ID 与 surface

React Chat 现在保留后端数字会话 ID，不再把真实 ID 替换为 `session-1` 等 fallback；列表请求明确传递 `surface=agent`，创建请求继续使用 Agent surface。新增数字 ID、列表查询、创建和失败重试行为测试。

### 3. Agent 会话权限契约

普通登录用户使用 `chat:use` 即可创建 Agent Chat 会话；guest 仍被后端拒绝。`agent:admin` 保留给 Hermes 管理能力，避免普通聊天页面出现 403。

### 4. 运行时与测试基础设施

- `backend/requirements.txt` 显式加入 `tzdata`。
- POSIX 启动脚本测试在无 `sh` 的 Windows 环境中明确跳过，而不是产生误报错误。
- OpenAPI 快照已重新导出。

### 5. 聊天回答的新鲜度证据

合并同一验收分支上的并行修复后，legacy Chat 会对缺少可验证来源时间的内容给出明确提示；新增 `chatEvidence` 纯函数与单元测试，避免把无时间依据的回答呈现为已验证的最新信息。

## 三、验收结果

| 检查项 | 结果 |
| --- | --- |
| 前端 Node 合约测试 | 30/30 通过 |
| 前端 Vitest | 45/45 文件，151/151 测试通过 |
| 前端 ESLint | 通过 |
| 前端生产构建 | 通过 |
| 后端全量 pytest | 414 通过，2 跳过，0 失败 |
| 后端新增 Chat PATCH/API 权限测试 | 通过 |
| 聊天新鲜度证据测试 | 通过 |

后端全量测试使用仓库内隔离临时目录执行，避免 Windows 默认临时目录权限污染。2 个跳过项均为 POSIX `up.sh` 测试，原因是当前 Windows 环境没有 `sh`；Linux CI 应安装 POSIX shell 后执行该测试。

## 四、当前仍需跟踪的架构事项

1. React 与 legacy `app.js` 仍然并存，`app.js` 约 1 万行；`work-items` 仍是 `legacy-host`。
2. legacy 知识库导入任务渲染仍被实际操作入口使用，本轮未删除，避免删除重试/任务状态功能。后续应将其迁移到 React 后再移除旧实现。
3. 迁移矩阵仍保留多项长期 `port` 工作，表示全量 React 迁移尚未完成。
4. 前端路由权限字段主要用于声明和 UI 边界，真正授权仍由后端执行；后续可补充统一的前端 forbidden route guard。
5. Python 测试输出仍有既有 FastAPI/Pydantic 弃用和字段元数据告警，不影响本轮通过，但建议单独治理。

## 五、结论

本轮审查中确认的 Chat 标题回写、React Chat ID、Agent surface 权限、OpenAPI 漂移、时区依赖、聊天新鲜度证据和回归测试问题已处理，最终验收命令通过。变更已提交并推送到 `codex/tuesday-single-user-acceptance`；React/legacy 长期迁移属于后续架构工作，不应宣称已经全部完成。
