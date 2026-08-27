import { describe, expect, it } from "vitest";
import {
  dashboardLayoutsToCockpitOrder,
  legacyCockpitOrderToDashboardLayouts,
} from "./dashboardLayoutMapper";

describe("dashboard layout mapper", () => {
  it("maps the legacy cockpit KPI order to contract grid layouts", () => {
    const layouts = legacyCockpitOrderToDashboardLayouts([
      "business",
      "staff",
      "market",
      "production",
      "other",
    ]);

    expect(layouts.lg).toEqual([
      { i: "business", x: 0, y: 0, w: 4, h: 2 },
      { i: "staff", x: 4, y: 0, w: 4, h: 2 },
      { i: "market", x: 8, y: 0, w: 4, h: 2 },
      { i: "production", x: 0, y: 2, w: 4, h: 2 },
      { i: "other", x: 4, y: 2, w: 4, h: 2 },
    ]);
    expect(layouts.md).toEqual([
      { i: "business", x: 0, y: 0, w: 4, h: 2 },
      { i: "staff", x: 4, y: 0, w: 4, h: 2 },
      { i: "market", x: 0, y: 2, w: 4, h: 2 },
      { i: "production", x: 4, y: 2, w: 4, h: 2 },
      { i: "other", x: 0, y: 4, w: 4, h: 2 },
    ]);
    expect(layouts.sm).toEqual([
      { i: "business", x: 0, y: 0, w: 4, h: 2 },
      { i: "staff", x: 0, y: 2, w: 4, h: 2 },
      { i: "market", x: 0, y: 4, w: 4, h: 2 },
      { i: "production", x: 0, y: 6, w: 4, h: 2 },
      { i: "other", x: 0, y: 8, w: 4, h: 2 },
    ]);
  });

  it("restores the cockpit order from the contract layout using grid position", () => {
    const order = dashboardLayoutsToCockpitOrder(
      {
        lg: [
          { i: "market", x: 8, y: 0, w: 4, h: 2 },
          { i: "business", x: 0, y: 0, w: 4, h: 2 },
          { i: "staff", x: 4, y: 0, w: 4, h: 2 },
        ],
        md: [],
        sm: [],
      },
      ["business", "staff", "market", "production"],
    );

    expect(order).toEqual(["business", "staff", "market", "production"]);
  });
});
