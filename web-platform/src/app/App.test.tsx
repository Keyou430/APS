import { act, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { describe, expect, it, vi } from "vitest";
import type { AppRuntime } from "./appRuntime";
import { App } from "./App";
import { appRoutes, isReactOwnedRoute, resolveRoute } from "./routes";

function createRuntime(): AppRuntime {
  return {
    auth: {
      cache: {
        get: vi.fn(),
        invalidateOrganization: vi.fn(),
        set: vi.fn(),
      },
      store: {
        getState: () => ({
          organizationId: 7,
          session: null,
          status: "authenticated",
          user: null,
        }),
        subscribe: () => () => undefined,
      },
    },
    services: {
      dashboard: {
        getDashboard: vi.fn(async () => ({
          metrics: [{ id: "m1", label: "线索", value: 18 }],
        })),
        getLayout: vi.fn(async () => ({
          id: "layout-1",
          layouts: {
            lg: [{ i: "metrics", x: 0, y: 0, w: 4, h: 2 }],
            md: [],
            sm: [],
          },
          revision: 3,
          updatedAt: "2026-08-14T08:00:00Z",
          userId: "7",
          widgets: [],
        })),
        resetLayout: vi.fn(),
        saveLayout: vi.fn(),
      },
      enterprise: {
        createAnnouncement: vi.fn(),
        getLegacyBootstrap: vi.fn(),
        getPortal: vi.fn(async () => ({
          activities: [],
          announcements: [{ id: 2, title: "组织周会安排" }],
          collaborators: [],
          company: { name: "星纪年" },
          currentUser: {},
          departments: [],
          people: [],
          positions: [],
          quickLinks: [],
          todos: [],
        })),
        listAnnouncements: vi.fn(),
        markAnnouncementRead: vi.fn(),
        pinAnnouncement: vi.fn(),
        publishAnnouncement: vi.fn(),
        updateAnnouncement: vi.fn(),
        updatePortalTodo: vi.fn(),
        withdrawAnnouncement: vi.fn(),
      },
      hermes: {
        createProfile: vi.fn(),
        deactivateProfile: vi.fn(),
        getProfile: vi.fn(async () => ({
          provider: "feishu",
          status: "active",
          user_id: 9,
        })),
        getProfileHealth: vi.fn(),
      },
      invitations: {
        acceptInvitation: vi.fn(),
        createInvitation: vi.fn(),
        listInvitations: vi.fn(async () => ({ items: [] })),
        regenerateInvitation: vi.fn(),
        revokeGuestMembership: vi.fn(),
        revokeInvitation: vi.fn(),
      },
      pipeline: {
        listTasks: vi.fn(async () => ({
          items: [{ id: "task-1", status: "ready", title: "行业日报" }],
        })),
        getTask: vi.fn(async () => ({
          id: "task-1",
          status: "ready",
          title: "行业日报",
        })),
        listDecisions: vi.fn(async () => ({ items: [] })),
        listPipelines: vi.fn(async () => ({
          items: [{ id: "task-1", status: "processing", title: "行业日报" }],
        })),
      },
      organization: {
        createPosition: vi.fn(),
        createUnit: vi.fn(),
        deletePosition: vi.fn(),
        deleteUnit: vi.fn(),
        getStructure: vi.fn(async () => ({
          organization_id: 7,
          revision: 4,
          units: [{ id: 1, parent_id: null, name: "星纪年", code: "root" }],
          positions: [],
          placements: [],
          people: [],
        })),
        updatePlacement: vi.fn(),
        updatePlacementsBatch: vi.fn(),
        updatePosition: vi.fn(),
        updateUnit: vi.fn(),
      },
      users: {
        assignRoles: vi.fn(),
        createUser: vi.fn(),
        deleteUser: vi.fn(),
        getUser: vi.fn(),
        listUsers: vi.fn(async () => ({
          items: [],
          total: 0,
          page: 1,
          page_size: 20,
        })),
        updateUser: vi.fn(),
      },
    },
  } as unknown as AppRuntime;
}

describe("React app shell", () => {
  it("reacts to organization changes without requiring a page reload", async () => {
    const runtime = createRuntime();
    let organizationId: number | null = null;
    const listeners = new Set<() => void>();
    runtime.auth.store = {
      ...runtime.auth.store,
      getState: () => ({
        organizationId,
        session: null,
        status: organizationId === null ? "anonymous" : "authenticated",
        user: null,
      }),
      subscribe: (listener: () => void) => {
        listeners.add(listener);
        return () => listeners.delete(listener);
      },
    };
    render(<App pathname="/pipeline" runtime={runtime} />);
    expect(screen.getByLabelText("任务描述")).toBeDisabled();

    act(() => {
      organizationId = 7;
      listeners.forEach((listener) => listener());
    });

    await waitFor(() => expect(screen.getByLabelText("任务描述")).toBeEnabled());
    expect(runtime.services.pipeline.listTasks).toHaveBeenCalled();
  });

  it("declares the approved route groups for the migration shell", () => {
    expect(appRoutes.map((route) => route.id)).toEqual([
      "portal",
      "dashboard",
      "organization",
      "users",
      "invitations",
      "knowledge",
      "chat",
      "pipeline",
      "work-items",
      "memory",
      "skills",
      "reminders",
      "hermes",
      "admin",
    ]);
    expect(appRoutes.every((route) => route.statuses.includes("error"))).toBe(
      true,
    );
  });

  it("renders the legacy workspace inside the React route host", () => {
    const view = render(<App />);

    expect(view.container.querySelector('[data-entry="react-route-shell"]')).toHaveAttribute(
      "data-entry",
      "react-route-shell",
    );
    expect(screen.queryByRole("application")).not.toBeInTheDocument();
    expect(screen.getByLabelText("legacy workspace host")).toHaveAttribute(
      "data-route",
      "dashboard",
    );
  });

  it("renders the invitations route as a React page", async () => {
    render(<App pathname="/invitations" runtime={createRuntime()} />);

    expect(
      await screen.findByRole("heading", { name: "邀请管理" }),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("legacy workspace host")).not.toBeInTheDocument();
  });

  it("renders the dashboard route as a React page", async () => {
    render(<App pathname="/" runtime={createRuntime()} />);

    expect(
      await screen.findByRole("heading", { name: "驾驶舱" }),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("legacy workspace host")).not.toBeInTheDocument();
    expect(isReactOwnedRoute("/")).toBe(true);
  });

  it("declares account management as a React-owned route", () => {
    expect(isReactOwnedRoute("/admin")).toBe(true);
    expect(resolveRoute("/admin").id).toBe("admin");
  });

  it("renders the portal route as a React page", async () => {
    render(<App pathname="/portal" runtime={createRuntime()} />);

    expect(
      await screen.findByRole("heading", { name: "企业门户" }),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("legacy workspace host")).not.toBeInTheDocument();
  });

  it("renders the pipeline route as a React page", async () => {
    render(<App pathname="/pipeline" runtime={createRuntime()} />);

    expect(
      await screen.findByRole("heading", { name: "Pipeline" }),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("legacy workspace host")).not.toBeInTheDocument();
    expect(isReactOwnedRoute("/pipeline")).toBe(true);
  });

  it("renders the organization route as a React page", async () => {
    render(<App pathname="/organization" runtime={createRuntime()} />);

    expect(
      await screen.findByRole("heading", { name: "组织架构" }),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("legacy workspace host")).not.toBeInTheDocument();
  });

  it("renders the users route as a React page", async () => {
    render(<App pathname="/users" runtime={createRuntime()} />);

    expect(
      await screen.findByRole("heading", { name: "用户管理" }),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("legacy workspace host")).not.toBeInTheDocument();
  });

  it("renders the AI service route as a React page", async () => {
    render(<App pathname="/hermes" runtime={createRuntime()} />);

    expect(
      await screen.findByRole("heading", { name: "AI 服务" }),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("legacy workspace host")).not.toBeInTheDocument();
  });

  it("keeps invitations on the legacy host when the runtime is unavailable", () => {
    render(<App pathname="/invitations" />);

    expect(screen.getByLabelText("legacy workspace host")).toHaveAttribute(
      "data-route",
      "invitations",
    );
  });
});
