import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom/vitest";
import { describe, expect, it, vi } from "vitest";
import type { OrganizationService } from "../api/services/organizationService";
import { OrganizationPage } from "./OrganizationPage";

function createCache() {
  return {
    get: vi.fn(),
    invalidateOrganization: vi.fn(),
    set: vi.fn(),
  };
}

function createStructure(revision = 4) {
  return {
    organization_id: 7,
    revision,
    units: [
      {
        id: 1,
        parent_id: null,
        name: "星纪年",
        code: "root",
        sort_order: 0,
        is_active: true,
      },
      {
        id: 2,
        parent_id: 1,
        name: "产品部",
        code: "product",
        sort_order: 1,
        is_active: true,
      },
    ],
    positions: [
      {
        id: 8,
        unit_id: 2,
        title: "产品经理",
        level: "P6",
        sort_order: 1,
        is_active: true,
      },
    ],
    placements: [
      {
        membership_id: 11,
        unit_id: 2,
        position_id: 8,
        manager_membership_id: null,
      },
    ],
    people: [
      {
        membership_id: 11,
        user_id: 5,
        username: "Keyou430",
        email: "keyou@example.com",
        role: "manager",
        member_type: "internal",
      },
    ],
  };
}

function createService(
  overrides: Partial<OrganizationService> = {},
): OrganizationService {
  return {
    createPosition: vi.fn(),
    createUnit: vi.fn(),
    deletePosition: vi.fn(async () => undefined),
    deleteUnit: vi.fn(async () => undefined),
    getStructure: vi.fn(async () => createStructure()),
    updatePlacement: vi.fn(),
    updatePlacementsBatch: vi.fn(),
    updatePosition: vi.fn(),
    updateUnit: vi.fn(),
    ...overrides,
  } as OrganizationService;
}

describe("OrganizationPage", () => {
  it("loads organization structure into an organization-scoped cache", async () => {
    const cache = createCache();
    const service = createService();

    render(<OrganizationPage cache={cache} organizationId={7} service={service} />);

    expect(screen.getByText("正在加载组织架构")).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "组织架构" })).toBeInTheDocument();
    expect(await screen.findByText("结构版本 4")).toBeInTheDocument();
    expect(screen.getByText("产品部")).toBeInTheDocument();
    expect(screen.getByText("产品经理")).toBeInTheDocument();
    expect(screen.getByText("Keyou430")).toBeInTheDocument();
    expect(cache.get).toHaveBeenCalledWith(7, ["organization", "structure"]);
    expect(cache.set).toHaveBeenCalledWith(
      7,
      ["organization", "structure"],
      expect.objectContaining({ revision: 4 }),
    );
  });

  it("fails closed without an organization context", async () => {
    const service = createService();

    render(<OrganizationPage cache={createCache()} organizationId={null} service={service} />);

    expect(await screen.findByText("没有组织架构访问权限")).toBeInTheDocument();
    expect(service.getStructure).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "刷新组织架构" })).toBeDisabled();
  });

  it("deletes a position with the expected revision and invalidates only the current organization", async () => {
    const cache = createCache();
    const service = createService();
    const user = userEvent.setup();

    render(<OrganizationPage cache={cache} organizationId={7} service={service} />);

    const positions = await screen.findByLabelText("组织职位");
    await user.click(within(positions).getByRole("button", { name: "删除 产品经理 职位" }));

    await waitFor(() =>
      expect(service.deletePosition).toHaveBeenCalledWith(8, {
        expected_revision: 4,
      }),
    );
    expect(cache.invalidateOrganization).toHaveBeenCalledWith(7);
  });

  it("keeps the current structure visible on revision conflict", async () => {
    const conflict = Object.assign(new Error("Conflict"), { status: 409 });
    const service = createService({
      deletePosition: vi.fn(async () => {
        throw conflict;
      }),
    });
    const user = userEvent.setup();

    render(<OrganizationPage cache={createCache()} organizationId={7} service={service} />);

    const positions = await screen.findByLabelText("组织职位");
    await user.click(within(positions).getByRole("button", { name: "删除 产品经理 职位" }));

    expect(await screen.findByText("组织架构版本已变化，请刷新后再试")).toBeInTheDocument();
    expect(screen.getByText("产品经理")).toBeInTheDocument();
  });
});
