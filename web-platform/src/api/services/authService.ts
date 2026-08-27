import type { ApiClient } from "../client";

export type LoginRequest = {
  password: string;
  username: string;
};

export type LogoutRequest = {
  refresh_token: string;
};

export type SwitchOrganizationRequest = {
  organization_id: number;
};

export type RefreshRequest = LogoutRequest;

export type TokenResponse = {
  access_token: string;
  expires_in: number;
  organization_id: number;
  refresh_token: string;
  token_type: "bearer";
};

export type UserResponse = {
  created_at: string;
  email: string;
  id: number;
  is_active: boolean;
  member_type: "internal" | "guest";
  membership_expires_at: string | null;
  membership_id: number | null;
  organization_id: number;
  permissions: string[];
  role: string;
  username: string;
};

export type OrganizationMembership = {
  member_type: "internal" | "guest";
  organization_id: number;
  organization_name: string;
  permissions: string[];
};

export type OrganizationMembershipListResponse = {
  items: OrganizationMembership[];
};

export type AuthSession = {
  token: TokenResponse;
  user: UserResponse;
};

export type AuthService = {
  login(request: LoginRequest): Promise<AuthSession>;
  logout(request: LogoutRequest): Promise<void>;
  me(): Promise<UserResponse>;
  organizations(): Promise<OrganizationMembershipListResponse>;
  refresh(request: RefreshRequest): Promise<TokenResponse>;
  switchOrganization(request: SwitchOrganizationRequest): Promise<AuthSession>;
};

type AuthServiceOptions = ApiClient & {
  setPendingAccessToken?: (token: string) => void;
};

export function createAuthService(client: AuthServiceOptions): AuthService {
  return {
    async login(request) {
      const token = await client.request<TokenResponse>("/auth/login", {
        method: "POST",
        body: request,
      });
      client.setPendingAccessToken?.(token.access_token);
      const user = await client.request<UserResponse>("/auth/me", {
        accessToken: token.access_token,
      });
      return { token, user };
    },
    async logout(request) {
      await client.request<void>("/auth/logout", {
        method: "POST",
        body: request,
        skipRefresh: true,
      });
    },
    me() {
      return client.request<UserResponse>("/auth/me");
    },
    organizations() {
      return client.request<OrganizationMembershipListResponse>(
        "/auth/organizations",
      );
    },
    refresh(request) {
      return client.request<TokenResponse>("/auth/refresh", {
        method: "POST",
        body: request,
        skipRefresh: true,
      });
    },
    async switchOrganization(request) {
      const token = await client.request<TokenResponse>(
        "/auth/switch-organization",
        {
          method: "POST",
          body: request,
        },
      );
      client.setPendingAccessToken?.(token.access_token);
      const user = await client.request<UserResponse>("/auth/me", {
        accessToken: token.access_token,
      });
      return { token, user };
    },
  };
}
