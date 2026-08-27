import { describe, expect, it, vi } from "vitest";
import type { ApiClient } from "../client";
import { createRemindersService } from "./remindersService";

function createClient() {
  const request = vi.fn();
  const client: ApiClient = {
    request: async (path, options) => request(path, options),
  };
  return { client, request };
}

describe("reminders service", () => {
  it("lists, creates and reads upcoming reminders", async () => {
    const { client, request } = createClient();
    request.mockResolvedValue({});
    const service = createRemindersService(client);

    await service.listReminders({ status: "open", page: 1 });
    await service.createReminder({ title: "联调复盘" });
    await service.listUpcoming({ limit: 5 });

    expect(request).toHaveBeenNthCalledWith(
      1,
      "/reminders?status=open&page=1",
      undefined,
    );
    expect(request).toHaveBeenNthCalledWith(2, "/reminders", {
      method: "POST",
      body: { title: "联调复盘" },
    });
    expect(request).toHaveBeenNthCalledWith(
      3,
      "/reminders/upcoming?limit=5",
      undefined,
    );
  });

  it("updates, deletes and completes reminders", async () => {
    const { client, request } = createClient();
    request.mockResolvedValue({});
    const service = createRemindersService(client);

    await service.updateReminder(9, { title: "已更新" });
    await service.completeReminder(9);
    await service.deleteReminder(9);

    expect(request).toHaveBeenNthCalledWith(1, "/reminders/9", {
      method: "PUT",
      body: { title: "已更新" },
    });
    expect(request).toHaveBeenNthCalledWith(2, "/reminders/9/complete", {
      method: "POST",
    });
    expect(request).toHaveBeenNthCalledWith(3, "/reminders/9", {
      method: "DELETE",
    });
  });
});
