# 自然对话定时任务与智能决策审批 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成自然对话创建定时任务草稿、可配置审批策略、结果进入智能决策、成员/角色审批、意见与驳回理由、主动通知和超时提醒升级的闭环。

**Architecture:** 在 `PipelineTask` 保存审批策略快照，在 `DashboardDecision` 保存单次结果的审批人、意见、时间和提醒状态。聊天动作只返回草稿，Pipeline 创建接口负责最终写库；pipeline worker 创建 decision 并写通知 outbox，独立 reminder worker 负责提醒和升级。前端复用现有 Pipeline 与 Dashboard 服务契约，保持决策动作幂等。

**Tech Stack:** FastAPI, Pydantic v2, SQLAlchemy async, Alembic, pytest/pytest-asyncio, React, TypeScript, Vitest, Testing Library.

---

### Task 1: 建立审批策略与决策审计数据模型

**Files:**
- Create: `backend/migrations/versions/20260827_0023_pipeline_approval.py`
- Modify: `backend/app/models/entities.py:1627-1762`
- Modify: `backend/app/schemas/pipeline.py:1-130`
- Test: `backend/tests/test_pipeline_approval_migration.py`

- [ ] **Step 1: Write the failing migration/model contract test**

```python
def test_pipeline_approval_contract_has_task_policy_and_decision_audit_fields():
    tasks = Base.metadata.tables["pipeline_tasks"].c
    decisions = Base.metadata.tables["dashboard_decisions"].c
    assert "approval_required" in tasks
    assert "approval_assignee_type" in tasks
    assert "approval_assignee_id" in tasks
    assert "approval_role_name" in tasks
    assert "approval_reminder_after_minutes" in tasks
    assert "approval_escalation_after_minutes" in tasks
    assert "approval_escalation_role_name" in tasks
    assert "approver_user_id" in decisions
    assert "approval_comment" in decisions
    assert "rejection_reason" in decisions
    assert "decided_at" in decisions
    assert "reminder_sent_at" in decisions
    assert "escalation_sent_at" in decisions
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run: `python -m pytest backend/tests/test_pipeline_approval_migration.py -q`

Expected: FAIL because the approval columns do not exist.

- [ ] **Step 3: Add model columns, constraints, indexes, and migration**

Use `approval_assignee_type` values `creator`, `member`, `role`; store member user ID in `approval_assignee_id`, role snapshot in `approval_role_name`, and default all reminder intervals to `null`. Add `approver_user_id`, nullable comment/reason/timestamps, and reminder timestamps to decisions. The migration must add nullable-safe defaults for existing tasks: `approval_required=true`, `approval_assignee_type='creator'`, `approval_reminder_after_minutes=1440`, `approval_escalation_after_minutes=2880`.

- [ ] **Step 4: Extend Pydantic contracts**

Add `ApprovalAssigneeType`, `PipelineApprovalConfig`, fields to `PipelineDraftResponse`, `PipelineTaskCreate`, `PipelineTaskResponse`, `PipelineDecisionResponse`, and an approval payload with optional comment. Validate non-negative intervals, member ID/role consistency, and require a reason for reject.

- [ ] **Step 5: Run migration and contract tests**

Run: `python -m pytest backend/tests/test_pipeline_approval_migration.py backend/tests/test_phase_d_memory_migration.py -q`

Expected: PASS.

### Task 2: Make chat scheduling draft-only and expand schedule parsing

**Files:**
- Modify: `backend/app/routers/pipeline.py:70-125`
- Modify: `backend/app/services/chat_platform_actions.py:30-220`
- Modify: `backend/app/routers/chat.py:1013-1045`
- Modify: `backend/app/schemas/pipeline.py:20-55`
- Test: `backend/tests/test_chat_platform_actions.py`
- Test: `backend/tests/test_pipeline_scheduler.py`

- [ ] **Step 1: Add failing parser and draft-only tests**

```python
def test_chat_schedule_action_returns_draft_without_creating_task():
    command = parse_scheduled_pipeline_command("请创建每天 09:30 的 AI 趋势日报")
    assert command is not None
    assert command.status == "draft"
    assert command.draft is not None

