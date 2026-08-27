import type { ApiClient } from "../client";
import { appendQuery, type QueryValue } from "./serviceUtils";

export type UserListQuery = Record<string, QueryValue>;
export type UserCreate = Record<string, unknown>;
export type UserUpdate = Record<string, unknown>;
export type RoleAssignment = Record<string, unknown>;
export type UserResponse = Record<string, unknown>;
export type UserListResponse = Record<string, unknown>;

export type UsersService = {
  assignRoles(userId: number, request: RoleAssignment): Promise<UserResponse>;
  createUser(request: UserCreate): Promise<UserResponse>;
  deleteUser(userId: number): Promise<void>;
  getUser(userId: number): Promise<UserResponse>;
  listUsers(query?: UserListQuery): Promise<UserListResponse>;
  updateUser(userId: number, request: UserUpdate): Promise<UserResponse>;
};

export function createUsersService(client: ApiClient): UsersService {
  return {
    assignRoles(userId, request) {
      return client.request<UserResponse>(`/users/${userId}/roles`, {
        method: "PUT",
        body: request,
      });
    },
    createUser(request) {
      return client.request<UserResponse>("/users", {
        method: "POST",
        body: request,
      });
    },
    deleteUser(userId) {
      return client.request<void>(`/users/${userId}`, {
        method: "DELETE",
      });
    },
    getUser(userId) {
      return client.request<UserResponse>(`/users/${userId}`);
    },
    listUsers(query) {
      return client.request<UserListResponse>(appendQuery("/users", query));
    },
    updateUser(userId, request) {
      return client.request<UserResponse>(`/users/${userId}`, {
        method: "PUT",
        body: request,
      });
    },
  };
}
