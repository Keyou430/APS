import { describe, expect, it, vi } from "vitest";
import {
  createAppRuntime,
  installAppRuntime,
  type AppRuntimeGlobal,
} from "./appRuntime";

function createStorage() {
  const values = new Map<string, string>();
  return {
    getItem: (key: string) => values.get(key) ?? null,
    removeItem: (key: string) => values.delete(key),
    setItem: (key: string, value: string) => values.set(key, value),
  };
}

describe("app runtime", () => {
  it("creates the shared auth and ui runtime stores", () => {
    const runtime = createAppRuntime({
      auth: {
        fetchFn: vi.fn(),
        storage: createStorage(),
      },
    });

    expect(runtime.auth.store.getState().status).toBe("anonymous");
    expect(runtime.services.dashboard).toBeDefined();
    expect(runtime.services.enterprise).toBeDefined();
    expect(runtime.services.pipeline).toBeDefined();
    expect(runtime.security.renderAssistantMessage("<b>x</b>")).toContain("&lt;b&gt;x&lt;/b&gt;");
    expect(runtime.ui.getState().activeView).toBe("workspace");
  });

  it("installs a single runtime on the global window bridge", () => {
    const target: AppRuntimeGlobal = {};
    const runtime = installAppRuntime(target, {
      auth: {
        fetchFn: vi.fn(),
        storage: createStorage(),
      },
    });

    expect(target.__agentRuntime).toBe(runtime);
    expect(target.__contractAuth?.getToken()).toBe(null);
  });
});
