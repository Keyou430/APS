import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom/vitest";
import { describe, expect, it, vi } from "vitest";
import type { InvitationsService } from "../api/services/invitationsService";
import { InvitationsPage } from "./InvitationsPage";

function createCache() {
  return {
    get: vi.fn(),
    invalidateOrganization: vi.fn(),
    set: vi.fn(),
  };
}

function createService(
  overrides: Partial<InvitationsService> = {},
): InvitationsService {
  return {
    acceptInvitation: vi.fn(),
    createInvitation: vi.fn(),
    listInvitations: vi.fn(async () => ({ items: [] })),
    regenerateInvitation: vi.fn(),
    revokeGuestMembership: vi.fn(),
    revokeInvitation: vi.fn(),
    ...overrides,
  };
}

describe("InvitationsPage", () => {
  it("loads invitations into an organization-scoped cache without adding a query parameter", async () => {
    const service = createService({
      listInvitations: vi.fn(async () => ({
        items: [
          {
            id: 42,
            email: "guest@example.com",
            role: "guest",
            status: "pending",
            expires_at: "2026-08-20T00:00:00Z",
          },
        ],
      })),
    });
    const cache = createCache();

    render(
      <InvitationsPage cache={cache} organizationId={7} service={service} />,
    );

    expect(screen.getByText("正在加载邀请记录")).toBeInTheDocument();
    expect(await screen.findByText("guest@example.com")).toBeInTheDocument();
    expect(service.listInvitations).toHaveBeenCalledWith();
    expect(cache.get).toHaveBeenCalledWith(7, ["invitations"]);
    expect(cache.set).toHaveBeenCalledWith(
      7,
      ["invitations"],
      expect.any(Array),
    );
    expect(
      screen.getByRole("button", { name: "撤销 guest@example.com 的邀请" }),
    ).toBeEnabled();
    expect(
      screen.getByRole("button", { name: "重新生成 guest@example.com 的邀请" }),
    ).toBeEnabled();
  });

  it("shows an empty state with a single create action", async () => {
    render(
      <InvitationsPage
        cache={createCache()}
        organizationId={7}
        service={createService()}
      />,
    );

    expect(await screen.findByText("还没有邀请记录")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "创建邀请" })).toBeEnabled();
  });

  it("fails closed without an organization id", async () => {
    const service = createService();

    render(
      <InvitationsPage
        cache={createCache()}
        organizationId={null}
        service={service}
      />,
    );

    expect(await screen.findByText("没有邀请成员权限")).toBeInTheDocument();
    expect(service.listInvitations).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "创建邀请" })).toBeDisabled();
  });

  it("invalidates the current organization cache before refreshing after create", async () => {
    const cache = createCache();
    cache.get.mockReturnValueOnce([
      { id: 42, email: "cached@example.com", status: "pending" },
    ]);
    cache.get.mockReturnValueOnce(undefined);
    const service = createService({
      createInvitation: vi.fn(async () => ({ id: 9 })),
      listInvitations: vi.fn(async () => ({ items: [] })),
    });
    const user = userEvent.setup();

    render(
      <InvitationsPage cache={cache} organizationId={7} service={service} />,
    );

    expect(await screen.findByText("cached@example.com")).toBeInTheDocument();
    await user.type(screen.getByLabelText("邀请邮箱"), "new@example.com");
    await user.type(screen.getByLabelText("知识资源 ID"), "12");
    await user.clear(screen.getByLabelText("邀请有效至"));
    await user.type(screen.getByLabelText("邀请有效至"), "2026-08-20T12:00");
    await user.click(screen.getByRole("button", { name: "创建邀请" }));

    await waitFor(() =>
      expect(cache.invalidateOrganization).toHaveBeenCalledWith(7),
    );
    expect(service.listInvitations).toHaveBeenCalledTimes(1);
  });

  it("creates an invitation and refreshes the scoped list", async () => {
    const service = createService({
      createInvitation: vi.fn(async () => ({ id: 9 })),
      listInvitations: vi
        .fn()
        .mockResolvedValueOnce({ items: [] })
        .mockResolvedValueOnce({
          items: [{ id: 9, email: "new@example.com", status: "pending" }],
        }),
    });
    const user = userEvent.setup();

    render(
      <InvitationsPage
        cache={createCache()}
        organizationId={7}
        service={service}
      />,
    );

    await user.type(await screen.findByLabelText("邀请邮箱"), "new@example.com");
    await user.type(screen.getByLabelText("知识资源 ID"), "12, 18");
    await user.clear(screen.getByLabelText("邀请有效至"));
    await user.type(screen.getByLabelText("邀请有效至"), "2026-08-20T12:00");
    await user.click(screen.getByRole("button", { name: "创建邀请" }));

    await waitFor(() =>
      expect(service.createInvitation).toHaveBeenCalledWith({
        email: "new@example.com",
        resource_ids: [12, 18],
        token_expires_at: new Date("2026-08-20T12:00").toISOString(),
      }),
    );
    expect(await screen.findByText("new@example.com")).toBeInTheDocument();
    expect(service.listInvitations).toHaveBeenLastCalledWith();
  });

  it("shows forbidden errors next to a failed create action", async () => {
    const forbidden = Object.assign(new Error("Forbidden"), { status: 403 });
    const service = createService({
      createInvitation: vi.fn(async () => {
        throw forbidden;
      }),
      listInvitations: vi.fn(async () => ({
        items: [{ id: 42, email: "guest@example.com", status: "pending" }],
      })),
    });
    const user = userEvent.setup();

    render(
      <InvitationsPage
        cache={createCache()}
        organizationId={7}
        service={service}
      />,
    );

    await user.type(await screen.findByLabelText("邀请邮箱"), "blocked@example.com");
    await user.type(screen.getByLabelText("知识资源 ID"), "12");
    await user.clear(screen.getByLabelText("邀请有效至"));
    await user.type(screen.getByLabelText("邀请有效至"), "2026-08-20T12:00");
    await user.click(screen.getByRole("button", { name: "创建邀请" }));
    expect(await screen.findByText("没有邀请成员权限")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "创建邀请" })).toBeDisabled();
  });

  it("shows conflict errors next to a failed revoke action", async () => {
    const conflict = Object.assign(new Error("Conflict"), { status: 409 });
    const service = createService({
      listInvitations: vi.fn(async () => ({
        items: [{ id: 42, email: "guest@example.com", status: "pending" }],
      })),
      revokeInvitation: vi.fn(async () => {
        throw conflict;
      }),
    });
    const user = userEvent.setup();

    render(
      <InvitationsPage
        cache={createCache()}
        organizationId={7}
        service={service}
      />,
    );

    await user.click(
      await screen.findByRole("button", {
        name: "撤销 guest@example.com 的邀请",
      }),
    );
    expect(await screen.findByText("邀请状态已变化，请刷新后重试")).toBeInTheDocument();
  });

  it("keeps malformed records visible but disables commands without an id", async () => {
    const service = createService({
      listInvitations: vi.fn(async () => ({
        items: [{ email: "malformed@example.com", status: "pending" }],
      })),
    });

    render(
      <InvitationsPage
        cache={createCache()}
        organizationId={7}
        service={service}
      />,
    );

    expect(await screen.findByText("malformed@example.com")).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: "撤销 malformed@example.com 的邀请",
      }),
    ).toBeDisabled();
  });
});
