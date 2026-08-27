# Phase 1 Live Acceptance

日期：2026-08-24（Asia/Shanghai）
集成分支：`codex/phase1-integration`
最终集成提交：`b85c878`

## 验收边界

- 正式机 SSH 连接已恢复；本次只在正式机创建独立候选目录和 Compose 项目
  `hermes-platform-acceptance-2696b66`。
- 验收栈使用独立 PostgreSQL volume、独立 Hermes data volume、独立 API/Web 端口
  `127.0.0.1:18080`，未切换线上项目，也未执行正式库迁移。
- provider 凭据仅在正式机运行时注入；证据、日志和本文件不包含 secret、token 或密码。
- 正式线上项目仍保持原 release/image；TLS 反代和公开入口没有在本轮改变。

## 网络搜索闭环

派生 Hermes 镜像固定基础版本 `hermes-agent:v2026.7.7.2`，显式安装 `exa-py`，并在网关边界补齐 provider 证据字段和 `tool.web_search` SSE 事件。A0 真实探针在隔离网关上通过：

- chat：出现 `tool.started`、`tool.completed`、`tool.web_search`、`run.completed`；
  `tool.web_search` 样本包含 URL、标题、`published_at`、`searched_at`、provider、
  `source_id` 和 correlation id。
- pipeline：出现 `function_call` + `function_call_output` + `message`；工具结果
  包装内解析出 URL、标题、发布时间、搜索时间、provider、source id。
- 平台 API：真实 chat SSE 出现 `web.search.started`/`web.search.completed`；一次
  验收返回 8-18 个来源，历史接口恢复并持久化同样数量的 `web_sources`。模型正文 URL
  不进入证据路径。

## 智能决策闭环

- 独立 PostgreSQL migration head：`20260823_0022`。
- 真实 `web_research` task 创建并入队；pipeline run `4` 最终为 `completed`，生成
  Markdown output `1`。
- dashboard decision 初始为 `pending`；approve 返回 HTTP 200，状态为 `approved`，
  revision 增加到 2。
- 模型偶发返回 ```json 围栏时，平台只从围栏中提取包含完整
  `title/markdown/summary/sources` 的 JSON 对象，再由 provider 证据交叉校验决定是否
  通过；任意正文链接仍不能证明“最新”。

## 飞书结论

- `GET /api/delivery/status` 返回 provider `feishu_not_configured`。
- 平台专用 `PLATFORM_FEISHU_APP_ID/SECRET` 未配置；本轮没有复用 Hermes 原生 Feishu
  bot 凭据，也没有发送真实 Feishu 消息。
- 因没有目标路由，验收审批没有伪造 delivery row；worker 未报告成功。提供独立平台
  app 凭据和目标会话后，才能执行真实出站 send、回读 external message id 并完成 C2。

## 代码和回归

- 后端全量：`490 passed, 1 skipped`（70 warnings，均为既有 Pydantic/pytest 标记警告）。
- 前端 Node/Vitest/lint/build：此前已通过 Node 32、Vitest 160、lint、build。
- Playwright：11/11 通过。

## 当前阻塞与后续门禁

1. 飞书真实出站仍是授权阻塞，不是代码假成功：需要平台专用 Feishu 应用凭据、目标
   会话/路由和一次真实发送授权。
2. 正式部署仍需在生产库备份并获得迁移确认后进行；当前线上 HTTP/docs/TLS 运维项未
   被本次验收掩盖。
3. `main`/`v1` 重命名、分支/issue/PR 清扫延后到三项功能都通过真实验收之后。
