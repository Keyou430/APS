import type { ApiClient } from "../client";
import { appendQuery, type QueryValue } from "./serviceUtils";

export type SkillListQuery = Record<string, QueryValue>;
export type SkillCreate = Record<string, unknown>;
export type SkillUpdate = Record<string, unknown>;
export type SkillGenerateRequest = Record<string, unknown>;
export type SkillResponse = Record<string, unknown>;
export type SkillListResponse = Record<string, unknown>;
export type HubSkillListResponse = Record<string, unknown>;
export type GeneratedSkillResponse = Record<string, unknown>;

export type SkillsService = {
  createSkill(request: SkillCreate): Promise<SkillResponse>;
  deleteSkill(skillId: number): Promise<void>;
  generateSkill(
    request: SkillGenerateRequest,
  ): Promise<GeneratedSkillResponse>;
  getHubSkills(): Promise<HubSkillListResponse>;
  getSkill(skillId: number): Promise<SkillResponse>;
  listSkills(query?: SkillListQuery): Promise<SkillListResponse>;
  updateSkill(skillId: number, request: SkillUpdate): Promise<SkillResponse>;
};

export function createSkillsService(client: ApiClient): SkillsService {
  return {
    createSkill(request) {
      return client.request<SkillResponse>("/skills", {
        method: "POST",
        body: request,
      });
    },
    deleteSkill(skillId) {
      return client.request<void>(`/skills/${skillId}`, {
        method: "DELETE",
      });
    },
    generateSkill(request) {
      return client.request<GeneratedSkillResponse>("/skills/generate", {
        method: "POST",
        body: request,
      });
    },
    getHubSkills() {
      return client.request<HubSkillListResponse>("/skills/hub");
    },
    getSkill(skillId) {
      return client.request<SkillResponse>(`/skills/${skillId}`);
    },
    listSkills(query) {
      return client.request<SkillListResponse>(appendQuery("/skills", query));
    },
    updateSkill(skillId, request) {
      return client.request<SkillResponse>(`/skills/${skillId}`, {
        method: "PUT",
        body: request,
      });
    },
  };
}
