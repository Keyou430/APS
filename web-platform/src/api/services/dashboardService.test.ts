import { describe, expect, it, vi } from "vitest";
import type { ApiClient } from "../client";
import { createDashboardService } from "./dashboardService";

function createClient() {
  const request = vi.fn();
  const client: ApiClient = {
    request: async (path, options) => request(path, options),
  };
  return { client, request };
}

describe("dashboard service", () => {
  it("requests dashboard data from the contract endpoint", async () => {
    const { client, request } = createClient();
    request.mockResolvedValue({ metrics: [] });
    const service = createDashboardService(client);

    const result = await service.getDashboard();

    expect(result).toEqual({ metrics: [] });
    expect(request).toHaveBeenCalledWith("/dashboard", undefined);
  });

  it("saves layout with expected revision", async () => {
    const { client, request } = createClient();
    request.mockResolvedValue({ revision: 3 });
    const service = createDashboardService(client);
    const layouts = {
      lg: [{ i: "todo", x: 0, y: 0, w: 4, h: 2 }],
      md: [],
      sm: [],
    };

    const result = await service.saveLayout({
      expectedRevision: 2,
      layouts,
    });

    expect(result).toEqual({ revision: 3 });
    expect(request).toHaveBeenCalledWith("/dashboard/layout", {
      method: "PUT",
      body: {
        expectedRevision: 2,
        layouts,
      },
    });
  });

  it("resets layout through the contract endpoint", async () => {
    const { client, request } = createClient();
    request.mockResolvedValue({ revision: 1 });
    const service = createDashboardService(client);

    await service.resetLayout();

    expect(request).toHaveBeenCalledWith("/dashboard/layout/reset", {
      method: "POST",
    });
  });

  it("manages cockpit smart decisions through dashboard contracts", async () => {
    const { client, request } = createClient();
    request
      .mockResolvedValueOnce({ items: [{ id: "decision-1" }] })
      .mockResolvedValueOnce({ id: "decision-1", status: "approved" })
      .mockResolvedValueOnce({ id: "decision-1", status: "regenerating" });
    const service = createDashboardService(client);

    await service.listDecisions({ limit: 5, status: "pending" });
    await service.approveDecision("decision-1", {
      comment: "已核对来源，可以归档",
    });
    await service.rejectDecision("decision-1", {
      reason: "数据口径需要按华东区单独分析",
      reason_type: "regenerate",
    });

    expect(request).toHaveBeenNthCalledWith(
      1,
      "/dashboard/decisions?limit=5&status=pending",
      undefined,
    );
    expect(request).toHaveBeenNthCalledWith(
      2,
      "/dashboard/decisions/decision-1/approve",
      {
        method: "POST",
        headers: { "Idempotency-Key": expect.any(String) },
        body: { comment: "已核对来源，可以归档" },
      },
    );
    expect(request).toHaveBeenNthCalledWith(
      3,
      "/dashboard/decisions/decision-1/reject",
      {
        method: "POST",
        headers: { "Idempotency-Key": expect.any(String) },
        body: {
          reason: "数据口径需要按华东区单独分析",
          reason_type: "regenerate",
        },
      },
    );
  });
});