async def test_chat_schedule_execution_never_writes_task_until_confirmation():
    result = await execute_scheduled_pipeline_command(...)
    assert result.status == "draft"
    assert result.task_id is None
    assert await db.scalar(select(PipelineTask).where(...)) is None
```

- [ ] **Step 2: Run focused tests and verify failure**

Run: `python -m pytest backend/tests/test_chat_platform_actions.py -q`

Expected: FAIL because the current action writes `PipelineTask`.

- [ ] **Step 3: Implement parser and action behavior**

Return the draft in `PlatformActionResult` and expose it through `as_event`. Keep run-now as a draft property and never execute it from chat. Add parser helpers for daily, weekday, workday and monthly expressions, preserving the existing cron validator.

- [ ] **Step 4: Add confirmation API behavior tests**

Assert `confirmed` is required and only the Pipeline task endpoint writes a task. Assert approval configuration from the confirmed payload is persisted.

- [ ] **Step 5: Run chat and scheduler regression tests**

Run: `python -m pytest backend/tests/test_chat_platform_actions.py backend/tests/test_pipeline_scheduler.py -q`

Expected: PASS.

### Task 3: Implement approval authorization, comments, memory, and notifications

**Files:**
- Create: `backend/app/services/pipeline_approval.py`
- Modify: `backend/app/routers/pipeline.py:120-630`
- Modify: `backend/app/services/pipeline_repository.py:80-150`
- Modify: `backend/app/services/pipeline_executor.py:396-430`
- Modify: `backend/app/services/feishu_delivery.py:20-45`
- Test: `backend/tests/test_pipeline_decisions.py`
- Test: `backend/tests/test_pipeline_worker.py`

- [ ] **Step 1: Add failing approval behavior tests**

Cover:

```python
async def test_enabled_approval_creates_pending_decision_and_pending_notifications(...):
    ...

async def test_disabled_approval_persists_output_without_decision(...):
    ...

async def test_only_assigned_member_or_role_can_decide(...):
    ...

async def test_approve_accepts_optional_comment_and_records_approver_time(...):
    ...

async def test_reject_requires_reason_and_records_it_without_memory(...):
    ...
```

- [ ] **Step 2: Run focused tests and verify failure**

Run: `python -m pytest backend/tests/test_pipeline_decisions.py backend/tests/test_pipeline_worker.py -q`

Expected: FAIL because all executions create owner decisions and approve has no comment/assignee checks.

- [ ] **Step 3: Add centralized approval policy helpers**

Implement `resolve_approval_user_ids`, `is_authorized_approver`, and `enqueue_pending_decision_notifications`. Creator resolves to task owner; member resolves to active organization membership; role resolves to active memberships with the saved role name. Reject inactive/missing assignees with 422 at task creation and deny non-assignees with 403 at decision time.

- [ ] **Step 4: Update executor decision creation**

Create a decision only when `task.approval_required` is true. Set `approver_user_id` only when there is one resolved approver; role policies remain represented by task policy and are checked on action. Enqueue one platform notification and route pending Feishu delivery rows using deterministic keys.

- [ ] **Step 5: Update decision endpoints**

Approve accepts `{comment?: string}` and records `approval_comment`, `approver_user_id`, `decided_at`; reject requires `reason` and records `rejection_reason`, `approver_user_id`, `decided_at`. Keep `request-changes` behavior unchanged except for assignee authorization. Preserve action payload hashes and replay behavior.

- [ ] **Step 6: Run focused and regression tests**

Run: `python -m pytest backend/tests/test_pipeline_decisions.py backend/tests/test_pipeline_worker.py backend/tests/test_chat_platform_actions.py -q`

Expected: PASS.

### Task 4: Add reminder and escalation worker

**Files:**
- Create: `backend/app/services/pipeline_approval_reminders.py`
- Create: `backend/app/workers/pipeline_approval_worker.py`
- Modify: `backend/app/config.py:15-45`
- Modify: `deploy/compose.hermes.yaml:120-190`
- Test: `backend/tests/test_pipeline_approval_reminders.py`

- [ ] **Step 1: Write failing reminder tests**

```python
async def test_pending_decision_reminder_is_enqueued_once_after_threshold(...):
    ...

async def test_escalation_is_enqueued_once_without_changing_pending_status(...):
    ...
