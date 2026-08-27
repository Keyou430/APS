import { describe, expect, it, vi } from "vitest";
import { ApiError, createApiClient } from "./client";

function jsonResponse(body: unknown, init: ResponseInit = {}) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json" },
    ...init,
  });
}

describe("api client", () => {
  it("uses /api as the single base URL and returns direct DTO responses", async () => {
    const fetchFn = vi.fn(async () => jsonResponse({ id: 1, username: "keyou" }));
    const client = createApiClient({
      fetchFn,
      getAccessToken: () => "access-token",
    });

    const result = await client.request("/auth/me");

    expect(result).toEqual({ id: 1, username: "keyou" });
    expect(fetchFn).toHaveBeenCalledWith(
      "/api/auth/me",
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: "Bearer access-token",
        }),
      }),
    );
  });

  it("returns undefined for 204 responses", async () => {
    const fetchFn = vi.fn(async () => new Response(null, { status: 204 }));
    const client = createApiClient({ fetchFn });

    await expect(client.request("/auth/logout", { method: "POST" })).resolves.toBeUndefined();
  });

  it("single-flights concurrent refresh and replays each request once", async () => {
    let token = "expired-token";
    const refresh = vi.fn(async () => {
      token = "fresh-token";
    });
    const fetchFn = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ error: { message: "expired" } }, { status: 401 }))
      .mockResolvedValueOnce(jsonResponse({ error: { message: "expired" } }, { status: 401 }))
      .mockResolvedValueOnce(jsonResponse({ ok: "first" }))
      .mockResolvedValueOnce(jsonResponse({ ok: "second" }));
    const client = createApiClient({
      fetchFn,
      getAccessToken: () => token,
      refresh,
    });

    await expect(Promise.all([client.request("/users"), client.request("/organization/structure")]))
      .resolves.toEqual([{ ok: "first" }, { ok: "second" }]);

    expect(refresh).toHaveBeenCalledTimes(1);
    expect(fetchFn.mock.calls.map(([, init]) => init?.headers)).toEqual([
      expect.objectContaining({ Authorization: "Bearer expired-token" }),
      expect.objectContaining({ Authorization: "Bearer expired-token" }),
      expect.objectContaining({ Authorization: "Bearer fresh-token" }),
      expect.objectContaining({ Authorization: "Bearer fresh-token" }),
    ]);
  });

  it("does not refresh auth endpoints", async () => {
    const refresh = vi.fn();
    const client = createApiClient({
      fetchFn: vi.fn(async () => jsonResponse({ error: { message: "bad login" } }, { status: 401 })),
      refresh,
    });

    await expect(client.request("/auth/login", { method: "POST" })).rejects.toBeInstanceOf(ApiError);
    expect(refresh).not.toHaveBeenCalled();
  });

  it("preserves FastAPI detail messages for authentication failures", async () => {
    const client = createApiClient({
      fetchFn: vi.fn(async () => jsonResponse({ detail: "用户名或密码错误" }, { status: 401 })),
    });

    await expect(client.request("/auth/login", { method: "POST" })).rejects.toMatchObject({
      status: 401,
      message: "用户名或密码错误",
    });
  });

  it("fails closed before a real request outside the mock adapter boundary", async () => {
    const fetchFn = vi.fn();
    const client = createApiClient({ fetchFn, mockMode: true });

    await expect(client.request("/knowledge")).rejects.toThrow(/Unexpected real request in mock mode/);
    expect(fetchFn).not.toHaveBeenCalled();
  });

  it("reports upload progress through the authenticated client", async () => {
    const progress = vi.fn();
    const xhr = {
      getResponseHeader: () => "application/json",
      open: vi.fn(),
      responseText: JSON.stringify({ id: 9 }),
      send: vi.fn(function (this: { onload?: () => void; upload: { onprogress?: (event: ProgressEvent) => void } }) {
        this.upload.onprogress?.({ lengthComputable: true, loaded: 5, total: 10 } as ProgressEvent);
        this.onload?.();
      }),
      setRequestHeader: vi.fn(),
      status: 200,
      statusText: "OK",
      upload: {},
    };
    const client = createApiClient({
      getAccessToken: () => "access-token",
      xhrFactory: () => xhr as unknown as XMLHttpRequest,
    });

    await expect(client.upload?.("/knowledge/upload", new FormData(), { onProgress: progress })).resolves.toEqual({ id: 9 });
    expect(progress).toHaveBeenCalledWith(5, 10);
  });
});
