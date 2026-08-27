import { describe, expect, it, vi } from "vitest";
import type { ApiClient } from "../client";
import { createHermesService } from "./hermesService";

function createClient() {
  const request = vi.fn();
  const client: ApiClient = {
    request: async (path, options) => request(path, options),
  };
  return { client, request };
}

describe("hermes service", () => {
  it("creates, reads, deactivates and checks profile health", async () => {
    const { client, request } = createClient();
    request.mockResolvedValue({});
    const service = createHermesService(client);

    await service.createProfile({ user_id: 9, provider: "feishu" });
    await service.getProfile(9);
    await service.deactivateProfile(9);
    await service.getProfileHealth(9);

    expect(request).toHaveBeenNthCalledWith(1, "/hermes/profiles", {
      method: "POST",
      body: { user_id: 9, provider: "feishu" },
    });
    expect(request).toHaveBeenNthCalledWith(2, "/hermes/profiles/9", undefined);
    expect(request).toHaveBeenNthCalledWith(3, "/hermes/profiles/9", {
      method: "DELETE",
    });
    expect(request).toHaveBeenNthCalledWith(
      4,
      "/hermes/profiles/9/health",
      undefined,
    );
  });
});
