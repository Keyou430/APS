import { describe, expect, it, vi } from "vitest";
import type { ApiClient } from "../client";
import { createEnterpriseService } from "./enterpriseService";

const portalResponse = {
  company: { id: 1, name: "星纪年" },
  currentUser: { id: 10, username: "keyou" },
  announcements: [],
  departments: [],
  positions: [],
  people: [],
  activities: [],
  todos: [],
  quickLinks: [],
  collaborators: [],
};

describe("enterprise service", () => {
  it("requests the contract enterprise portal endpoint", async () => {
    const request = vi.fn();
    const client: ApiClient = {
      request: async (path) => request(path),
    };
    request.mockResolvedValue(portalResponse);
    const service = createEnterpriseService(client);

    const result = await service.getPortal();

    expect(result).toBe(portalResponse);
    expect(request).toHaveBeenCalledWith("/enterprise/portal");
  });

  it("maps the contract portal endpoint to legacy bootstrap data", async () => {
    const request = vi.fn();
    const client: ApiClient = {
      request: async (path) => request(path),
    };
    request.mockResolvedValue({
      ...portalResponse,
      currentUser: {
        id: "10",
        name: "Keyou",
        email: "keyou@example.com",
        department: "前端组",
        position: "负责人",
      },
      todos: [
        {
          id: "todo-1",
          title: "处理审批",
          priority: "high",
          completed: false,
        },
      ],
    });
    const service = createEnterpriseService(client);

    const bootstrap = await service.getLegacyBootstrap({
      metrics: [{ id: "m1" }],
    });

    expect(bootstrap.workspace?.tasks?.[0]).toMatchObject({
      id: "todo-1",
      done: false,
    });
    expect(bootstrap.workspace?.dashboard?.profile).toMatchObject({
      name: "Keyou",
      department: "前端组",
    });
    expect(bootstrap.workspace?.dashboard?.metrics).toEqual([{ id: "m1" }]);
  });

  it("manages announcements through contract endpoints", async () => {
    const request = vi.fn();
    const client: ApiClient = {
      request: async (path, options) => request(path, options),
    };
    request.mockResolvedValue({});
    const service = createEnterpriseService(client);

    await service.listAnnouncements({ status: "draft", page: 1 });
    await service.createAnnouncement({ title: "公告", content: "正文" });
    await service.updateAnnouncement(3, { title: "更新公告" });
    await service.publishAnnouncement(3);
    await service.pinAnnouncement(3, { isPinned: true });
    await service.withdrawAnnouncement(3);
    await service.markAnnouncementRead(3);

    expect(request).toHaveBeenNthCalledWith(
      1,
      "/enterprise/announcements?status=draft&page=1",
      undefined,
    );
    expect(request).toHaveBeenNthCalledWith(2, "/enterprise/announcements", {
      method: "POST",
      body: { title: "公告", content: "正文" },
    });
    expect(request).toHaveBeenNthCalledWith(
      3,
      "/enterprise/announcements/3",
      {
        method: "PATCH",
        body: { title: "更新公告" },
      },
    );
    expect(request).toHaveBeenNthCalledWith(
      4,
      "/enterprise/announcements/3/publish",
      { method: "POST" },
    );
    expect(request).toHaveBeenNthCalledWith(
      5,
      "/enterprise/announcements/3/pin",
      { method: "POST", body: { isPinned: true } },
    );
    expect(request).toHaveBeenNthCalledWith(
      6,
      "/enterprise/announcements/3/withdraw",
      { method: "POST" },
    );
    expect(request).toHaveBeenNthCalledWith(
      7,
      "/enterprise/announcements/3/read",
      { method: "POST" },
    );
  });

  it("updates portal todos through the enterprise contract endpoint", async () => {
    const request = vi.fn();
    const client: ApiClient = {
      request: async (path, options) => request(path, options),
    };
    request.mockResolvedValue({ completed: true });
    const service = createEnterpriseService(client);

    const result = await service.updatePortalTodo(9, { completed: true });

    expect(result).toEqual({ completed: true });
    expect(request).toHaveBeenCalledWith("/enterprise/portal/todos/9", {
      method: "PUT",
      body: { completed: true },
    });
  });

  it("creates and publishes a notice as one UI operation", async () => {
    const request = vi
      .fn()
      .mockResolvedValueOnce({ id: 3, status: "draft" })
      .mockResolvedValueOnce({ id: 3, status: "published" });
    const client: ApiClient = {
      request: async (path, options) => request(path, options),
    };
    const service = createEnterpriseService(client);

    const result = await service.createPublishedAnnouncement({
      title: "公告",
      content: "正文",
    });

    expect(result).toMatchObject({ id: 3, status: "published" });
    expect(request).toHaveBeenNthCalledWith(1, "/enterprise/announcements", {
      method: "POST",
      body: { title: "公告", content: "正文" },
    });
    expect(request).toHaveBeenNthCalledWith(
      2,
      "/enterprise/announcements/3/publish",
      { method: "POST" },
    );
  });
});
