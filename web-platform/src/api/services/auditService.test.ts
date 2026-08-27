import { describe, expect, it, vi } from "vitest";
import type { ApiClient } from "../client";
import { createAuditService } from "./auditService";

function createClient() {
  const request = vi.fn();
  const client: ApiClient = {
    request: async (path, options) => request(path, options),
  };
  return { client, request };
}

describe("audit service", () => {
  it("lists audit events with query parameters", async () => {
    const { client, request } = createClient();
    request.mockResolvedValue({});

    await createAuditService(client).listAuditEvents({
      actor_id: 7,
      action: "login",
      page: 1,
    });

    expect(request).toHaveBeenCalledWith(
      "/audit-events?actor_id=7&action=login&page=1",
      undefined,
    );
  });
});
