import { expect, test } from "@playwright/test";

const authSession = {
  token: {
    access_token: "decision-action-token",
    expires_in: 3600,
    organization_id: 7,
    refresh_token: "decision-action-refresh-token",
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

const pendingDecision = {
  id: "decision-action-1",
  title: "预算审批链路压缩",
  summary: "检查预算审批耗时并给出调整建议",
  action: "压缩重复审批节点",
  sourceTask: "预算审批效率巡检",
  generatedAt: "2026-08-14T08:30:00",
  status: "pending",
};

const rejectionDecision = {
  ...pendingDecision,
  id: "decision-action-2",
  title: "华东区仓储排班调整",
};

test.beforeEach(async ({ page }) => {
  await page.addInitScript((session) => {
    window.sessionStorage.setItem("agent-platform.auth", JSON.stringify(session));
  }, authSession);
});

test("approval and rejection actions use backend responses as the source of truth", async ({
  page,
}) => {
  const requests: Array<{ method: string; pathname: string; body: string }> = [];
  const decisions = {
    [pendingDecision.id]: { ...pendingDecision },
    [rejectionDecision.id]: { ...rejectionDecision },
  };

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

    if (url.pathname === "/api/dashboard/decisions") {
      await route.fulfill({
        status: 200,
        headers: { "content-type": "application/json; charset=utf-8" },
        body: JSON.stringify({ items: Object.values(decisions) }),
      });
      return;
    }

    if (
      url.pathname === "/api/dashboard/decisions/decision-action-1/approve" ||
      url.pathname === "/api/dashboard/decisions/decision-action-2/reject"
    ) {
      const body = request.postData() || "";
      requests.push({ method: request.method(), pathname: url.pathname, body });
      const isApprove = url.pathname.endsWith("/approve");
      const decisionId = isApprove ? pendingDecision.id : rejectionDecision.id;
      const rejectionPayload = body ? JSON.parse(body) : null;
      decisions[decisionId] = isApprove
        ? { ...decisions[decisionId], status: "approved" }
        : {
            ...decisions[decisionId],
            status:
              rejectionPayload.reason_type === "regenerate"
                ? "regenerating"
                : "rejected",
            rejectionReason: rejectionPayload.reason,
          };
      await route.fulfill({
        status: 200,
        headers: { "content-type": "application/json; charset=utf-8" },
        body: JSON.stringify(decisions[decisionId]),
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
  const decisionCard = page.locator('[data-decision-id="decision-action-1"]');
  await expect(decisionCard).toContainText("预算审批链路压缩");

  await decisionCard.getByRole("button", { name: "同意" }).click();
  await expect(decisionCard.locator(".cockpit-status-chip")).toHaveText("已同意");
  expect(requests).toEqual([
    {
      method: "POST",
      pathname: "/api/dashboard/decisions/decision-action-1/approve",
      body: "",
    },
  ]);

  await page.reload();
  const pendingCard = page.locator('[data-decision-id="decision-action-2"]');
  await pendingCard.getByRole("button", { name: "驳回" }).click();
  await pendingCard.locator("textarea").fill("数据口径需要重新生成");
  await pendingCard.getByRole("button", { name: "提交驳回" }).click();
  await expect(pendingCard.locator(".cockpit-status-chip")).toHaveText("重新生成中");
  expect(requests[1]).toEqual({
    method: "POST",
    pathname: "/api/dashboard/decisions/decision-action-2/reject",
    body: JSON.stringify({
      reason: "数据口径需要重新生成",
      reason_type: "regenerate",
    }),
  });
});
