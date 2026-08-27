import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom/vitest";
import { describe, expect, it, vi } from "vitest";
import type { HermesService } from "../api/services/hermesService";
import { HermesPage } from "./HermesPage";

function createCache() {
  return {
    get: vi.fn(),
    invalidateOrganization: vi.fn(),
    set: vi.fn(),
  };
}

function createService(overrides: Partial<HermesService> = {}): HermesService {
  return {
    createProfile: vi.fn(async () => ({
      provider: "feishu",
      status: "active",
      user_id: 9,
    })),
    deactivateProfile: vi.fn(async () => undefined),
    getProfile: vi.fn(async () => ({
      capabilities: ["chat", "approval"],
      provider: "feishu",
      secret: "should-not-render",
      status: "active",
      token: "should-not-render",
      user_id: 9,
    })),
    getProfileHealth: vi.fn(async () => ({
      last_checked_at: "2026-08-14T08:00:00Z",
      status: "healthy",
    })),
    ...overrides,
  };
}

describe("HermesPage", () => {
  it("loads a selected profile through an organization-scoped cache", async () => {
    const cache = createCache();
    const service = createService();
    const user = userEvent.setup();

    render(<HermesPage cache={cache} organizationId={7} service={service} />);

    await user.clear(screen.getByLabelText("用户 ID"));
    await user.type(screen.getByLabelText("用户 ID"), "9");
    await user.click(screen.getByRole("button", { name: "查看 Profile" }));

    const profile = await screen.findByLabelText("Hermes Profile");
    expect(within(profile).getByText("feishu")).toBeInTheDocument();
    expect(within(profile).getByText("chat")).toBeInTheDocument();
    expect(within(profile).getByText("approval")).toBeInTheDocument();
    expect(screen.queryByText("should-not-render")).not.toBeInTheDocument();
    expect(service.getProfile).toHaveBeenCalledWith(9);
    expect(cache.get).toHaveBeenCalledWith(7, ["hermes", "profile", "9"]);
    expect(cache.set).toHaveBeenCalledWith(
      7,
      ["hermes", "profile", "9"],
      expect.objectContaining({ userId: 9 }),
    );
  });

  it("creates a profile and invalidates only the current organization cache", async () => {
    const cache = createCache();
    const service = createService();
    const user = userEvent.setup();

    render(<HermesPage cache={cache} organizationId={7} service={service} />);

    await user.clear(screen.getByLabelText("用户 ID"));
    await user.type(screen.getByLabelText("用户 ID"), "9");
    await user.selectOptions(screen.getByLabelText("服务 Provider"), "feishu");
    await user.click(screen.getByRole("button", { name: "创建 Profile" }));

    await waitFor(() =>
      expect(service.createProfile).toHaveBeenCalledWith({
        provider: "feishu",
        user_id: 9,
      }),
    );
    expect(cache.invalidateOrganization).toHaveBeenCalledWith(7);
    expect(await screen.findByText("active")).toBeInTheDocument();
  });

  it("checks health and deactivates a profile", async () => {
    const cache = createCache();
    const service = createService();
    const user = userEvent.setup();

    render(<HermesPage cache={cache} organizationId={7} service={service} />);

    await user.clear(screen.getByLabelText("用户 ID"));
    await user.type(screen.getByLabelText("用户 ID"), "9");
    await user.click(screen.getByRole("button", { name: "健康检查" }));
    expect(await screen.findByText("healthy")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "停用 Profile" }));
    await waitFor(() => expect(service.deactivateProfile).toHaveBeenCalledWith(9));
    expect(cache.invalidateOrganization).toHaveBeenCalledWith(7);
  });

  it("caches profile health by organization and user", async () => {
    const cache = createCache();
    cache.get.mockReturnValueOnce({
      checkedAt: "2026-08-14T08:00:00Z",
      status: "healthy",
    });
    const service = createService();
    const user = userEvent.setup();

    render(<HermesPage cache={cache} organizationId={7} service={service} />);

    await user.clear(screen.getByLabelText("用户 ID"));
    await user.type(screen.getByLabelText("用户 ID"), "9");
    await user.click(screen.getByRole("button", { name: "健康检查" }));

    expect(await screen.findByText("healthy")).toBeInTheDocument();
    expect(service.getProfileHealth).not.toHaveBeenCalled();
    expect(cache.get).toHaveBeenCalledWith(7, ["hermes", "health", "9"]);
  });

  it("fails closed when organization context is missing", async () => {
    const service = createService();

    render(<HermesPage cache={createCache()} organizationId={null} service={service} />);

    expect(screen.getByText("没有 AI 服务管理权限")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "查看 Profile" })).toBeDisabled();
    expect(service.getProfile).not.toHaveBeenCalled();
  });

  it("disables write actions after a forbidden response", async () => {
    const forbidden = Object.assign(new Error("Forbidden"), { status: 403 });
    const service = createService({
      createProfile: vi.fn(async () => {
        throw forbidden;
      }),
    });
    const user = userEvent.setup();

    render(<HermesPage cache={createCache()} organizationId={7} service={service} />);

    await user.clear(screen.getByLabelText("用户 ID"));
    await user.type(screen.getByLabelText("用户 ID"), "9");
    await user.click(screen.getByRole("button", { name: "创建 Profile" }));

    expect(await screen.findByText("没有 AI 服务管理权限")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "创建 Profile" })).toBeDisabled();
  });
});
