import type { ApiClient } from "../client";
import { appendQuery, type QueryValue } from "./serviceUtils";

export type AuditEventListQuery = Record<string, QueryValue>;
export type AuditEventListResponse = Record<string, unknown>;

export type AuditService = {
  listAuditEvents(
    query?: AuditEventListQuery,
  ): Promise<AuditEventListResponse>;
};

export function createAuditService(client: ApiClient): AuditService {
  return {
    listAuditEvents(query) {
      return client.request<AuditEventListResponse>(
        appendQuery("/audit-events", query),
      );
    },
  };
}