```

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest backend/tests/test_pipeline_approval_reminders.py -q`

Expected: FAIL because no reminder service exists.

- [ ] **Step 3: Implement scan and enqueue logic**

Use decision creation time plus task interval. Claim with row locking where PostgreSQL is active; set `reminder_sent_at` and `escalation_sent_at` atomically with deterministic `NotificationOutbox.event_key`. Notify assigned member/role and escalation role/admins. Never mutate decision status.

- [ ] **Step 4: Add worker loop and deployment service**

Use configured poll interval and add `pipeline-approval-worker` to compose with the same database environment as `pipeline-worker`.

- [ ] **Step 5: Run worker and migration tests**

Run: `python -m pytest backend/tests/test_pipeline_approval_reminders.py backend/tests/test_pipeline_decisions.py -q`

Expected: PASS.

### Task 5: Add Pipeline and Dashboard frontend approval controls

**Files:**
- Modify: `web-platform/src/api/services/pipelineService.ts:1-190`
- Modify: `web-platform/src/api/services/dashboardService.ts:40-145`
- Modify: `web-platform/src/pages/PipelinePage.tsx:1-620`
- Modify: `web-platform/src/components/dashboard/DashboardDecisionPanel.tsx:1-40`
- Test: `web-platform/src/api/services/pipelineService.test.ts`
- Test: `web-platform/src/pages/PipelinePage.test.tsx`
- Test: `web-platform/src/pages/DashboardPage.test.tsx`

- [ ] **Step 1: Add failing service and UI tests**

Cover draft approval fields, create payload, approve comment, reject reason, assignee display, and the fact that a reject button is disabled until a reason is entered.

- [ ] **Step 2: Run Vitest and verify failure**

Run: `npm --prefix web-platform test -- --run src/api/services/pipelineService.test.ts src/pages/PipelinePage.test.tsx`

Expected: FAIL because current service methods do not accept comments and the dashboard panel hardcodes a rejection reason.

- [ ] **Step 3: Extend service types and request payloads**

Add `PipelineApprovalConfig`, `PipelineApprovalAssignee`, decision audit fields, `approveDecision(id, payload?)`, and `rejectDecision(id, payload)`. Keep deterministic idempotency keys stable.

- [ ] **Step 4: Build the confirmation controls**

In the existing draft confirmation section add approval required toggle, assignee mode selector, organization member/role selector, reminder and escalation numeric inputs, and a compact summary. Submit the edited draft with `confirmed: true`.

- [ ] **Step 5: Build decision interaction**

Add per-decision comment input for approval and reason input for rejection, show approver/time/status/reason, and refresh after mutations. Dashboard panel uses the same interaction contract without hardcoded reason text.

- [ ] **Step 6: Run frontend tests**

Run: `npm --prefix web-platform test -- --run src/api/services/pipelineService.test.ts src/pages/PipelinePage.test.tsx src/pages/DashboardPage.test.tsx`

Expected: PASS.

### Task 6: End-to-end verification and contract cleanup

**Files:**
- Modify: `backend/tests/test_pipeline_decisions.py`
- Modify: `backend/tests/test_chat_platform_actions.py`
- Modify: `web-platform/tests/e2e/production-artifact.spec.ts`
- Modify: `docs/frontend-api-contract.md`

- [ ] **Step 1: Add end-to-end acceptance assertions**

Exercise chat draft, confirmed task creation, scheduled execution, pending decision notification, approval with comment, rejection with required reason, and reminder idempotency.

- [ ] **Step 2: Run backend migration and full focused suite**

Run: `python -m pytest backend/tests/test_pipeline_approval_migration.py backend/tests/test_chat_platform_actions.py backend/tests/test_pipeline_scheduler.py backend/tests/test_pipeline_worker.py backend/tests/test_pipeline_decisions.py backend/tests/test_pipeline_approval_reminders.py -q`

Expected: PASS.

- [ ] **Step 3: Run frontend typecheck and tests**

Run: `npm --prefix web-platform run typecheck`
Run: `npm --prefix web-platform test -- --run`

Expected: PASS.

- [ ] **Step 4: Inspect the final diff**

Run: `git diff --check`
Run: `git status --short`

Expected: no whitespace errors; unrelated pre-existing changes remain untouched.
