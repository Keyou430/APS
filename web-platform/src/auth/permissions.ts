/**
 * Permission constants and helper functions for frontend permission-aware UI.
 *
 * IMPORTANT: These helpers only HIDE/DISABLE UI elements. They are NOT a
 * security boundary — the backend independently enforces all permissions.
 * Never trust client-side permission checks for authorization decisions.
 */

import type { UserInfo } from "../types/index";

// ── Permission code constants (mirrors backend authorization/permissions.py) ─

export const PERM = {
  // User management
  USER_VIEW: "user:view",
  USER_CREATE: "user:create",
  USER_UPDATE: "user:update",
  USER_DISABLE: "user:disable",
  USER_ASSIGN_ROLE: "user:assign_role",

  // Org
  ORG_VIEW: "org:view",
  ORG_UPDATE: "org:update",

  // Dept
  DEPT_VIEW: "dept:view",
  DEPT_UPDATE: "dept:update",

  // System
  SYSTEM_CONFIG: "system:config",

  // Audit
  AUDIT_VIEW: "audit:view",

  // Tasks
  TASK_VIEW: "task:view",
  TASK_CREATE: "task:create",
  TASK_UPDATE: "task:update",
  TASK_DELETE: "task:delete",

  // Calendar
  CALENDAR_VIEW: "calendar:view",
  CALENDAR_CREATE: "calendar:create",
  CALENDAR_UPDATE: "calendar:update",
  CALENDAR_DELETE: "calendar:delete",

  // Knowledge base
  KB_VIEW: "kb:view",
  KB_CREATE: "kb:create",
  KB_UPDATE: "kb:update",
  KB_DELETE: "kb:delete",
  KB_IMPORT: "kb:import",
  KB_CHAT: "kb:chat",
  KB_CHAT_SENSITIVE: "kb:chat_sensitive",

  // Search
  SEARCH_VIEW: "search:view",

  // Notices
  NOTICE_VIEW: "notice:view",
  NOTICE_CREATE: "notice:create",
  NOTICE_UPDATE: "notice:update",
  NOTICE_DELETE: "notice:delete",

  // Repair (报修)
  REPAIR_VIEW: "repair:view",
  REPAIR_CREATE: "repair:create",
  REPAIR_ASSIGN: "repair:assign",
  REPAIR_UPDATE: "repair:update",
  REPAIR_CLOSE: "repair:close",

  // Asset (资产)
  ASSET_VIEW: "asset:view",
  ASSET_CREATE: "asset:create",
  ASSET_UPDATE: "asset:update",
  ASSET_BORROW: "asset:borrow",

  // OA (OA 审批)
  OA_VIEW: "oa:view",
  OA_CREATE: "oa:create",
  OA_UPDATE: "oa:update",

  // HR (人事)
  HR_VIEW: "hr:view",
  HR_CREATE: "hr:create",
  HR_UPDATE: "hr:update",

  // Finance (财务)
  FINANCE_VIEW: "finance:view",
  FINANCE_CREATE: "finance:create",
  FINANCE_APPROVE: "finance:approve",

  // Subsystem (子系统管理)
  SUBSYSTEM_VIEW: "subsystem:view",
  SUBSYSTEM_MANAGE: "subsystem:manage",

  // Dashboard (仪表板)
  DASHBOARD_VIEW: "dashboard:view",

  // Enterprise records (企业记录)
  ENTERPRISE_RECORDS_VIEW: "enterprise:records:view",
} as const;

export type PermissionCode = (typeof PERM)[keyof typeof PERM];

// ── Role constants ──────────────────────────────────────────────────

export const ROLE = {
  SUPER_ADMIN: "super_admin",
  ORG_ADMIN: "org_admin",
  DEPT_LEADER: "dept_leader",
  DEPT_STAFF: "dept_staff",
  EXTERNAL: "external",
} as const;

export type RoleCode = (typeof ROLE)[keyof typeof ROLE];

// ── Permission check helpers ────────────────────────────────────────

/**
 * Check if the current user holds a specific permission.
 * Reads from the in-memory auth state (window.__auth).
 */
export function hasPermission(perm: PermissionCode): boolean {
  const auth = getAuthState();
  if (!auth || !auth.user) return false;

  // super_admin bypass (mirrors backend)
  const roles: readonly string[] = auth.user.roles ?? [];
  if (roles.includes(ROLE.SUPER_ADMIN)) return true;

  const permissions: readonly string[] = auth.user.permissions ?? [];
  return permissions.includes(perm);
}

/**
 * Check if the current user has ALL of the specified permissions.
 */
export function hasAllPermissions(...perms: PermissionCode[]): boolean {
  return perms.every((p) => hasPermission(p));
}

/**
 * Check if the current user has ANY of the specified permissions.
 */
export function hasAnyPermission(...perms: PermissionCode[]): boolean {
  return perms.some((p) => hasPermission(p));
}

/**
 * Check if the current user holds a specific role.
 */
export function hasRole(role: RoleCode): boolean {
  const auth = getAuthState();
  if (!auth || !auth.user) return false;
  const roles: readonly string[] = auth.user.roles ?? [];
  return roles.includes(role);
}

/**
 * Check if the user is authenticated (has a valid session).
 */
export function isAuthenticated(): boolean {
  const auth = getAuthState();
  return !!(auth && auth.isLoggedIn);
}

// ── Internal helpers ────────────────────────────────────────────────

interface AuthState {
  user: UserInfo | null;
  isLoggedIn: boolean;
}

function getAuthState(): AuthState | null {
  if (typeof window === "undefined") return null;
  const auth = (window as unknown as Record<string, unknown>).__auth as
    | AuthState
    | undefined;
  return auth ?? null;
}

/**
 * Build a set of permission flags from the current user for efficient
 * bulk checks in templates.
 */
export function getPermissionFlags(): Record<PermissionCode, boolean> {
  const flags: Record<string, boolean> = {};
  for (const key of Object.keys(PERM)) {
    const code = (PERM as Record<string, string>)[key];
    flags[code] = hasPermission(code as PermissionCode);
  }
  return flags as Record<PermissionCode, boolean>;
}
