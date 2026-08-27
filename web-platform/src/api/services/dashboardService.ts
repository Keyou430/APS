import type { ApiClient } from "../client";
import { appendQuery, type QueryValue } from "./serviceUtils";

type DashboardGridItem = {
  h: number;
  i: string;
  maxH?: number | null;
  maxW?: number | null;
  minH?: number | null;
  minW?: number | null;
  static?: boolean;
  w: number;
  x: number;
  y: number;
};

export type DashboardLayouts = {
  lg: DashboardGridItem[];
  md: DashboardGridItem[];
  sm: DashboardGridItem[];
  xs?: DashboardGridItem[] | null;
  xxs?: DashboardGridItem[] | null;
};

export type DashboardDataResponse = {
  calendarEvents?: Record<string, unknown>[];
  metrics?: Record<string, unknown>[];
  notifications?: Record<string, unknown>[];
  pipelines?: Record<string, unknown>[];
  quickActions?: Record<string, unknown>[];
  recentVisits?: Record<string, unknown>[];
  todos?: Record<string, unknown>[];
};

export type DashboardLayoutResponse = {
  id: string;
  layouts: DashboardLayouts;
  revision: number;
  updatedAt: string;
  userId: string;
  widgets: Record<string, unknown>[];
};

export type DashboardLayoutUpdate = {
  expectedRevision: number;
  layouts: DashboardLayouts;
};

export type DashboardDecisionStatus =
  | "pending"
  | "approved"
  | "rejected"
  | "changes_requested"
  | "regenerating";

export type DashboardDecision = {
  action?: string;
  approvedAt?: string | null;
  confidence?: number | null;
  generatedAt?: string | null;
  id: number | string;
  rejectedAt?: string | null;
  rejectionReason?: string | null;
  sourceTask?: string | null;
  status: DashboardDecisionStatus;
  summary?: string;
  title: string;
};

export type DashboardDecisionListQuery = Record<string, QueryValue>;
export type DashboardDecisionListResponse = {
  items?: DashboardDecision[];
};
export type DashboardDecisionRejectPayload = {
  reason: string;
  reason_type: "no_need" | "other" | "regenerate";
};

export type DashboardService = {
  approveDecision(id: number | string): Promise<DashboardDecision>;
  getDashboard(): Promise<DashboardDataResponse>;
  getLayout(): Promise<DashboardLayoutResponse>;
  listDecisions(
    query?: DashboardDecisionListQuery,
  ): Promise<DashboardDecisionListResponse>;
  rejectDecision(
    id: number | string,
    payload: DashboardDecisionRejectPayload,
  ): Promise<DashboardDecision>;
  resetLayout(): Promise<DashboardLayoutResponse>;
  saveLayout(request: DashboardLayoutUpdate): Promise<DashboardLayoutResponse>;
};

const operationKeys = new Map<string, string>();

function idempotencyKey(operation: string, id: number | string): string {
  const cacheKey = `${operation}:${String(id)}`;
  const existing = operationKeys.get(cacheKey);
  if (existing) return existing;
  const key = globalThis.crypto?.randomUUID?.() ?? `${operation}-${String(id)}-${Date.now()}`;
  operationKeys.set(cacheKey, key);
  return key;
}

export function createDashboardService(client: ApiClient): DashboardService {
  return {
    approveDecision(id) {
      return client.request<DashboardDecision>(
        `/dashboard/decisions/${id}/approve`,
        {
          method: "POST",
          headers: { "Idempotency-Key": idempotencyKey("decision-approve", id) },
        },
      );
    },
    getDashboard() {
      return client.request<DashboardDataResponse>("/dashboard");
    },
    getLayout() {
      return client.request<DashboardLayoutResponse>("/dashboard/layout");
    },
    listDecisions(query) {
      return client.request<DashboardDecisionListResponse>(
        appendQuery("/dashboard/decisions", query),
      );
    },
    rejectDecision(id, payload) {
      return client.request<DashboardDecision>(
        `/dashboard/decisions/${id}/reject`,
        {
          method: "POST",
          headers: { "Idempotency-Key": idempotencyKey("decision-reject", id) },
          body: payload,
        },
      );
    },
    resetLayout() {
      return client.request<DashboardLayoutResponse>("/dashboard/layout/reset", {
        method: "POST",
      });
    },
    saveLayout(request) {
      return client.request<DashboardLayoutResponse>("/dashboard/layout", {
        method: "PUT",
        body: request,
      });
    },
  };
}
