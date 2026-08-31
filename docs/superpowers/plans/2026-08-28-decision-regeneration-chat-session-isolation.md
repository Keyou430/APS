# 驳回重新生成与聊天会话隔离实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 驳回驾驶舱决策后以理由重新生成并在前端展示新结果，同时确保 AI 对话窗口彼此隔离且同一窗口持续使用完整上下文。

**Architecture:** 后端将驳回动作与唯一 regeneration run 绑定，旧决策保留审计状态，新 run 完成后产生新的 pending 决策；前端立即展示 regenerating 并轮询该 run，完成后刷新决策列表。聊天后端继续以 organization/user/session 为所有权边界，前端将消息、流式请求、附件和知识范围按 session key 保存，并在切换时丢弃旧请求事件、从后端加载目标窗口历史。

**Tech Stack:** FastAPI、SQLAlchemy、pytest/pytest-asyncio、TypeScript service contracts、原生前端 app.js、Vitest。

---

### Task 1: 补足驳回重新生成的后端闭环测试

**Files:**
- Modify: `backend/tests/test_pipeline_decisions.py`
- Modify: `backend/tests/test_pipeline_worker.py`

- [ ] **Step 1: Write failing tests**

增加测试：驳回接口返回 `changes_requested`、`regeneration_run_id`；运行该 ID 后旧输出不变、新输出和新 pending decision 产生；同一 Idempotency-Key 不重复创建 run；缺少理由返回 422。

- [ ] **Step 2: Run targeted tests**

Run: `python -m pytest backend/tests/test_pipeline_decisions.py backend/tests/test_pipeline_worker.py -q`

Expected: 新增前端可观察行为相关断言至少有一项失败，若现有后端已满足则记录为已覆盖并继续 Task 2。

- [ ] **Step 3: Implement only missing backend behavior**

保持 `request_changes` 的 run 级 `prompt_override` 和 action 幂等；若缺失则补充状态字段、失败状态读取或唯一约束，不能改写原 task prompt。

- [ ] **Step 4: Re-run targeted tests**

Run: `python -m pytest backend/tests/test_pipeline_decisions.py backend/tests/test_pipeline_worker.py -q`

Expected: PASS。

### Task 2: 驳回后前端状态、轮询与失败重试

**Files:**
- Modify: `web-platform/src/app.js`
- Modify: `web-platform/src/api/services/pipelineService.ts`
- Test: `web-platform/src/app/*.test.ts`, `web-platform/tests/platform_contracts.test.js`

- [ ] **Step 1: Write failing UI contract tests**

断言 `rejectCockpitDecision` 提交成功后将旧卡显示为“重新生成中”，保存返回的 `regeneration_run_id`，轮询 `/pipeline/runs/{id}`；run 完成后重新获取 decisions，失败时显示失败原因并保留可重试动作。

- [ ] **Step 2: Run tests to verify failure**

Run: `npm test -- --run web-platform/src/app web-platform/tests/platform_contracts.test.js`

Expected: 当前实现缺少轮询/完成刷新断言而失败。

- [ ] **Step 3: Implement minimal frontend flow**

在 `rejectCockpitDecision` 成功分支中使用 API 返回的状态和 `regeneration_run_id` 更新本地卡；新增带取消/超时保护的 run 轮询，状态为 `completed` 后调用 `fetchCockpitDecisions()`，状态为 `failed` 后显示重试入口；重复点击使用稳定 Idempotency-Key，避免重复生成。

- [ ] **Step 4: Re-run frontend tests and build**

Run: `npm test -- --run web-platform/src/app web-platform/tests/platform_contracts.test.js`；`npm run build`（工作目录 `web-platform`）。

Expected: PASS，构建成功。

### Task 3: 后端聊天会话隔离与上下文连续性测试

**Files:**
- Modify: `backend/tests/test_api.py`
- Modify: `backend/tests/test_chat_knowledge_context.py`
- Inspect/modify only if needed: `backend/app/routers/chat.py`

