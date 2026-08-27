import { expect, test } from "@playwright/test";

const authSession = {
  token: {
    access_token: "custom-websites-token",
    expires_in: 3600,
    organization_id: 7,
    refresh_token: "custom-websites-refresh-token",
    token_type: "bearer",
  },
  user: {
    id: 1,
    username: "demo",
    email: "demo@example.com",
    role: "admin",
    member_type: "internal",
    permissions: ["portal:read", "chat:use"],
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

  await page.route("https://*.example.test/**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "text/html; charset=utf-8",
      body: "<title>Embedded test website</title><h1>Embedded test website</h1>",
    });
  });

  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (!url.pathname.startsWith("/api/")) {
      await route.continue();
      return;
    }

    if (url.pathname === "/api/auth/me" || url.pathname === "/api/v1/auth/me") {
      await route.fulfill({ json: authSession.user });
      return;
    }

    if (
      url.pathname === "/api/auth/refresh" ||
      url.pathname === "/api/v1/auth/refresh"
    ) {
      await route.fulfill({ json: authSession.token });
      return;
    }

    if (url.pathname === "/api/v1/portal/bootstrap") {
      await route.fulfill({
        json: {
          workspace: { tasks: [], notices: [], documents: [], resources: [], shortcuts: [] },
          calendar: { events: [] },
          knowledge: { spaces: [] },
          portal: { systems: [], services: [], news: [], preferences: {}, dashboard: {} },
        },
      });
      return;
    }

    await route.fulfill({ json: {} });
  });
});

test("users can manage custom work platform websites", async ({ page }) => {
  await page.goto("/");
  await expect(
    page.locator("#tabBar").getByRole("button", { name: "驾驶舱", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "工作平台" }).click();
  const customWebsiteMenu = page.locator("#customWebsiteMenu");

  await page.getByRole("button", { name: "添加自定义网站" }).click();
  await page
    .locator(".custom-website-view.active")
    .getByLabel("自定义网站名称")
    .fill("采购门户");
  await page
    .locator(".custom-website-view.active")
    .getByLabel("自定义网站地址")
    .fill("procurement.example.test");
  await page
    .locator(".custom-website-view.active")
    .getByRole("button", { name: "保存并载入" })
    .click();

  await expect(
    customWebsiteMenu.getByRole("button", { name: "采购门户" }),
  ).toBeVisible();
  await expect(page.getByRole("heading", { name: "采购门户" })).toBeVisible();
  await expect(
    page
      .locator(".custom-website-view.active")
      .getByLabel("自定义网站地址"),
  ).toHaveValue("https://procurement.example.test/");

  await page.getByRole("button", { name: "添加自定义网站" }).click();
  await page
    .locator(".custom-website-view.active")
    .getByLabel("自定义网站名称")
    .fill("财务门户");
  await page
    .locator(".custom-website-view.active")
    .getByLabel("自定义网站地址")
    .fill("finance.example.test");
  await page
    .locator(".custom-website-view.active")
    .getByRole("button", { name: "保存并载入" })
    .click();
  await expect(
    customWebsiteMenu.getByRole("button", { name: "财务门户" }),
  ).toBeVisible();

  await customWebsiteMenu.getByRole("button", { name: "采购门户" }).click();
  await page
    .locator(".custom-website-view.active")
    .getByLabel("自定义网站名称")
    .fill("采购中心");
  await page
    .locator(".custom-website-view.active")
    .getByRole("button", { name: "保存并载入" })
    .click();
  await expect(
    customWebsiteMenu.getByRole("button", { name: "采购中心" }),
  ).toBeVisible();
  await expect(page.getByRole("heading", { name: "采购中心" })).toBeVisible();

  await customWebsiteMenu.getByRole("button", { name: "财务门户" }).click();
  await page
    .locator(".custom-website-view.active")
    .getByLabel("自定义网站名称")
    .fill("采购中心");
  await page
    .locator(".custom-website-view.active")
    .getByRole("button", { name: "保存并载入" })
    .click();
  await expect(page.getByRole("alert")).toContainText("名称已存在");
  await expect(
    page
      .locator(".custom-website-view.active")
      .getByLabel("自定义网站地址"),
  ).toHaveValue("https://finance.example.test/");

  await customWebsiteMenu.getByRole("button", { name: "采购中心" }).click();
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "删除此网站" }).click();
  await expect(
    customWebsiteMenu.getByRole("button", { name: "采购中心" }),
  ).toHaveCount(0);
  await expect(
    customWebsiteMenu.getByRole("button", { name: "财务门户" }),
  ).toBeVisible();

  await page.reload();
  await expect(
    customWebsiteMenu.getByRole("button", { name: "财务门户" }),
  ).toBeVisible();
  await expect(
    customWebsiteMenu.getByRole("button", { name: "采购中心" }),
  ).toHaveCount(0);
});
