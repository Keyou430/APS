import type { ApiClient } from "../client";
import { appendQuery, type QueryValue } from "./serviceUtils";

export type WorkItemListQuery = Record<string, QueryValue>;
export type WorkItemCreate = Record<string, unknown>;
export type WorkItemUpdate = Record<string, unknown>;
export type WorkItemStatusUpdate = Record<string, unknown>;
export type WorkItemResponse = Record<string, unknown>;
export type WorkItemListResponse = Record<string, unknown>;
export type WorkItemEventResponse = Record<string, unknown>;
export type WorkItemEventListResponse = Record<string, unknown>;

export type WorkItemsService = {
  createWorkItem(request: WorkItemCreate): Promise<WorkItemResponse>;
  deleteWorkItem(workItemId: number): Promise<void>;
  getWorkItem(workItemId: number): Promise<WorkItemResponse>;
  getWorkItemEvent(eventId: number): Promise<WorkItemEventResponse>;
  listWorkItemEvents(
    workItemId: number,
  ): Promise<WorkItemEventListResponse>;
  listWorkItems(query?: WorkItemListQuery): Promise<WorkItemListResponse>;
  updateWorkItem(
    workItemId: number,
    request: WorkItemUpdate,
  ): Promise<WorkItemResponse>;
  updateWorkItemStatus(
    workItemId: number,
    request: WorkItemStatusUpdate,
  ): Promise<WorkItemResponse>;
};

export function createWorkItemsService(client: ApiClient): WorkItemsService {
  return {
    createWorkItem(request) {
      return client.request<WorkItemResponse>("/work-items", {
        method: "POST",
        body: request,
      });
    },
    deleteWorkItem(workItemId) {
      return client.request<void>(`/work-items/${workItemId}`, {
        method: "DELETE",
      });
    },
    getWorkItem(workItemId) {
      return client.request<WorkItemResponse>(`/work-items/${workItemId}`);
    },
    getWorkItemEvent(eventId) {
      return client.request<WorkItemEventResponse>(
        `/work-items/events/${eventId}`,
      );
    },
    listWorkItemEvents(workItemId) {
      return client.request<WorkItemEventListResponse>(
        `/work-items/${workItemId}/events`,
      );
    },
    listWorkItems(query) {
      return client.request<WorkItemListResponse>(
        appendQuery("/work-items", query),
      );
    },
    updateWorkItem(workItemId, request) {
      return client.request<WorkItemResponse>(`/work-items/${workItemId}`, {
        method: "PATCH",
        body: request,
      });
    },
    updateWorkItemStatus(workItemId, request) {
      return client.request<WorkItemResponse>(
        `/work-items/${workItemId}/status`,
        {
          method: "PATCH",
          body: request,
        },
      );
    },
  };
}
