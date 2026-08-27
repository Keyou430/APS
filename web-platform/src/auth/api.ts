/**
 * Auth API module — zero-dependency fetch wrappers for auth endpoints.
 *
 * All functions use ``credentials: "include"`` so HttpOnly refresh cookies
 * are sent automatically.  The access token is kept in module-level memory
 * (never localStorage) and managed by the AuthContext.
 */

const API_BASE = "/api/auth";

// ── In-memory token storage ────────────────────────────────────────

let _accessToken: string | null = null;
let _currentUser: import("../types/index.ts").UserInfo | null = null;

export function getAccessToken(): string | null {
  return _accessToken;
}

export function setAccessToken(token: string | null): void {
  _accessToken = token;
}

export function getCurrentUser(): import("../types/index.ts").UserInfo | null {
  return _currentUser;
}

export function setCurrentUser(user: import("../types/index.ts").UserInfo | null): void {
  _currentUser = user;
}

/**
 * Sync external auth state into this module — used by the inline script in
 * index.html to keep both auth stores consistent.
 */
export function syncAuthState(token: string | null, user: import("../types/index.ts").UserInfo | null): void {
  _accessToken = token;
  _currentUser = user;
}

export function isAuthenticated(): boolean {
  return _accessToken !== null && _currentUser !== null;
}

// ── API calls ──────────────────────────────────────────────────────

export async function login(
  username: string,
  password: string,
): Promise<import("../types/index.ts").LoginResponse> {
  const resp = await fetch(`${API_BASE}/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ username, password }),
  });

  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: "登录失败" }));
    throw new Error(err.detail || "登录失败");
  }

  const data: import("../types/index.ts").LoginResponse = await resp.json();
  _accessToken = data.access_token;
  _currentUser = data.user;
  return data;
}

export async function register(
  username: string,
  password: string,
  displayName?: string,
  email?: string,
): Promise<import("../types/index.ts").LoginResponse> {
  void username;
  void password;
  void displayName;
  void email;
  throw new Error("注册接口尚未纳入前端契约");
}

export async function refresh(): Promise<void> {
  const resp = await fetch(`${API_BASE}/refresh`, {
    method: "POST",
    credentials: "include",
  });

  if (!resp.ok) {
    _accessToken = null;
    _currentUser = null;
    const err = await resp.json().catch(() => ({ detail: "会话已过期" }));
    throw new Error(err.detail || "会话已过期");
  }

  const data: import("../types/index.ts").RefreshResponse = await resp.json();
  _accessToken = data.access_token;
}

export async function logout(): Promise<void> {
  try {
    await fetch(`${API_BASE}/logout`, {
      method: "POST",
      credentials: "include",
    });
  } finally {
    _accessToken = null;
    _currentUser = null;
  }
}

export async function fetchMe(): Promise<import("../types/index.ts").UserInfo> {
  if (!_accessToken) {
    throw new Error("未登录");
  }

  const resp = await fetch(`${API_BASE}/me`, {
    headers: { Authorization: `Bearer ${_accessToken}` },
  });

  if (!resp.ok) {
    if (resp.status === 401) {
      // Try to refresh once
      try {
        await refresh();
        // Retry with new token
        const retryResp = await fetch(`${API_BASE}/me`, {
          headers: { Authorization: `Bearer ${_accessToken}` },
        });
        if (retryResp.ok) {
          _currentUser = await retryResp.json();
          return _currentUser!;
        }
      } catch {
        // refresh failed, fall through to error
      }
    }
    _accessToken = null;
    _currentUser = null;
    throw new Error("认证已失效");
  }

  _currentUser = await resp.json();
  return _currentUser!;
}

export async function changePassword(
  currentPassword: string,
  newPassword: string,
): Promise<import("../types/index.ts").UserInfo> {
  void currentPassword;
  void newPassword;
  throw new Error("修改密码接口尚未纳入前端契约");
}

/**
 * Wrap the global apiJson() with automatic auth header and 401 refresh.
 * Call this once during app initialization to patch the global API layer.
 */
export function installAuthInterceptor(
  apiJsonFn: (path: string, options?: Record<string, unknown>) => Promise<unknown>,
): (path: string, options?: Record<string, unknown>) => Promise<unknown> {
  let _refreshing = false;
  let _refreshPromise: Promise<void> | null = null;

  return async function authApiJson(
    path: string,
    options: Record<string, unknown> = {},
  ): Promise<unknown> {
    // Attach access token
    if (_accessToken) {
      options.headers = {
        ...(options.headers as Record<string, string> || {}),
        Authorization: `Bearer ${_accessToken}`,
      };
    }

    let resp = await apiJsonFn(path, options);

    // If 401, try refresh once
    if (
      resp &&
      typeof resp === "object" &&
      "status" in resp &&
      (resp as Record<string, unknown>).status === 401
    ) {
      if (!_refreshing) {
        _refreshing = true;
        _refreshPromise = refresh().finally(() => {
          _refreshing = false;
          _refreshPromise = null;
        });
      }

      try {
        await _refreshPromise;
        // Retry with new token
        if (_accessToken) {
          options.headers = {
            ...(options.headers as Record<string, string> || {}),
            Authorization: `Bearer ${_accessToken}`,
          };
        }
        resp = await apiJsonFn(path, options);
      } catch {
        // refresh failed — caller handles
      }
    }

    return resp;
  };
}
