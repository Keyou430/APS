# Phase 1 Formal Deployment Record

日期：2026-08-24（Asia/Shanghai）

代码分支：`codex/tuesday-single-user-acceptance`

最终代码提交：`ea18b30`

## 发布边界

- 正式 Compose 项目：`agent-platform-stable`。
- 正式 Web 入口：`http://106.53.85.84:8092/`；主服务仍保留 `8080` 绑定。
- API、pipeline-worker、delivery-worker 使用不可变镜像标签 `ea18b30`。
- Hermes 主网关与知识网关使用已通过搜索探针的证据镜像；API、Web、worker 与数据库均通过健康检查。
- `EXPOSE_DOCS=false`，`/docs` 和 `/openapi.json` 对正式边界返回 404；`/health` 和 `/ready` 返回 200。
- 24 张前端验收截图属于受保护的未提交工作区改动，没有进入发布包。

## 数据库迁移

- 迁移前版本：`20260820_0019`。
- 迁移后唯一 head：`20260823_0022`。
- 实际执行链：`0019 -> 0020 -> 0021 -> 0022`。
- 备份：`/home/huangtianhao/agent-platform-system-stable/backups/pre-phase1-afcb975-20260824T042222Z.dump`。
- 备份格式为 PostgreSQL custom archive；`pg_restore -l` 成功，恢复到临时数据库后版本、表计数和 pgvector `0.8.6` 均核对通过；临时数据库已删除。
- 迁移后核心业务数据计数保持：用户 1、组织 1、成员 1、会话 11、知识条目 1、任务 1、运行 1；新增经验方法表为空。

## 三条正式链路

### 智能决策

正式 `web_research` run `5` 完成并生成 output `1`；来源数量 3，全部带 provider、URL、source id、published_at、searched_at 和同一 correlation id。decision `1` 从 `pending` 审批为 `approved`，revision `1 -> 2`；相同幂等键重放保持 revision `2`。

### 搜索

- Hermes 正式探针：chat 产生 `tool.web_search`，pipeline 产生 function call/output，结构化结果包含 URL、标题、provider、source id、发布时间和搜索时间。
- 平台 pipeline 只接受本次 run 的 provider evidence；模型只声明 URL，权威标题和时间由 provider evidence 补齐，模型伪造或跨 run 来源仍 fail-closed。
- 正式浏览器 AI 工作台真实搜索显示来源链接和 `2026-08-24` 检索时间；回到驾驶舱后已批准决策仍可见。

### 飞书

- 平台 delivery-worker 使用平台专用环境变量；API 只接收非敏感 `FEISHU_DELIVERY_CONFIGURED=true` 状态，不持有 app secret。
- 临时正式测试路由绑定当前用户唯一可见 `open_id`，目标和路由均标记为 `temporary_user_test`，未广播到群聊。
- decision `approved` 生成唯一 outbox；最终状态 `sent`、`attempts=1`、`delivered_at` 存在、`last_error=null`，provider message id 回读 HTTP/API code 0 且与 outbox 匹配。
- 当前仍使用用户凭据完成最终测试；测试人员凭据尚未提供，切换时必须同时替换平台 app 凭据、目标 open_id 和临时路由，不能复用当前 app 作用域下的 open_id。

## 回归与剩余项

- 后端：`495 passed, 1 skipped`；pipeline 定向回归 `40 passed`；Ruff、OpenAPI、Alembic 单 head 通过。
- 浏览器：正式桌面和 390px 移动首屏均非空、无横向溢出；登录、驾驶舱批准决策、AI 工作台真实搜索和来源展示通过。
- 浏览器仍有既有 `Notifications API contract missing` 与 portal bootstrap fallback warning；它们不阻断本次智能决策、搜索、飞书闭环，但应由前端后续补齐通知与企业门户契约。
- 生产回滚点是迁移前 custom dump 与 `agent-platform-api:rollback-pre-afcb975` / `agent-platform-web:rollback-pre-afcb975` 镜像标签；没有执行 downgrade 作为恢复证明。
