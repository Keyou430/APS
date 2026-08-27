import { describe, expect, it, vi } from "vitest";
import type { ApiClient } from "../client";
import { createMemoryService } from "./memoryService";

function createClient() {
  const request = vi.fn();
  const client: ApiClient = {
    request: async (path, options) => request(path, options),
  };
  return { client, request };
}

describe("memory service", () => {
  it("lists and creates memories", async () => {
    const { client, request } = createClient();
    request.mockResolvedValue({});
    const service = createMemoryService(client);

    await service.listMemory({ search: "契约", page: 1 });
    await service.createMemory({ content: "API 契约优先" });

    expect(request).toHaveBeenNthCalledWith(
      1,
      "/memory?search=%E5%A5%91%E7%BA%A6&page=1",
      undefined,
    );
    expect(request).toHaveBeenNthCalledWith(2, "/memory", {
      method: "POST",
      body: { content: "API 契约优先" },
    });
  });

  it("reads, updates and deletes a memory", async () => {
    const { client, request } = createClient();
    request.mockResolvedValue({});
    const service = createMemoryService(client);

    await service.getMemory(3);
    await service.updateMemory(3, { content: "更新后的记忆" });
    await service.deleteMemory(3);

    expect(request).toHaveBeenNthCalledWith(1, "/memory/3", undefined);
    expect(request).toHaveBeenNthCalledWith(2, "/memory/3", {
      method: "PUT",
      body: { content: "更新后的记忆" },
    });
    expect(request).toHaveBeenNthCalledWith(3, "/memory/3", {
      method: "DELETE",
    });
  });
});
