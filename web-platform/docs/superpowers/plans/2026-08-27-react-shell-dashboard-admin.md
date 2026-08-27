# React Shell, Dashboard, and Admin Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the dashboard and complete admin workspace onto one React shell and pathname router while preserving the existing CSS, DOM class contract, behavior, and legacy fallback for unmigrated routes.

**Architecture:** React owns the shared shell for React routes and renders typed page components inside it. The dashboard and admin pages use existing service boundaries, organization-scoped cache behavior, and local storage adapters; missing admin contracts remain typed fail-closed operations. `index.html` and `app.js` keep only the markup and modules still required by legacy routes until later migrations remove them.

**Tech Stack:** React 19, TypeScript, Vite, Vitest, React Testing Library, Playwright, existing `styles.css`, GridStack. Tailwind, shadcn/ui, and lucide are not installed in this phase; local React UI components use the existing CSS class contract and can adopt those libraries later without changing the visual baseline.

---

## File Map

Create:

- `src/app/location.ts`: pathname and historical hash normalization.
- `src/app/AppShell.tsx`: shared React shell and navigation.
- `src/app/AppShell.test.tsx`: shell structure and navigation behavior.
- `src/app/Icon.tsx`: existing symbol sprite wrapper.
- `src/app/SymbolSprite.tsx`: symbol definitions used by React routes.
- `src/components/ui/Button.tsx`, `Card.tsx`, `Tabs.tsx`, `Badge.tsx`, `EmptyState.tsx`: class-preserving primitives.
- `src/components/ui/Dialog.tsx`, `Sheet.tsx`, `AlertDialog.tsx`, `Toast.tsx`: accessible overlay primitives.
- `src/components/ui/DataTable.tsx`: semantic table with caller-owned filtering and pagination.
- `src/components/ui/ui.test.tsx`: shared primitive behavior tests.
- `src/components/dashboard/DashboardKpiGrid.tsx` and its test.
- `src/components/dashboard/DashboardDecisionPanel.tsx` and its test.
- `src/components/dashboard/DashboardWorkPanels.tsx` and its test.
- `src/components/dashboard/dashboardModel.ts` and its test.
- `src/pages/AdminPage.tsx` and its test.
- `src/components/admin/adminModel.ts` and its test.
- `src/components/admin/AdminUsersPanel.tsx`, `AdminAuditPanel.tsx`, `AdminAIQueryPanel.tsx`, `AdminSessionsPanel.tsx`, `AdminNewsPanel.tsx`, `AdminAnomaliesPanel.tsx`.
- `src/api/services/adminCompatibilityService.ts` and its test.
- `src/app/modalRegistry.tsx` and its test.

Modify:

- `src/app/routes.tsx`: add `/admin` and mark `/` React-owned.
- `src/app/App.tsx`: render the common shell and page routes.
- `src/app/mountReactApp.tsx`: mount the pathname-aware app.
- `src/legacy-entry.ts`: normalize historical hashes and load legacy modules only for legacy routes.
- `index.html`: remove dashboard/admin markup only after the React replacements pass their tests; retain legacy markup needed by other routes during transition.
- `styles.css`: add only the React shell visibility/geometry bridge; do not rewrite existing component rules.
- `src/pages/DashboardPage.tsx`: replace the placeholder dashboard view with the class-preserving composition.
- `src/api/services/index.ts` and `src/app/appRuntime.ts`: expose any typed compatibility service required by admin.
- `src/app/App.test.tsx`, `tests/e2e/production-artifact.spec.ts`, and focused E2E tests: replace legacy dashboard assumptions with React ownership checks.

## Task 1: Lock Pathname Ownership and Build the Shared Shell

**Files:**
- Create: `src/app/location.ts`
- Create: `src/app/AppShell.tsx`
- Create: `src/app/AppShell.test.tsx`
- Create: `src/app/Icon.tsx`
- Create: `src/app/SymbolSprite.tsx`
- Modify: `src/app/routes.tsx`
- Modify: `src/app/App.tsx`
- Modify: `src/app/mountReactApp.tsx`
- Modify: `src/legacy-entry.ts`
- Modify: `styles.css`

- [ ] **Step 1: Write the failing route and shell tests.**

Add these behaviors to `src/app/AppShell.test.tsx` and the route test section of `src/app/App.test.tsx`:

