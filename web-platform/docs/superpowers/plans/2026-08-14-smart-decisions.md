# Smart Decisions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the cockpit smart decision row only after dashboard decision contracts are present in the backend OpenAPI snapshot. Until then, the frontend may only render existing read-only `DashboardDataResponse.pipelines` data.

**Architecture:** Keep the first implementation inside the existing legacy cockpit because `/` is intentionally legacy-hosted. Do not add typed dashboard decision service methods until the backend router, schema, OpenAPI snapshot, frontend API contract, and contract tests are updated together. The current acceptance-safe route reads `/dashboard` and adapts the `pipelines` field only.

**Tech Stack:** Legacy HTML/CSS/JavaScript, TypeScript dashboard service contracts, Node contract tests, Vite build.

---

### Task 1: Contract Boundary Tests

**Files:**
- Modify: `D:\3.0\web-platform\tests\portal_workbench.test.js`
- Modify: `D:\3.0\web-platform\src\api\services\dashboardService.test.ts`

- [ ] **Step 1: Write failing layout and interaction contract assertions**

Add assertions that `cockpit-decisions` appears before `cockpit-panels`, the preview limit is 5, the drawer exists, and approve/reject action handlers are present.

- [ ] **Step 2: Write failing dashboard service assertions**

Assert that dashboard service exposes only registered dashboard endpoints and does not call `/dashboard/decisions` or any `/pipeline/*` endpoint before OpenAPI includes those paths.

- [ ] **Step 3: Run tests and verify red**

Run: `npm.cmd test` and `npx.cmd vitest run src/api/services/dashboardService.test.ts`

Expected: tests fail if unregistered decision or pipeline endpoints are exposed.

### Task 2: Backend Contract Gate

**Files:**
- Modify only after backend confirmation: backend router/schema, `backend/docs/openapi.json`, `docs/frontend-api-contract.md`, frontend service and tests.

- [ ] **Step 1: Freeze backend operations**

Record operationId, request/response/error schemas, permissions, organization boundaries, and retention behavior in the backend API contract.

- [ ] **Step 2: Add service methods only after OpenAPI is updated**

Implement list, approve, reject, or regenerate methods only when the corresponding paths are present in the generated OpenAPI snapshot.

- [ ] **Step 3: Run service tests**

Run: `npx.cmd vitest run src/api/services/dashboardService.test.ts`

Expected: service tests pass without unregistered API paths.

### Task 3: Cockpit Markup And Styles

**Files:**
- Modify: `D:\3.0\web-platform\index.html`
- Modify: `D:\3.0\web-platform\styles.css`

- [ ] **Step 1: Move smart decision card**

Place `#cockpit-decisions` after `#cockpitKpiGrid` and before `.cockpit-panels`.

- [ ] **Step 2: Add drawer shell**

Add `#cockpitDecisionDrawer` with status filter buttons and list container.

- [ ] **Step 3: Add responsive styles**

Style the full-width smart decision row, five-item preview grid, pending action buttons, status chips, rejection panel, and drawer.

### Task 4: Cockpit Behavior

**Files:**
- Modify: `D:\3.0\web-platform\src\app.js`
- Modify: `D:\3.0\web-platform\tests\portal_workbench.test.js`

- [ ] **Step 1: Replace static decisions with state-backed decisions**

Add sample decision fallback data and render only the first 5 in the cockpit row.

- [ ] **Step 2: Add runtime contract calls**

Fetch decisions through dashboard decision service methods only after the backend contract exists. Before then, use read-only dashboard pipelines and disabled/local presentation state.

- [ ] **Step 3: Add interactions**

Add `查看全部`, drawer filters, `同意`, `驳回`, quick reasons, free-text reason, and rejection submit/cancel behavior.

- [ ] **Step 4: Run contract tests**

Run: `npm.cmd test`

Expected: contract tests pass.

### Task 5: Verification And Commit

**Files:**
- Modified source and test files from Tasks 1-4.

- [ ] **Step 1: Run full verification**

Run:
- `npm.cmd test`
- `npx.cmd vitest run`
- `npm.cmd run build`

- [ ] **Step 2: Commit and push**

Commit all files related to this smart decision feature and push the current branch.
