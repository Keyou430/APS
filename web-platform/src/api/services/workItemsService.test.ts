import { describe, expect, it, vi } from "vitest";
import type { ApiClient } from "../client";
import { createWorkItemsService } from "./workItemsService";

function createClient() {
  const request = vi.fn();
  const client: ApiClient = {
    request: async (path, options) => request(path, options),
  };
  return { client, request };
}

describe("work items service", () => {
  it("lists work items with query parameters and creates items", async () => {
    const { client, request } = createClient();
    request.mockResolvedValue({});
    const service = createWorkItemsService(client);

    await service.listWorkItems({
      status: "pending",
      assignee_id: 42,
      page: 2,
    });
    await service.createWorkItem({ title: "补齐契约", priority: "high" });

    expect(request).toHaveBeenNthCalledWith(
      1,
      "/work-items?status=pending&assignee_id=42&page=2",
      undefined,
    );
    expect(request).toHaveBeenNthCalledWith(2, "/work-items", {
      method: "POST",
      body: { title: "补齐契约", priority: "high" },
    });
  });

  it("updates, deletes and changes status through contract endpoints", async () => {
    const { client, request } = createClient();
    request.mockResolvedValue({});
    const service = createWorkItemsService(client);

    await service.getWorkItem(7);
    await service.updateWorkItem(7, { title: "更新" });
    await service.updateWorkItemStatus(7, { status: "in_progress" });
    await service.deleteWorkItem(7);

    expect(request).toHaveBeenNthCalledWith(1, "/work-items/7", undefined);
    expect(request).toHaveBeenNthCalledWith(2, "/work-items/7", {
      method: "PATCH",
      body: { title: "更新" },
    });
    expect(request).toHaveBeenNthCalledWith(3, "/work-items/7/status", {
      method: "PATCH",
      body: { status: "in_progress" },
    });
    expect(request).toHaveBeenNthCalledWith(4, "/work-items/7", {
      method: "DELETE",
    });
  });

  it("reads work item events by item and event id", async () => {
    const { client, request } = createClient();
    request.mockResolvedValue({});
    const service = createWorkItemsService(client);

    await service.listWorkItemEvents(7);
    await service.getWorkItemEvent(22);

    expect(request).toHaveBeenNthCalledWith(
      1,
      "/work-items/7/events",
      undefined,
    );
    expect(request).toHaveBeenNthCalledWith(
      2,
      "/work-items/events/22",
      undefined,
    );
  });
});
