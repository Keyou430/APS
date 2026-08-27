import { describe, expect, it, vi } from "vitest";
import { createUiStore } from "./uiStore";

describe("ui store", () => {
  it("tracks active view changes", () => {
    const store = createUiStore({ activeView: "workspace" });

    store.setActiveView("portal");

    expect(store.getState().activeView).toBe("portal");
  });

  it("notifies subscribers after state changes", () => {
    const store = createUiStore({ activeView: "workspace" });
    const listener = vi.fn();

    const unsubscribe = store.subscribe(listener);
    store.setSidebarWidth(320);
    unsubscribe();
    store.setSidebarWidth(280);

    expect(listener).toHaveBeenCalledTimes(1);
    expect(listener).toHaveBeenCalledWith(
      expect.objectContaining({ sidebarWidth: 320 }),
    );
  });
});
