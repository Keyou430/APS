import type { ApiClient } from "../client";
import { appendQuery, type QueryValue } from "./serviceUtils";

export type PipelineTaskStatus =
  | "draft"
  | "ready"
  | "running"
  | "completed"
  | "failed"
  | "cancelled";

export type PipelineDecisionStatus =
  | "pending"
  | "approved"
  | "changes_requested"
  | "rejected";

export type PipelineRunStatus =
  | "queued"
  | "running"
  | "completed"
  | "failed"
  | "cancelled";

export type PipelineTaskRequest = Record<string, unknown>;
export type PipelineTaskListQuery = Record<string, QueryValue>;

export type PipelineTask = {
  description?: string | null;
  id: number | string;
  output_id?: number | string | null;
  outputId?: number | string | null;
  status?: PipelineTaskStatus | string;
  title?: string | null;
  prompt?: string | null;
  task_type?: string | null;
  schedule?: string | null;
  timezone?: string | null;
  input_sources?: string[];
  output_format?: string | null;
  approval_required?: boolean;
  approval_assignee_type?: "creator" | "member" | "role" | string;
  approval_reminder_after_minutes?: number | null;
  approval_escalation_after_minutes?: number | null;
};

export type PipelineTaskDraft = Omit<PipelineTask, "id">;

export type PipelineTaskListResponse = {
  items?: PipelineTask[];
};

export type PipelineRun = {
  id: number | string;
  output_id?: number | string | null;
  outputId?: number | string | null;
  status?: PipelineRunStatus | string;
};

export type PipelineDecision = {
  id: number | string;
  status?: PipelineDecisionStatus | string;
  summary?: string | null;
  title?: string | null;
  approval_comment?: string | null;
  rejection_reason?: string | null;
  reason_type?: string | null;
  decided_at?: string | null;
};

export type PipelineDecisionListResponse = {
  items?: PipelineDecision[];
};

export type PipelineRequestChangesPayload = {
  reason: string;
};
export type PipelineApprovePayload = {
  comment?: string;
};

export type PipelineOutput = {
  id: number | string;
  markdown?: string | null;
  title?: string | null;
  sources?: Array<{
    url?: string;
    title?: string;
    published_at?: string;
    searched_at?: string;
  }>;
};

export type PipelineService = {
  approveDecision(
    id: number | string,
    payload?: PipelineApprovePayload,
  ): Promise<PipelineDecision>;
  createDraft(request: PipelineTaskRequest): Promise<PipelineTaskDraft>;
  createTask(request: PipelineTaskRequest): Promise<PipelineTask>;
  downloadOutput(id: number | string): Promise<Blob>;
  getOutput(id: number | string): Promise<PipelineOutput>;
  getRun(id: number | string): Promise<PipelineRun>;
  getTask(id: number | string): Promise<PipelineTask>;
  listDecisions(): Promise<PipelineDecisionListResponse>;
  listTasks(query?: PipelineTaskListQuery): Promise<PipelineTaskListResponse>;
  requestChanges(
    id: number | string,
    payload: PipelineRequestChangesPayload,
  ): Promise<PipelineDecision>;
  runTask(id: number | string): Promise<PipelineRun>;
  /**
   * Marks the previous manual-run intent for this task as finished so the
   * next runTask click can mint a fresh Idempotency-Key. Retries within one
   * intent always reuse the same key.
   */
  releaseRunIntent(id: string): void;
};

function stableHash(input: string): string {
  let hash = 5381;
  for (let index = 0; index < input.length; index += 1) {
    hash = ((hash << 5) + hash + input.charCodeAt(index)) | 0;
  }
  return (hash >>> 0).toString(36);
}

export function createPipelineService(client: ApiClient): PipelineService {
  // Manual-run keys are minted once per user intent and reused across network
  // retries; decision-action keys are fully deterministic so replays across
  // page reloads stay idempotent server-side.
  const runIntentKeys = new Map<string, string>();
  const runIntentKey = (id: number | string) => {
    const cacheKey = `task-run:${String(id)}`;
    const existing = runIntentKeys.get(cacheKey);
    if (existing) return existing;
    const key = `task-run-${String(id)}-${globalThis.crypto?.randomUUID?.() ?? stableHash(`${Date.now()}${cacheKey}`)}`;
    runIntentKeys.set(cacheKey, key);
    return key;
  };
  return {
    approveDecision(id, payload) {
      return client.request<PipelineDecision>(
        `/dashboard/decisions/${id}/approve`,
        {
          method: "POST",
          headers: { "Idempotency-Key": `decision-approve:${String(id)}` },
          ...(payload ? { body: payload } : {}),
        },
      );
    },
    createDraft(request) {
      return client.request<PipelineTask>("/pipeline/tasks/draft", {
        method: "POST",
        body: request,
      });
    },
    createTask(request) {
      const identity = String(
        request.id ?? request.client_request_id ?? JSON.stringify(request),
      );
      return client.request<PipelineTask>("/pipeline/tasks", {
        method: "POST",
        body: request,
        headers: {
          "Idempotency-Key": `task-create:${stableHash(identity)}`,
        },
      });
    },
    downloadOutput(id) {
      return client.request<Blob>(`/pipeline/outputs/${id}/download`, {
        headers: { Accept: "application/octet-stream" },
        responseType: "blob",
      });
    },
    getOutput(id) {
      return client.request<PipelineOutput>(`/pipeline/outputs/${id}`);
    },
    getRun(id) {
      return client.request<PipelineRun>(`/pipeline/runs/${id}`);
    },
    getTask(id) {
      return client.request<PipelineTask>(`/pipeline/tasks/${id}`);
    },
    listDecisions() {
      return client.request<PipelineDecisionListResponse>("/dashboard/decisions");
    },
    listTasks(query) {
      return client.request<PipelineTaskListResponse>(
        appendQuery("/pipeline/tasks", query),
      );
    },
    requestChanges(id, payload) {
      return client.request<PipelineDecision>(
        `/dashboard/decisions/${id}/request-changes`,
        {
          method: "POST",
          body: payload,
          headers: { "Idempotency-Key": `decision-changes:${String(id)}` },
        },
      );
    },
    runTask(id) {
      return client.request<PipelineRun>(`/pipeline/tasks/${id}/run`, {
        method: "POST",
        headers: { "Idempotency-Key": runIntentKey(id) },
      });
    },
    releaseRunIntent(id) {
      runIntentKeys.delete(`task-run:${id}`);
    },
  };
}
