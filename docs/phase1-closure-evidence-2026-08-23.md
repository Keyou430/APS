# Phase 1（智能决策 / 飞书 / 网络搜索真实闭环）执行证据

**日期**：2026-08-23
**执行者**：zcode；**审阅**：Codex
**执行计划**：`docs/superpowers/plans/2026-08-22-phase1-decision-feishu-web-closure.md`
**实现分支**：`codex/phase1-closure`（worktree `E:\My_Opjects\agent-platform-system-worktrees\phase1-closure`）
**基点**：`24d9e89`（= `origin/codex/tuesday-single-user-acceptance`）
**最终 HEAD**：`1bf88260a82e094d2c3ce5ff81cbd2ae23c8bd44`

---

## 1. 批次提交清单（每批独立可审阅，含 RED→GREEN）

| # | SHA | 批次（phase1/area） | 内容 |
|---|---|---|---|
| 1 | `2344dd9` | test-baseline | 修复基线 e2e 陈旧断言（/knowledge 已 React-owned，legacy 启动检查改指 dashboard 路由） |
| 2 | `6dde36a` | web-evidence-contract | 平台 WebEvidence DTO/校验器（A1） |
| 3 | `e64e8d0` | web-evidence-pipeline | Pipeline 交叉验证 + 错误码 + A0 探针脚本（A2 pipeline 侧） |
| 4 | `72e5336` | web-evidence-chat | chat SSE evidence 解析/平台事件/持久化 + migration 0020（A2 chat 侧） |
| 5 | `8725298` | web-evidence-fail-closed | 前端仅渲染校验证据、真实外链、fail-closed 新鲜度（A3） |
| 6 | `1818e58` | smart-decision-semantics | 诚实创建语义 + 确定性/意图级幂等键（B1） |
| 7 | `3056690` | smart-decision-worker | 错误码脱敏 + 轮询超时“执行中”（B2） |
| 8 | `cb3400d` | feishu-routing | 路由 provider 谓词（CR-021，C1） |
| 9 | `e56a09c` | feishu-outbox | FeishuDeliveryAdapter + outbox consumer + migration 0021（C1） |
| 10 | `d0c0472` | feishu-decision-notify | 审批/拒绝事务写 delivery 行 + /api/delivery/status + compose/文档（C0/C2） |
| 11 | `1bf8826` | ops-convergence | EXPOSE_DOCS 门禁 + notifications 入口正式禁用（D） |

白名单 diff 总量：39 files，+3253 / −58。未提交任何截图、日志、provider 原始响应或 `.env`。根 dirty 工作树（`codex/frontend-replacement` @ `7f2dd52` 及其未跟踪文档）全程未触碰。

## 2. Gate 0 基线（在 clean worktree 记录）

- 根工作树 dirty 清单已存档（见计划文档 gitStatus）；未被修改。
- 分支关系：`origin/main` = `543b133`（`24d9e89` 的祖先）；`origin/codex/tuesday-single-user-acceptance` = `24d9e89`。
- 测试基线（精确数量）：后端 pytest **413 passed, 1 skipped**（skip 为设计性凭证门禁）；node contract **30 passed**；vitest **150 passed（45 文件）**；eslint 通过；build 通过；ruff 通过；OpenAPI `--check` 通过；Playwright **10 passed / 1 failed**。
- 基线失败分类：`production-artifact.spec.ts:232` —— `/knowledge` 已列入 `reactOwnedRouteIds`，legacy `#workspace` 按设计隐藏，测试断言陈旧（P2，fd28bac→24d9e89 间前端迁移提交引入；测试侧问题）。已在批次 1 修复，Playwright 此后 11/11。
- Alembic：单 head `20260820_0019`（注意：Phase D 计划中的 `20260815_0018` skill derivation 已被实际仓库的 `20260817_0018_work_item_week_archive` 取代，`0019` 为当前权威 head）。本 Phase 新增 `20260823_0020`、`20260823_0021`，串行接续，最终单 head `20260823_0021`。

## 3. A0 provider 探针状态：**blocked（外部依赖）**

