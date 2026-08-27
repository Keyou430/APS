import { describe, expect, it, vi } from "vitest";
import type { ApiClient } from "../client";
import { createOrganizationService } from "./organizationService";

function createClient() {
  const request = vi.fn();
  const client: ApiClient = {
    request: async (path, options) => request(path, options),
  };
  return { client, request };
}

describe("organization service", () => {
  it("requests the organization structure", async () => {
    const { client, request } = createClient();
    request.mockResolvedValue({ revision: 4, units: [] });

    await createOrganizationService(client).getStructure();

    expect(request).toHaveBeenCalledWith("/organization/structure", undefined);
  });

  it("creates and updates units with optimistic revision payloads", async () => {
    const { client, request } = createClient();
    request.mockResolvedValue({ revision: 5 });
    const service = createOrganizationService(client);

    await service.createUnit({
      name: "前端组",
      parent_id: null,
      expected_revision: 4,
    });
    await service.updateUnit(12, { name: "平台前端", expected_revision: 5 });

    expect(request).toHaveBeenNthCalledWith(1, "/organization/units", {
      method: "POST",
      body: { name: "前端组", parent_id: null, expected_revision: 4 },
    });
    expect(request).toHaveBeenNthCalledWith(2, "/organization/units/12", {
      method: "PATCH",
      body: { name: "平台前端", expected_revision: 5 },
    });
  });

  it("deletes positions and batch updates placements with revision bodies", async () => {
    const { client, request } = createClient();
    request.mockResolvedValue({});
    const service = createOrganizationService(client);

    await service.deletePosition(7, { expected_revision: 8 });
    await service.updatePlacementsBatch({
      expected_revision: 9,
      items: [{ membership_id: 11, unit_id: 3, position_id: 4 }],
    });

    expect(request).toHaveBeenNthCalledWith(1, "/organization/positions/7", {
      method: "DELETE",
      body: { expected_revision: 8 },
    });
    expect(request).toHaveBeenNthCalledWith(
      2,
      "/organization/placements/batch",
      {
        method: "POST",
        body: {
          expected_revision: 9,
          items: [{ membership_id: 11, unit_id: 3, position_id: 4 }],
        },
      },
    );
  });
});