```tsx
it("owns the dashboard and admin pathnames", () => {
  expect(isReactOwnedRoute("/")).toBe(true);
  expect(isReactOwnedRoute("/admin")).toBe(true);
  expect(resolveRoute("/admin").id).toBe("admin");
});

it("converts historical view hashes into pathnames", () => {
  expect(normalizeLocation({ pathname: "/", hash: "#workspace" })).toBe("/");
  expect(normalizeLocation({ pathname: "/", hash: "#admin" })).toBe("/admin");
  expect(normalizeLocation({ pathname: "/portal", hash: "#portal-overview" })).toBe("/portal");
});

it("renders the existing shell class structure and navigates by pathname", async () => {
  const user = userEvent.setup();
  const pushState = vi.spyOn(window.history, "pushState");
  render(<AppShell pathname="/">{<h1>驾驶舱</h1>}</AppShell>);

  expect(document.querySelector(".app-shell")).toBeInTheDocument();
  expect(document.querySelector(".module-sidebar")).toBeInTheDocument();
  expect(document.querySelector(".content-area")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "账号管理" }));
  expect(pushState).toHaveBeenCalledWith({}, "", "/admin");
});
```

- [ ] **Step 2: Run the focused tests and verify the expected failure.**

Run: `npm exec vitest run src/app/App.test.tsx src/app/AppShell.test.tsx`

Expected: FAIL because `/` is still `legacy-host`, `/admin` is not registered, `normalizeLocation` and `AppShell` do not exist, and the current app does not render the shell from React.

- [ ] **Step 3: Implement the minimal route and shell foundation.**

Add the `admin` route and change dashboard ownership in `src/app/routes.tsx`. Add a pure helper with this contract:

```ts
export type LocationLike = { pathname: string; hash: string };

export function normalizeLocation(location: LocationLike): string {
  if (location.pathname === "/" && location.hash === "#admin") return "/admin";
  return location.pathname;
}
```

`AppShell` must render the existing shell class names, use `history.pushState` for internal pathname navigation, dispatch `popstate`, and keep sidebar collapse and width in the existing `UiStore`. `SymbolSprite` must contain the current icon symbols needed by the shell; `Icon` renders `<svg className="icon"><use href={`#${id}`} /></svg>`.

Update `mountReactApp` to pass the normalized pathname and subscribe to `popstate`. Update `legacy-entry.ts` to use the same normalization before deciding whether to dynamically import legacy modules. Add the smallest CSS bridge needed to hide the static legacy shell while React owns the route and let the React shell occupy the viewport:

```css
body.react-route-active > .app-shell { display: none; }
body.react-route-active #reactAppRoot { display: block; min-height: 100dvh; padding: 0; }
```

- [ ] **Step 4: Run the focused tests and verify they pass.**

Run: `npm exec vitest run src/app/App.test.tsx src/app/AppShell.test.tsx`

Expected: PASS, including route ownership, hash conversion, shell class structure, and pathname navigation.

- [ ] **Step 5: Commit the shell boundary.**

Run: `git add src/app/location.ts src/app/AppShell.tsx src/app/AppShell.test.tsx src/app/Icon.tsx src/app/SymbolSprite.tsx src/app/routes.tsx src/app/App.tsx src/app/mountReactApp.tsx src/legacy-entry.ts styles.css && git commit -m "feat: establish React shell route ownership"`

In the current workspace this command is expected to report that no Git repository exists; retain the files and continue without destructive cleanup.

## Task 2: Extract Class-Preserving React UI Primitives

**Files:**
- Create: `src/components/ui/Button.tsx`, `Card.tsx`, `Tabs.tsx`, `Badge.tsx`, `EmptyState.tsx`
- Create: `src/components/ui/Dialog.tsx`, `Sheet.tsx`, `AlertDialog.tsx`, `Toast.tsx`, `DataTable.tsx`
- Create: `src/components/ui/ui.test.tsx`

- [ ] **Step 1: Write failing primitive tests.**

Cover one behavior per test:

```tsx
it("Button preserves the existing classes and disabled behavior", async () => {
  const onClick = vi.fn();
  render(<Button className="primary" onClick={onClick}>保存</Button>);
  expect(screen.getByRole("button", { name: "保存" })).toHaveClass("btn", "primary");
  await userEvent.click(screen.getByRole("button", { name: "保存" }));
  expect(onClick).toHaveBeenCalledOnce();
});

it("Dialog closes on Escape and returns focus to its trigger", async () => {
  const user = userEvent.setup();
  render(<Dialog title="编辑" trigger={<button>打开</button>}><input aria-label="名称" /></Dialog>);
  await user.click(screen.getByRole("button", { name: "打开" }));
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("dialog", { name: "编辑" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "打开" })).toHaveFocus();
});

it("DataTable renders an accessible empty row", () => {
  render(<DataTable ariaLabel="用户列表" columns={[{ key: "name", label: "名称" }]} rows={[]} emptyMessage="暂无用户" />);
  expect(screen.getByRole("table", { name: "用户列表" })).toBeInTheDocument();
  expect(screen.getByText("暂无用户")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the tests and verify they fail for missing components.**

Run: `npm exec vitest run src/components/ui/ui.test.tsx`

Expected: FAIL because the primitives do not exist.

- [ ] **Step 3: Implement the primitives against the existing CSS contract.**

Use `className="btn"`, `className="card"`, `className="tabs"`, `className="tab"`, `className="status-badge"`, `className="modal-backdrop"`, `className="modal"`, `className="drawer-overlay"`, `className="drawer-panel"`, `className="toast"`, and `className="data-table"` as the default DOM classes. `Dialog` must implement `role="dialog"`, `aria-modal="true"`, ESC close, backdrop close, focus capture, and focus restoration. `AlertDialog` must require an explicit confirm callback. `DataTable` must render headers, body, empty row, and caller-provided pagination controls without embedding data-fetching logic.

- [ ] **Step 4: Run the tests and verify they pass.**

Run: `npm exec vitest run src/components/ui/ui.test.tsx`

Expected: PASS with no console errors.

- [ ] **Step 5: Commit the shared primitives when Git metadata is available.**

Run: `git add src/components/ui && git commit -m "feat: add class-preserving React UI primitives"`

## Task 3: Replace the Dashboard Placeholder with the Existing Cockpit Structure

**Files:**
- Create: `src/components/dashboard/dashboardModel.ts`
- Create: `src/components/dashboard/dashboardModel.test.ts`
- Create: `src/components/dashboard/DashboardKpiGrid.tsx`
- Create: `src/components/dashboard/DashboardKpiGrid.test.tsx`
- Create: `src/components/dashboard/DashboardDecisionPanel.tsx`
- Create: `src/components/dashboard/DashboardDecisionPanel.test.tsx`
- Create: `src/components/dashboard/DashboardWorkPanels.tsx`
- Create: `src/components/dashboard/DashboardWorkPanels.test.tsx`
- Modify: `src/pages/DashboardPage.tsx`
- Modify: `src/app/App.tsx`

- [ ] **Step 1: Write failing dashboard behavior tests.**

Add tests for the actual cockpit sections and mutations:

```tsx
type DashboardPageProps = {
  cache: PageCache;
  organizationId: number | null;
  service: DashboardService;
  workItems: WorkItemsService;
  knowledge: KnowledgeService;
  enterprise: EnterpriseService;
  pipeline: PipelineService;
};

it("renders the cockpit sections with the legacy class structure", async () => {
  render(<DashboardPage cache={cache} organizationId={7} service={dashboardService} workItems={workItems} knowledge={knowledge} enterprise={enterprise} pipeline={pipeline} />);
  expect(await screen.findByRole("heading", { name: "驾驶舱" })).toBeInTheDocument();
  expect(document.querySelector("#cockpitKpiGrid")).toBeInTheDocument();
  expect(document.querySelector("#cockpit-decisions")).toBeInTheDocument();
  expect(document.querySelector("#cockpit-tasks")).toBeInTheDocument();
  expect(document.querySelector("#cockpit-calendar")).toBeInTheDocument();
  expect(document.querySelector("#cockpit-docs")).toBeInTheDocument();
  expect(document.querySelector("#cockpit-shortcuts")).toBeInTheDocument();
});