- `backend/scripts/probe_web_evidence.py` 已交付：对 agent gateway 双路径（chat `POST /v1/runs`+SSE、pipeline `POST /v1/responses`）做一次授权 smoke，输出脱敏结构报告（事件名/字段名/嵌套类型/是否含结构化 web 结果；URL 只保留 host；不含凭钥与正文）。
- 当前运行输出：`{"status":"blocked","blocked_reason":"HERMES_API_KEY is not configured ... formal SSH access is currently blocked pending the user rebuilding the connection."}`，退出码 **2**。
- blocked_reason：正式机 SSH MCP 条目（`formal-ai-password-fix-20260818`）密码已失效待用户重建（见 full-code-review-report §7.1 与既有记忆条目）；本地无任何 provider 凭据（deploy/.env 不存在）。
- **后果（诚实声明）**：探针未确认任何上游事件形态。`WEB_SEARCH_SOURCE_EVENT_NAMES` / `_WEB_SEARCH_OUTPUT_ITEM_TYPES` 中的形态常量处于**未激活**状态——真实上游若不产生这些形态，解析自然为空：
  - Pipeline `web_research` 任务将以 `web_evidence_provider_contract_missing` 失败（不生成 output/decision）——这是计划的 fail-closed 要求，非缺陷。
  - chat 不发 `web.search.*` 平台事件，前端显示“未搜索/不可证明”。
  - 探针恢复后若形态不同，只需扩展这两个常量 + 对应解析测试。

## 4. Phase A（统一 Web Evidence 契约）证据

**A1（`6dde36a`）**：`app/services/web_evidence.py` — 单一 fail-closed 契约：http(s)/公网 host 校验（拒绝 javascript:/data:/ftp/file、回环、私网、link-local；`allow_private_hosts` 仅测试模式）、tz-aware 时间校验（published 不得未来、searched 不得未来且不早于 published）、run correlation 绑定（缺失/错配拒绝）、事件信封跨 run 拒绝、provider-event-only 解析（模型文本无法进入）。RED：`ModuleNotFoundError`；GREEN：`test_web_evidence.py` **34 passed**。

**A2 pipeline（`e64e8d0`）**：executor 从 /v1/responses 的 output items 收集证据（仅认可 web_search_call 类 item）；`cross_validated_web_sources` 交叉验证：模型声称的每个 URL 必须存在于本 run 证据集，落库 sources 由校验证据重建（provider/correlation_id 字段入库），非模型 JSON。错误码闭集：`sources_required` / `web_evidence_mismatch` / `web_evidence_provider_contract_missing`。RED（行为级，5 failed）：模型伪造 sources 现在失败、证据 URL 不匹配失败、跨 run 证据失败；夹具更新为证据契约。

**A2 chat（`72e5336`）**：SSE relay 解析认可事件 → 发射 `web.search.started/completed/failed` 平台事件（带 correlation_id）→ 校验证据持久化 `chat_turn_web_sources`（migration `20260823_0020`：`(chat_turn_id, ordinal)` 唯一、组织隔离、cascade；`alembic heads` 单 head）。历史接口按 turn 附着 `web_sources`。OpenAPI 快照再生成（117 paths）。未知事件透传但永不成为证据；跨 run 事件整事件拒绝。`test_chat_web_evidence.py` **4 passed**（全路径 API 驱动）。

**A3（`8725298`）**：`web.search.*` 事件消费；`tool.*` 仅为状态指示；校验证据渲染为真实外链（`target=_blank rel="noopener noreferrer nofollow"`，发布/检索日期）；历史 `web_sources` → `webEvidence` 恢复。`chatEvidence` 收紧：**只有平台校验的 webEvidence 才能证明新鲜度**——正文 URL、检索时间字样、知识库引用一律不算；搜索失败/空结果各有独立提示。RED：chatEvidence 测试（URL-in-content 不再是证据）；node 契约新增两段。

## 5. Phase B（智能决策真实状态闭环）证据

既有能力（Gate 0 核实）：claim/lease/reaper（`SKIP LOCKED` pg 方言）、scheduled/manual 分离幂等、output+decision 单事务、approve CAS + DecisionAction 重放、失败不写伪 decision。

**B1（`1818e58`）**：chat 创建声明改为“已创建任务/运行已入队”；只有后端实际返回 `DashboardDecision(status=pending)` 才声明“已生成待审决策”（`refreshScheduledDecision` 只认 pending）。幂等键：decision 动作键完全确定性（`decision-approve:{id}` / `decision-changes:{id}`，跨重载重放）；manual run 键按意图铸造、重试复用、终态后 `releaseRunIntent` 释放；create-task 键由请求内容派生。后端 regeneration run 键从 action 键派生（`decision-regen:{id}:{key}`，可追溯）。

**B2（`3056690`）**：worker ValueError 折叠进闭集脱敏码（未知文本→`structured_output_invalid`，测试证明 secret/路径不落 error_code）；PipelinePage 轮询超时显示“任务仍在执行中（状态：X）”而非静默假完成（fake-timer 测试覆盖 21 次轮询耗尽路径）。

## 6. Phase C（飞书真实交付闭环）证据

