import type { ApiClient } from "../client";
import { appendQuery, type QueryValue } from "./serviceUtils";

export type ChatSessionListQuery = Record<string, QueryValue>;
export type ChatMessageListQuery = Record<string, QueryValue>;
export type ChatSessionCreate = Record<string, unknown>;
export type ChatSessionUpdate = Record<string, unknown>;
export type KnowledgeScopeUpdate =
  | { mode: "selected"; source_ids: number[] }
  | { mode: "all_visible" | "none"; source_ids: [] };
export type LinkPreviewRequest = Record<string, unknown>;
export type RunApprovalRequest = Record<string, unknown>;
export type ChatSessionResponse = Record<string, unknown>;
export type ChatSessionListResponse = Record<string, unknown>;
export type KnowledgeScopeResponse = Record<string, unknown>;
export type LinkPreviewResponse = Record<string, unknown>;
export type ChatAttachmentResponse = Record<string, unknown>;
export type ChatMessageListResponse = Record<string, unknown>;
export type RunStopResponse = Record<string, unknown>;
export type RunApprovalResponse = Record<string, unknown>;

export type ChatService = {
  approveRun(
    sessionId: string,
    runId: string,
    request: RunApprovalRequest,
  ): Promise<RunApprovalResponse>;
  createSession(request: ChatSessionCreate): Promise<ChatSessionResponse>;
  deleteSession(sessionId: string): Promise<void>;
  getMessages(
    sessionId: string,
    query?: ChatMessageListQuery,
  ): Promise<ChatMessageListResponse>;
  listSessions(query?: ChatSessionListQuery): Promise<ChatSessionListResponse>;
  updateSession(
    sessionId: string,
    request: ChatSessionUpdate,
  ): Promise<ChatSessionResponse>;
  prepareAttachment(
    form: FormData,
    onProgress?: (loaded: number, total: number) => void,
  ): Promise<ChatAttachmentResponse>;
  previewLink(request: LinkPreviewRequest): Promise<LinkPreviewResponse>;
  setKnowledgeScope(
    sessionId: string,
    request: KnowledgeScopeUpdate,
  ): Promise<KnowledgeScopeResponse>;
  stopRun(sessionId: string, runId: string): Promise<RunStopResponse>;
};

export function createChatService(client: ApiClient): ChatService {
  return {
    approveRun(sessionId, runId, request) {
      return client.request<RunApprovalResponse>(
        `/chat/sessions/${sessionId}/runs/${runId}/approval`,
        {
          method: "POST",
          body: request,
        },
      );
    },
    createSession(request) {
      return client.request<ChatSessionResponse>("/chat/sessions", {
        method: "POST",
        body: request,
      });
    },
    deleteSession(sessionId) {
      return client.request<void>(`/chat/sessions/${sessionId}`, {
        method: "DELETE",
      });
    },
    getMessages(sessionId, query) {
      return client.request<ChatMessageListResponse>(
        appendQuery(`/chat/sessions/${sessionId}/messages`, query),
      );
    },
    listSessions(query) {
      return client.request<ChatSessionListResponse>(
        appendQuery("/chat/sessions", query),
      );
    },
    updateSession(sessionId, request) {
      return client.request<ChatSessionResponse>(`/chat/sessions/${sessionId}`, {
        method: "PATCH",
        body: request,
      });
    },
    prepareAttachment(form, onProgress) {
      if (onProgress && client.upload) {
        return client.upload<ChatAttachmentResponse>("/chat/attachments", form, {
          onProgress,
        });
      }
      return client.request<ChatAttachmentResponse>("/chat/attachments", {
        method: "POST",
        body: form,
      });
    },
    previewLink(request) {
      return client.request<LinkPreviewResponse>("/chat/link-preview", {
        method: "POST",
        body: request,
      });
    },
    setKnowledgeScope(sessionId, request) {
      return client.request<KnowledgeScopeResponse>(
        `/chat/sessions/${sessionId}/knowledge-scope`,
        {
          method: "PUT",
          body: request,
        },
      );
    },
    stopRun(sessionId, runId) {
      return client.request<RunStopResponse>(
        `/chat/sessions/${sessionId}/runs/${runId}/stop`,
        { method: "POST" },
      );
    },
  };
}
