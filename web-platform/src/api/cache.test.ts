import { describe, expect, it } from "vitest";
import { createOrganizationAbortRegistry, createOrganizationCache } from "./cache";

describe("organization cache", () => {
  it("keys values by organization and invalidates a single organization", () => {
    const cache = createOrganizationCache();

    cache.set(1, ["portal", "dashboard"], { visits: 1 });
    cache.set(2, ["portal", "dashboard"], { visits: 2 });
    cache.invalidateOrganization(1);

    expect(cache.get(1, ["portal", "dashboard"])).toBeUndefined();
    expect(cache.get(2, ["portal", "dashboard"])).toEqual({ visits: 2 });
  });
});

describe("organization abort registry", () => {
  it("aborts only controllers for the selected organization", () => {
    const registry = createOrganizationAbortRegistry();
    const orgOneSignal = registry.createSignal(1, "portal");
    const orgTwoSignal = registry.createSignal(2, "portal");

    registry.abortOrganization(1);

    expect(orgOneSignal.aborted).toBe(true);
    expect(orgTwoSignal.aborted).toBe(false);
  });
});
