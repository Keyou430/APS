import { describe, expect, it, vi } from "vitest";
import { createAuthRuntime } from "./authRuntime";

function response(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function createStorage() {
  const values = new Map<string, string>();
  return {
    getItem: (key: string) => values.get(key) ?? null,
    removeItem: (key: string) => values.delete(key),
    setItem: (key: string, value: string) => values.set(key, value),
  };
}

describe("auth runtime", () => {
  it("wires login through api client, auth service and auth store", async () => {
    const fetchFn = vi
      .fn()
      .mockResolvedValueOnce(
        response({
          access_token: "access",
          refresh_token: "refresh",
          token_type: "bearer",
          expires_in: 3600,
          organization_id: 7,
        }),
      )
      .mockResolvedValueOnce(
        response({
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
        }),
      );
    const runtime = createAuthRuntime({
      fetchFn,
      storage: createStorage(),
    });

    await runtime.store.login({ username: "keyou", password: "secret" });

    expect(runtime.store.getState().organizationId).toBe(7);
    expect(fetchFn).toHaveBeenNthCalledWith(
      1,
      "/api/auth/login",
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetchFn).toHaveBeenNthCalledWith(
      2,
      "/api/auth/me",
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: "Bearer access" }),
      }),
    );
  });

  it("invalidates old organization resources on successful switch", async () => {
    const onOrganizationChange = vi.fn();
    const fetchFn = vi
      .fn()
      .mockResolvedValueOnce(
        response({
          access_token: "access",
          refresh_token: "refresh",
          token_type: "bearer",
          expires_in: 3600,
          organization_id: 7,
        }),
      )
      .mockResolvedValueOnce(
        response({
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
        }),
      )
      .mockResolvedValueOnce(
        response({
          access_token: "target-access",
          refresh_token: "target-refresh",
          token_type: "bearer",
          expires_in: 3600,
          organization_id: 11,
        }),
      )
      .mockResolvedValueOnce(
        response({
          id: 10,
          username: "keyou",
          email: "keyou@example.com",
          role: "member",
          member_type: "internal",
          permissions: ["portal:read"],
          membership_id: 101,
          membership_expires_at: null,
          organization_id: 11,
          is_active: true,
          created_at: "2026-08-12T00:00:00Z",
        }),
      );
    const runtime = createAuthRuntime({
      fetchFn,
      storage: createStorage(),
      onOrganizationChange,
    });

    await runtime.store.login({ username: "keyou", password: "secret" });
    runtime.cache.set(7, ["portal"], { stale: true });
    const signal = runtime.abortRegistry.createSignal(7, "portal");
    await runtime.store.switchOrganization({ organization_id: 11 });

    expect(runtime.cache.get(7, ["portal"])).toBeUndefined();
    expect(signal.aborted).toBe(true);
    expect(onOrganizationChange).toHaveBeenCalledWith(7, 11);
  });

  it("refreshes the stored token and replays a protected request once", async () => {
    const fetchFn = vi
      .fn()
      .mockResolvedValueOnce(
        response({
          access_token: "access",
          refresh_token: "refresh",
          token_type: "bearer",
          expires_in: 3600,
          organization_id: 7,
        }),
      )
      .mockResolvedValueOnce(
        response({
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
        }),
      )
      .mockResolvedValueOnce(response({ error: { message: "expired" } }, 401))
      .mockResolvedValueOnce(
        response({
          access_token: "fresh-access",
          refresh_token: "fresh-refresh",
          token_type: "bearer",
          expires_in: 3600,
          organization_id: 7,
        }),
      )
      .mockResolvedValueOnce(response({ ok: true }));
    const runtime = createAuthRuntime({
      fetchFn,
      storage: createStorage(),
    });

    await runtime.store.login({ username: "keyou", password: "secret" });
    const result = await runtime.client.request<{ ok: boolean }>("/portal/bootstrap");

    expect(result.ok).toBe(true);
    expect(runtime.store.getState().session?.token.access_token).toBe(
      "fresh-access",
    );
    expect(fetchFn).toHaveBeenNthCalledWith(
      4,
      "/api/auth/refresh",
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetchFn).toHaveBeenNthCalledWith(
      5,
      "/api/portal/bootstrap",
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: "Bearer fresh-access" }),
      }),
    );
  });
});
