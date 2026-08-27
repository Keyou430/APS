import type {
  AuthSession,
  TokenResponse,
  UserResponse,
} from "../api/services/authService";
import type { AuthRuntime } from "../features/auth/authRuntime";
import type { LoginResponse, RefreshResponse, UserInfo } from "../types/index";

export type ContractAuthBridge = {
  fetchMe(): Promise<UserInfo>;
  getToken(): string | null;
  login(username: string, password: string): Promise<LoginResponse>;
  logout(): Promise<void>;
  refresh(): Promise<RefreshResponse>;
};

function toLegacyUser(user: UserResponse): UserInfo {
  return {
    id: user.id,
    username: user.username,
    display_name: user.username,
    email: user.email || null,
    default_org_id: String(user.organization_id),
    default_dept_id: null,
    roles: [user.role],
    permissions: user.permissions,
    must_change_password: false,
  };
}

function toLegacyLogin(session: AuthSession): LoginResponse {
  return {
    access_token: session.token.access_token,
    token_type: session.token.token_type,
    expires_in: session.token.expires_in,
    user: toLegacyUser(session.user),
    must_change_password: false,
  };
}

function toLegacyRefresh(token: TokenResponse): RefreshResponse {
  return {
    access_token: token.access_token,
    token_type: token.token_type,
    expires_in: token.expires_in,
  };
}

export function createContractAuthBridge(
  runtime: AuthRuntime,
): ContractAuthBridge {
  return {
    async fetchMe() {
      const user = await runtime.client.request<UserResponse>("/auth/me");
      return toLegacyUser(user);
    },
    getToken() {
      return runtime.store.getState().session?.token.access_token ?? null;
    },
    async login(username, password) {
      const session = await runtime.store.login({ username, password });
      return toLegacyLogin(session);
    },
    logout() {
      return runtime.store.logout();
    },
    async refresh() {
      const refreshToken =
        runtime.store.getState().session?.token.refresh_token ?? "";
      const token = await runtime.client.request<TokenResponse>("/auth/refresh", {
        method: "POST",
        body: { refresh_token: refreshToken },
        skipRefresh: true,
      });
      runtime.store.commitToken(token);
      return toLegacyRefresh(token);
    },
  };
}
