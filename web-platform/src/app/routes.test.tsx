import { describe, expect, it } from "vitest";
import { isReactOwnedRoute, resolveRoute } from "./routes";

describe("React route ownership", () => {
  it("owns the dashboard and admin pathnames", () => {
    expect(isReactOwnedRoute("/")).toBe(true);
    expect(isReactOwnedRoute("/admin")).toBe(true);
    expect(resolveRoute("/admin").id).toBe("admin");
  });
});
