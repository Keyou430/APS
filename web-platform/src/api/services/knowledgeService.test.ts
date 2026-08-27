import { describe, expect, it, vi } from "vitest";
import type { ApiClient } from "../client";
import {
  createKnowledgeService,
  type KnowledgeService,
} from "./knowledgeService";

function createClient() {
  const request = vi.fn();
  const client: ApiClient = {
    request: async (path, options) => request(path, options),
  };
  return { client, request };
}

function assertNumericCitationTurnId(
  resolveCitation: KnowledgeService["resolveCitation"],
) {
  if (false) {
    const arbitraryTurnId: string = "turn-1";
    // @ts-expect-error citation turn IDs must be numbers or numeric strings.
    void resolveCitation("turn-1", 2);
    // @ts-expect-error arbitrary strings are not valid citation turn IDs.
    void resolveCitation(arbitraryTurnId, 2);
  }
}

describe("knowledge service", () => {
  it("lists, creates, reads, updates and archives entries", async () => {
    const { client, request } = createClient();
    request.mockResolvedValue({});
    const service = createKnowledgeService(client);

    await service.listEntries({ q: "契约", page: 1 });
    await service.createEntry({ title: "前端契约" });
    await service.getEntry(5);
    await service.updateEntry(5, { title: "更新契约" });
    await service.archiveEntry(5);

    expect(request).toHaveBeenNthCalledWith(
      1,
      "/knowledge?q=%E5%A5%91%E7%BA%A6&page=1",
      undefined,
    );
    expect(request).toHaveBeenNthCalledWith(2, "/knowledge", {
      method: "POST",
      body: { title: "前端契约" },
    });
    expect(request).toHaveBeenNthCalledWith(3, "/knowledge/5", undefined);
    expect(request).toHaveBeenNthCalledWith(4, "/knowledge/5", {
      method: "PUT",
      body: { title: "更新契约" },
    });
    expect(request).toHaveBeenNthCalledWith(5, "/knowledge/5", {
      method: "DELETE",
    });
  });

  it("reserves upload, preview, download, ingestion and access endpoints", async () => {
    const { client, request } = createClient();
    request.mockResolvedValue({});
    const service = createKnowledgeService(client);
    const form = new FormData();
    form.set("title", "文件");

    await service.uploadEntry(form);
    await service.ingestEntry(5);
    await service.getIngestionStatus(5);
    await service.previewContent(5);
    await service.downloadEntry(5);
    await service.updateAccess(5, { visibility: "organization" });

    expect(request).toHaveBeenNthCalledWith(1, "/knowledge/upload", {
      method: "POST",
      body: form,
    });
    expect(request).toHaveBeenNthCalledWith(2, "/knowledge/5/ingest", {
      method: "POST",
    });
    expect(request).toHaveBeenNthCalledWith(
      3,
      "/knowledge/5/ingestion",
      undefined,
    );
    expect(request).toHaveBeenNthCalledWith(
      4,
      "/knowledge/5/content",
      undefined,
    );
    expect(request).toHaveBeenNthCalledWith(
      5,
      "/knowledge/5/download",
      { headers: { Accept: "application/octet-stream" } },
    );
    expect(request).toHaveBeenNthCalledWith(6, "/knowledge/5/access", {
      method: "PUT",
      body: { visibility: "organization" },
    });
  });

  it("manages grants, restore, purge and collection assignment", async () => {
    const { client, request } = createClient();
    request.mockResolvedValue({});
    const service = createKnowledgeService(client);

    await service.listGrants(5);
    await service.createGrant(5, { member_id: 9 });
    await service.revokeGrant(5, 2);
    await service.restoreEntry(5);
    await service.purgeEntry(5);
    await service.assignCollection(5, { collection_id: 4 });

    expect(request).toHaveBeenNthCalledWith(1, "/knowledge/5/grants", undefined);
    expect(request).toHaveBeenNthCalledWith(2, "/knowledge/5/grants", {
      method: "POST",
      body: { member_id: 9 },
    });
    expect(request).toHaveBeenNthCalledWith(3, "/knowledge/5/grants/2", {
      method: "DELETE",
    });
    expect(request).toHaveBeenNthCalledWith(4, "/knowledge/5/restore", {
      method: "POST",
    });
    expect(request).toHaveBeenNthCalledWith(5, "/knowledge/5/purge", {
      method: "DELETE",
    });
    expect(request).toHaveBeenNthCalledWith(6, "/knowledge/5/collection", {
      method: "PUT",
      body: { collection_id: 4 },
    });
  });

  it("covers search, retrieve, citations, members, fixed contexts and operations", async () => {
    const { client, request } = createClient();
    request.mockResolvedValue({});
    const service = createKnowledgeService(client);
    assertNumericCitationTurnId(service.resolveCitation);

    await service.search({ query: "合同" });
    await service.retrieve({ query: "合同" });
    await service.resolveCitation("9", 2);
    await service.listMembers();
    await service.listFixedContexts();
    await service.getFixedContext("ctx-1");
    await service.getOperationsOverview();
    await service.listOperationJobs({ status: "failed" });
    await service.retryOperationJob("job-1");
    await service.cancelOperationJob("job-1");

    expect(request).toHaveBeenNthCalledWith(1, "/knowledge/search", {
      method: "POST",
      body: { query: "合同" },
    });
    expect(request).toHaveBeenNthCalledWith(2, "/knowledge/retrieve", {
      method: "POST",
      body: { query: "合同" },
    });
    expect(request).toHaveBeenNthCalledWith(
      3,
      "/knowledge/citations/9/2",
      undefined,
    );
    expect(request).toHaveBeenNthCalledWith(4, "/knowledge/members", undefined);
    expect(request).toHaveBeenNthCalledWith(
      5,
      "/knowledge/fixed-contexts",
      undefined,
    );
    expect(request).toHaveBeenNthCalledWith(
      6,
      "/knowledge/fixed-contexts/ctx-1",
      undefined,
    );
    expect(request).toHaveBeenNthCalledWith(
      7,
      "/knowledge/operations/overview",
      undefined,
    );
    expect(request).toHaveBeenNthCalledWith(
      8,
      "/knowledge/operations/jobs?status=failed",
      undefined,
    );
    expect(request).toHaveBeenNthCalledWith(
      9,
      "/knowledge/operations/jobs/job-1/retry",
      { method: "POST" },
    );
    expect(request).toHaveBeenNthCalledWith(
      10,
      "/knowledge/operations/jobs/job-1/cancel",
      { method: "POST" },
    );
  });

  it("manages knowledge collections", async () => {
    const { client, request } = createClient();
    request.mockResolvedValue({});
    const service = createKnowledgeService(client);

    await service.listCollections();
    await service.createCollection({ name: "合同" });
    await service.updateCollection(4, { name: "合同库" });
    await service.deleteCollection(4);

    expect(request).toHaveBeenNthCalledWith(
      1,
      "/knowledge/collections",
      undefined,
    );
    expect(request).toHaveBeenNthCalledWith(2, "/knowledge/collections", {
      method: "POST",
      body: { name: "合同" },
    });
    expect(request).toHaveBeenNthCalledWith(3, "/knowledge/collections/4", {
      method: "PATCH",
      body: { name: "合同库" },
    });
    expect(request).toHaveBeenNthCalledWith(4, "/knowledge/collections/4", {
      method: "DELETE",
    });
  });
});
