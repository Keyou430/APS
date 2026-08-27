import type { ApiClient } from "../client";
import { appendQuery, type QueryValue } from "./serviceUtils";

export type KnowledgeListQuery = Record<string, QueryValue>;
export type KnowledgeOperationJobQuery = Record<string, QueryValue>;
export type KnowledgeCreate = Record<string, unknown>;
export type KnowledgeUpdate = Record<string, unknown>;
export type KnowledgeAccessUpdate = Record<string, unknown>;
export type KnowledgeGrantCreate = Record<string, unknown>;
export type KnowledgeCollectionCreate = Record<string, unknown>;
export type KnowledgeCollectionUpdate = Record<string, unknown>;
export type KnowledgeCollectionAssignment = Record<string, unknown>;
export type KnowledgeSearchRequest = Record<string, unknown>;
export type KnowledgeRetrieveRequest = Record<string, unknown>;
export type KnowledgeResponse = Record<string, unknown>;
export type KnowledgeListResponse = Record<string, unknown>;
export type KnowledgeContentPreview = Record<string, unknown>;
export type KnowledgeIngestionResponse = Record<string, unknown>;
export type KnowledgeGrantListResponse = Record<string, unknown>;
export type KnowledgeGrantResponse = Record<string, unknown>;
export type KnowledgeCollectionListResponse = Record<string, unknown>;
export type KnowledgeCollectionResponse = Record<string, unknown>;
export type KnowledgeSearchResponse = Record<string, unknown>;
export type KnowledgeRetrieveResponse = Record<string, unknown>;
export type KnowledgeCitationResolveResponse = Record<string, unknown>;
type NumericString = `${number}`;
export type KnowledgeMemberListResponse = Record<string, unknown>;
export type FixedKnowledgeContextListResponse = Record<string, unknown>;
export type FixedKnowledgeContextResponse = Record<string, unknown>;
export type KnowledgeOperationsOverview = Record<string, unknown>;
export type KnowledgeOperationJobList = Record<string, unknown>;
export type KnowledgeOperationJob = Record<string, unknown>;

export type KnowledgeService = {
  archiveEntry(entryId: number): Promise<void>;
  assignCollection(
    entryId: number,
    request: KnowledgeCollectionAssignment,
  ): Promise<KnowledgeResponse>;
  cancelOperationJob(jobId: string): Promise<KnowledgeOperationJob>;
  createCollection(
    request: KnowledgeCollectionCreate,
  ): Promise<KnowledgeCollectionResponse>;
  createEntry(request: KnowledgeCreate): Promise<KnowledgeResponse>;
  createGrant(
    entryId: number,
    request: KnowledgeGrantCreate,
  ): Promise<KnowledgeGrantResponse>;
  deleteCollection(collectionId: number): Promise<void>;
  downloadEntry(entryId: number): Promise<unknown>;
  getEntry(entryId: number): Promise<KnowledgeResponse>;
  getFixedContext(contextId: string): Promise<FixedKnowledgeContextResponse>;
  getIngestionStatus(entryId: number): Promise<KnowledgeIngestionResponse>;
  getOperationsOverview(): Promise<KnowledgeOperationsOverview>;
  ingestEntry(entryId: number): Promise<unknown>;
  listCollections(): Promise<KnowledgeCollectionListResponse>;
  listEntries(query?: KnowledgeListQuery): Promise<KnowledgeListResponse>;
  listFixedContexts(): Promise<FixedKnowledgeContextListResponse>;
  listGrants(entryId: number): Promise<KnowledgeGrantListResponse>;
  listMembers(): Promise<KnowledgeMemberListResponse>;
  listOperationJobs(
    query?: KnowledgeOperationJobQuery,
  ): Promise<KnowledgeOperationJobList>;
  previewContent(entryId: number): Promise<KnowledgeContentPreview>;
  purgeEntry(entryId: number): Promise<void>;
  resolveCitation(
    turnId: number | NumericString,
    ordinal: number,
  ): Promise<KnowledgeCitationResolveResponse>;
  restoreEntry(entryId: number): Promise<KnowledgeResponse>;
  retrieve(request: KnowledgeRetrieveRequest): Promise<KnowledgeRetrieveResponse>;
  retryOperationJob(jobId: string): Promise<KnowledgeOperationJob>;
  revokeGrant(entryId: number, grantId: number): Promise<void>;
  search(request: KnowledgeSearchRequest): Promise<KnowledgeSearchResponse>;
  updateAccess(
    entryId: number,
    request: KnowledgeAccessUpdate,
  ): Promise<KnowledgeResponse>;
  updateCollection(
    collectionId: number,
    request: KnowledgeCollectionUpdate,
  ): Promise<KnowledgeCollectionResponse>;
  updateEntry(
    entryId: number,
    request: KnowledgeUpdate,
  ): Promise<KnowledgeResponse>;
  uploadEntry(
    form: FormData,
    onProgress?: (loaded: number, total: number) => void,
  ): Promise<KnowledgeResponse>;
};

