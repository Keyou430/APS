import { mkdir, readFile } from "node:fs/promises";
import { createServer, type Server } from "node:http";
import type { AddressInfo } from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test, type Page } from "@playwright/test";

const jsonHeaders = { "content-type": "application/json; charset=utf-8" };
const distDir = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../../dist",
);
const screenshotDir = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../artifacts/keyou430-dashboard-hermes",
);
let artifactServer: Server;
let artifactOrigin = "";

async function getAppShellScale(page: Page) {
  return page.evaluate(() => {
    const shell = document.getElementById("appShell");
    if (!shell) return null;
    const styles = getComputedStyle(shell);
    const scale = Number(styles.getPropertyValue("--app-shell-scale").trim());
    const rect = shell.getBoundingClientRect();
    return {
      height: rect.height,
      scale,
      transform: styles.transform,
      width: rect.width,
    };
  });
}

const expectedPortalResponses: Record<string, unknown> = {
  "/api/v1/portal/bootstrap": {
    workspace: {
      tasks: [],
      notices: [],
      documents: [],
      resources: [],
      shortcuts: [],
      dashboard: {},
    },
    calendar: { events: [] },
    knowledge: { spaces: [] },
    portal: {
      systems: [],
      services: [
        {
          code: "it-help",
          title: "IT 支持",
          category: "信息服务",
          description: "账号、设备和网络支持。",
        },
      ],
      news: [],
      preferences: {},
      dashboard: {},
    },
  },
  "/api/v1/knowledge/mappings": { items: [] },
};

function authResponse(pathname: string) {
  if (pathname.endsWith("/refresh") || pathname.endsWith("/me")) {
    return { status: 401, body: { detail: "not authenticated" } };
  }
  return { status: 200, body: {} };
}

function chatResponse() {
  return { status: 200, body: { items: [] } };
}

function enterprisePortalResponse() {
  return {
    activities: [{ id: "a1", title: "完成客户回访" }],
    announcements: [{ id: 2, title: "组织周会安排", status: "published" }],
    collaborators: [{ id: "u1", name: "Keyou430" }],
    company: { name: "星纪年", slogan: "Enterprise Workspace" },
    currentUser: { name: "演示用户" },
    departments: [{ id: "d1", name: "产品部" }],
    people: [{ id: "p1", name: "张三" }, { id: "p2", name: "李四" }],
    positions: [{ id: "pos1", name: "产品经理" }],
    quickLinks: [{ id: "q1", title: "知识库", url: "/knowledge" }],
    todos: [{ id: 8, title: "审批合同", completed: false }],
  };
}

function organizationStructureResponse() {
  return {
    organization_id: 7,
    revision: 4,
    units: [
      {
        id: 1,
        parent_id: null,
        name: "星纪年",
        code: "root",
        sort_order: 0,
        is_active: true,
      },
      {
        id: 2,
        parent_id: 1,
        name: "产品部",
        code: "product",
        sort_order: 1,
        is_active: true,
      },
    ],
    positions: [
      {
        id: 8,
        unit_id: 2,
        title: "产品经理",
        level: "P6",
        sort_order: 1,
        is_active: true,
      },
    ],
    placements: [
      {
        membership_id: 11,
        unit_id: 2,
        position_id: 8,
        manager_membership_id: null,
      },
    ],
    people: [
      {
        membership_id: 11,
        user_id: 5,
        username: "Keyou430",
        email: "keyou@example.com",
        role: "manager",
        member_type: "internal",
      },
    ],
  };
}

function usersResponse(role = "user") {
  return {
    items: [
      {
        id: 5,
        username: "Keyou430",
        email: "keyou@example.com",
        role,
        member_type: "internal",
        permissions: ["users:read"],
        membership_id: 11,
        membership_expires_at: null,
        organization_id: 7,
        is_active: true,
        created_at: "2026-08-14T00:00:00Z",
      },
    ],
    total: 1,
    page: 1,
    page_size: 20,
  };
}

function hermesProfileResponse() {
  return {
    capabilities: ["chat", "approval"],
    provider: "feishu",
    status: "active",
    token: "should-not-render",
    secret: "should-not-render",
    user_id: 9,
  };
}

