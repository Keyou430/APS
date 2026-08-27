import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom/vitest";
import { describe, expect, it, vi } from "vitest";
import type { UsersService } from "../api/services/usersService";
import { UsersPage } from "./UsersPage";

function createCache() {
  return {
    get: vi.fn(),
    invalidateOrganization: vi.fn(),
    set: vi.fn(),
  };
}

function createUser(role = "user") {
  return {
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
  };
}

function createService(overrides: Partial<UsersService> = {}): UsersService {
  return {
    assignRoles: vi.fn(async () => createUser("manager")),
    createUser: vi.fn(),
    deleteUser: vi.fn(async () => undefined),
    getUser: vi.fn(),
    listUsers: vi.fn(async () => ({
      items: [createUser()],
      total: 1,
      page: 1,
      page_size: 20,
    })),
    updateUser: vi.fn(),
    ...overrides,
  } as UsersService;
}

describe("UsersPage", () => {
  it("loads users into an organization-scoped cache", async () => {
    const cache = createCache();
    const service = createService();

    render(<UsersPage cache={cache} organizationId={7} service={service} />);

    expect(screen.getByText("正在加载用户列表")).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "用户管理" })).toBeInTheDocument();
    expect(await screen.findByText("Keyou430")).toBeInTheDocument();
    expect(screen.getByText("keyou@example.com")).toBeInTheDocument();
    expect(screen.getByText("user")).toBeInTheDocument();
    expect(screen.getByText("共 1 位用户")).toBeInTheDocument();
    expect(service.listUsers).toHaveBeenCalledWith({ page: 1, page_size: 20 });
    expect(cache.get).toHaveBeenCalledWith(7, ["users", "directory"]);
    expect(cache.set).toHaveBeenCalledWith(
      7,
      ["users", "directory"],
      expect.objectContaining({ total: 1 }),
    );
  });

  it("keeps the user directory table label accessible without rendering a mobile caption", async () => {
    render(<UsersPage cache={createCache()} organizationId={7} service={createService()} />);

    const table = await screen.findByRole("table", { name: "当前组织用户列表" });

    expect(table.querySelector("caption")).not.toBeInTheDocument();
  });

  it("fails closed without an organization context", async () => {
    const service = createService();

    render(<UsersPage cache={createCache()} organizationId={null} service={service} />);

    expect(await screen.findByText("没有用户管理访问权限")).toBeInTheDocument();
    expect(service.listUsers).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "刷新用户列表" })).toBeDisabled();
  });

  it("assigns a role and invalidates only the current organization", async () => {
    const cache = createCache();
    const service = createService();
    const user = userEvent.setup();

    render(<UsersPage cache={cache} organizationId={7} service={service} />);

    const row = await screen.findByRole("row", { name: /Keyou430/ });
    await user.click(within(row).getByRole("button", { name: "设为 manager" }));

    await waitFor(() =>
      expect(service.assignRoles).toHaveBeenCalledWith(5, { role: "manager" }),
    );
    expect(cache.invalidateOrganization).toHaveBeenCalledWith(7);
    expect(await screen.findByText("manager")).toBeInTheDocument();
  });

  it("disables user actions after a forbidden response", async () => {
    const forbidden = Object.assign(new Error("Forbidden"), { status: 403 });
    const service = createService({
      deleteUser: vi.fn(async () => {
        throw forbidden;
      }),
    });
    const user = userEvent.setup();

    render(<UsersPage cache={createCache()} organizationId={7} service={service} />);

    const row = await screen.findByRole("row", { name: /Keyou430/ });
    await user.click(within(row).getByRole("button", { name: "删除 Keyou430" }));

    expect(await screen.findByText("没有用户管理访问权限")).toBeInTheDocument();
    expect(within(row).getByRole("button", { name: "删除 Keyou430" })).toBeDisabled();
  });
});