- [ ] **Step 1: Write failing tests**

用两个 session 创建消息，断言 Hermes provider 收到不同的 `session_id` 和 `correlation_id`；第二条消息只携带同一 session 的历史/previous response；跨用户或跨组织读取、发送仍返回 404/403。

- [ ] **Step 2: Run targeted tests**

Run: `python -m pytest backend/tests/test_api.py backend/tests/test_chat_knowledge_context.py -q`

Expected: 若现有后端契约已满足则 PASS；否则先出现针对错误 previous response 或 session scope 的失败。

- [ ] **Step 3: Implement missing server-owned context propagation**

确保 `owned_session()` 查询同时约束 organization、user、session id；`hermes_context_for`、`create_response`、`stream_events`、`get_session_messages` 始终使用该 session 的 Hermes ID；previous response 只从该 session 的最后一轮恢复，禁止接受客户端任意 session/context 标识。

- [ ] **Step 4: Re-run targeted backend tests**

Run: `python -m pytest backend/tests/test_api.py backend/tests/test_chat_knowledge_context.py -q`

Expected: PASS。

### Task 4: 前端会话窗口状态隔离与同窗记忆

**Files:**
- Modify: `web-platform/src/app.js`
- Modify: `web-platform/src/api/services/chatService.ts` only if an existing contract lacks required query
- Test: `web-platform/src/pages/ChatPage.test.tsx`, `web-platform/src/app/chat*.test.ts`, `web-platform/tests/platform_contracts.test.js`

- [ ] **Step 1: Write failing tests**

测试切换 A/B 会话后消息列表、附件 chips、知识范围和流式 loading 不互串；切回 A 从后端恢复 A 的消息；A 的旧流事件到达时不得覆盖 B 的 DOM/state；同一 A 连续发送使用同一 session ID。

- [ ] **Step 2: Run tests to verify failure**

Run: `npm test -- --run web-platform/src/pages/ChatPage.test.tsx web-platform/src/app web-platform/tests/platform_contracts.test.js`

Expected: 至少有一项关于旧流事件或窗口级状态的断言失败。

- [ ] **Step 3: Implement session-scoped UI state**

为每个 `state.chatSessions.sessions` 项维护消息、attachments、knowledge scope、active run 和 request generation；`switchChatSession` 先递增旧 session generation/取消可取消请求，再加载目标 session；所有 SSE 回调校验目标 session 仍为 active 且 generation 未变化；消息持久化以后端 session ID 为 key，刷新/重新进入优先 `getMessages`。

- [ ] **Step 4: Re-run frontend tests and build**

Run: `npm test -- --run web-platform/src/pages/ChatPage.test.tsx web-platform/src/app web-platform/tests/platform_contracts.test.js`；`npm run build`。

Expected: PASS，构建成功。

### Task 5: 全量验证与运行态检查

**Files:**
- No source changes unless a failing regression requires one.

- [ ] **Step 1: Run backend suite**

Run: `python -m pytest backend/tests -q`

Expected: 全部通过，允许已有明确标记的 skip。

- [ ] **Step 2: Run frontend suites**

Run: `npm test -- --run` and `npm run build` in `web-platform`。

Expected: 全部通过，构建成功。

- [ ] **Step 3: Verify live APIs**

使用 `admin/admin123` 创建两个聊天 session，分别发送消息并切换；对驾驶舱决策填写理由提交，确认旧卡变为重新生成中，worker 完成后出现新的 pending 卡；确认服务仍监听 `127.0.0.1:5173` 和 `127.0.0.1:8000`。

---

## 自审

- 驳回理由、唯一 regeneration run、旧卡审计和新 pending 卡均有测试与实现任务。
- 会话隔离覆盖服务端所有权、Hermes session ID、前端消息/附件/知识范围/流式事件。
- 未把长期记忆库伪装成窗口上下文；仅保证同一窗口历史连续。
- 计划没有未定义的 TODO 或占位步骤。
