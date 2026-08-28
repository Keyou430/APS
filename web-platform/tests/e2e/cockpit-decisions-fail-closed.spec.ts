import { expect, test } from "@playwright/test";

const authSession = {
  token: {
    access_token: "demo-access-token",
    expires_in: 3600,
    organization_id: 7,
    refresh_token: "demo-refresh-token",
    token_type: "bearer",
  },
  user: {
    id: 1,
    username: "demo",
    email: "demo@example.com",
    role: "admin",
    member_type: "internal",
    permissions: ["portal:read", "org:read", "users:read", "agent:admin"],
    membership_id: 11,
    membership_expires_at: null,
    organization_id: 7,
    is_active: true,
    created_at: "2026-08-14T00:00:00Z",
  },
};

const decisionItems = [
  {
    id: "d1",
    title: "预算审批链路压缩",
    sourceTask: "预算审批效率巡检",
    generatedAt: "2026-08-14T08:30:00",
    status: "pending",
  },
  {
    id: "d2",
    title: "华东区仓储排班调整",
    sourceTask: "仓储履约日报",
    generatedAt: "2026-08-14T07:50:00",
    status: "pending",
  },
  {
    id: "d3",
    title: "新员工培训材料更新",
    sourceTask: "员工服务问答复盘",
    generatedAt: "2026-08-13T18:10:00",
    status: "approved",
  },
  {
    id: "d4",
    title: "CRM 客户跟进提醒",
    sourceTask: "销售机会健康度检查",
    generatedAt: "2026-08-13T16:40:00",
    status: "pending",
  },
  {
    id: "d5",
    title: "安全整改验收排序",
    sourceTask: "安全整改追踪",
    generatedAt: "2026-08-13T11:20:00",
    status: "regenerating",
  },
  {
    id: "d6",
    title: "服务台知识库补全",
    sourceTask: "IT 工单周报",
    generatedAt: "2026-08-12T15:20:00",
    status: "approved",
  },
];

test.beforeEach(async ({ page }) => {
  await page.addInitScript((session) => {
    window.sessionStorage.setItem("agent-platform.auth", JSON.stringify(session));
  }, authSession);
});

test("legacy cockpit fails closed without sample decisions when mock mode is off", async ({
  page,
}) => {
  await page.route("**/*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());

    if (!url.pathname.startsWith("/api/")) {
      await route.continue();
      return;
    }

    if (url.pathname === "/api/v1/auth/me" || url.pathname === "/api/auth/me") {
      await route.fulfill({
        status: 200,
        headers: { "content-type": "application/json; charset=utf-8" },
        body: JSON.stringify(authSession.user),
      });
      return;
    }

    if (
      url.pathname === "/api/v1/auth/refresh" ||
      url.pathname === "/api/auth/refresh"
    ) {
      await route.fulfill({
        status: 200,
        headers: { "content-type": "application/json; charset=utf-8" },
        body: JSON.stringify(authSession.token),
      });
      return;
    }

    if (url.pathname === "/api/v1/portal/bootstrap") {
      await route.fulfill({
        status: 200,
        headers: { "content-type": "application/json; charset=utf-8" },
        body: JSON.stringify({
          workspace: { tasks: [], notices: [], documents: [], resources: [], shortcuts: [] },
          calendar: { events: [] },
          knowledge: { spaces: [] },
          portal: { systems: [], services: [], news: [], preferences: {}, dashboard: {} },
        }),
      });
      return;
    }

    if (
      url.pathname === "/api/dashboard/decisions" ||
      url.pathname === "/api/v1/dashboard/decisions"
    ) {
      await route.fulfill({
        status: 500,
        headers: { "content-type": "application/json; charset=utf-8" },
        body: JSON.stringify({ error: { message: "boom" } }),
      });
      return;
    }

    await route.fulfill({
      status: 200,
      headers: { "content-type": "application/json; charset=utf-8" },
      body: JSON.stringify({}),
    });
  });

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "驾驶舱" })).toBeVisible();
  await expect(page.locator("#cockpitScheduledTaskList")).toHaveCount(0);
  await expect(page.locator("#cockpit-decisions").getByRole("button", { name: "待决策" })).toBeVisible();
  await expect(page.locator("#cockpit-decisions").getByRole("button", { name: "已同意" })).toBeVisible();
  await expect(page.locator("#cockpitDecisionViewAll")).toHaveCount(0);
  await expect(page.locator("#cockpitDecisionDrawer")).toHaveCount(0);
  await page.getByText("定时任务看板").first().click();
  await expect(page.getByRole("dialog", { name: "定时任务看板" })).toBeVisible();
  await expect(page.getByRole("dialog", { name: "定时任务看板" })).toContainText("暂无定时任务");
  await expect(page.getByText("boom")).toBeVisible();
  await expect(page.getByText("预算审批链路压缩")).toHaveCount(0);
  await expect(page.getByText("演示数据")).toHaveCount(0);
});

