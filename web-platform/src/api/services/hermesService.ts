import type { ApiClient } from "../client";

export type ProfileCreate = Record<string, unknown>;
export type ProfileResponse = Record<string, unknown>;
export type ProfileHealthResponse = Record<string, unknown>;

export type HermesService = {
  createProfile(request: ProfileCreate): Promise<ProfileResponse>;
  deactivateProfile(userId: number): Promise<void>;
  getProfile(userId: number): Promise<ProfileResponse>;
  getProfileHealth(userId: number): Promise<ProfileHealthResponse>;
};

export function createHermesService(client: ApiClient): HermesService {
  return {
    createProfile(request) {
      return client.request<ProfileResponse>("/hermes/profiles", {
        method: "POST",
        body: request,
      });
    },
    deactivateProfile(userId) {
      return client.request<void>(`/hermes/profiles/${userId}`, {
        method: "DELETE",
      });
    },
    getProfile(userId) {
      return client.request<ProfileResponse>(`/hermes/profiles/${userId}`);
    },
    getProfileHealth(userId) {
      return client.request<ProfileHealthResponse>(
        `/hermes/profiles/${userId}/health`,
      );
    },
  };
}
