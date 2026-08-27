import { describe, expect, it, vi } from "vitest";
import type { ApiClient } from "../client";
import { createInvitationsService } from "./invitationsService";

function createClient() {
  const request = vi.fn();
  const client: ApiClient = {
    request: async (path, options) => request(path, options),
  };
  return { client, request };
}

describe("invitations service", () => {
  it("lists and creates invitations through contract endpoints", async () => {
    const { client, request } = createClient();
    request.mockResolvedValue({});
    const service = createInvitationsService(client);

    await service.listInvitations({ status: "pending", page: 1 });
    await service.createInvitation({
      email: "guest@example.com",
      role: "guest",
      expires_at: "2026-08-13T00:00:00Z",
    });

    expect(request).toHaveBeenNthCalledWith(
      1,
      "/invitations?status=pending&page=1",
      undefined,
    );
    expect(request).toHaveBeenNthCalledWith(2, "/invitations", {
      method: "POST",
      body: {
        email: "guest@example.com",
        role: "guest",
        expires_at: "2026-08-13T00:00:00Z",
      },
    });
  });

  it("handles revoke, regenerate, accept and guest membership revoke", async () => {
    const { client, request } = createClient();
    request.mockResolvedValue({});
    const service = createInvitationsService(client);

    await service.revokeInvitation(3);
    await service.regenerateInvitation(3, { expires_at: "2026-08-14T00:00:00Z" });
    await service.acceptInvitation({ token: "fragment-token" });
    await service.revokeGuestMembership(8);

    expect(request).toHaveBeenNthCalledWith(1, "/invitations/3/revoke", {
      method: "POST",
    });
    expect(request).toHaveBeenNthCalledWith(2, "/invitations/3/regenerate", {
      method: "POST",
      body: { expires_at: "2026-08-14T00:00:00Z" },
    });
    expect(request).toHaveBeenNthCalledWith(3, "/invitations/accept", {
      method: "POST",
      body: { token: "fragment-token" },
    });
    expect(request).toHaveBeenNthCalledWith(
      4,
      "/invitations/guest-memberships/8/revoke",
      { method: "POST" },
    );
  });
});
