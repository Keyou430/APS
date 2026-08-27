export interface EmbedUrls {
  feishu: string | null;
  dingtalk: string | null;
}

export interface PortalCatalogItem {
  code: string;
  title: string;
  description: string;
  status: string | null;
}

export interface PortalCatalog {
  items: PortalCatalogItem[];
  total: number;
}

export interface PortalBootstrapResponse {
  embed_urls: EmbedUrls;
  capabilities: PortalCatalog;
  skills: PortalCatalog;
}

// 鈹€鈹€ Auth types (Phase 2) 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

export interface LoginRequest {
  username: string;
  password: string;
}

export interface UserInfo {
  id: number;
  username: string;
  display_name: string;
  email: string | null;
  default_org_id: string | null;
  default_dept_id: string | null;
  roles: string[];
  permissions: string[];
  must_change_password: boolean;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: UserInfo;
  must_change_password: boolean;
}

export interface RefreshResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
}

export interface ChangePasswordRequest {
  current_password: string;
  new_password: string;
}

export interface RegisterRequest {
  username: string;
  password: string;
  display_name?: string;
  email?: string;
}

// 鈹€鈹€ Permission types (Phase 3) 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

/** Permission codes matching backend authorization/permissions.py (53 total) */
export type PermissionCode =
  | "user:view" | "user:create" | "user:update" | "user:disable" | "user:assign_role"
  | "org:view" | "org:update"
  | "dept:view" | "dept:update"
  | "system:config"
  | "audit:view"
  | "task:view" | "task:create" | "task:update" | "task:delete"
  | "calendar:view" | "calendar:create" | "calendar:update" | "calendar:delete"
  | "kb:view" | "kb:create" | "kb:update" | "kb:delete" | "kb:import" | "kb:chat" | "kb:chat_sensitive"
  | "search:view"
  | "notice:view" | "notice:create" | "notice:update" | "notice:delete"
  | "repair:view" | "repair:create" | "repair:assign" | "repair:update" | "repair:close"
  | "asset:view" | "asset:create" | "asset:update" | "asset:borrow"
  | "oa:view" | "oa:create" | "oa:update"
  | "hr:view" | "hr:create" | "hr:update"
  | "finance:view" | "finance:create" | "finance:approve"
  | "subsystem:view" | "subsystem:manage"
  | "dashboard:view"
  | "enterprise:records:view";

/** Role codes matching backend authorization/permissions.py */
export type RoleCode =
  | "super_admin"
  | "org_admin"
  | "dept_leader"
  | "dept_staff"
  | "external";

// 鈹€鈹€ Phase 6: Admin / Audit types 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

export interface AuditLogItem {
  id: number;
  request_id: string;
  user_id: number | null;
  org_id: string | null;
  department_id: string | null;
  action: string;
  resource_type: string | null;
  resource_id: string | null;
  decision: string;
  reason: string | null;
  ip_address: string | null;
  user_agent: string | null;
  detail_json: string | null;
  created_at: string | null;
}

export interface AuditLogListResponse {
  items: AuditLogItem[];
  total: number;
}

export interface AIQueryLogItem {
  id: number;
  request_id: string;
  user_id: number;
  org_id: string | null;
  department_id: string | null;
  query_hash: string;
  query_snippet: string | null;
  risk_label: string | null;
  policy_version: string;
  decision: string;
  blocked_reason: string | null;
  accessible_resource_count: number;
  response_time_ms: number | null;
  created_at: string | null;
}

export interface AIQueryLogListResponse {
  items: AIQueryLogItem[];
  total: number;
}

export interface AdminSessionItem {
  id: string;
  user_id: number;
  username: string | null;
  display_name: string | null;
  user_agent: string | null;
  ip_address: string | null;
  expires_at: string | null;
  revoked_at: string | null;
  created_at: string | null;
  is_active: boolean;
}

export interface AdminSessionListResponse {
  items: AdminSessionItem[];
  total: number;
}

export interface AnomalyStats {
  total_users: number;
  active_users: number;
  disabled_users: number;
  total_sessions: number;
  active_sessions: number;
  recent_failed_logins_24h: number;
  recent_403_24h: number;
  recent_ai_blocks_24h: number;
  recent_injections_24h: number;
}
