import { describe, expect, it } from "vitest";
import { normalizeLocation } from "./location";

describe("normalizeLocation", () => {
  it("keeps the root pathname as the dashboard route", () => {
    expect(normalizeLocation({ pathname: "/", hash: "" })).toBe("/");
  });

  it("converts the historical admin hash into the admin pathname", () => {
    expect(normalizeLocation({ pathname: "/", hash: "#admin" })).toBe(
      "/admin",
    );
  });

  it("keeps the historical workspace hash on the dashboard route", () => {
    expect(normalizeLocation({ pathname: "/", hash: "#workspace" })).toBe(
      "/",
    );
  });

  it("ignores hashes on non-root pathnames", () => {
    expect(normalizeLocation({ pathname: "/portal", hash: "#admin" })).toBe(
      "/portal",
    );
  });
});
