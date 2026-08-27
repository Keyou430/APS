import { describe, expect, it, vi } from "vitest";
import { createAuthService } from "./authService";
import type { ApiClient } from "../client";

describe("auth service", () => {
  it("logs in with token response, then loads profile with the new access token", async () => {
    const request = vi
      .fn()
      .mockResolvedValueOnce({
        access_token: "access",
        refresh_token: "refresh",
        token_type: "bearer",
        expires_in: 3600,
        organization_id: 7,
      })
      .mockResolvedValueOnce({
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
      });
    const service = createAuthService({
      request: request as unknown as ApiClient["request"],
      setPendingAccessToken: vi.fn(),
    });

    const session = await service.login({ username: "keyou", password: "secret" });

    expect(session.user.username).toBe("keyou");
    expect(request).toHaveBeenNthCalledWith(1, "/auth/login", {
      method: "POST",
      body: {
        username: "keyou",
        password: "secret",
      },
    });
    expect(request).toHaveBeenNthCalledWith(2, "/auth/me", {
      accessToken: "access",
    });
  });

  it("switches organization by loading profile with the target access token", async () => {
    const request = vi
      .fn()
      .mockResolvedValueOnce({
        access_token: "target-access",
        refresh_token: "target-refresh",
        token_type: "bearer",
        expires_in: 3600,
        organization_id: 11,
      })
      .mockResolvedValueOnce({
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
      });
    const service = createAuthService({
      request: request as unknown as ApiClient["request"],
    });

    const session = await service.switchOrganization({ organization_id: 11 });

    expect(session.token.organization_id).toBe(11);
    expect(session.user.organization_id).toBe(11);
    expect(request).toHaveBeenNthCalledWith(1, "/auth/switch-organization", {
      method: "POST",
      body: { organization_id: 11 },
    });
    expect(request).toHaveBeenNthCalledWith(2, "/auth/me", {
      accessToken: "target-access",
    });
  });

  it("logs out with the current refresh token", async () => {
    const request = vi.fn().mockResolvedValueOnce(undefined);
    const service = createAuthService({
      request: request as unknown as ApiClient["request"],
    });

    await service.logout({ refresh_token: "refresh" });

    expect(request).toHaveBeenCalledWith("/auth/logout", {
      method: "POST",
      body: { refresh_token: "refresh" },
      skipRefresh: true,
    });
  });

  it("refreshes with the current refresh token", async () => {
    const request = vi.fn().mockResolvedValueOnce({
      access_token: "fresh-access",
      refresh_token: "fresh-refresh",
      token_type: "bearer",
      expires_in: 3600,
      organization_id: 7,
    });
    const service = createAuthService({
      request: request as unknown as ApiClient["request"],
    });

    const token = await service.refresh({ refresh_token: "refresh" });

    expect(token.access_token).toBe("fresh-access");
    expect(request).toHaveBeenCalledWith("/auth/refresh", {
      method: "POST",
      body: { refresh_token: "refresh" },
      skipRefresh: true,
    });
  });

  it("loads the current user profile", async () => {
    const request = vi.fn().mockResolvedValueOnce({
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
    });
    const service = createAuthService({
      request: request as unknown as ApiClient["request"],
    });

    const user = await service.me();

    expect(user.username).toBe("keyou");
    expect(request).toHaveBeenCalledWith("/auth/me");
  });

  it("loads organization memberships", async () => {
    const request = vi.fn().mockResolvedValueOnce({
      items: [
        {
          organization_id: 7,
          organization_name: "Main Org",
          member_type: "internal",
          permissions: ["portal:read"],
        },
      ],
    });
    const service = createAuthService({
      request: request as unknown as ApiClient["request"],
    });

    const organizations = await service.organizations();

    expect(organizations.items).toHaveLength(1);
    expect(request).toHaveBeenCalledWith("/auth/organizations");
  });
});
