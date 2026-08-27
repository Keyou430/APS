import type { ApiClient } from "../client";

export type ExperienceDomain = Record<string, unknown>;
export type ExperienceMethod = Record<string, unknown>;

export type ExperienceService = {
  listDomains(): Promise<{ items: ExperienceDomain[] }>;
  createDomain(request: Record<string, unknown>): Promise<ExperienceDomain>;
  updateDomain(id: number, request: Record<string, unknown>): Promise<ExperienceDomain>;
  deleteDomain(id: number): Promise<void>;
  listMethods(domainId: number): Promise<{ items: ExperienceMethod[] }>;
  createMethod(domainId: number, request: Record<string, unknown>): Promise<ExperienceMethod>;
  updateMethod(id: number, request: Record<string, unknown>): Promise<ExperienceMethod>;
  deleteMethod(id: number): Promise<void>;
};

export function createExperienceService(client: ApiClient): ExperienceService {
  return {
    listDomains() {
      return client.request("/experience/domains");
    },
    createDomain(request) {
      return client.request("/experience/domains", { method: "POST", body: request });
    },
    updateDomain(id, request) {
      return client.request(`/experience/domains/${id}`, { method: "PATCH", body: request });
    },
    deleteDomain(id) {
      return client.request(`/experience/domains/${id}`, { method: "DELETE" });
    },
    listMethods(domainId) {
      return client.request(`/experience/domains/${domainId}/methods`);
    },
    createMethod(domainId, request) {
      return client.request(`/experience/domains/${domainId}/methods`, { method: "POST", body: request });
    },
    updateMethod(id, request) {
      return client.request(`/experience/methods/${id}`, { method: "PATCH", body: request });
    },
    deleteMethod(id) {
      return client.request(`/experience/methods/${id}`, { method: "DELETE" });
    },
  };
}
