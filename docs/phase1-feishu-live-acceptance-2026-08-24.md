# Phase 1 Feishu Live Acceptance

日期：2026-08-24（Asia/Shanghai）

集成分支：`codex/tuesday-single-user-acceptance`

被测提交：`9508c9d`

## 验收边界

- 使用用户明确提供的测试 Feishu 应用凭据；凭据仅从仓库外 `.secret` 在运行时读取。
- 未输出或提交 app secret、tenant token、用户 open id、完整 message id 或私有会话内容。
- 外部目标发现为只读：机器人可见群聊为 0，可见用户为 1，因此使用唯一用户的 `open_id`，没有猜测或广播目标。
- 平台路径在一次性 SQLite 数据库中执行；数据库在完成后删除。未连接、迁移或写入正式数据库。

## 真实 Provider 证据

### Feishu API 探测

- tenant token：签发成功，过期时间 7200 秒。
- bot info：HTTP/API code 0，机器人名称与 open id 均存在。
- chat list：API code 0，可见群聊 0。
- contact visible range：API code 0，可见用户 1，且具有 open id。

### 直接发送与回读

- 唯一测试标记：`P1-FS-01-20260824-115919`。
- 发送 API code 0；按 provider message id 查询 API code 0；回读消息与标记匹配。
- message id 只记录 SHA-256 前缀：`00dfcd761b33`。

### 平台 Outbox 路径

执行路径：

```text
DeliveryTarget(open_id)
  -> DeliveryOutbox(pending)
  -> run_delivery_cycle
  -> FeishuDeliveryAdapter
  -> DeliveryOutbox(sent + external_message_id + delivered_at)
  -> Feishu message read-back
```

结果：

- 第一个 worker cycle 处理 1 行，outbox 最终为 `sent`。
- `attempts=1`、`delivered_at` 存在、`last_error=null`、`external_message_id` 存在。
- 第二个 worker cycle 处理 0 行，没有重复发送同一 outbox。
- provider 消息查询 code 0，message id 与 outbox 回执匹配。
- message id 只记录 SHA-256 前缀：`290bece4c9f6`。

## 结论

- `P1-FS-01` 的测试租户真实发送、平台 outbox 状态转换、provider message id 和消息回读已验证。
- 该结论证明当前代码的真实 Feishu 出站路径可用，不等于正式机已经部署。
- 正式机仍运行旧 API：数据库 migration head 为 `20260820_0019`，没有 delivery-worker，没有平台 Feishu 环境变量，`GET /api/delivery/status` 返回 404。
- 未经数据库迁移确认，不升级正式机。个人测试凭据也不常驻正式机；测试人员凭据尚未提供，后续切换保持待授权。

## 同批回归

- 后端：`492 passed, 1 skipped`。
- Ruff：通过。
- OpenAPI snapshot：通过。
- Alembic：单 head `20260823_0022`。
- 前端 Node：`32 passed`。
- Vitest：`163 passed`（47 files）。
- ESLint、生产构建：通过。
- Chromium 目标用例：AI 工作台菜单切换与缩放布局 `1 passed`。
- in-app Browser：桌面和 390px 均非空、无框架错误层；390px shell 原生 14px、宽 390、无横向溢出；`全部资料 -> 经验方法` 交互通过。