**C0**：单一通道权威已固化——平台 `delivery_outbox` + `FeishuDeliveryAdapter` 为决策通知唯一出站权威；Hermes 原生 `FEISHU_*`/`platform_toolsets.feishu: [web]` 明确标注为仅入站 bot/工具流量（compose 注释 + README 新章节 + `test_platform_delivery_worker_uses_dedicated_feishu_credentials` 强制平台凭据独立命名 `PLATFORM_FEISHU_*` 且 delivery-worker 不接触 Hermes）。

**C1**：`FeishuDeliveryAdapter`（官方 OpenAPI：tenant_access_token 缓存 + im/v1/messages；凭据仅来自 settings；错误码 `feishu_auth_failed/feishu_send_failed/feishu_rate_limited/feishu_network_error`；轻通知文案=通用状态+可选平台链接，无模型原文/密钥/内部路径）。consumer：claim（pg `SKIP LOCKED`；pending/due-retry）、`sending`+`claimed_at` lease、reaper 回收（`delivery_lease_expired`）、指数退避至 dead-letter（复用 `mark_delivery_failure`）、成功记 `external_message_id`+`delivered_at`。migration `20260823_0021`（`run_correlation_id` 转 nullable + 两新列，单 head）。**凭据缺失时行进 retry 且 `last_error=feishu_not_configured`，绝不假 sent（P1-FS-02 契约级）**。`test_delivery_outbox.py` **10 passed**（全部 fake transport；token 缓存、轻 payload、脱敏错误、重试/dead-letter、双 consumer 不重领、lease 回收、幂等 enqueue、凭据门禁）。

**C2（`d0c0472`）**：approve/reject 事务内为组织**每个 active feishu target** 写幂等 delivery 行（`decision-{status}:{id}:feishu:{target}`；重放不重复）；HTTP 请求内不直接调用 Feishu。`GET /api/delivery/status`（`pipeline:observe`）：provider 配置状态（`feishu_not_configured`）+ outbox 各状态计数。compose 增 `delivery-worker` 服务（依赖仅 db）。

**C3（入站 bot）**：**未纳入本阶段**（需产品确认 + 测试租户授权），列未决项。

**C4/C5（外部授权与实发）**：**待授权/阻塞**——真实租户实发、provider message ID、目标会话读回（P1-FS-01）需：用户重建正式机 SSH 条目、提供 `PLATFORM_FEISHU_APP_ID/SECRET`、确认目标 chat/open id 与测试租户。当前所有 C 证据均为 **fixture/fake transport 级（第 8 节声明）**。

## 7. Phase D（既存运行时收敛）证据（`1bf8826`）

- **Notifications API contract missing**：定位完成——前端铃铛调用本地过期待办，无后端端点；正式化为**测试固化的禁用入口**（不伪造 `/api/notifications` 调用；警告保留不隐藏）。
- **Portal bootstrap unavailable**：定位完成——真实端点 `/api/enterprise/portal` 存在（portal.py:462）；失败回退到**用户自己的 localStorage 数据**而非示例配置；cockpit 示例决策严格 `VITE_USE_MOCK` 门禁（PR #7 退出条件已在库中满足）。无代码变更需求。
- **/docs、/openapi.json**：`EXPOSE_DOCS` 门禁（默认 true 开发可用；formal compose api 服务显式 `false`）；`test_docs_exposure.py` 3 tests。
- **TLS 反代**：运维项——README 既有章节 + web 端口默认 loopback；正式机 TLS 落地待 SSH 恢复（未决项）。

## 8. 验证命令与精确结果（最终 HEAD `1bf8826`）

| 命令 | 结果 | 退出码 |
|---|---|---|
| `python -m pytest -q`（backend） | **472 passed, 1 skipped**（69→70 warnings，均为既有 pydantic 噪音） | 0 |
| `python -m ruff check app tests scripts` | All checks passed | 0 |
| `python scripts/export_openapi.py --check` | snapshot current（118 paths） | 0 |
| `python -m alembic heads` | `20260823_0021 (head)` 单 head | 0 |
| `python scripts/probe_web_evidence.py` | `status=blocked`（见 §3） | 2 |
| `npm test`（web-platform） | **32 passed / 0 failed** | 0 |
| `npx vitest run` | **156 passed / 45 files**（见 §9 flake 说明） | 0 |
| `npm run lint` | 通过 | 0 |
| `npm run build` | 通过（0 errors） | 0 |
| `npx playwright test` | **11 passed** | 0 |

RED 证据：每批次的 RED 命令与失败数记录于本报告各节（A1 模块缺失 34 红、A2 行为红 5、chat 红 4、C1b 模块缺失→逐绿、B2 双端红、docs 红 3 等），GREEN 数量如上。