function hermesHealthResponse() {
  return {
    last_checked_at: "2026-08-14T08:00:00Z",
    status: "healthy",
  };
}

function contentType(filePath: string) {
  if (filePath.endsWith(".html")) return "text/html; charset=utf-8";
  if (filePath.endsWith(".js")) return "text/javascript; charset=utf-8";
  if (filePath.endsWith(".css")) return "text/css; charset=utf-8";
  if (filePath.endsWith(".svg")) return "image/svg+xml";
  return "application/octet-stream";
}

test.beforeAll(async () => {
  await mkdir(screenshotDir, { recursive: true });
  artifactServer = createServer(async (request, response) => {
    const url = new URL(request.url || "/", "http://127.0.0.1");
    const pathname = decodeURIComponent(url.pathname);
    const relativePath = pathname === "/" ? "index.html" : pathname.slice(1);
    const filePath = path.resolve(distDir, relativePath);

    if (!filePath.startsWith(distDir)) {
      response.writeHead(403);
      response.end("Forbidden");
      return;
    }

    try {
      const body = await readFile(filePath);
      response.writeHead(200, { "content-type": contentType(filePath) });
      response.end(body);
    } catch {
      const body = await readFile(path.join(distDir, "index.html"));
      response.writeHead(200, { "content-type": contentType("index.html") });
      response.end(body);
    }
  });

  await new Promise<void>((resolve) => {
    artifactServer.listen(0, "127.0.0.1", resolve);
  });
  const address = artifactServer.address() as AddressInfo;
  artifactOrigin = `http://127.0.0.1:${address.port}`;
});

test.afterAll(async () => {
  await new Promise<void>((resolve, reject) => {
    artifactServer.close((error) => (error ? reject(error) : resolve()));
  });
});

test("production artifact boots without unregistered real API requests", async ({
  page,
}) => {
  const unexpectedRequests: string[] = [];

  await page.route("**/*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());

    if (!url.pathname.startsWith("/api/")) {
      await route.continue();
      return;
    }

    if (url.pathname.startsWith("/api/v1/auth/")) {
      const response = authResponse(url.pathname);
      await route.fulfill({
        status: response.status,
        headers: jsonHeaders,
        body: JSON.stringify(response.body),
      });
      return;
    }

    if (url.pathname.startsWith("/api/v1/chat/")) {
      const response = chatResponse();
      await route.fulfill({
        status: response.status,
        headers: jsonHeaders,
        body: JSON.stringify(response.body),
      });
      return;
    }

    if (url.pathname in expectedPortalResponses) {
      await route.fulfill({
        status: 200,
        headers: jsonHeaders,
        body: JSON.stringify(expectedPortalResponses[url.pathname]),
      });
      return;
    }

    unexpectedRequests.push(`${request.method()} ${url.pathname}`);
    await route.abort("failed");
  });

  // /knowledge is a React-owned route (legacy shell intentionally hidden),
  // so the legacy boot check targets the legacy-hosted dashboard route.
  await page.goto(artifactOrigin + "/");

  await expect(page.locator("#workspace")).toBeVisible();
  await expect(page.getByRole("heading", { name: "驾驶舱" })).toBeVisible();
  await expect(
    page.locator(
      'script[src^="/src/"], script[src^="/node_modules/"], script[src*="cdn.jsdelivr.net"]',
    ),
  ).toHaveCount(0);
  expect(unexpectedRequests).toEqual([]);
});

