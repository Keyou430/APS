import { describe, expect, it, vi } from "vitest";
import type { ApiClient } from "../client";
import { createUsersService } from "./usersService";

function createClient() {
  const request = vi.fn();
  const client: ApiClient = {
    request: async (path, options) => request(path, options),
  };
  return { client, request };
}

describe("users service", () => {
  it("lists users with query parameters", async () => {
    const { client, request } = createClient();
    request.mockResolvedValue({ items: [], total: 0 });

    await createUsersService(client).listUsers({
      page: 2,
      page_size: 20,
      search: "keyou",
      role: "org_admin",
    });

    expect(request).toHaveBeenCalledWith(
      "/users?page=2&page_size=20&search=keyou&role=org_admin",
      undefined,
    );
  });

  it("creates, updates, deletes and assigns user roles", async () => {
    const { client, request } = createClient();
    request.mockResolvedValue({});
    const service = createUsersService(client);

    await service.createUser({ username: "keyou", password: "change-me-123", email: "k@example.com" });
    await service.updateUser(5, { email: "new@example.com" });
    await service.assignRoles(5, { role: "admin" });
    await service.deleteUser(5);

    expect(request).toHaveBeenNthCalledWith(1, "/users", {
      method: "POST",
      body: { username: "keyou", password: "change-me-123", email: "k@example.com" },
    });
    expect(request).toHaveBeenNthCalledWith(2, "/users/5", {
      method: "PUT",
      body: { email: "new@example.com" },
    });
    expect(request).toHaveBeenNthCalledWith(3, "/users/5/roles", {
      method: "PUT",
      body: { role: "admin" },
    });
    expect(request).toHaveBeenNthCalledWith(4, "/users/5", {
      method: "DELETE",
    });
  });
});
