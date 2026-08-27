import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom/vitest";
import { describe, expect, it, vi } from "vitest";
import type { DashboardService } from "../api/services/dashboardService";
import { DashboardPage } from "./DashboardPage";

function createCache() {
  return {
    get: vi.fn(),
    invalidateOrganization: vi.fn(),
    set: vi.fn(),
  };
}

const layout = {
  id: "layout-1",
  layouts: {
    lg: [{ i: "metrics", x: 0, y: 0, w: 4, h: 2 }],
    md: [],
    sm: [],
  },
  revision: 3,
  updatedAt: "2026-08-14T08:00:00Z",
  userId: "7",
  widgets: [{ id: "metrics", title: "关键指标" }],
};

function createService(
  overrides: Partial<DashboardService> = {},
): DashboardService {
  return {
    approveDecision: vi.fn(async () => ({ id: "decision-1", status: "approved" as const, title: "审批" })),
    getDashboard: vi.fn(async () => ({
      calendarEvents: [{ id: "c1", title: "产品例会" }],
      metrics: [{ id: "m1", label: "线索", value: 18 }],
      notifications: [{ id: "n1" }],
      pipelines: [{ id: "p1" }],
      quickActions: [{ id: "q1" }],
      recentVisits: [{ id: "v1", title: "知识库" }],
      todos: [{ id: "t1", title: "审批合同" }],
    })),
    getLayout: vi.fn(async () => layout),
    listDecisions: vi.fn(async () => ({ items: [] })),
    rejectDecision: vi.fn(async () => ({ id: "decision-1", status: "rejected" as const, title: "审批" })),
    resetLayout: vi.fn(async () => ({ ...layout, revision: 1 })),
    saveLayout: vi.fn(async () => ({ ...layout, revision: 4 })),
    ...overrides,
  } as DashboardService;
}

describe("DashboardPage", () => {
  it("loads dashboard data and layout into an organization-scoped cache", async () => {
    const cache = createCache();
    const service = createService();

    render(<DashboardPage cache={cache} organizationId={7} service={service} />);

    expect(screen.getByText("正在加载驾驶舱")).toBeInTheDocument();
    expect(await screen.findByText("线索")).toBeInTheDocument();
    expect(screen.getByText("产品例会")).toBeInTheDocument();
    expect(screen.getByText("知识库")).toBeInTheDocument();
    expect(screen.getByText("布局版本 3")).toBeInTheDocument();
    expect(service.getDashboard).toHaveBeenCalledWith();
    expect(service.getLayout).toHaveBeenCalledWith();
    expect(cache.get).toHaveBeenCalledWith(7, ["dashboard", "overview"]);
    expect(cache.set).toHaveBeenCalledWith(
      7,
      ["dashboard", "overview"],
      expect.objectContaining({ layout: expect.objectContaining({ revision: 3 }) }),
    );
  });

  it("fails closed when organization context is missing", async () => {
    const service = createService();

    render(
      <DashboardPage cache={createCache()} organizationId={null} service={service} />,
    );

    expect(await screen.findByText("没有驾驶舱访问权限")).toBeInTheDocument();
    expect(service.getDashboard).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "保存布局" })).toBeDisabled();
  });

  it("saves layout with expected revision and invalidates the current organization", async () => {
    const cache = createCache();
    const service = createService();
    const user = userEvent.setup();

    render(<DashboardPage cache={cache} organizationId={7} service={service} />);

    await screen.findByText("布局版本 3");
    await user.click(screen.getByRole("button", { name: "保存布局" }));

    await waitFor(() =>
      expect(service.saveLayout).toHaveBeenCalledWith({
        expectedRevision: 3,
        layouts: layout.layouts,
      }),
    );
    expect(cache.invalidateOrganization).toHaveBeenCalledWith(7);
    expect(await screen.findByText("布局版本 4")).toBeInTheDocument();
  });

  it("keeps the current layout visible when save returns a revision conflict", async () => {
    const conflict = Object.assign(new Error("Conflict"), { status: 409 });
    const service = createService({
      saveLayout: vi.fn(async () => {
        throw conflict;
      }),
    });
    const user = userEvent.setup();

    render(
      <DashboardPage cache={createCache()} organizationId={7} service={service} />,
    );

    await screen.findByText("布局版本 3");
    await user.click(screen.getByRole("button", { name: "保存布局" }));

    expect(
      await screen.findByText("布局版本已被更新，请刷新后再保存"),
    ).toBeInTheDocument();
    expect(screen.getByText("布局版本 3")).toBeInTheDocument();
  });

  it("refreshes from the server after a layout conflict", async () => {
    const conflict = Object.assign(new Error("Conflict"), { status: 409 });
    const cache = createCache();
    const service = createService({
      getLayout: vi
        .fn()
        .mockResolvedValueOnce(layout)
        .mockResolvedValueOnce({ ...layout, revision: 8 }),
      saveLayout: vi.fn(async () => {
        throw conflict;
      }),
    });
    const user = userEvent.setup();

    render(<DashboardPage cache={cache} organizationId={7} service={service} />);

    await screen.findByText("布局版本 3");
    await user.click(screen.getByRole("button", { name: "保存布局" }));
    await screen.findByText("布局版本已被更新，请刷新后再保存");
    await user.click(screen.getByRole("button", { name: "刷新驾驶舱" }));

    expect(await screen.findByText("布局版本 8")).toBeInTheDocument();
    expect(cache.invalidateOrganization).toHaveBeenCalledWith(7);
  });
});
