import type { ApiClient } from "../client";
import { appendQuery, type QueryValue } from "./serviceUtils";
import {
  mapEnterprisePortalToLegacyBootstrap,
  type LegacyPortalBootstrap,
} from "./enterprisePortalMapper";
import type { DashboardDataResponse } from "./dashboardService";

export type EnterprisePortalResponse = {
  activities: unknown[];
  announcements: unknown[];
  collaborators: unknown[];
  company: Record<string, unknown>;
  currentUser: Record<string, unknown>;
  departments: unknown[];
  people: unknown[];
  positions: unknown[];
  quickLinks: unknown[];
  todos: unknown[];
};

export type AnnouncementListQuery = Record<string, QueryValue>;
export type AnnouncementPriority = "normal" | "important";
export type AnnouncementCreate = { title: string; summary?: string; content?: string | null; priority?: AnnouncementPriority };
export type AnnouncementUpdate = { title?: string; summary?: string; content?: string | null; priority?: AnnouncementPriority };
export type AnnouncementPinUpdate = { isPinned: boolean };
export type AnnouncementResponse = { id: number; title: string; summary: string; author: string; priority: AnnouncementPriority; publishedAt: string | null; content?: string | null; isPinned: boolean; isRead: boolean; status: "draft" | "published" | "withdrawn" };
export type AnnouncementListResponse = { items: AnnouncementResponse[]; total: number; page: number; pageSize: number };
export type PortalTodoUpdate = Record<string, unknown>;
export type PortalTodoResponse = Record<string, unknown>;

export type EnterpriseService = {
  createAnnouncement(
    request: AnnouncementCreate,
  ): Promise<AnnouncementResponse>;
  createPublishedAnnouncement(
    request: AnnouncementCreate,
  ): Promise<AnnouncementResponse>;
  getLegacyBootstrap(
    dashboard?: DashboardDataResponse,
  ): Promise<LegacyPortalBootstrap>;
  getPortal(): Promise<EnterprisePortalResponse>;
  listAnnouncements(
    query?: AnnouncementListQuery,
  ): Promise<AnnouncementListResponse>;
  markAnnouncementRead(announcementId: number): Promise<void>;
  pinAnnouncement(
    announcementId: number,
    request: AnnouncementPinUpdate,
  ): Promise<AnnouncementResponse>;
  publishAnnouncement(announcementId: number): Promise<AnnouncementResponse>;
  updateAnnouncement(
    announcementId: number,
    request: AnnouncementUpdate,
  ): Promise<AnnouncementResponse>;
  updatePortalTodo(
    reminderId: number,
    request: PortalTodoUpdate,
  ): Promise<PortalTodoResponse>;
  withdrawAnnouncement(announcementId: number): Promise<AnnouncementResponse>;
};

export function createEnterpriseService(client: ApiClient): EnterpriseService {
  async function getPortal() {
    return client.request<EnterprisePortalResponse>("/enterprise/portal");
  }

  return {
    createAnnouncement(request) {
      return client.request<AnnouncementResponse>("/enterprise/announcements", {
        method: "POST",
        body: request,
      });
    },
    async createPublishedAnnouncement(request) {
      const draft = await client.request<AnnouncementResponse>(
        "/enterprise/announcements",
        { method: "POST", body: request },
      );
      return client.request<AnnouncementResponse>(
        `/enterprise/announcements/${draft.id}/publish`,
        { method: "POST" },
      );
    },
    async getLegacyBootstrap(dashboard) {
      return mapEnterprisePortalToLegacyBootstrap(await getPortal(), dashboard);
    },
    getPortal,
    listAnnouncements(query) {
      return client.request<AnnouncementListResponse>(
        appendQuery("/enterprise/announcements", query),
      );
    },
    markAnnouncementRead(announcementId) {
      return client.request<void>(
        `/enterprise/announcements/${announcementId}/read`,
        { method: "POST" },
      );
    },
    pinAnnouncement(announcementId, request) {
      return client.request<AnnouncementResponse>(
        `/enterprise/announcements/${announcementId}/pin`,
        {
          method: "POST",
          body: request,
        },
      );
    },
    publishAnnouncement(announcementId) {
      return client.request<AnnouncementResponse>(
        `/enterprise/announcements/${announcementId}/publish`,
        { method: "POST" },
      );
    },
    updateAnnouncement(announcementId, request) {
      return client.request<AnnouncementResponse>(
        `/enterprise/announcements/${announcementId}`,
        {
          method: "PATCH",
          body: request,
        },
      );
    },
    updatePortalTodo(reminderId, request) {
      return client.request<PortalTodoResponse>(
        `/enterprise/portal/todos/${reminderId}`,
        {
          method: "PUT",
          body: request,
        },
      );
    },
    withdrawAnnouncement(announcementId) {
      return client.request<AnnouncementResponse>(
        `/enterprise/announcements/${announcementId}/withdraw`,
        { method: "POST" },
      );
    },
  };
}