export function createKnowledgeService(client: ApiClient): KnowledgeService {
  return {
    archiveEntry(entryId) {
      return client.request<void>(`/knowledge/${entryId}`, {
        method: "DELETE",
      });
    },
    assignCollection(entryId, request) {
      return client.request<KnowledgeResponse>(
        `/knowledge/${entryId}/collection`,
        {
          method: "PUT",
          body: request,
        },
      );
    },
    cancelOperationJob(jobId) {
      return client.request<KnowledgeOperationJob>(
        `/knowledge/operations/jobs/${jobId}/cancel`,
        { method: "POST" },
      );
    },
    createCollection(request) {
      return client.request<KnowledgeCollectionResponse>(
        "/knowledge/collections",
        {
          method: "POST",
          body: request,
        },
      );
    },
    createEntry(request) {
      return client.request<KnowledgeResponse>("/knowledge", {
        method: "POST",
        body: request,
      });
    },
    createGrant(entryId, request) {
      return client.request<KnowledgeGrantResponse>(
        `/knowledge/${entryId}/grants`,
        {
          method: "POST",
          body: request,
        },
      );
    },
    deleteCollection(collectionId) {
      return client.request<void>(`/knowledge/collections/${collectionId}`, {
        method: "DELETE",
      });
    },
    downloadEntry(entryId) {
      return client.request<unknown>(`/knowledge/${entryId}/download`, {
        headers: { Accept: "application/octet-stream" },
      });
    },
    getEntry(entryId) {
      return client.request<KnowledgeResponse>(`/knowledge/${entryId}`);
    },
    getFixedContext(contextId) {
      return client.request<FixedKnowledgeContextResponse>(
        `/knowledge/fixed-contexts/${contextId}`,
      );
    },
    getIngestionStatus(entryId) {
      return client.request<KnowledgeIngestionResponse>(
        `/knowledge/${entryId}/ingestion`,
      );
    },
    getOperationsOverview() {
      return client.request<KnowledgeOperationsOverview>(
        "/knowledge/operations/overview",
      );
    },
    ingestEntry(entryId) {
      return client.request<unknown>(`/knowledge/${entryId}/ingest`, {
        method: "POST",
      });
    },
    listCollections() {
      return client.request<KnowledgeCollectionListResponse>(
        "/knowledge/collections",
      );
    },
    listEntries(query) {
      return client.request<KnowledgeListResponse>(
        appendQuery("/knowledge", query),
      );
    },
    listFixedContexts() {
      return client.request<FixedKnowledgeContextListResponse>(
        "/knowledge/fixed-contexts",
      );
    },
    listGrants(entryId) {
      return client.request<KnowledgeGrantListResponse>(
        `/knowledge/${entryId}/grants`,
      );
    },
    listMembers() {
      return client.request<KnowledgeMemberListResponse>("/knowledge/members");
    },
    listOperationJobs(query) {
      return client.request<KnowledgeOperationJobList>(
        appendQuery("/knowledge/operations/jobs", query),
      );
    },
    previewContent(entryId) {
      return client.request<KnowledgeContentPreview>(
        `/knowledge/${entryId}/content`,
      );
    },
    purgeEntry(entryId) {
      return client.request<void>(`/knowledge/${entryId}/purge`, {
        method: "DELETE",
      });
    },
    resolveCitation(turnId, ordinal) {
      return client.request<KnowledgeCitationResolveResponse>(
        `/knowledge/citations/${turnId}/${ordinal}`,
      );
    },
    restoreEntry(entryId) {
      return client.request<KnowledgeResponse>(
        `/knowledge/${entryId}/restore`,
        { method: "POST" },
      );
    },
    retrieve(request) {
      return client.request<KnowledgeRetrieveResponse>("/knowledge/retrieve", {
        method: "POST",
        body: request,
      });
    },
    retryOperationJob(jobId) {
      return client.request<KnowledgeOperationJob>(
        `/knowledge/operations/jobs/${jobId}/retry`,
        { method: "POST" },
      );
    },
    revokeGrant(entryId, grantId) {
      return client.request<void>(`/knowledge/${entryId}/grants/${grantId}`, {
        method: "DELETE",
      });
    },
    search(request) {
      return client.request<KnowledgeSearchResponse>("/knowledge/search", {
        method: "POST",
        body: request,
      });
    },
    updateAccess(entryId, request) {
      return client.request<KnowledgeResponse>(`/knowledge/${entryId}/access`, {
        method: "PUT",
        body: request,
      });
    },
    updateCollection(collectionId, request) {
      return client.request<KnowledgeCollectionResponse>(
        `/knowledge/collections/${collectionId}`,
        {
          method: "PATCH",
          body: request,
        },
      );
    },
    updateEntry(entryId, request) {
      return client.request<KnowledgeResponse>(`/knowledge/${entryId}`, {
        method: "PUT",
        body: request,
      });
    },
    uploadEntry(form, onProgress) {
      if (onProgress && client.upload) {
        return client.upload<KnowledgeResponse>("/knowledge/upload", form, {
          onProgress,
        });
      }
      return client.request<KnowledgeResponse>("/knowledge/upload", {
        method: "POST",
        body: form,
      });
    },
  };
}
