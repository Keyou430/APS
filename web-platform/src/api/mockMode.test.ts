import { describe, expect, it } from "vitest";
import { assertMockNetworkAllowed } from "./mockMode";

describe("mock mode network boundary", () => {
  it("allows auth, chat, health and readiness requests", () => {
    expect(() => assertMockNetworkAllowed("/auth/me")).not.toThrow();
    expect(() => assertMockNetworkAllowed("/chat/sessions")).not.toThrow();
    expect(() => assertMockNetworkAllowed("/health")).not.toThrow();
    expect(() => assertMockNetworkAllowed("/ready")).not.toThrow();
  });

  it("fails closed for non Auth/Chat API requests", () => {
    expect(() => assertMockNetworkAllowed("/knowledge")).toThrow(
      /Unexpected real request in mock mode/,
    );
    expect(() => assertMockNetworkAllowed("/portal/bootstrap")).toThrow(
      /Unexpected real request in mock mode/,
    );
    expect(() => assertMockNetworkAllowed("/enterprise/announcements")).toThrow(
      /Unexpected real request in mock mode/,
    );
    expect(() => assertMockNetworkAllowed("/work-items")).toThrow(
      /Unexpected real request in mock mode/,
    );
  });
});
