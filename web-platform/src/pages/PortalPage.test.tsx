import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom/vitest";
import { describe, expect, it, vi } from "vitest";
import type { EnterpriseService } from "../api/services/enterpriseService";
import { PortalPage } from "./PortalPage";

function createCache() {
  return {
    get: vi.fn(),
    invalidateOrganization: vi.fn(),
    set: vi.fn(),
  };
}

function createService(
  overrides: Partial<EnterpriseService> = {},
): EnterpriseService {
  return {
    createAnnouncement: vi.fn(),
    getLegacyBootstrap: vi.fn(),
    getPortal: vi.fn(async () => ({
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
    })),
    listAnnouncements: vi.fn(),
    markAnnouncementRead: vi.fn(),
    pinAnnouncement: vi.fn(),
    publishAnnouncement: vi.fn(),
    updateAnnouncement: vi.fn(),
    updatePortalTodo: vi.fn(async () => ({ id: 8, title: "审批合同", completed: true })),
    withdrawAnnouncement: vi.fn(),
    ...overrides,
  } as EnterpriseService;
}

describe("PortalPage", () => {
  it("loads portal data into an organization-scoped cache", async () => {
    const cache = createCache();
    const service = createService();

    render(<PortalPage cache={cache} organizationId={7} service={service} />);

    expect(screen.getByText("正在加载企业门户")).toBeInTheDocument();
    expect(await screen.findByText("星纪年")).toBeInTheDocument();
    expect(screen.getByText("组织周会安排")).toBeInTheDocument();
    expect(screen.getByText("审批合同")).toBeInTheDocument();
    expect(screen.getByText("知识库")).toBeInTheDocument();
    expect(screen.getByText("Keyou430")).toBeInTheDocument();
    expect(service.getPortal).toHaveBeenCalledWith();
    expect(cache.get).toHaveBeenCalledWith(7, ["portal", "overview"]);
    expect(cache.set).toHaveBeenCalledWith(
      7,
      ["portal", "overview"],
      expect.objectContaining({
        companyName: "星纪年",
        todos: [expect.objectContaining({ id: 8 })],
      }),
    );
  });

  it("fails closed when organization context is missing", async () => {
    const service = createService();

    render(<PortalPage cache={createCache()} organizationId={null} service={service} />);

    expect(await screen.findByText("没有企业门户访问权限")).toBeInTheDocument();
    expect(service.getPortal).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "刷新企业门户" })).toBeDisabled();
  });

  it("updates a portal todo and invalidates only the current organization", async () => {
    const cache = createCache();
    const service = createService();
    const user = userEvent.setup();

    render(<PortalPage cache={cache} organizationId={7} service={service} />);

    const todos = await screen.findByLabelText("门户待办");
    await user.click(within(todos).getByRole("button", { name: "完成 审批合同" }));

    await waitFor(() =>
      expect(service.updatePortalTodo).toHaveBeenCalledWith(8, {
        completed: true,
      }),
    );
    expect(cache.invalidateOrganization).toHaveBeenCalledWith(7);
    expect(await screen.findByText("已完成")).toBeInTheDocument();
  });

  it("disables portal actions after a forbidden response", async () => {
    const forbidden = Object.assign(new Error("Forbidden"), { status: 403 });
    const service = createService({
      updatePortalTodo: vi.fn(async () => {
        throw forbidden;
      }),
    });
    const user = userEvent.setup();

    render(<PortalPage cache={createCache()} organizationId={7} service={service} />);

    const todos = await screen.findByLabelText("门户待办");
    await user.click(within(todos).getByRole("button", { name: "完成 审批合同" }));

    expect(await screen.findByText("没有企业门户访问权限")).toBeInTheDocument();
    expect(within(todos).getByRole("button", { name: "完成 审批合同" })).toBeDisabled();
  });
});