**未执行（阻塞）**：PostgreSQL 行为级 CI（claim/lease `SKIP LOCKED` 真并发、migration roundtrip）——本地无 docker/psql；代码路径已按方言分支并在 SQLite 覆盖逻辑，需在 CI（`migration/postgres`）或正式机验证。真实 formal Hermes/provider smoke、真实 Feishu 实发/读回、正式机隔离部署（Phase E/验收矩阵 P1-WEB-01 实测、P1-FS-01、P1-OPS-01）——全部待 SSH 恢复后执行。

## 9. 已知 flake

`ChatPage.test.tsx > shows an actionable failure and retry affordance` 在**后端 pytest 并行占用机器时**的全量 vitest 偶发超时（本会话两次出现、两次串行重跑通过；单文件运行稳定通过）。与本次改动无关联路径（未触碰 ChatPage）；不作为通过依据，最终验收以串行全量 156/156 为准。建议后续给该测试加超时余量。

## 10. 未决项表

| 项 | 状态 | 责任层 | 下一步 |
|---|---|---|---|
| A0 provider 事件形态确认 | **阻塞** | 用户（重建正式机 SSH 条目，或提供本地 HERMES_API_KEY） | 运行 `python scripts/probe_web_evidence.py`，按报告扩展/确认 `WEB_SEARCH_SOURCE_EVENT_NAMES` 与 `_WEB_SEARCH_OUTPUT_ITEM_TYPES` |
| P1-WEB-01 真实联网来源端到端 | **待授权**（依赖上项 + formal Hermes） | 用户 + 运维 | 探针通过后 formal smoke + Chrome 验证 |
| P1-FS-01 Feishu 真实实发/读回 | **待授权** | 用户（测试租户、`PLATFORM_FEISHU_APP_ID/SECRET`、目标 chat/open id） | 正式机配置后触发一次审批 → outbox sent + message_id + 会话读回 |
| P1-FS-03 入站 Bot（C3） | **未纳入/待产品确认** | 产品 + 用户 | 若纳入：官方长连接 worker、事件去重、ChannelIdentity→组织路由 |
| P1-OPS-01 formal 隔离部署验收 | **阻塞**（SSH） | 用户 + 运维 | `compose.acceptance.yaml` 隔离栈 + 备份/回滚演练 |
| TLS 反代 + 8092 端口回收 | **待运维** | 运维 | TLS 反代上线后收紧 `FORMAL_APP_BIND` |
| PostgreSQL 行为级验证 | **推进中** | CI | 在 CI `migration/postgres` job 上跑全链（含新 0020/0021）；无本地 pg |
| ChatPage flake | 记录 | 前端 | 加超时余量或拆分测试 |
| Dependabot PR #11 | 未处理（不绕过门禁） | 仓库维护者 | 走正常 review |

## 11. 真实 vs fixture 证据声明（不得混写）

- **fixture/mock 级**：本报告全部自动化测试证据（pytest/node/vitest/playwright 中的 fake executor、fake transport、mock provider）。它们证明**代码契约**，不证明真实 Hermes、真实 web provider 或真实 Feishu。
- **真实级（本阶段仅有的）**：正式机 health/ready 外部探测 200（2026-08-23 复测）；A0 探针的 blocked 状态本身是真实环境事实（本地确无凭据）。
- **未取得的真实证据**：真实 web_search 事件流、真实来源 URL/发布/检索时间、真实 Feishu message_id 与会话读回、正式机部署回滚演练。在这些完成前，Web evidence、Feishu 闭环的状态只能是 **推进中/待授权**，不得表述为“已完成/已验证/已部署”。

## 12. Codex 审阅门槛对照（计划 §11）

1. Web evidence 非模型猜测：契约级已实现并测试（chat 与 pipeline 共用 `web_evidence.py`）；**真实 provider 证据待探针**。
2. Smart Decision task/run→pending/approve 真实数据库与权限证据：SQLite 级全绿（含跨组织/owner 负面既有测试）；pg 行为级待 CI。
3. Feishu 真实外部回执：**未取得**（待授权）；只有 outbox pending 的部分不宣称通过。
4. 无 P0/P1 核心缺陷：本轮未发现新 P0/P1；失败路径/重试/重启/幂等契约级覆盖；跨 provider 路由已修。
5. formal 可回滚 + TLS/docs：EXPOSE_DOCS 已入库；部署/回滚演练与 TLS **待 SSH**。
6. 根 dirty 工作树未动、无 secret 提交、旧 Phase E 作废语义未回引：确认（`git log` 全部 11 个提交均在 `codex/phase1-closure`；白名单 diff 见 §1）。