test.describe("React migration acceptance", () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      window.sessionStorage.setItem(
        "agent-platform.auth",
        JSON.stringify({
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
            permissions: [
              "portal:read",
              "org:read",
              "org:admin",
              "users:read",
              "agent:admin",
            ],
            membership_id: 11,
            membership_expires_at: null,
            organization_id: 7,
            is_active: true,
            created_at: "2026-08-14T00:00:00Z",
          },
        }),
      );
    });
  });

  async function installAcceptanceRoutes(page: Page) {
    const unexpectedRequests: string[] = [];

    await page.route("**/*", async (route) => {
      const request = route.request();
      const url = new URL(request.url());

      if (!url.pathname.startsWith("/api/")) {
        await route.continue();
        return;
      }

      if (url.pathname.startsWith("/api/auth/")) {
        const response = authResponse(url.pathname);
        await route.fulfill({
          status: response.status,
          headers: jsonHeaders,
          body: JSON.stringify(response.body),
        });
        return;
      }

      if (url.pathname.startsWith("/api/chat/")) {
        const response = chatResponse();
        await route.fulfill({
          status: response.status,
          headers: jsonHeaders,
          body: JSON.stringify(response.body),
        });
        return;
      }

      if (url.pathname.startsWith("/api/v1/auth/")) {
        const response = authResponse(url.pathname);
        await route.fulfill({
          status: response.status,
          headers: jsonHeaders,
          body: JSON.stringify(response.body),
        });
        return;
      }

      if (url.pathname.startsWith("/api/v1/chat/")) {
        const response = chatResponse();
        await route.fulfill({
          status: response.status,
          headers: jsonHeaders,
          body: JSON.stringify(response.body),
        });
        return;
      }

      if (url.pathname in expectedPortalResponses) {
        await route.fulfill({
          status: 200,
          headers: jsonHeaders,
          body: JSON.stringify(expectedPortalResponses[url.pathname]),
        });
        return;
      }

      if (url.pathname === "/api/enterprise/portal") {
        await route.fulfill({
          status: 200,
          headers: jsonHeaders,
          body: JSON.stringify(enterprisePortalResponse()),
        });
        return;
      }

      if (url.pathname === "/api/enterprise/portal/todos/8") {
        await route.fulfill({
          status: 200,
          headers: jsonHeaders,
          body: JSON.stringify({ id: 8, title: "审批合同", completed: true }),
        });
        return;
      }

      if (url.pathname === "/api/organization/structure") {
        await route.fulfill({
          status: 200,
          headers: jsonHeaders,
          body: JSON.stringify(organizationStructureResponse()),
        });
        return;
      }

      if (url.pathname === "/api/organization/positions/8") {
        await route.fulfill({
          status: 204,
          headers: jsonHeaders,
          body: "",
        });
        return;
      }

      if (url.pathname === "/api/users") {
        await route.fulfill({
          status: 200,
          headers: jsonHeaders,
          body: JSON.stringify(usersResponse()),
        });
        return;
      }

      if (url.pathname === "/api/users/5/roles") {
        await route.fulfill({
          status: 200,
          headers: jsonHeaders,
          body: JSON.stringify(usersResponse("manager").items[0]),
        });
        return;
      }

      if (url.pathname === "/api/hermes/profiles/9") {
        if (request.method() === "GET") {
          await route.fulfill({
            status: 200,
            headers: jsonHeaders,
            body: JSON.stringify(hermesProfileResponse()),
          });
          return;
        }
        if (request.method() === "DELETE") {
          await route.fulfill({
            status: 204,
            headers: jsonHeaders,
            body: "",
          });
          return;
        }
      }

      if (url.pathname === "/api/hermes/profiles") {
        await route.fulfill({
          status: 200,
          headers: jsonHeaders,
          body: JSON.stringify(hermesProfileResponse()),
        });
        return;
      }

      if (url.pathname === "/api/hermes/profiles/9/health") {
        await route.fulfill({
          status: 200,
          headers: jsonHeaders,
          body: JSON.stringify(hermesHealthResponse()),
        });
        return;
      }

      unexpectedRequests.push(`${request.method()} ${url.pathname}`);
      await route.abort("failed");
    });

    return unexpectedRequests;
  }

  for (const viewport of [
    { width: 320, height: 900 },
    { width: 390, height: 900 },
    { width: 414, height: 900 },
    { width: 768, height: 900 },
    { width: 1280, height: 900 },
    { width: 1440, height: 900 },
  ]) {
    test(`renders portal, organization, users, and AI service at ${viewport.width}px`, async ({
      page,
    }) => {
      await page.setViewportSize(viewport);
      const unexpectedRequests = await installAcceptanceRoutes(page);
      const consoleMessages: string[] = [];

      page.on("console", (message) => {
        if (message.type() === "error" || message.type() === "warning") {
          consoleMessages.push(`${message.type()}: ${message.text()}`);
        }
      });

      await page.goto(`${artifactOrigin}/portal`);
      await expect(page.getByRole("heading", { name: "企业门户" })).toBeVisible();
      await expect(page.getByRole("heading", { name: "星纪年" })).toBeVisible();
      const appShellScale = await getAppShellScale(page);
      expect(appShellScale).not.toBeNull();
      expect(appShellScale?.width).toBeCloseTo(viewport.width, 0);
      expect(appShellScale?.height).toBeCloseTo(viewport.height, 0);
      expect(appShellScale?.scale).toBe(1);
      await expect(page.getByText("组织周会安排")).toBeVisible();
      await expect(page.getByText("审批合同")).toBeVisible();
      await expect(page.getByLabel("快捷入口").getByText("知识库")).toBeVisible();
      await expect(page.getByText("Keyou430")).toBeVisible();
      await page.getByRole("button", { name: "完成 审批合同" }).click();
      await expect(page.getByLabel("门户待办").getByText("已完成")).toBeVisible();
      await expect
        .poll(() =>
          page.evaluate(() => ({
            clientWidth: document.documentElement.clientWidth,
            scrollWidth: document.documentElement.scrollWidth,
          })),
        )
        .toEqual({
          clientWidth: viewport.width,
          scrollWidth: viewport.width,
        });
      await page.screenshot({
        path: path.join(screenshotDir, `portal-${viewport.width}.png`),
        fullPage: true,
      });

      await page.goto(`${artifactOrigin}/organization`);
      await expect(page.getByRole("heading", { name: "组织架构" })).toBeVisible();
      await expect(page.getByText("结构版本 4")).toBeVisible();
      await expect(page.getByLabel("组织单元").getByText("产品部")).toBeVisible();
      await expect(page.getByLabel("组织职位").getByText("产品经理")).toBeVisible();
      await expect(page.getByLabel("组织成员").getByText("Keyou430")).toBeVisible();
      await expect
        .poll(() =>
          page.evaluate(() => ({
            clientWidth: document.documentElement.clientWidth,
            scrollWidth: document.documentElement.scrollWidth,
          })),
        )
        .toEqual({
          clientWidth: viewport.width,
          scrollWidth: viewport.width,
        });
      await page.screenshot({
        path: path.join(screenshotDir, `organization-${viewport.width}.png`),
        fullPage: true,
      });
      await page.getByRole("button", { name: "删除 产品经理 职位" }).click();
      await expect(page.getByLabel("组织职位")).not.toContainText("产品经理");

      await page.goto(`${artifactOrigin}/users`);
      await expect(page.getByRole("heading", { name: "用户管理" })).toBeVisible();
      await expect(page.getByText("共 1 位用户")).toBeVisible();
      await expect(page.getByRole("row", { name: /Keyou430/ })).toBeVisible();
      await page.getByRole("button", { name: "设为 manager" }).click();
      await expect(page.getByRole("row", { name: /manager/ })).toBeVisible();
      await expect
        .poll(() =>
          page.evaluate(() => ({
            clientWidth: document.documentElement.clientWidth,
            scrollWidth: document.documentElement.scrollWidth,
          })),
        )
        .toEqual({
          clientWidth: viewport.width,
          scrollWidth: viewport.width,
        });
      await page.screenshot({
        path: path.join(screenshotDir, `users-${viewport.width}.png`),
        fullPage: true,
      });

      await page.goto(`${artifactOrigin}/hermes`);
      await expect(page.getByRole("heading", { name: "AI 服务" })).toBeVisible();
      await expect(page.getByRole("button", { name: "查看 Profile" })).toBeVisible();
      await page.getByRole("button", { name: "查看 Profile" }).click();
      await expect(page.getByLabel("Hermes Profile")).toContainText("feishu");
      await page.getByRole("button", { name: "健康检查" }).click();
      await expect(page.getByLabel("Hermes 健康状态")).toContainText("healthy");
      await page.getByRole("button", { name: "停用 Profile" }).click();
      await expect(page.getByLabel("Hermes Profile")).toContainText("inactive");
      await expect(page.locator("body")).not.toContainText("should-not-render");
      await page.screenshot({
        path: path.join(screenshotDir, `hermes-${viewport.width}.png`),
        fullPage: true,
      });

      expect(unexpectedRequests).toEqual([]);
      expect(consoleMessages).toEqual([]);
    });
  }
});
