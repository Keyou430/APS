import { describe, expect, it, vi } from "vitest";
import { createAuthStore } from "./authStore";
import type { AuthService, AuthSession } from "../../api/services/authService";

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

function createMemoryStorage() {
  const values = new Map<string, string>();
  return {
    getItem: (key: string) => values.get(key) ?? null,
    removeItem: (key: string) => values.delete(key),
    setItem: (key: string, value: string) => values.set(key, value),
  };
}

describe("auth store", () => {
  it("notifies subscribers when login changes the active organization", async () => {
    const service = { login: vi.fn(async () => session) } as unknown as AuthService;
    const store = createAuthStore({ service, storage: createMemoryStorage() });
    const listener = vi.fn();
    const unsubscribe = store.subscribe(listener);

    await store.login({ username: "keyou", password: "secret" });

    expect(listener).toHaveBeenCalledTimes(1);
    unsubscribe();
  });

  it("commits login token and profile atomically to session storage", async () => {
    const storage = createMemoryStorage();
    const service = {
      login: vi.fn(async () => session),
    } as unknown as AuthService;
    const store = createAuthStore({ service, storage });

    await store.login({ username: "keyou", password: "secret" });

    expect(store.getState().user?.username).toBe("keyou");
    expect(storage.getItem("agent-platform.auth")).toContain('"access_token":"access"');
  });

  it("does not replace the current session when organization switch fails", async () => {
    const storage = createMemoryStorage();
    const service = {
      login: vi.fn(async () => session),
      switchOrganization: vi.fn(async () => {
        throw new Error("switch failed");
      }),
    } as unknown as AuthService;
    const store = createAuthStore({ service, storage });
    await store.login({ username: "keyou", password: "secret" });

    await expect(store.switchOrganization({ organization_id: 11 })).rejects.toThrow(
      "switch failed",
    );

    expect(store.getState().organizationId).toBe(7);
    expect(storage.getItem("agent-platform.auth")).toContain('"organization_id":7');
  });

  it("invalidates and aborts the previous organization after a successful switch", async () => {
    const nextSession: AuthSession = {
      ...session,
      token: { ...session.token, organization_id: 11 },
      user: { ...session.user, organization_id: 11 },
    };
    const storage = createMemoryStorage();
    const onOrganizationChange = vi.fn();
    const service = {
      login: vi.fn(async () => session),
      switchOrganization: vi.fn(async () => nextSession),
    } as unknown as AuthService;
    const store = createAuthStore({ service, storage, onOrganizationChange });
    await store.login({ username: "keyou", password: "secret" });

    await store.switchOrganization({ organization_id: 11 });

    expect(store.getState().organizationId).toBe(11);
    expect(onOrganizationChange).toHaveBeenCalledWith(7, 11);
  });

  it("updates the stored token without replacing the current user", async () => {
    const storage = createMemoryStorage();
    const service = {
      login: vi.fn(async () => session),
    } as unknown as AuthService;
    const store = createAuthStore({ service, storage });
    await store.login({ username: "keyou", password: "secret" });

    store.commitToken({
      access_token: "fresh-access",
      refresh_token: "fresh-refresh",
      token_type: "bearer",
      expires_in: 3600,
      organization_id: 7,
    });

    expect(store.getState().user?.username).toBe("keyou");
    expect(store.getState().session?.token.access_token).toBe("fresh-access");
    expect(storage.getItem("agent-platform.auth")).toContain(
      '"access_token":"fresh-access"',
    );
  });
});
