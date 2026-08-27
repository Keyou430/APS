import { describe, expect, it, vi } from "vitest";
import type { ApiClient } from "../client";
import { createSkillsService } from "./skillsService";

function createClient() {
  const request = vi.fn();
  const client: ApiClient = {
    request: async (path, options) => request(path, options),
  };
  return { client, request };
}

describe("skills service", () => {
  it("lists, creates, updates and deletes skills", async () => {
    const { client, request } = createClient();
    request.mockResolvedValue({});
    const service = createSkillsService(client);

    await service.listSkills({ search: "写作", page: 1 });
    await service.createSkill({ name: "契约检查" });
    await service.updateSkill(6, { name: "契约检查 v2" });
    await service.deleteSkill(6);

    expect(request).toHaveBeenNthCalledWith(
      1,
      "/skills?search=%E5%86%99%E4%BD%9C&page=1",
      undefined,
    );
    expect(request).toHaveBeenNthCalledWith(2, "/skills", {
      method: "POST",
      body: { name: "契约检查" },
    });
    expect(request).toHaveBeenNthCalledWith(3, "/skills/6", {
      method: "PUT",
      body: { name: "契约检查 v2" },
    });
    expect(request).toHaveBeenNthCalledWith(4, "/skills/6", {
      method: "DELETE",
    });
  });

  it("reads a skill, hub list and generated skill", async () => {
    const { client, request } = createClient();
    request.mockResolvedValue({});
    const service = createSkillsService(client);

    await service.getSkill(6);
    await service.getHubSkills();
    await service.generateSkill({ prompt: "生成契约检查技能" });

    expect(request).toHaveBeenNthCalledWith(1, "/skills/6", undefined);
    expect(request).toHaveBeenNthCalledWith(2, "/skills/hub", undefined);
    expect(request).toHaveBeenNthCalledWith(3, "/skills/generate", {
      method: "POST",
      body: { prompt: "生成契约检查技能" },
    });
  });
});
