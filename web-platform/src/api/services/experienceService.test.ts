import { describe, expect, it, vi } from "vitest";
import { createExperienceService } from "./experienceService";

describe("experience service", () => {
  it("uses organization-scoped domain and method endpoints", async () => {
    const request = vi.fn(async () => ({ items: [] }));
    const service = createExperienceService({ request } as never);

    await service.listDomains();
    await service.createDomain({ name: "招聘" });
    await service.listMethods(7);
    await service.createMethod(7, {
      title: "结构化面试",
      content: "按 STAR 追问",
      source_type: "ai_summary",
    });
    await service.updateMethod(8, { content: "更新后的方法" });
    await service.deleteMethod(8);

    expect(request).toHaveBeenNthCalledWith(1, "/experience/domains");
    expect(request).toHaveBeenNthCalledWith(2, "/experience/domains", {
      method: "POST",
      body: { name: "招聘" },
    });
    expect(request).toHaveBeenNthCalledWith(3, "/experience/domains/7/methods");
    expect(request).toHaveBeenNthCalledWith(4, "/experience/domains/7/methods", {
      method: "POST",
      body: {
        title: "结构化面试",
        content: "按 STAR 追问",
        source_type: "ai_summary",
      },
    });
    expect(request).toHaveBeenNthCalledWith(5, "/experience/methods/8", {
      method: "PATCH",
      body: { content: "更新后的方法" },
    });
    expect(request).toHaveBeenNthCalledWith(6, "/experience/methods/8", {
      method: "DELETE",
    });
  });
});
