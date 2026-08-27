import { describe, expect, it, vi } from "vitest";
import type { ApiClient } from "../client";
import {
  createChatService,
  type KnowledgeScopeUpdate,
} from "./chatService";

function createClient() {
  const request = vi.fn();
  const client: ApiClient = {
    request: async (path, options) => request(path, options),
  };
  return { client, request };
}

describe("chat service", () => {
  it("models knowledge scope requests as backend variants", () => {
    const selected: KnowledgeScopeUpdate = {
      mode: "selected",
      source_ids: [1, 2],
    };
    const allVisible: KnowledgeScopeUpdate = {
      mode: "all_visible",
      source_ids: [],
    };
    const none: KnowledgeScopeUpdate = { mode: "none", source_ids: [] };

    // @ts-expect-error mode is required by the backend contract.
    const missingMode: KnowledgeScopeUpdate = { source_ids: [1, 2] };
    // @ts-expect-error selected scope requires source_ids.
    const missingSelectedSources: KnowledgeScopeUpdate = { mode: "selected" };
    // @ts-expect-error non-selected scopes only accept an empty source_ids list.
    const invalidAllVisible: KnowledgeScopeUpdate = {
      mode: "all_visible",
      source_ids: [1],
    };

    expect({
      selected,
      allVisible,
      none,
      missingMode,
      missingSelectedSources,
      invalidAllVisible,
    }).toBeDefined();
  });

  it("manages chat sessions and knowledge scope", async () => {
    const { client, request } = createClient();
    request.mockResolvedValue({});
    const service = createChatService(client);

    await service.listSessions({ page: 1 });
    await service.createSession({ title: "联调" });
    await service.updateSession("s1", { title: "首问标题" });
    await service.setKnowledgeScope("s1", {
      mode: "selected",
      source_ids: [1, 2],
    });
    await service.deleteSession("s1");

    expect(request).toHaveBeenNthCalledWith(1, "/chat/sessions?page=1", undefined);
    expect(request).toHaveBeenNthCalledWith(2, "/chat/sessions", {
      method: "POST",
      body: { title: "联调" },
    });
    expect(request).toHaveBeenNthCalledWith(3, "/chat/sessions/s1", {
      method: "PATCH",
      body: { title: "首问标题" },
    });
    expect(request).toHaveBeenNthCalledWith(
      4,
      "/chat/sessions/s1/knowledge-scope",
      {
        method: "PUT",
        body: { mode: "selected", source_ids: [1, 2] },
      },
    );
    expect(request).toHaveBeenNthCalledWith(5, "/chat/sessions/s1", {
      method: "DELETE",
    });
  });

  it("reserves attachments, link preview, history, stop and approval endpoints", async () => {
    const { client, request } = createClient();
    request.mockResolvedValue({});
    const service = createChatService(client);
    const form = new FormData();
    form.set("file", new Blob(["hello"]), "hello.txt");

    await service.prepareAttachment(form);
    await service.previewLink({ url: "https://example.com" });
    await service.getMessages("s1", { limit: 20 });
    await service.stopRun("s1", "r1");
    await service.approveRun("s1", "r1", { action: "once" });

    expect(request).toHaveBeenNthCalledWith(1, "/chat/attachments", {
      method: "POST",
      body: form,
    });
    expect(request).toHaveBeenNthCalledWith(2, "/chat/link-preview", {
      method: "POST",
      body: { url: "https://example.com" },
    });
    expect(request).toHaveBeenNthCalledWith(
      3,
      "/chat/sessions/s1/messages?limit=20",
      undefined,
    );
    expect(request).toHaveBeenNthCalledWith(
      4,
      "/chat/sessions/s1/runs/r1/stop",
      { method: "POST" },
    );
    expect(request).toHaveBeenNthCalledWith(
      5,
      "/chat/sessions/s1/runs/r1/approval",
      { method: "POST", body: { action: "once" } },
    );
  });
});