test("scheduled task modal stays inside the viewport with task results", async ({
  page,
}) => {
  await page.setViewportSize({ width: 700, height: 480 });
  await page.route("**/*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());

    if (!url.pathname.startsWith("/api/")) {
      await route.continue();
      return;
    }

    if (url.pathname === "/api/v1/auth/me" || url.pathname === "/api/auth/me") {
      await route.fulfill({
        status: 200,
        headers: { "content-type": "application/json; charset=utf-8" },
        body: JSON.stringify(authSession.user),
      });
      return;
    }

    if (
      url.pathname === "/api/v1/auth/refresh" ||
      url.pathname === "/api/auth/refresh"
    ) {
      await route.fulfill({
        status: 200,
        headers: { "content-type": "application/json; charset=utf-8" },
        body: JSON.stringify(authSession.token),
      });
      return;
    }

    if (url.pathname === "/api/v1/portal/bootstrap") {
      await route.fulfill({
        status: 200,
        headers: { "content-type": "application/json; charset=utf-8" },
        body: JSON.stringify({
          workspace: { tasks: [], notices: [], documents: [], resources: [], shortcuts: [] },
          calendar: { events: [] },
          knowledge: { spaces: [] },
          portal: { systems: [], services: [], news: [], preferences: {}, dashboard: {} },
        }),
      });
      return;
    }

    if (
      url.pathname === "/api/dashboard/decisions" ||
      url.pathname === "/api/v1/dashboard/decisions"
    ) {
      await route.fulfill({
        status: 200,
        headers: { "content-type": "application/json; charset=utf-8" },
        body: JSON.stringify({ items: decisionItems }),
      });
      return;
    }

    await route.fulfill({
      status: 200,
      headers: { "content-type": "application/json; charset=utf-8" },
      body: JSON.stringify({}),
    });
  });

  await page.goto("/");
  const decisionPreview = page.locator(
    "#cockpitDecisionList .cockpit-decision-preview-grid",
  );
  await expect(decisionPreview.locator("[data-decision-id]")).toHaveCount(5);
  await expect(decisionPreview.getByText("服务台知识库补全")).toHaveCount(0);

  const viewAllButton = page.locator("#cockpitDecisionViewAll");
  await expect(viewAllButton).toBeVisible();
  await viewAllButton.click();

  const decisionDrawer = page.getByRole("dialog", { name: "全部智能决策" });
  await expect(decisionDrawer).toBeVisible();
  await expect(decisionDrawer.locator("[data-decision-id]")).toHaveCount(6);
  await expect(decisionDrawer).toContainText("服务台知识库补全");
  await decisionDrawer.getByRole("button", { name: "关闭" }).click();
  await expect(decisionDrawer).toHaveCount(0);
  await expect(viewAllButton).toBeFocused();

  await page.getByText("定时任务看板").first().click();
  const modal = page.getByRole("dialog", { name: "定时任务看板" });
  await expect(modal).toBeVisible();
  await expect(modal).toContainText("预算审批效率巡检");
  await expect
    .poll(() =>
      page.evaluate(() => ({
        clientWidth: document.documentElement.clientWidth,
        modalRight: Math.ceil(
          document
            .querySelector(".cockpit-scheduled-task-modal")
            ?.getBoundingClientRect().right || 0,
        ),
        scrollWidth: document.documentElement.scrollWidth,
      })),
    )
    .toEqual({ clientWidth: 700, modalRight: 684, scrollWidth: 700 });
});
