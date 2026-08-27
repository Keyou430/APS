import { describe, expect, it, vi } from "vitest";
import { createContractAuthBridge } from "./contractAuthBridge";
import type { AuthRuntime } from "../features/auth/authRuntime";
import type { AuthSession } from "../api/services/authService";

const session: AuthSession = {
  token: {
    access_token: "access",
    refresh_token: "refresh",
    token_type: "bearer",
    expires_in: 3600,
    organization_id: 7,
  },
  user: {
    id: 10,
    username: "keyou",
    email: "keyou@example.com",
    role: "member",
    member_type: "internal",
    permissions: ["portal:read"],
    membership_id: 99,
    membership_expires_at: null,
    organization_id: 7,
    is_active: true,
    created_at: "2026-08-12T00:00:00Z",
  },
};

describe("contract auth bridge", () => {
  it("adapts contract login sessions to the legacy auth shape", async () => {
    const runtime = {
      store: {
        login: vi.fn(async () => session),
      },
    } as unknown as AuthRuntime;
    const bridge = createContractAuthBridge(runtime);

    const result = await bridge.login("keyou", "secret");

    expect(runtime.store.login).toHaveBeenCalledWith({
      username: "keyou",
      password: "secret",
    });
    expect(result.access_token).toBe("access");
    expect(result.must_change_password).toBe(false);
    expect(result.user).toEqual({
      id: 10,
      username: "keyou",
      display_name: "keyou",
      email: "keyou@example.com",
      default_org_id: "7",
      default_dept_id: null,
      roles: ["member"],
      permissions: ["portal:read"],
      must_change_password: false,
    });
  });

  it("exposes refresh, fetchMe and logout through the runtime store", async () => {
    const runtime = {
      store: {
        commitToken: vi.fn(),
        getState: vi.fn(() => ({ session })),
        logout: vi.fn(async () => undefined),
      },
      client: {
        request: vi
          .fn()
          .mockResolvedValueOnce({
            access_token: "fresh-access",
            refresh_token: "fresh-refresh",
            token_type: "bearer",
            expires_in: 3600,
            organization_id: 7,
          })
          .mockResolvedValueOnce(session.user),
      },
    } as unknown as AuthRuntime;
    const bridge = createContractAuthBridge(runtime);

    const refresh = await bridge.refresh();
    const user = await bridge.fetchMe();
    await bridge.logout();

    expect(refresh.access_token).toBe("fresh-access");
    expect(user.display_name).toBe("keyou");
    expect(runtime.client.request).toHaveBeenNthCalledWith(1, "/auth/refresh", {
      method: "POST",
      body: { refresh_token: "refresh" },
      skipRefresh: true,
    });
    expect(runtime.client.request).toHaveBeenNthCalledWith(2, "/auth/me");
    expect(runtime.store.commitToken).toHaveBeenCalledWith({
      access_token: "fresh-access",
      refresh_token: "fresh-refresh",
      token_type: "bearer",
      expires_in: 3600,
      organization_id: 7,
    });
    expect(runtime.store.logout).toHaveBeenCalledOnce();
  });
});
