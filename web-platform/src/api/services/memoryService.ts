import type { ApiClient } from "../client";
import { appendQuery, type QueryValue } from "./serviceUtils";

export type MemoryListQuery = Record<string, QueryValue>;
export type MemoryCreate = Record<string, unknown>;
export type MemoryUpdate = Record<string, unknown>;
export type MemoryResponse = Record<string, unknown>;
export type MemoryListResponse = Record<string, unknown>;

export type MemoryService = {
  createMemory(request: MemoryCreate): Promise<MemoryResponse>;
  deleteMemory(memoryId: number): Promise<void>;
  getMemory(memoryId: number): Promise<MemoryResponse>;
  listMemory(query?: MemoryListQuery): Promise<MemoryListResponse>;
  updateMemory(
    memoryId: number,
    request: MemoryUpdate,
  ): Promise<MemoryResponse>;
};

export function createMemoryService(client: ApiClient): MemoryService {
  return {
    createMemory(request) {
      return client.request<MemoryResponse>("/memory", {
        method: "POST",
        body: request,
      });
    },
    deleteMemory(memoryId) {
      return client.request<void>(`/memory/${memoryId}`, {
        method: "DELETE",
      });
    },
    getMemory(memoryId) {
      return client.request<MemoryResponse>(`/memory/${memoryId}`);
    },
    listMemory(query) {
      return client.request<MemoryListResponse>(appendQuery("/memory", query));
    },
    updateMemory(memoryId, request) {
      return client.request<MemoryResponse>(`/memory/${memoryId}`, {
        method: "PUT",
        body: request,
      });
    },
  };
}