it("marks a dashboard layout conflict without replacing the current layout", async () => {
  service.saveLayout.mockRejectedValueOnce({ status: 409 });
  render(<DashboardPage {...props} />);
  await userEvent.click(await screen.findByRole("button", { name: "保存布局" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("布局版本已被更新");
});

it("adds and completes a cockpit task through the work item service", async () => {
  render(<DashboardPage {...props} />);
  await userEvent.type(await screen.findByLabelText("添加新任务"), "准备周报");
  await userEvent.click(screen.getByRole("button", { name: "添加任务" }));
  expect(workItems.createWorkItem).toHaveBeenCalledWith(expect.objectContaining({ title: "准备周报" }));
});
```

Add model tests for mapping missing arrays to empty states, preserving stable widget IDs, and translating layout revision data without string concatenation.

- [ ] **Step 2: Run dashboard tests and verify the expected failure.**

Run: `npm exec vitest run src/pages/DashboardPage.test.tsx src/components/dashboard`

Expected: FAIL because the current page does not render cockpit IDs, does not accept the required service composition, and does not implement cockpit actions.

- [ ] **Step 3: Implement the dashboard model and component slices.**

Keep `DashboardPage` responsible for loading/status/cache orchestration. Move markup and local interaction state into these slices:

- `DashboardKpiGrid`: `#cockpitKpiGrid`, KPI cards, expand/collapse detail, add-component menu, save/reset layout buttons, and GridStack registration.
- `DashboardDecisionPanel`: `#cockpit-decisions`, filter tabs, decision status rendering, approve/reject/regenerate callbacks, and fail-closed demo-mode behavior.
- `DashboardWorkPanels`: tasks, calendar, documents, and shortcuts under their existing IDs and class names. Tasks use `workItems`; calendar and shortcuts use the existing scoped local storage adapters; documents use `knowledge` data.

The dashboard view model must expose stable IDs and optional arrays rather than raw DOM payloads:

```ts
export type DashboardViewModel = {
  layout: DashboardLayoutResponse;
  kpis: DashboardKpi[];
  decisions: DashboardDecision[];
  tasks: DashboardTask[];
  calendarEvents: DashboardEvent[];
  documents: DashboardDocument[];
  shortcuts: DashboardShortcut[];
};
```

Preserve `GridStack` for layout behavior and use the existing `dashboardLayoutMapper`. Do not create sample decisions when mock mode is off. Map 403 to forbidden, 409 to conflict, and all other request errors to the existing dashboard error message.

- [ ] **Step 4: Run dashboard tests and verify they pass.**

Run: `npm exec vitest run src/pages/DashboardPage.test.tsx src/components/dashboard`

Expected: PASS for structure, loading/empty/error/forbidden/conflict states, layout save/reset, KPI interaction, decision filtering, task creation/completion, calendar operations, documents, shortcuts, and organization-scoped cache behavior.

- [ ] **Step 5: Commit the dashboard migration when Git metadata is available.**

Run: `git add src/pages/DashboardPage.tsx src/components/dashboard src/app/App.tsx && git commit -m "feat: migrate dashboard cockpit to React"`

## Task 4: Migrate the Complete Admin Workspace

**Files:**
- Create: `src/api/services/adminCompatibilityService.ts`
- Create: `src/api/services/adminCompatibilityService.test.ts`
- Create: `src/components/admin/adminModel.ts`
- Create: `src/components/admin/adminModel.test.ts`
- Create: `src/pages/AdminPage.tsx`
- Create: `src/pages/AdminPage.test.tsx`
- Create: `src/components/admin/AdminUsersPanel.tsx`
- Create: `src/components/admin/AdminAuditPanel.tsx`
- Create: `src/components/admin/AdminAIQueryPanel.tsx`
- Create: `src/components/admin/AdminSessionsPanel.tsx`
- Create: `src/components/admin/AdminNewsPanel.tsx`
- Create: `src/components/admin/AdminAnomaliesPanel.tsx`
- Modify: `src/app/routes.tsx`, `src/app/App.tsx`, `src/app/appRuntime.ts`, `src/api/services/index.ts`

- [ ] **Step 1: Write failing admin and compatibility tests.**

The compatibility service must fail closed with a typed error:

```ts
it("does not invent an API for an unavailable admin operation", async () => {
  const service = createAdminCompatibilityService();
  await expect(service.listAIQueries({ page: 1, pageSize: 20 })).rejects.toMatchObject({
    code: "frontend_contract_missing",
    operation: "admin_ai_queries_list",
  });
});
```

The page tests must prove all six tabs exist and the primary flows call the existing services:

```tsx
it("renders all admin panels", async () => {
  render(<AdminPage {...props} />);
  expect(screen.getByRole("tab", { name: "用户管理" })).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "审计日志" })).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "AI查询" })).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "会话管理" })).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "资讯管理" })).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "异常统计" })).toBeInTheDocument();
});

it("creates a user through UsersService", async () => {
  render(<AdminPage {...props} />);
  await userEvent.click(screen.getByRole("button", { name: "添加账号" }));
  await userEvent.type(screen.getByLabelText("用户名"), "new-user");
  await userEvent.type(screen.getByLabelText("密码"), "password-123");
  await userEvent.click(screen.getByRole("button", { name: "创建账号" }));
  expect(users.createUser).toHaveBeenCalledWith(expect.objectContaining({ username: "new-user" }));
});
```

Add tests for pagination/filter query parameters, role assignment, enable/disable confirmation, password reset validation, audit filtering, news service calls, and fail-closed unavailable panels.

- [ ] **Step 2: Run admin tests and verify the expected failure.**

Run: `npm exec vitest run src/components/admin src/api/services/adminCompatibilityService.test.ts`

Expected: FAIL because the React admin page and typed compatibility service do not exist.

- [ ] **Step 3: Implement admin models, panels, and service wiring.**

Use existing service methods without changing their endpoint contracts:

- `users.listUsers/createUser/updateUser/deleteUser/assignRoles` for the users panel.
- `audit.listAuditEvents` for audit logs.
- `enterprise.listAnnouncements/createAnnouncement/updateAnnouncement/publishAnnouncement/withdrawAnnouncement` for news.
- `adminCompatibilityService` for AI queries, sessions, anomalies, and password reset; it rejects with `code: "frontend_contract_missing"` and never falls back to a fabricated request.

Keep the existing admin class IDs and visual structure (`admin-subtabs`, `admin-subtab`, `admin-panel`, `adminPanelUsers`, `adminPanelAudit`, `adminPanelAIQuery`, `adminPanelSessions`, `adminPanelNews`, `adminPanelAnomalies`). Use the shared `DataTable`, `Badge`, `Dialog`, `AlertDialog`, and `Toast` primitives. Store the active admin tab and pagination in React state; do not read or write admin state through `querySelector`, `innerHTML`, or global mutable variables.

- [ ] **Step 4: Run admin tests and verify they pass.**

Run: `npm exec vitest run src/components/admin src/api/services/adminCompatibilityService.test.ts`

Expected: PASS for all six panels, service calls, filtering, pagination, loading/empty/error/forbidden states, role authorization, and fail-closed unavailable operations.

- [ ] **Step 5: Commit the admin migration when Git metadata is available.**

Run: `git add src/api/services/adminCompatibilityService.ts src/api/services/adminCompatibilityService.test.ts src/components/admin src/app/routes.tsx src/app/App.tsx src/app/appRuntime.ts src/api/services/index.ts && git commit -m "feat: migrate complete admin workspace to React"`

## Task 5: Move Dashboard/Admin Native Modals to React

**Files:**
- Create: `src/app/modalRegistry.tsx`
- Create: `src/app/modalRegistry.test.tsx`
- Modify: `src/components/dashboard/DashboardWorkPanels.tsx`
- Modify: `src/pages/AdminPage.tsx`
- Modify: `src/components/ui/Dialog.tsx`, `Sheet.tsx`, `AlertDialog.tsx`, `Toast.tsx`
- Modify: `index.html`
- Modify: `src/app.js`

- [ ] **Step 1: Write failing modal flow tests.**

Cover the dashboard event modal, admin create-user modal, role modal, reset-password two-step flow, and news modal:

```tsx
it("clears the reset password output when the modal closes", async () => {
  render(<AdminPage {...props} />);
  await userEvent.click(screen.getByRole("button", { name: "重置密码" }));
  await userEvent.click(screen.getByRole("button", { name: "确认重置" }));
  expect(await screen.findByText("新密码仅显示一次")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "我已保存密码" }));
  expect(screen.queryByText("新密码仅显示一次")).not.toBeInTheDocument();
  expect(screen.queryByText(/password/)).not.toBeInTheDocument();
});

it("closes an active modal on backdrop click", async () => {
  render(<DashboardPage {...props} />);
  await userEvent.click(screen.getByRole("button", { name: "添加日程" }));
  await userEvent.click(screen.getByTestId("dialog-backdrop"));
  expect(screen.queryByRole("dialog", { name: "添加日程" })).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run modal tests and verify the expected failure.**

Run: `npm exec vitest run src/app/modalRegistry.test.tsx src/pages/AdminPage.test.tsx src/components/dashboard/DashboardWorkPanels.test.tsx`

Expected: FAIL because the modal flows are still bound to legacy IDs and global handlers.

- [ ] **Step 3: Implement the modal registry and migrate the required forms.**

Render only the active React modal from `modalRegistry.tsx`; modal state belongs to the owning page. Preserve the existing modal classes, titles, labels, form validation, mobile bottom-sheet layout, and close semantics. Use `AlertDialog` for delete/enable/disable confirmations. Password reset must clear generated password and username when closed. Keep remaining legacy modal markup for routes that still use it.

After React tests pass, remove only these matching blocks from `index.html`: dashboard event modal, dashboard scheduled-task/component modal blocks, admin news/notice modal, admin user modal, admin role modal, and admin reset-password modal. Remove only the corresponding `app.js` handlers after `rg` confirms no remaining React or legacy consumer references those IDs.

- [ ] **Step 4: Run modal tests and verify they pass.**

Run: `npm exec vitest run src/app/modalRegistry.test.tsx src/pages/AdminPage.test.tsx src/components/dashboard/DashboardWorkPanels.test.tsx`

Expected: PASS for ESC, backdrop click, focus restoration, form submission, validation, error toast, confirmation, and sensitive-data cleanup.

- [ ] **Step 5: Commit modal migration when Git metadata is available.**

Run: `git add src/app/modalRegistry.tsx src/app/modalRegistry.test.tsx src/components/ui src/components/admin src/components/dashboard index.html src/app.js && git commit -m "feat: migrate dashboard and admin modals to React"`

## Task 6: Finish Route Cleanup and Verify Legacy Isolation

**Files:**
- Modify: `src/app/App.test.tsx`
- Modify: `tests/production_artifact.test.js`
- Modify: `tests/e2e/production-artifact.spec.ts`
- Create or modify: `tests/e2e/react-shell-dashboard-admin.spec.ts`
- Modify: `styles.css` only if screenshot comparison proves a required shell bridge is missing

- [ ] **Step 1: Write failing route isolation and responsive E2E tests.**

The new Playwright test must assert:

```ts
test("dashboard and admin are React-owned without duplicated legacy shell", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator('[data-entry="react-route-shell"]')).toHaveAttribute("data-active-route", "dashboard");
  await expect(page.locator("#legacyWorkspaceHost")).toHaveCount(0);
  await expect(page.locator("body.react-route-active > .app-shell")).toBeHidden();
  await expect(page.locator("#reactAppRoot > .app-shell")).toBeVisible();

  await page.goto("/admin");
  await expect(page.getByRole("heading", { name: "账号管理" })).toBeVisible();
  await expect(page.locator("#legacyWorkspaceHost")).toHaveCount(0);

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.locator("body")).toHaveJSProperty("scrollWidth", 390);
});
```

- [ ] **Step 2: Run the focused E2E test and verify it fails before cleanup.**

Run: `npm exec playwright test tests/e2e/react-shell-dashboard-admin.spec.ts`

Expected: FAIL until the route shell owns both pages, the old shell is hidden, and the dashboard/admin markup is removed from the React route DOM.

- [ ] **Step 3: Update production and app tests to express the new ownership contract.**

Change tests that currently expect `/` to remain legacy-hosted so they assert React dashboard ownership. Keep assertions that legacy-only routes dynamically load their modules and that no React route uses a legacy API v1 fallback. Add a source-level check that `legacy-entry.ts` conditionally imports `app.js` only outside React-owned routes.

- [ ] **Step 4: Run the complete verification set.**

Run:

```text
npm test
npm exec vitest run
npm run lint
npm run build
npm exec playwright test tests/e2e/react-shell-dashboard-admin.spec.ts tests/e2e/production-artifact.spec.ts
```

Expected: all Node tests, Vitest tests, lint, TypeScript/Vite build, and focused Playwright tests pass without console errors, React route DOM duplication, horizontal overflow, or CSS class regressions.

- [ ] **Step 5: Record the completed migration boundary.**

Run: `rg -n "cockpit|adminPanel|admin.*Modal|eventModal|adminUserModal|adminResetPwdModal" index.html src/app.js`

Expected: remaining matches are only legacy modules still used by unmigrated routes; dashboard/admin React components own their matching IDs and modal flows. When Git metadata is available, commit with `git add . && git commit -m "test: verify React dashboard and admin route isolation"` after reviewing the staged file list.

## Plan Self-Review

- Route ownership is covered by Task 1 and Task 6.
- Existing CSS and visual class preservation are enforced by Task 1, Task 2, Task 3, Task 4, and the responsive E2E check in Task 6.
- Complete admin scope is covered by six named panels in Task 4.
- Native modal migration and fail-closed missing contracts are covered by Task 4 and Task 5.
- Organization cache, status mapping, dashboard layout revision/409 behavior, and GridStack are covered by Task 3.
- Legacy fallback remains available until the final cleanup task and is checked by Task 6.
- No Tailwind, shadcn default theme, or lucide dependency is introduced before the visual baseline is verified.
- The plan contains no unresolved feature placeholders; the only environment limitation is the documented absence of Git metadata for commit commands.
