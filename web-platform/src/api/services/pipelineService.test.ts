import { describe, expect, it, vi } from "vitest";
import type { ApiClient } from "../client";
import { createPipelineService } from "./pipelineService";

function createClient() {
  const request = vi.fn();
  const client: ApiClient = {
    request: async (path, options) => request(path, options),
  };
  return { client, request };
}

describe("pipeline service", () => {
  it("uses the frozen task, run, decision and output contracts", async () => {
    const { client, request } = createClient();
    request
      .mockResolvedValueOnce({ id: "draft-1" })
      .mockResolvedValueOnce({ id: "task-1" })
      .mockResolvedValueOnce({ items: [{ id: "task-1" }] })
      .mockResolvedValueOnce({ id: "task-1" })
      .mockResolvedValueOnce({ id: "run-1" })
      .mockResolvedValueOnce({ id: "run-1", status: "completed" })
      .mockResolvedValueOnce({ items: [{ id: "decision-1" }] })
      .mockResolvedValueOnce({ id: "decision-1", status: "approved" })
      .mockResolvedValueOnce({ id: "decision-1", status: "changes_requested" })
      .mockResolvedValueOnce({ id: "output-1", markdown: "# 周报" })
      .mockResolvedValueOnce(new Blob(["# 周报"], { type: "text/markdown" }));
    const service = createPipelineService(client);

    await service.createDraft({ title: "周报" });
    await service.createTask({ title: "周报" });
    await service.listTasks({ status: "ready", limit: 10 });
    await service.getTask("task-1");
    await service.runTask("task-1");
    await service.getRun("run-1");
    await service.listDecisions();
    await service.approveDecision("decision-1", {
      comment: "已核对来源，可以归档",
    });
    await service.requestChanges("decision-1", {
      reason: "需要补充审批依据",
    });
    await service.getOutput("output-1");
    await service.downloadOutput("output-1");

    expect(request).toHaveBeenNthCalledWith(1, "/pipeline/tasks/draft", {
      method: "POST",
      body: { title: "周报" },
    });
    expect(request).toHaveBeenNthCalledWith(2, "/pipeline/tasks", {
      method: "POST",
      body: { title: "周报" },
      headers: { "Idempotency-Key": expect.any(String) },
    });
    expect(request).toHaveBeenNthCalledWith(
      3,
      "/pipeline/tasks?status=ready&limit=10",
      undefined,
    );
    expect(request).toHaveBeenNthCalledWith(4, "/pipeline/tasks/task-1", undefined);
    expect(request).toHaveBeenNthCalledWith(5, "/pipeline/tasks/task-1/run", {
      method: "POST",
      headers: { "Idempotency-Key": expect.any(String) },
    });
    expect(request).toHaveBeenNthCalledWith(6, "/pipeline/runs/run-1", undefined);
    expect(request).toHaveBeenNthCalledWith(
      7,
      "/dashboard/decisions",
      undefined,
    );
    expect(request).toHaveBeenNthCalledWith(
      8,
      "/dashboard/decisions/decision-1/approve",
      {
        method: "POST",
        headers: { "Idempotency-Key": expect.any(String) },
        body: { comment: "已核对来源，可以归档" },
      },
    );
    expect(request).toHaveBeenNthCalledWith(
      9,
      "/dashboard/decisions/decision-1/request-changes",
      {
        method: "POST",
        body: { reason: "需要补充审批依据" },
        headers: { "Idempotency-Key": expect.any(String) },
      },
    );
    expect(request).toHaveBeenNthCalledWith(10, "/pipeline/outputs/output-1", undefined);
    expect(request).toHaveBeenNthCalledWith(
      11,
      "/pipeline/outputs/output-1/download",
      {
        headers: { Accept: "application/octet-stream" },
        responseType: "blob",
      },
    );
  });

  it("reuses idempotency keys for repeated mutations of the same resource", async () => {
    const { client, request } = createClient();
    request.mockResolvedValue({ id: "decision-1", status: "approved" });
    const service = createPipelineService(client);

    await service.approveDecision("decision-1");
    await service.approveDecision("decision-1");
    expect(request.mock.calls[0][1].headers["Idempotency-Key"]).toBe(
      request.mock.calls[1][1].headers["Idempotency-Key"],
    );
  });

  it("keeps decision action keys deterministic across service instances (no random UUIDs)", async () => {
    const { client, request } = createClient();
    request.mockResolvedValue({ id: 7, status: "approved" });

    await createPipelineService(client).approveDecision(7);
    await createPipelineService(client).approveDecision(7);
    await createPipelineService(client).requestChanges(9, { reason: "tighten" });

    const approveKey = request.mock.calls[0][1].headers["Idempotency-Key"];
    expect(approveKey).toBe(request.mock.calls[1][1].headers["Idempotency-Key"]);
    expect(approveKey).not.toMatch(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}/);
  });

  it("reuses the run key within one intent and mints a fresh key after release", async () => {
    const { client, request } = createClient();
    request.mockResolvedValue({ id: 5, status: "queued" });
    const service = createPipelineService(client);

    await service.runTask(5);
    await service.runTask(5);
    const intentKey = request.mock.calls[0][1].headers["Idempotency-Key"];
    expect(request.mock.calls[1][1].headers["Idempotency-Key"]).toBe(intentKey);

    service.releaseRunIntent(String(5));
    await service.runTask(5);
    expect(request.mock.calls[2][1].headers["Idempotency-Key"]).not.toBe(intentKey);
  });

  it("derives the create-task key from request content deterministically", async () => {
    const { client, request } = createClient();
    request.mockResolvedValue({ id: 11 });
    const service = createPipelineService(client);

    const payload = { confirmed: true, prompt: "每周三 AI 周报" };
    await service.createTask(payload);
    await service.createTask({ ...payload });

    const first = request.mock.calls[0][1].headers["Idempotency-Key"];
    expect(first).toContain("task-create");
    expect(first).toBe(request.mock.calls[1][1].headers["Idempotency-Key"]);
  });
});
