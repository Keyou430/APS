# Phase D Task 0 基线检查点

> 日期：2026-08-12。范围：Task 0 Steps 1-6；Step 7 未勾选。Task 4/5 未启动。

## 执行边界

- 唯一执行计划：`docs/superpowers/plans/2026-08-10-phase-d-memory-first-governance.md`。
- 当前工作树 `E:\My_Opjects\agent-platform-system` 保持原状：`codex/frontend-replacement@5c29449`，计划文件有本地修改；未 pull、reset、checkout、clean、stage 或 commit。
- 独立 backend worktree：`E:\My_Opjects\agent-platform-system-phase-d-memory`，分支 `codex/phase-d-memory`，从 `origin/main@25dbd67bc07138e37d11b4ae41ee9ca94021e181` 创建。
- 计划同步是该分支首个独立边界提交：`e371ed9 docs(phase-d): sync memory governance execution plan`。提交前 staged allowlist 仅为计划文件；未夹带 PR #7、`web-platform/**`、`.superpowers/`、runtime、uploads、凭据或真实数据。
- 嵌套前端 worktree 未触碰：`web-platform` branch `refactor/modern-ui`，HEAD `8072e0bfc93c40ed476710f958cdd4cc6671685c`，status 162 entries；存在 nested `.git`、`.env`、`node_modules`、`dist`、`test-results`、`.sisyphus`。

## Frontend baseline and gate

- PR #7: `https://github.com/OneAsmallFish/agent-platform-system/pull/7`
  - state `OPEN`, `Draft=true`, `BLOCKED`, `REVIEW_REQUIRED`。
  - base `main@25dbd67bc07138e37d11b4ae41ee9ca94021e181`。
  - current remote head observed 2026-08-12: `d6f4ea1785a05e09547b9a39ab64bd5fb106142f`.
  - required checks: `test`, `sqlite`, `postgres`, `config` pass; `quality` fail。
- Issue #6 remains `OPEN`.
- Issue #8 remains `OPEN`.
- PR #7/Issue #6/#8 gate remains active. No replacement merge SHA exists; Step 7 is not satisfied. Task 4 and Task 5 stay blocked.

## Backend characterization

Commands were run from `E:\My_Opjects\agent-platform-system-phase-d-memory\backend` using the existing interpreter at `E:\My_Opjects\agent-platform-system\backend\.venv\Scripts\python.exe` because the isolated worktree does not carry ignored `.venv` files:

```text
.\.venv\Scripts\python.exe -m pytest -q
263 passed, 60 warnings in 44.12s

.\.venv\Scripts\python.exe -m ruff check .
All checks passed!

.\.venv\Scripts\python.exe scripts\export_openapi.py --check
OpenAPI snapshot is current: docs\openapi.json

.\.venv\Scripts\python.exe -m alembic heads
20260810_0012 (head)
```

定向 coverage（memory/skills/chat-context/attachments/link/sandbox/Hermes boundary）:

```text
84 passed in 6.93s
```

既有 warnings 为 Pydantic alias/validation_alias/serialization_alias metadata warnings；本轮未修改这些既有问题。

## Demo-only exclusions

已确认以下内容不能成为 Phase D memory source 或组织授权来源，负向测试留给 Task 2/3：

- `backend/app/services/fixed_knowledge.py` 的固定企业/岗位 context 与 username mapping。
- `deploy/hermes/skills/hr-weekly-report` 的 filesystem Skill 全局挂载。
- `dingtalk_documents` global operator/toolset。
- 临时 attachments 与 public collaboration links。

现有 authorization 仍须只使用 `CurrentOrganizationContext + membership role/permission`；不得从 `User.default_organization_id`、username、请求 DTO 或 provider 返回值推导授权。

## Alembic and migration gate

- Current single head: `20260810_0012`。
- `backend/migrations/versions/20260811_0013_phase_d_memory.py` 未被占用。
- Task 1 migration must use `revision='20260811_0013'` and `down_revision='20260810_0012'`.
- 未执行任何 upgrade/downgrade；未连接共享、演示或生产数据库。
- `alembic check` 在未升级的本地 SQLite 测试数据库上报告 `Target database is not up to date`；这不是 migration roundtrip 证据，也没有改变数据库。

## Gate decision

- Task 0 Steps 1-6：通过。
- Task 0 Step 7：未通过且未勾选，继续等待 PR #7 / Issue #6 / Issue #8 门禁。
- Backend-only Task 1-3：解锁，可从真实 RED 开始。
- Task 4：阻塞。
- Task 5：阻塞。

后续任何 stage、commit、push 或 Draft PR 写操作，都必须先展示精确 allowlist 与验证结果并请求用户确认。
