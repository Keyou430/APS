/**
 * Minimal auth state management — vanilla JS, no framework dependency.
 *
 * Exposes ``window.__auth`` for the rest of the app to read current
 * auth state without importing ES modules.  The api.ts module is the
 * single writer of auth state; this module is the single reader.
 */

import type { UserInfo } from "../types/index";
import {
  login as apiLogin,
  logout as apiLogout,
  refresh as apiRefresh,
  fetchMe as apiFetchMe,
  changePassword as apiChangePassword,
  isAuthenticated,
  getAccessToken,
  getCurrentUser,
  syncAuthState,
} from "./api";

export interface AuthState {
  readonly user: UserInfo | null;
  readonly isLoggedIn: boolean;
  readonly mustChangePassword: boolean;

  login(username: string, password: string): Promise<UserInfo>;
  logout(): Promise<void>;
  refresh(): Promise<void>;
  fetchMe(): Promise<UserInfo>;
  changePassword(current: string, newPw: string): Promise<UserInfo>;
  getToken(): string | null;
  /** Sync external auth state into the module — keeps inline-script state consistent. */
  _syncState(token: string | null, user: UserInfo | null): void;
}

function createAuthState(): AuthState {
  return {
    get user(): UserInfo | null {
      return getCurrentUser();
    },
    get isLoggedIn(): boolean {
      return isAuthenticated();
    },
    get mustChangePassword(): boolean {
      return getCurrentUser()?.must_change_password ?? false;
    },

    async login(username: string, password: string): Promise<UserInfo> {
      const resp = await apiLogin(username, password);
      return resp.user;
    },

    async logout(): Promise<void> {
      await apiLogout();
    },

    async refresh(): Promise<void> {
      await apiRefresh();
    },

    async fetchMe(): Promise<UserInfo> {
      return apiFetchMe();
    },

    async changePassword(current: string, newPw: string): Promise<UserInfo> {
      return apiChangePassword(current, newPw);
    },

    getToken(): string | null {
      return getAccessToken();
    },

    _syncState(token: string | null, user: UserInfo | null): void {
      syncAuthState(token, user);
    },
  };
}

// Singleton
const _auth = createAuthState();

// Expose globally so vanilla JS in index.html can access it
if (typeof window !== "undefined") {
  (window as unknown as Record<string, unknown>).__auth = _auth;
}

export default _auth;
