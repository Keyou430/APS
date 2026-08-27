import { describe, expect, it } from "vitest";
import { mapEnterprisePortalToLegacyBootstrap } from "./enterprisePortalMapper";
import type { EnterprisePortalResponse } from "./enterpriseService";

describe("enterprise portal mapper", () => {
  it("maps enterprise portal DTOs to the legacy bootstrap shape", () => {
    const portal: EnterprisePortalResponse = {
      company: { id: "org-1", name: "星纪年", shortName: "星纪年" },
      currentUser: {
        id: "10",
        name: "Keyou",
        email: "keyou@example.com",
        department: "前端组",
        position: "负责人",
      },
      announcements: [
        {
          id: "notice-1",
          title: "平台公告",
          summary: "欢迎使用",
          author: "运营",
          priority: "important",
          publishedAt: "2026-08-12T00:00:00Z",
          content: "正文",
          isPinned: true,
          isRead: false,
        },
      ],
      departments: [{ id: "d1", name: "前端组", memberCount: 3 }],
      positions: [{ id: "p1", title: "负责人", departmentId: "d1", level: "L5" }],
      people: [
        {
          id: "10",
          name: "Keyou",
          email: "keyou@example.com",
          departmentId: "d1",
          department: "前端组",
          positionId: "p1",
          position: "负责人",
        },
      ],
      activities: [
        {
          id: "activity-1",
          type: "news",
          title: "门户上线",
          summary: "企业门户已上线",
          occurredAt: "2026-08-12T01:00:00Z",
        },
      ],
      todos: [
        {
          id: "todo-1",
          title: "处理审批",
          dueAt: "2026-08-13T00:00:00Z",
          priority: "high",
          completed: false,
          href: "/todo/1",
        },
      ],
      quickLinks: [
        {
          id: "link-1",
          name: "知识库",
          url: "/knowledge",
          icon: "book",
          order: 1,
        },
      ],
      collaborators: [],
    };

    const bootstrap = mapEnterprisePortalToLegacyBootstrap(portal);

    expect(bootstrap.workspace?.tasks?.[0]).toMatchObject({
      id: "todo-1",
      title: "处理审批",
      done: false,
      priority: "high",
    });
    expect(bootstrap.workspace?.notices?.[0]).toMatchObject({
      id: "notice-1",
      title: "平台公告",
      pinned: true,
      read: false,
    });
    expect(bootstrap.portal?.news?.[0]).toMatchObject({
      id: "activity-1",
      title: "门户上线",
      source: "enterprise",
    });
    expect(bootstrap.workspace?.shortcuts?.[0]).toEqual([
      "知识库",
      "/knowledge",
      "app-blue",
    ]);
    expect(bootstrap.portal?.dashboard?.company).toMatchObject({
      name: "星纪年",
    });
    expect(bootstrap.workspace?.dashboard?.profile).toMatchObject({
      name: "Keyou",
      department: "前端组",
    });
  });

  it("merges dashboard data into the legacy workspace dashboard", () => {
    const bootstrap = mapEnterprisePortalToLegacyBootstrap(
      {
        company: { id: "org-1", name: "星纪年", shortName: "星纪年" },
        currentUser: {
          id: "10",
          name: "Keyou",
          email: "keyou@example.com",
          department: "前端组",
          position: "负责人",
        },
        announcements: [],
        departments: [],
        positions: [],
        people: [],
        activities: [],
        todos: [],
        quickLinks: [],
        collaborators: [],
      },
      {
        metrics: [{ id: "m1", label: "访问量", value: 12 }],
        notifications: [{ id: "n1", title: "通知" }],
        todos: [{ id: "dash-todo", title: "看板待办" }],
      },
    );

    expect(bootstrap.workspace?.dashboard).toMatchObject({
      metrics: [{ id: "m1", label: "访问量", value: 12 }],
      notifications: [{ id: "n1", title: "通知" }],
      todos: [{ id: "dash-todo", title: "看板待办" }],
    });
  });
});
