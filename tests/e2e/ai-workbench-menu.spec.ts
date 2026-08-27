import { expect, test } from "@playwright/test";

const authSession = {
  token: {
    access_token: "ai-workbench-token",
    expires_in: 3600,
    organization_id: 7,
    refresh_token: "ai-workbench-refresh-token",
    token_type: "bearer",
  },
  user: {
    id: 1,
    username: "demo",
    email: "demo@example.com",
    role: "admin",
    member_type: "internal",
    permissions: ["portal:read", "chat:use", "knowledge:read", "agent:admin"],
    membership_id: 11,
    membership_expires_at: null,
    organization_id: 7,
    is_active: true,
    created_at: "2026-08-14T00:00:00Z",
  },
};

test.beforeEach(async ({ page }) => {
  await page.addInitScript((session) => {
    window.sessionStorage.setItem("agent-platform.auth", JSON.stringify(session));
  }, authSession);
});

test("AI service submenu switching keeps the chat window mounted", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1000, height: 900 });
  await page.route("**/*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());

    if (!url.pathname.startsWith("/api/")) {
      await route.continue();
      return;
    }

    if (url.pathname === "/api/auth/me" || url.pathname === "/api/v1/auth/me") {
      await route.fulfill({
        status: 200,
        headers: { "content-type": "application/json; charset=utf-8" },
        body: JSON.stringify(authSession.user),
      });
      return;
    }

    if (
      url.pathname === "/api/auth/refresh" ||
      url.pathname === "/api/v1/auth/refresh"
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

    if (url.pathname === "/api/knowledge" || url.pathname === "/api/knowledge/entries") {
      await route.fulfill({
        status: 200,
        headers: { "content-type": "application/json; charset=utf-8" },
        body: JSON.stringify({ items: [] }),
      });
      return;
    }

    if (url.pathname.startsWith("/api/chat/")) {
      await route.fulfill({
        status: 200,
        headers: { "content-type": "application/json; charset=utf-8" },
        body: JSON.stringify({ items: [] }),
      });
      return;
    }

    await route.fulfill({
      status: 200,
      headers: { "content-type": "application/json; charset=utf-8" },
      body: JSON.stringify({}),
    });
  });

  await page.goto("/#knowledge");
  await expect(page.locator("#aiChat")).toBeVisible();
  await expect(page.locator("#chatTranscript")).toBeVisible();
  await expect
    .poll(() =>
      page.evaluate(() => {
        const workbench = document.querySelector<HTMLElement>(".ai-workbench");
        const left = document.querySelector<HTMLElement>("#aiLeft");
        const sidebar = document.querySelector<HTMLElement>(".module-sidebar");
        if (!workbench || !left || !sidebar) return null;
        return {
          direction: getComputedStyle(workbench).flexDirection,
          leftHeight: left.getBoundingClientRect().height,
          leftWidth: left.getBoundingClientRect().width,
          sidebarWidth: sidebar.getBoundingClientRect().width,
          workbenchWidth: workbench.getBoundingClientRect().width,
        };
      }),
    )
    .toMatchObject({ direction: "column" });
  const aiLayout = await page.evaluate(() => {
    const workbench = document.querySelector<HTMLElement>(".ai-workbench");
    const left = document.querySelector<HTMLElement>("#aiLeft");
    if (!workbench || !left) return null;
    return {
      leftHeight: left.getBoundingClientRect().height,
      leftWidth: left.getBoundingClientRect().width,
      workbenchWidth: workbench.getBoundingClientRect().width,
    };
  });
  expect(aiLayout).not.toBeNull();
  expect(aiLayout?.leftHeight).toBeGreaterThan(200);
  expect(aiLayout?.leftWidth).toBeCloseTo(aiLayout?.workbenchWidth ?? 0, 0);
  const sidebarWidth = await page.locator(".module-sidebar").evaluate(
    (sidebar) => sidebar.getBoundingClientRect().width,
  );
  expect(sidebarWidth).toBeGreaterThanOrEqual(230);

  await page.evaluate(() => {
    const testWindow = window as unknown as {
      __aiWorkbenchTranscriptNode?: Element | null;
    };
    testWindow.__aiWorkbenchTranscriptNode =
      document.querySelector("#chatTranscript");
    const transcript = document.querySelector("#chatTranscript");
    if (transcript) {
      transcript.setAttribute("data-stability-marker", "stable-chat-window");
    }
  });

  await page.getByRole("button", { name: "经验方法" }).click();
  await expect(page.locator("#aiLeftBottom")).toContainText("经验模板");
  await expect(page.locator("#aiLeftBottom")).not.toContainText("记忆库");
  await expect(page.locator("#aiLeftBottom")).not.toContainText("暂无记忆");

  await page.getByRole("button", { name: "技能库" }).click();

  await expect
    .poll(() =>
      page.evaluate(() => ({
        marker: document
          .querySelector("#chatTranscript")
          ?.getAttribute("data-stability-marker"),
        sameNode:
          (window as unknown as {
            __aiWorkbenchTranscriptNode?: Element | null;
          }).__aiWorkbenchTranscriptNode === document.querySelector("#chatTranscript"),
      })),
    )
    .toEqual({ marker: "stable-chat-window", sameNode: true });
});
